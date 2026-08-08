"""Ingest-Pipeline: Text -> Chunks -> Embeddings -> chunk_embeddings (Issue #372).

Buendelt den Weg vom Paper-Text zum durchsuchbaren Vektor an einer Stelle:

    Textquelle -> Chunking -> Embedding -> DB

Zerlegt wird seit #708 ueber ``chunking.chunk_pages`` (#374): tokenbasierte
Fenster, deterministischer Kontextsatz, ``embedding_text`` aus Kontextsatz +
Chunk. Bis dahin lief hier der Zeichenfenster-Platzhalter ``split_text`` aus
#372 mit ``context_sentence=""`` -- #374 hatte den Ersatz gebaut, aber niemand
haengte ihn ein. Folge war eine stille Zweiteilung: das Retrieval-Goldset aus
#708 mass ``chunk_pages``-Chunks, der Betrieb speicherte andere. Ein Eval, das
etwas anderes misst als das, was laeuft, ist keine Messung.

Der Text stammt aus ``resolve_paper_text`` und damit aus ``papers_fts.fulltext``,
das seit #373 bewusst KEINE Seitengrenzen mehr traegt. Er geht deshalb als
genau eine Seite in ``chunk_pages``; die Seitenangabe im Kontextsatz lautet auf
diesem Weg immer "Seite 1-1". Das ist die einzige verbleibende Abweichung zum
Goldset (dessen Quelldokumente mehrseitig sind) und beruehrt weder Chunkgrenzen
noch Section-Titel -- vermessen in
``tests/test_issue_708_ingest_uses_chunk_pages.py``. Seit #728 schreibt der
Ingest ``page_start``/``page_end``/``section_title`` strukturiert in
``chunk_embeddings`` (vorher nur unstrukturiert im Kontextsatz-Text).
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from .db import VaultDB
from .embedding_model import get_embedder

if TYPE_CHECKING:  # pragma: no cover - nur fuer die Typpruefung
    from . import chunking

# Obergrenze pro Ingest: haelt die Latenz von add_paper beschraenkt (#372, Risiko 5).
DEFAULT_MAX_CHUNKS = 64

ENV_MAX_CHUNKS = "VAULT_MAX_CHUNKS"


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


def _paper_meta_from_csl(csl_json: str | None) -> chunking.PaperMeta | None:
    """Baut ``PaperMeta`` (#701) aus dem CSL-JSON eines Papers.

    Deterministisch aus Metadaten, die beim Ingest ohnehin vorliegen -- kein
    Modellaufruf. Liefert ``None`` bei fehlendem/kaputtem CSL-JSON, statt den
    Ingest abzubrechen; :func:`chunking.default_context_sentence` behandelt
    das identisch zu "keine Metadaten vorhanden".
    """
    from . import chunking
    from .db import csl_families, csl_title, csl_year

    if not csl_json:
        return None
    try:
        csl = json.loads(csl_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(csl, dict):
        return None

    return chunking.PaperMeta(
        title=csl_title(csl),
        authors=csl_families(csl) or None,
        year=csl_year(csl),
    )


def ingest_paper_embeddings(
    db_path: str,
    paper_id: str,
    text: str | None = None,
    embedder: object | None = None,
    max_chunks: int | None = None,
) -> int:
    """Erzeugt Chunk-Embeddings fuer ein Paper und schreibt sie in den Vault.

    Ersetzt vorhandene Chunks desselben Papers (``add_paper`` ist ein Upsert und
    darf die Tabelle nicht aufblaehen).

    Zerlegt wird ueber :func:`academic_vault.chunking.chunk_pages` mit dessen
    Produktionsdefaults (``TARGET_TOKENS``, ``OVERLAP_RATIO``,
    ``default_context_sentence``) -- derselbe Weg, den das Retrieval-Goldset aus
    #708 misst. Der frueher hier eingebaute Zeichenfenster-Platzhalter
    ``split_text`` ist mit #708 entfallen; ein Chunker-Parameter existiert
    bewusst nicht mehr, weil genau seine Nicht-Nutzung die Zweiteilung zwischen
    Eval und Betrieb erzeugt hat.

    Args:
        db_path: Pfad zur Vault-DB.
        paper_id: Paper, dessen Chunks eingebettet werden.
        text: Expliziter Text. ``None`` = Kaskade aus :func:`resolve_paper_text`.
        embedder: Embedder-Instanz. ``None`` = ``get_embedder()``.
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
    paper = db.get_paper(paper_id)
    if paper is None:
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

    # Import erst hier: ``chunking`` zieht ``transformers`` nach, und der
    # Modulimport von ``ingest`` soll das nicht bezahlen. Ausserdem greift so
    # ein Monkeypatch auf ``academic_vault.chunking.chunk_pages``.
    from . import chunking

    paper_meta = _paper_meta_from_csl(paper.get("csl_json"))

    # Eine Seite: der Volltext aus #373 traegt keine Seitengrenzen mehr (siehe
    # Modul-Docstring). Die Seitenangabe im Kontextsatz lautet damit "Seite 1-1".
    chunks = [
        c
        for c in chunking.chunk_pages([(1, source)], paper_meta=paper_meta)
        if c.chunk_text.strip()
    ]
    if not chunks:
        return 0
    limit = max_chunks if max_chunks is not None else _max_chunks_from_env()
    if limit > 0:
        chunks = chunks[:limit]

    # Der Kontextsatz kommt aus ``chunking.default_context_sentence`` -- seit
    # #632 der einzige Kontextsatz-Weg, weil keine Plugin-Funktion einen
    # ANTHROPIC_API_KEY voraussetzen darf.
    embedding_texts = [c.embedding_text for c in chunks]
    # Embeddings VOR der Schreib-Transaktion berechnen: Modell-Inferenz kann
    # Sekunden dauern und darf keinen SQLite-Write-Lock halten.
    vectors = active_embedder.embed_documents(embedding_texts)  # type: ignore[attr-defined]

    from .embedding_model import serialize_f32

    # Ein Transaktionsblock fuer Loeschen + Neuschreiben: ein Abbruch mittendrin
    # darf kein Paper mit halb geloeschten Chunks hinterlassen.
    with VaultDB(db_path) as writer:
        writer.delete_chunk_embeddings(paper_id)
        for chunk, vector in zip(chunks, vectors, strict=True):
            writer.add_chunk_embedding(
                paper_id=paper_id,
                chunk_text=chunk.chunk_text,
                context_sentence=chunk.context_sentence,
                embedding_text=chunk.embedding_text,
                embedding_vector=serialize_f32(vector),
                section_title=chunk.section_title,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
            )
    return len(chunks)
