"""Ingest-Pipeline: Text -> Chunks -> Embeddings -> chunk_embeddings (Issue #372).

Buendelt den Weg vom Paper-Text zum durchsuchbaren Vektor an einer Stelle:

    Textquelle -> Chunking -> (optionaler Kontextsatz) -> Embedding -> DB

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
ENV_CONTEXTUAL = "VAULT_CONTEXTUAL_EMBEDDING"


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


def _contextual_enabled() -> bool:
    """Kontextsaetze sind Opt-in: sie kosten einen Anthropic-API-Call pro Chunk."""
    flag = os.environ.get(ENV_CONTEXTUAL, "").strip().lower()
    if flag not in {"1", "true", "yes", "on"}:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


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
    """
    active_embedder = embedder if embedder is not None else get_embedder()
    if active_embedder is None:
        return 0

    db = VaultDB(db_path)
    if db.get_paper(paper_id) is None:
        return 0

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

    contexts = _context_sentences(db, paper_id, chunks)
    embedding_texts = [
        _embedding_text(ctx, chunk) for ctx, chunk in zip(contexts, chunks, strict=True)
    ]
    # Embeddings VOR der Schreib-Transaktion berechnen: Modell-Inferenz kann
    # Sekunden dauern und darf keinen SQLite-Write-Lock halten.
    vectors = active_embedder.embed_documents(embedding_texts)  # type: ignore[attr-defined]

    from .embedding_model import serialize_f32

    # Ein Transaktionsblock fuer Loeschen + Neuschreiben: ein Abbruch mittendrin
    # darf kein Paper mit halb geloeschten Chunks hinterlassen.
    with VaultDB(db_path) as writer:
        writer.delete_chunk_embeddings(paper_id)
        for chunk, ctx, embedding_text, vector in zip(
            chunks, contexts, embedding_texts, vectors, strict=True
        ):
            writer.add_chunk_embedding(
                paper_id=paper_id,
                chunk_text=chunk,
                context_sentence=ctx,
                embedding_text=embedding_text,
                embedding_vector=serialize_f32(vector),
            )
    return len(chunks)


def _embedding_text(context_sentence: str, chunk: str) -> str:
    if not context_sentence:
        return chunk
    from .embeddings import build_contextual_embedding_text

    return build_contextual_embedding_text(context_sentence, chunk)


def _context_sentences(db: VaultDB, paper_id: str, chunks: list[str]) -> list[str]:
    """Erzeugt pro Chunk einen 1-Satz-Kontext — nur wenn explizit aktiviert."""
    if not _contextual_enabled():
        return [""] * len(chunks)

    paper = db.get_paper(paper_id) or {}
    try:
        csl = json.loads(paper.get("csl_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        csl = {}
    title = str(csl.get("title") or "")
    abstract = str(csl.get("abstract") or "")

    from .embeddings import generate_context_sentence

    return [
        generate_context_sentence(
            chunk_text=chunk,
            paper_title=title,
            paper_abstract=abstract,
            paper_id=paper_id,
        )
        for chunk in chunks
    ]
