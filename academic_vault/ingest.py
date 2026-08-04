"""Ingest-Pipeline: Text -> Chunks -> Embeddings -> chunk_embeddings (Issue #372).

Buendelt den Weg vom Paper-Text zum durchsuchbaren Vektor an einer Stelle:

    Textquelle -> Chunking -> Embedding -> DB

Chunker und Textquelle sind injizierbar. Die hier enthaltene Chunk-Zerlegung
ist bewusst ein einfacher Platzhalter: sobald die dedizierte Chunking-Logik
(#374) und die PDF-Volltext-Extraktion (#373) stehen, werden sie ueber die
Parameter ``chunker`` bzw. ``text`` eingehaengt, ohne dass diese Datei sich
aendern muss.
"""

import json
import os
from collections.abc import Callable

from .db import VaultDB
from .embedding_model import get_embedder

# ~512 Tokens entsprechen grob 1600 Zeichen deutschem/englischem Fliesstext.
DEFAULT_CHUNK_CHARS = 1600
DEFAULT_CHUNK_OVERLAP = 200
# Obergrenze pro Ingest: haelt die Latenz von add_paper beschraenkt (#372, Risiko 5).
DEFAULT_MAX_CHUNKS = 64

ENV_MAX_CHUNKS = "VAULT_MAX_CHUNKS"


def split_text(
    text: str,
    max_chars: int = DEFAULT_CHUNK_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Zerlegt Text in ueberlappende Chunks entlang von Wortgrenzen.

    Platzhalter-Chunker bis #374; bewusst simpel und deterministisch.
    """
    normalized = " ".join(text.split())
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    overlap = max(0, min(overlap, max_chars // 2))
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        if end < len(normalized):
            # Auf der letzten Wortgrenze der hinteren Chunk-Haelfte schneiden.
            boundary = normalized.rfind(" ", start + max_chars // 2, end)
            if boundary != -1:
                end = boundary
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return chunks


def resolve_paper_text(db_path: str, paper_id: str) -> str:
    """Ermittelt den einzubettenden Text eines Papers.

    Kaskade: ``papers_fts.fulltext`` (seit #373 real befuellt, siehe
    ``academic_vault/fulltext.py``) -> Titel + Abstract aus ``papers.csl_json``.
    Leerer String, wenn nichts davon verfuegbar ist.
    """
    conn = VaultDB._open(db_path)
    try:
        row = conn.execute(
            "SELECT fulltext FROM papers_fts WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        if row is not None and (row["fulltext"] or "").strip():
            return str(row["fulltext"]).strip()

        paper = conn.execute(
            "SELECT csl_json FROM papers WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        if paper is None:
            return ""
        try:
            csl = json.loads(paper["csl_json"])
        except (json.JSONDecodeError, TypeError):
            return ""
        if not isinstance(csl, dict):
            return ""
        parts = [str(csl.get(field) or "").strip() for field in ("title", "abstract")]
        return "\n\n".join(p for p in parts if p)
    finally:
        conn.close()


def _max_chunks_from_env() -> int:
    raw = os.environ.get(ENV_MAX_CHUNKS, "").strip()
    if not raw:
        return DEFAULT_MAX_CHUNKS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_CHUNKS
    return value if value > 0 else DEFAULT_MAX_CHUNKS


def ingest_paper_embeddings(
    db_path: str,
    paper_id: str,
    text: str | None = None,
    embedder: object | None = None,
    chunker: Callable[[str], list[str]] | None = None,
    max_chunks: int | None = None,
) -> int:
    """Erzeugt Chunk-Embeddings fuer ein Paper und schreibt sie in den Vault.

    Ersetzt vorhandene Chunks desselben Papers (``add_paper`` ist ein Upsert und
    darf die Tabelle nicht aufblaehen).

    Args:
        db_path: Pfad zur Vault-DB.
        paper_id: Paper, dessen Chunks eingebettet werden.
        text: Expliziter Text. ``None`` = Kaskade aus :func:`resolve_paper_text`.
        embedder: Embedder-Instanz. ``None`` = ``get_embedder()``.
        chunker: Chunk-Funktion. ``None`` = :func:`split_text`.
        max_chunks: Obergrenze. ``None`` = ``VAULT_MAX_CHUNKS`` bzw. Default.

    Returns:
        Anzahl geschriebener Chunks. 0, wenn kein Embedder verfuegbar ist, das
        Paper nicht existiert oder kein Text gefunden wurde.

    Raises:
        EmbeddingDimensionMismatchError: Das Modell liefert eine andere
            Dimension als der vorhandene Bestand (Issue #629). Geprueft wird
            VOR der Berechnung -- ein Modellwechsel ohne Re-Index soll nicht
            erst Minuten Inferenz kosten, um dann zu scheitern.
    """
    active_embedder = embedder if embedder is not None else get_embedder()
    if active_embedder is None:
        return 0

    db = VaultDB(db_path)
    if db.get_paper(paper_id) is None:
        return 0

    # Bestandsabgleich vor dem teuren Teil: passt die Modell-Dimension nicht
    # zum Vault, wirft das hier -- statt spaeter halb geschriebene Chunks in
    # zwei Vektorraeumen zu hinterlassen.
    db.register_embedding_inventory(
        getattr(active_embedder, "model_id", None),
        int(active_embedder.dim),  # type: ignore[attr-defined]
    )

    source = text if text is not None else resolve_paper_text(db_path, paper_id)
    if not source or not source.strip():
        return 0

    split = chunker if chunker is not None else split_text
    chunks = [c for c in split(source) if c.strip()]
    if not chunks:
        return 0
    limit = max_chunks if max_chunks is not None else _max_chunks_from_env()
    if limit > 0:
        chunks = chunks[:limit]

    # Kein Kontextsatz auf diesem Weg: der ``split_text``-Platzhalter kennt
    # weder Abschnitt noch Seitenzahlen. Kontextualisierte Embedding-Texte
    # entstehen im seitenbewussten Pfad (``chunking.chunk_pages``, #374) ueber
    # ``default_context_sentence`` -- seit #632 der einzige Kontextsatz-Weg,
    # weil keine Plugin-Funktion einen ANTHROPIC_API_KEY voraussetzen darf.
    embedding_texts = list(chunks)
    # Embeddings VOR der Schreib-Transaktion berechnen: Modell-Inferenz kann
    # Sekunden dauern und darf keinen SQLite-Write-Lock halten.
    vectors = active_embedder.embed_documents(embedding_texts)  # type: ignore[attr-defined]

    from .embedding_model import serialize_f32

    # Ein Transaktionsblock fuer Loeschen + Neuschreiben: ein Abbruch mittendrin
    # darf kein Paper mit halb geloeschten Chunks hinterlassen.
    with VaultDB(db_path) as writer:
        writer.delete_chunk_embeddings(paper_id)
        for chunk, embedding_text, vector in zip(chunks, embedding_texts, vectors, strict=True):
            writer.add_chunk_embedding(
                paper_id=paper_id,
                chunk_text=chunk,
                context_sentence="",
                embedding_text=embedding_text,
                embedding_vector=serialize_f32(vector),
            )
    return len(chunks)
