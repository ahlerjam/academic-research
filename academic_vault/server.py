"""academic_vault MCP-Server.

Stellt MCP-Tools vault.search/get_paper/add_paper/ensure_file/
add_quote/find_quotes/get_quote/add_note/find_notes/search_notes/stats bereit.

Start via: python -m academic_vault.server
"""

import json
import logging
import os
from pathlib import Path
from uuid import uuid4

from .db import _UNSET, VALID_PAPER_TYPES, VaultDB, _sanitize_fts5_query, _Unset, default_db_path
from .embedding_model import get_embedder
from .files_api import FilesAPIClient

logger = logging.getLogger(__name__)

# Kanonischer DB-Default (Single Source of Truth, Issue #190):
# VAULT_DB_PATH aus Env, sonst ~/.academic-research/projects/<slug>/vault.db.
_DEFAULT_DB = default_db_path()
_ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Maximale Snippet-Laenge eines Vektor-Treffers in der Suchausgabe.
_VEC_SNIPPET_CHARS = 240


# JSON-Schema fuer das csl_json eines Papers (Issue #213, Security Round-2 M3).
# 'type' ist Pflichtfeld und muss einer der CSL-Typen sein, die der Vault
# kennt. So landet kein als 'article-journal' fehl-getaggter Eintrag im Vault,
# wenn ein Skill versehentlich kaputtes oder unvollstaendiges JSON sendet.
_CSL_JSON_SCHEMA = {
    "type": "object",
    "required": ["type"],
    "properties": {
        "type": {"enum": sorted(VALID_PAPER_TYPES)},
    },
}


def validate_csl_json(csl_json: str) -> dict:
    """Validiert csl_json strikt und gibt das geparste dict zurueck.

    Wirft ValueError bei: kaputtem JSON, Nicht-Objekt, fehlendem Pflichtfeld
    'type' oder unbekanntem type-Wert. Kein stiller Default mehr (#213).
    """
    try:
        data = json.loads(csl_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"csl_json ist kein valides JSON: {exc}") from exc

    try:
        import jsonschema
    except ImportError:
        # Fallback ohne jsonschema-Lib: gleiche Invarianten manuell pruefen.
        if not isinstance(data, dict):
            raise ValueError("csl_json muss ein JSON-Objekt sein.") from None
        if "type" not in data:
            raise ValueError(
                f"csl_json: Pflichtfeld 'type' fehlt -- erlaubt: {sorted(VALID_PAPER_TYPES)}"
            ) from None
        if data["type"] not in VALID_PAPER_TYPES:
            raise ValueError(
                f"Ungueltiger type '{data['type']}' -- erlaubt: {sorted(VALID_PAPER_TYPES)}"
            ) from None
        return data

    try:
        jsonschema.validate(instance=data, schema=_CSL_JSON_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"csl_json verletzt Schema: {exc.message}") from exc
    return data


# ---------------------------------------------------------------------------
# Reine Funktionen (testbar ohne MCP-Framework)
# ---------------------------------------------------------------------------


def _ensure_schema_for_read(db_path: str) -> None:
    """Stellt vor einem reinen Lesezugriff sicher, dass die DB nutzbar ist.

    Bewusst NICHT einfach ``VaultDB(db_path).init_schema()``: ``schema.sql``
    enthaelt drei unbedingte ``DROP TRIGGER``+``CREATE TRIGGER``-Paare (siehe
    Kommentar dort), die -- anders als ``CREATE TABLE IF NOT EXISTS`` -- bei
    jedem Lauf sqlite_master schreiben. Riefe jeder Lesepfad unconditional
    ``init_schema()``, wuerde jeder Read (get_paper, search_papers, ...) zu
    einem DDL-Schreibvorgang (Review-Fund P1 zu PR #478/#455).

    Der Guard hier prueft nur billig, ob die DB ueberhaupt schon eine
    ``papers``-Tabelle hat. Fehlt sie (frische, leere DB-Datei -- der Fall,
    den AC3 aus #455 abdeckt), wird einmalig der volle
    ``VaultDB.init_schema()`` durchlaufen. Existiert sie bereits, wird nichts
    weiter getan -- Reparatur von Bestands-Drift (fehlende Spalten/Tabellen,
    veraltete Trigger) bleibt bewusst Aufgabe der Schreibpfade (add_paper,
    add_quote, ...), die weiterhin unbedingt ``init_schema()`` aufrufen und
    damit voll migrations-/reparaturfaehig bleiben (z.B. Trigger-Refresh auf
    Bestands-DBs, Issue #373).

    Zusaetzlich wird ``notes_fts`` geprueft (Review-Fund P1 zu PR #490):
    ``notes_fts`` ist erst mit Issue #462 hinzugekommen und existiert auf
    keinem Bestands-Vault, dessen ``papers``-Tabelle schon vorher da war.
    Ohne diesen zweiten Guard wuerde ``search_notes()`` auf jeder solchen
    Bestands-DB mit ``sqlite3.OperationalError: no such table: notes_fts``
    abstuerzen statt (wie #369 fuer ``papers_fts`` etabliert) ein leeres
    Ergebnis zu liefern -- der Schreibpfad ``add_note()`` (unbedingtes
    ``init_schema()``) legt ``notes_fts`` erst beim ersten Schreibzugriff an,
    ein reiner Lesezugriff (``find_notes``/``search_notes``/``get_note``)
    kann diesem aber zeitlich vorausgehen.
    """
    conn = VaultDB._open(db_path)
    try:
        papers_exists = (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='papers'"
            ).fetchone()
            is not None
        )
        notes_fts_exists = (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='notes_fts'"
            ).fetchone()
            is not None
        )
    finally:
        conn.close()
    if not papers_exists or not notes_fts_exists:
        VaultDB(db_path).init_schema()


def add_quote(
    db_path: str,
    paper_id: str,
    verbatim: str,
    extraction_method: str,
    api_response_id: str | None = None,
    pdf_page: int | None = None,
    printed_page: int | None = None,
    section: str | None = None,
    context_before: str | None = None,
    context_after: str | None = None,
    stance: str | None = None,
) -> str:
    """Fuegt Quote in Vault ein. Gibt quote_id zurueck.

    Halluzinationsschutz: extraction_method='citations-api' erfordert
    api_response_id. Bei Fehlen wird ValueError geworfen.

    ``stance`` (optional, Issue #400) haelt die Haltung des Zitats zur
    zitierenden Aussage fest -- einer der Werte aus ``VALID_STANCES``
    (``supports``/``contrasts``/``mentions``) oder ``None``. Ungueltige Werte
    weist ``VaultDB.add_quote`` mit ``ValueError`` ab. Das Feld wird derzeit nur
    manuell gesetzt; die automatische Klassifikation per lokalem NLI-Modell
    (Konzept-Anleihe: scite Smart Citations / SemanticCite, jeweils nur als
    Idee uebernommen -- keine API-Anbindung) ist ein separates Folge-Issue.
    """
    if extraction_method == "citations-api" and not api_response_id:
        raise ValueError(
            "vault.add_quote: api_response_id required for extraction_method='citations-api'"
        )
    quote_id = str(uuid4())
    db = VaultDB(db_path)
    db.init_schema()
    db.add_quote(
        quote_id=quote_id,
        paper_id=paper_id,
        verbatim=verbatim,
        extraction_method=extraction_method,
        api_response_id=api_response_id,
        pdf_page=pdf_page,
        printed_page=printed_page,
        section=section,
        context_before=context_before,
        context_after=context_after,
        stance=stance,
    )
    return quote_id


def get_quote(db_path: str, quote_id: str) -> dict | None:
    """Gibt vollstaendigen Quote-Record als dict zurueck oder None.

    Enthaelt seit Issue #400 auch das Feld ``stance`` (``supports``/
    ``contrasts``/``mentions`` oder ``None``). Auf Bestands-DBs, die noch nicht
    ueber ``VaultDB.init_schema()`` migriert wurden, kann der Schluessel fehlen
    -- Konsumenten greifen deshalb per ``.get("stance")`` zu. Befuellt wird das
    Feld aktuell nur manuell; die NLI-Klassifikation ist ein Folge-Issue.
    """
    db = VaultDB(db_path)
    _ensure_schema_for_read(db_path)
    return db.get_quote(quote_id)


def search_papers(
    db_path: str,
    query: str,
    type_filter: str | None = None,
    k: int = 5,
    rerank: bool = False,
) -> list[dict]:
    """FTS5/Hybrid-Suche in papers_fts. Gibt [{paper_id, snippet, score}] zurueck.

    Mit ``rerank=True`` bleiben diese Felder erhalten (fuer jeden per FTS5
    gefundenen Treffer inklusive '<b>'-Highlighting im Snippet) und werden um
    'rrf_score' sowie die vec0-Felder 'chunk_id'/'distance' ergaenzt. Rein
    vektoriell gefundene Paper haben mangels FTS5-Treffer kein 'score' und ein
    Snippet aus dem passenden Chunk-Text (ohne Highlighting).

    Args:
        db_path: Pfad zur Vault-DB.
        query: Suchquery.
        type_filter: Optionaler Paper-Type-Filter (article-journal, book, chapter).
        k: Maximale Trefferzahl.
        rerank: Wenn True, wird Hybrid-Retrieval (RRF) und Reranking aktiviert.
                Prioritaet (#376): VOYAGE_API_KEY > COHERE_API_KEY > kostenfreier
                lokaler bge-reranker-v2-m3-Fallback (nur wenn beide Cloud-Keys
                fehlen). Jedes Ergebnis-Dict traegt 'reranked' (bool) und
                'reranker' (str), damit ein fehlgeschlagenes Cloud-Reranking
                sichtbar bleibt statt still auf RRF zurueckzufallen.
    """
    raw_query = query
    query = _sanitize_fts5_query(query)
    if not query:
        # Leere oder rein aus FTS5-Sonderzeichen bestehende Query: kein
        # gueltiger MATCH-Ausdruck moeglich, daher leeres Ergebnis statt
        # sqlite3.OperationalError (Issue #369).
        return []
    # Schema-Sicherstellung vor der rohen SQL-Query unten (Issue #455): diese
    # Funktion umgeht VaultDB komplett und oeffnet die Connection direkt
    # ueber VaultDB._open(), daher greift keine der init_schema()-Aufrufe in
    # den anderen Lesepfaden. Ohne dies crasht die erste Suche auf einer
    # frischen DB mit sqlite3.OperationalError statt ein leeres Ergebnis zu
    # liefern. _ensure_schema_for_read() statt unbedingtem init_schema()
    # (Review-Fund P1 zu PR #478): letzteres fuehrt bei jedem Aufruf DDL aus.
    _ensure_schema_for_read(db_path)
    conn = VaultDB._open(db_path)
    try:
        if type_filter:
            rows = conn.execute(
                """
                SELECT f.paper_id,
                       snippet(papers_fts, -1, '<b>', '</b>', '...', 10) AS snippet,
                       rank AS score
                FROM papers_fts f
                JOIN papers p ON p.paper_id = f.paper_id
                WHERE papers_fts MATCH ?
                  AND p.type = ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, type_filter, k),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT paper_id,
                       snippet(papers_fts, -1, '<b>', '</b>', '...', 10) AS snippet,
                       rank AS score
                FROM papers_fts
                WHERE papers_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, k),
            ).fetchall()
    finally:
        conn.close()

    fts_results = [dict(r) for r in rows]

    if not rerank:
        return fts_results

    from .retrieval import apply_reranker, reciprocal_rank_fusion

    # Der Vektorpfad bekommt die UNSANITIERTE Query: das FTS5-Sanitizing
    # entfernt Bindestriche und Operator-Keywords und verfaelscht damit die
    # Semantik, auf die das Embedding-Modell reagiert.
    fused = reciprocal_rank_fusion(
        _vec0_search(db_path, raw_query, k=k), fts_results, k=60, top_n=k
    )

    voyage_key = os.environ.get("VOYAGE_API_KEY") or None
    cohere_key = os.environ.get("COHERE_API_KEY") or None

    # Kein Gate mehr auf "irgendein Cloud-Key gesetzt" (#376): apply_reranker
    # wird immer aufgerufen, damit auch ohne Cloud-Keys der kostenfreie lokale
    # bge-reranker-v2-m3-Fallback greifen kann. Ohne diesen Aufruf bliebe der
    # lokale Fallback in retrieval.py toter Code.
    return apply_reranker(
        query=query,
        candidates=fused,
        voyage_api_key=voyage_key,
        cohere_api_key=cohere_key,
    )


def _vec0_search(db_path: str, query: str, k: int = 10) -> list[dict]:
    """Vektor-KNN ueber chunk_embeddings fuer das Hybrid-Retrieval (Issue #372).

    Ablauf: Query-Embedding (lokales e5-Modell) -> KNN ueber die Chunks ->
    Aggregation auf Paper-Ebene (bester Chunk je Paper), weil
    ``reciprocal_rank_fusion`` auf ``paper_id`` schluesselt.

    Leere Liste — und damit RRF auf FTS5-Basis — genau dann, wenn kein
    Embedding-Backend installiert ist, noch keine Chunk-Vektoren existieren oder
    die Vektor-Suche fehlschlaegt. Die Textsuche darf daran nie scheitern.

    Returns:
        Liste aus ``{paper_id, chunk_id, snippet, text, distance}``, aufsteigend
        nach Distanz (nahester Treffer zuerst), maximal ``k`` Eintraege.
        ``snippet`` ist der gekuerzte, ``text`` der volle Chunk-Text
        (Reranker-Input).
    """
    embedder = get_embedder()
    if embedder is None:
        return []

    try:
        query_vector = embedder.embed_query(query)
        # Mehr Chunks als Paper anfragen: mehrere Chunks koennen zum selben
        # Paper gehoeren und werden anschliessend aggregiert.
        hits = VaultDB(db_path).knn_chunks(query_vector, k=max(k * 4, k))
    except Exception as exc:  # Vektorsuche ist optional — nie fatal fuer die Textsuche
        logger.warning("vec0-Suche fehlgeschlagen, Fallback auf FTS5-only: %s", exc)
        return []

    best_per_paper: dict[str, dict] = {}
    for hit in hits:  # bereits aufsteigend nach Distanz sortiert
        paper_id = hit["paper_id"]
        if paper_id in best_per_paper:
            continue
        chunk_text = hit.get("chunk_text") or ""
        best_per_paper[paper_id] = {
            "paper_id": paper_id,
            "chunk_id": hit["chunk_id"],
            "snippet": _vec_snippet(chunk_text),
            # Reranker-Input explizit mitgeben: im RRF-Merge gewinnt fuer
            # 'snippet' das FTS5-Feld (Vertrag + Highlighting), waehrend
            # 'text' den laengeren Chunk-Text fuer apply_reranker erhaelt.
            "text": chunk_text,
            "distance": hit["distance"],
        }

    ranked = sorted(best_per_paper.values(), key=lambda entry: entry["distance"])
    return ranked[:k]


def _vec_snippet(chunk_text: str, limit: int = _VEC_SNIPPET_CHARS) -> str:
    """Kuerzt einen Chunk auf Snippet-Laenge (Ausgabe + Reranker-Input)."""
    text = " ".join(chunk_text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _auto_embed_enabled() -> bool:
    """Ob ``add_paper`` Embeddings erzeugt (abschaltbar via ``VAULT_AUTO_EMBED=0``)."""
    return os.environ.get("VAULT_AUTO_EMBED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _auto_fulltext_enabled() -> bool:
    """Ob ``add_paper`` den PDF-Volltext extrahiert (aus via ``VAULT_AUTO_FULLTEXT=0``)."""
    return os.environ.get("VAULT_AUTO_FULLTEXT", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _maybe_extract_fulltext(db_path: str, paper_id: str, pdf_path: str | None) -> bool:
    """Best-effort-Volltextextraktion nach einem Paper-Upsert (Issue #373).

    Laeuft VOR dem Embedding-Ingest, damit dieser den PDF-Text statt nur
    Titel+Abstract einbettet (Textquellen-Kaskade in ``ingest.resolve_paper_text``).
    Bereits extrahierte Paper werden uebersprungen: ``add_paper`` ist ein Upsert
    und wird bei Metadaten-Korrekturen wiederholt aufgerufen.

    Fehler werden geloggt, nie geworfen — ein fehlendes oder defektes PDF darf
    ``vault.add_paper`` nicht scheitern lassen.
    """
    if not pdf_path or not _auto_fulltext_enabled():
        return False
    try:
        db = VaultDB(db_path)
        db.init_schema()
        if db.get_fulltext(paper_id) is not None:
            return False
        from .fulltext import extract_fulltext

        text, extractor = extract_fulltext(pdf_path)
        if not text:
            return False
        return db.set_fulltext(paper_id, text, extractor)
    except Exception as exc:  # Extraktion ist optional — nie fatal fuer add_paper
        logger.warning("Volltext-Extraktion fuer '%s' fehlgeschlagen: %s", paper_id, exc)
        return False


def _maybe_ingest_embeddings(db_path: str, paper_id: str) -> int:
    """Best-effort-Ingest nach einem Paper-Upsert.

    Fehler werden geloggt, nie geworfen: ein kaputtes/fehlendes
    Embedding-Backend darf ``vault.add_paper`` nicht scheitern lassen.
    """
    if not _auto_embed_enabled():
        return 0
    try:
        from .ingest import ingest_paper_embeddings

        return ingest_paper_embeddings(db_path, paper_id)
    except Exception as exc:  # Ingest ist optional — nie fatal fuer add_paper
        logger.warning("Embedding-Ingest fuer '%s' fehlgeschlagen: %s", paper_id, exc)
        return 0


def search_quote_text(db_path: str, verbatim: str, k: int = 5) -> list[dict]:
    """LIKE-Suche in quotes.verbatim. Gibt [{quote_id, verbatim, paper_id}] zurueck."""
    db = VaultDB(db_path)
    _ensure_schema_for_read(db_path)
    return db.search_quote_text(verbatim, k)


def find_quotes(
    db_path: str,
    paper_id: str,
    query: str | None = None,
    k: int = 10,
) -> list[dict]:
    """Gibt Quotes fuer ein Paper zurueck, optional per verbatim-Filter."""
    db = VaultDB(db_path)
    _ensure_schema_for_read(db_path)
    return db.find_quotes(paper_id, query, k)


def verify_citation(
    db_path: str,
    family: str,
    year: int,
    page: int | None = None,
) -> dict:
    """Prueft einen Klammer-Beleg (Autor/Jahr/Seite) gegen den Vault (Issue #378).

    Kein MCP-Tool-Dekorator: die Funktion wird ausschliesslich aus
    ``hooks/verbatim-guard.mjs`` per ``python3 -c``-Subprozess aufgerufen
    (analog zu :func:`search_quote_text` und :func:`find_figure_by_caption`).

    Rueckgabe ``{"status": ..., "paper_ids": [...]}`` mit Status:
      ``"verified"``      — Autor/Jahr im Vault und (falls angegeben) Seite gedeckt
                            bzw. mangels Seitendaten nicht widerlegbar.
      ``"page-mismatch"`` — Autor/Jahr im Vault, Seite liegt nachweislich
                            ausserhalb aller bekannten Seitenbereiche. Der Vault
                            ist hier autoritativ; die externe Kaskade kann
                            Seitenzahlen nicht pruefen und wird uebersprungen.
      ``"no-match"``      — kein Paper mit dieser Autor/Jahr-Kombination.
    """
    db = VaultDB(db_path)
    papers = db.find_papers_by_author_year(family, int(year))
    if not papers:
        return {"status": "no-match", "paper_ids": []}

    paper_ids = [p["paper_id"] for p in papers]
    if page is None:
        return {"status": "verified", "paper_ids": paper_ids}

    coverages = [db.page_coverage(pid, int(page)) for pid in paper_ids]
    if any(c in ("covered", "unknown") for c in coverages):
        return {"status": "verified", "paper_ids": paper_ids}
    return {"status": "page-mismatch", "paper_ids": paper_ids}


# ---------------------------------------------------------------------------
# Notes-Funktionen (rein, testbar ohne MCP-Framework) -- Issue #462
# ---------------------------------------------------------------------------


def add_note(
    db_path: str,
    paper_id: str,
    text: str,
    tags: str | None = None,
    page: int | None = None,
) -> str:
    """Fuegt eine Notiz/ein Exzerpt zu einer Quelle in den Vault ein.

    Gibt note_id zurueck. ``page`` ist optional (AC2).
    """
    db = VaultDB(db_path)
    db.init_schema()
    return db.add_note(paper_id=paper_id, text=text, tags=tags, page=page)


def get_note(db_path: str, note_id: str) -> dict | None:
    """Gibt vollstaendigen Note-Record als dict zurueck oder None."""
    db = VaultDB(db_path)
    _ensure_schema_for_read(db_path)
    return db.get_note(note_id)


def find_notes(
    db_path: str,
    paper_id: str,
    query: str | None = None,
    k: int = 10,
) -> list[dict]:
    """Gibt Notizen fuer ein Paper zurueck, optional per Text-Filter (AC1)."""
    db = VaultDB(db_path)
    _ensure_schema_for_read(db_path)
    return db.find_notes(paper_id, query, k)


def search_notes(db_path: str, query: str, k: int = 5) -> list[dict]:
    """FTS5-Volltextsuche ueber alle Notizen.

    AC3: macht Exzerpte beim Kapitelschreiben themenbezogen auffindbar.
    AC4: Volltextsuche findet Notizinhalte.
    """
    db = VaultDB(db_path)
    _ensure_schema_for_read(db_path)
    return db.search_notes(query, k)


# ---------------------------------------------------------------------------
# Figure-Funktionen (rein, testbar ohne MCP-Framework)
# ---------------------------------------------------------------------------


def add_figure(
    db_path: str,
    paper_id: str,
    page: int | None,
    caption: str | None,
    vlm_description: str | None,
    data_extracted: str | None,
) -> str:
    """Fuegt Figure in Vault ein. Gibt figure_id zurueck."""
    db = VaultDB(db_path)
    db.init_schema()
    return db.add_figure(
        paper_id=paper_id,
        page=page,
        caption=caption,
        vlm_description=vlm_description,
        data_extracted_json=data_extracted,
    )


def get_figure(db_path: str, figure_id: str) -> dict | None:
    """Gibt vollstaendigen Figure-Record als dict oder None."""
    db = VaultDB(db_path)
    _ensure_schema_for_read(db_path)
    return db.get_figure(figure_id)


def list_figures(db_path: str, paper_id: str) -> list[dict]:
    """Gibt alle Figures fuer ein Paper, nach page sortiert."""
    db = VaultDB(db_path)
    _ensure_schema_for_read(db_path)
    return db.list_figures(paper_id)


def find_figure_by_caption(
    db_path: str,
    caption_fragment: str,
    paper_id: str | None = None,
) -> list[dict]:
    """Matcht ein In-Text-Referenz-Label gegen Figure-Captions. Kein MCP-Tool-Dekorator.

    Wird ausschliesslich aus dem verbatim-guard-Hook via Python-Subprocess
    aufgerufen (analog zu search_quote_text). Trotz des Namens (stabil
    gehalten fuer den Hook-Aufrufer) delegiert diese Funktion seit Issue #379
    an ``VaultDB.find_figures_by_reference()`` (Typ+Nummer-Vergleich statt
    Freitext-LIKE-Suche), da das uebergebene ``caption_fragment`` tatsaechlich
    ein In-Text-Referenz-Label ist (z. B. ``"Abb. 3.4"``), kein Caption-Fragment.
    """
    db = VaultDB(db_path)
    _ensure_schema_for_read(db_path)
    return db.find_figures_by_reference(caption_fragment, paper_id=paper_id)


def add_paper(
    db_path: str,
    paper_id: str,
    csl_json: str,
    pdf_path: str | None | _Unset = _UNSET,
    doi: str | None | _Unset = _UNSET,
    isbn: str | None | _Unset = _UNSET,
    page_offset: int | _Unset = _UNSET,
    editor: str | None | _Unset = _UNSET,
    chapter: str | None | _Unset = _UNSET,
    page_first: int | None | _Unset = _UNSET,
    page_last: int | None | _Unset = _UNSET,
    container_title: str | None | _Unset = _UNSET,
    parent_paper_id: str | None | _Unset = _UNSET,
    provenance: str | None | _Unset = _UNSET,
) -> None:
    """Upsert eines Papers in den Vault. Unterstuetzt type=book|chapter.

    provenance: Herkunfts-Tag (z.B. "scihub") fuer Provenance-Audit (#195).

    csl_json wird strikt validiert (Issue #213): Pflichtfeld 'type', gueltiger
    CSL-Typ, valides JSON. Bei Verstoss ValueError statt silent default.

    Alle optionalen Parameter defaulten auf das Sentinel ``_UNSET`` statt auf
    ``None``/``0`` (Issue #455) und werden unveraendert an ``VaultDB.add_paper()``
    durchgereicht: ein zweiter Aufruf fuer dieselbe ``paper_id``, der ein
    optionales Feld nicht mit uebergibt, laesst dessen Bestandswert
    unangetastet statt ihn auf den Default zurueckzusetzen. Ein bewusst
    geleertes Feld (explizit ``None``/``0`` uebergeben) wird weiterhin
    geleert.

    Nach dem Upsert laufen zwei best-effort-Schritte, beide loggen Fehler statt
    sie zu werfen: die PDF-Volltext-Extraktion (Issue #373, abschaltbar via
    ``VAULT_AUTO_FULLTEXT=0``) und darauf aufbauend der Embedding-Ingest
    (Issue #372, abschaltbar via ``VAULT_AUTO_EMBED=0``).
    """
    validate_csl_json(csl_json)
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(
        paper_id,
        csl_json,
        doi=doi,
        isbn=isbn,
        pdf_path=pdf_path,
        page_offset=page_offset,
        editor=editor,
        chapter=chapter,
        page_first=page_first,
        page_last=page_last,
        container_title=container_title,
        parent_paper_id=parent_paper_id,
        provenance=provenance,
    )
    # _maybe_extract_fulltext() erwartet str | None -- Sentinel ("nicht
    # uebergeben") ist fuer die Volltextextraktion aequivalent zu "kein
    # PDF-Pfad angegeben". isinstance() statt "is _UNSET", damit mypy den
    # else-Zweig zuverlaessig auf "str | None" narrowed.
    resolved_pdf_path: str | None = None if isinstance(pdf_path, _Unset) else pdf_path
    _maybe_extract_fulltext(db_path, paper_id, resolved_pdf_path)
    _maybe_ingest_embeddings(db_path, paper_id)


def add_chapter(
    db_path: str,
    parent_paper_id: str,
    chapter_number: int,
    csl_json: str,
    paper_id: str | None = None,
    pdf_path: str | None = None,
    page_first: int | None = None,
    page_last: int | None = None,
) -> str:
    """Legt ein Kapitel als Kind-Paper in den Vault. Gibt paper_id zurueck.

    Setzt type=chapter automatisch falls nicht in csl_json angegeben.
    """
    if paper_id is None:
        paper_id = f"{parent_paper_id}-ch{chapter_number}"
    # Sicherstellen dass type=chapter in csl_json gesetzt ist
    try:
        csl = json.loads(csl_json)
        csl.setdefault("type", "chapter")
        csl_json = json.dumps(csl, ensure_ascii=False)
    except Exception as exc:
        # Kein stilles Durchreichen von malformed csl_json -- sonst wuerde
        # add_paper() es als article-journal fehlklassifizieren (siehe #232).
        raise ValueError(f"add_chapter: Ungueltiges csl_json: {exc}") from exc
    add_paper(
        db_path=db_path,
        paper_id=paper_id,
        csl_json=csl_json,
        pdf_path=pdf_path,
        chapter=str(chapter_number),
        page_first=page_first,
        page_last=page_last,
        parent_paper_id=parent_paper_id,
    )
    return paper_id


def get_paper(db_path: str, paper_id: str) -> dict | None:
    """Gibt Paper-Metadata als dict zurueck oder None."""
    db = VaultDB(db_path)
    _ensure_schema_for_read(db_path)
    return db.get_paper(paper_id)


def list_papers_by_provenance(db_path: str, provenance: str) -> list[dict]:
    """Gibt alle Papers mit dem angegebenen provenance-Tag zurueck (Audit, #195)."""
    db = VaultDB(db_path)
    db.init_schema()
    return db.list_papers_by_provenance(provenance)


def ensure_file(db_path: str, paper_id: str, api_key: str = "") -> str:
    """Delegiert an FilesAPIClient.ensure_file(). Gibt file_id zurueck."""
    paper = get_paper(db_path, paper_id)
    if paper is None:
        raise ValueError(f"Paper '{paper_id}' nicht gefunden.")
    pdf_path = paper.get("pdf_path")
    if not pdf_path:
        raise ValueError(f"Paper '{paper_id}' hat keinen pdf_path.")
    client = FilesAPIClient(
        anthropic_api_key=api_key or _ANTHROPIC_KEY,
        cache_db_path=db_path,
    )
    return client.ensure_file(pdf_path)


def get_stats(db_path: str) -> dict:
    """Delegiert an FilesAPIClient.get_stats()."""
    return FilesAPIClient.get_stats(db_path)


def set_ocr_done(db_path: str, paper_id: str, value: int = 1) -> None:
    """Setzt ocr_done-Flag fuer ein Paper im Vault."""
    db = VaultDB(db_path)
    db.init_schema()
    db.set_ocr_done(paper_id, value)


def update_pdf_path(db_path: str, paper_id: str, new_path: str) -> None:
    """Aktualisiert pdf_path fuer ein Paper im Vault."""
    db = VaultDB(db_path)
    db.init_schema()
    db.update_pdf_path(paper_id, new_path)


def set_page_offset(db_path: str, paper_id: str, offset: int) -> None:
    """Setzt page_offset fuer ein Paper im Vault."""
    db = VaultDB(db_path)
    db.init_schema()
    db.set_page_offset(paper_id, offset)


# ---------------------------------------------------------------------------
# Decision-Log Funktionen (v6.4, #90)
# ---------------------------------------------------------------------------


def add_decision(
    db_path: str,
    category: str | None,
    text: str,
    rationale: str | None = None,
) -> str:
    """Fuegt Decision in Vault ein. Gibt decision_id zurueck."""
    db = VaultDB(db_path)
    db.init_schema()
    return db.add_decision(category=category, text=text, rationale=rationale)


def list_decisions(
    db_path: str,
    category: str | None = None,
    active_only: bool = True,
) -> list[dict]:
    """Gibt Decisions zurueck. Optionaler Kategorie-Filter und active_only-Flag."""
    db = VaultDB(db_path)
    db.init_schema()
    return db.list_decisions(category=category, active_only=active_only)


def supersede_decision(db_path: str, decision_id: str, superseded_by: str) -> None:
    """Markiert eine Decision als superseded."""
    db = VaultDB(db_path)
    db.init_schema()
    db.supersede_decision(decision_id=decision_id, superseded_by=superseded_by)


def add_excluded_source(
    db_path: str,
    paper_id: str,
    reason: str | None = None,
) -> None:
    """Fuegt paper_id zu excluded_sources hinzu."""
    db = VaultDB(db_path)
    db.init_schema()
    db.add_excluded_source(paper_id=paper_id, reason=reason)


def list_excluded_sources(db_path: str) -> list[dict]:
    """Gibt alle excluded_sources zurueck."""
    db = VaultDB(db_path)
    db.init_schema()
    return db.list_excluded_sources()


def is_excluded(db_path: str, paper_id: str) -> bool:
    """Gibt True zurueck wenn paper_id in excluded_sources ist."""
    db = VaultDB(db_path)
    db.init_schema()
    return db.is_excluded(paper_id=paper_id)


# ---------------------------------------------------------------------------
# Risk-of-Bias Funktionen (v6.4, #100)
# ---------------------------------------------------------------------------


def add_risk_of_bias(
    db_path: str,
    paper_id: str,
    study_type: str,
    domain_scores: "dict | str",
) -> str:
    """Fuegt RoB-Assessment in Vault ein. Gibt assessment_id zurueck.

    domain_scores: dict oder JSON-String mit Bewertungen pro Domaene.
    """
    if isinstance(domain_scores, dict):
        domain_scores_json = json.dumps(domain_scores, ensure_ascii=False)
    else:
        domain_scores_json = str(domain_scores)
    db = VaultDB(db_path)
    db.init_schema()
    return db.add_risk_of_bias(
        paper_id=paper_id,
        study_type=study_type,
        domain_scores_json=domain_scores_json,
    )


def list_risk_of_bias(
    db_path: str,
    paper_id: str | None = None,
) -> list[dict]:
    """Gibt RoB-Assessments zurueck, optional nach paper_id gefiltert."""
    db = VaultDB(db_path)
    db.init_schema()
    return db.list_risk_of_bias(paper_id=paper_id)


# ---------------------------------------------------------------------------
# Score-History Funktionen (v6.4, #102)
# ---------------------------------------------------------------------------


def add_score_snapshot(
    db_path: str,
    paper_id: str,
    session_id: str,
    scores: "dict | str",
) -> str:
    """Fuegt Score-Snapshot in Vault ein. Gibt snapshot_id zurueck.

    scores: dict oder JSON-String mit Score-Werten.
    """
    if isinstance(scores, dict):
        scores_json = json.dumps(scores, ensure_ascii=False)
    else:
        scores_json = str(scores)
    db = VaultDB(db_path)
    db.init_schema()
    return db.add_score_snapshot(
        paper_id=paper_id,
        session_id=session_id,
        scores_json=scores_json,
    )


def get_score_history(
    db_path: str,
    paper_id: str,
    k: int | None = None,
) -> list[dict]:
    """Gibt Score-History fuer ein Paper zurueck (neueste zuerst)."""
    db = VaultDB(db_path)
    db.init_schema()
    return db.get_score_history(paper_id=paper_id, k=k)


# ---------------------------------------------------------------------------
# Material Passport / Vault Lock Funktionen (v6.4, #104)
# ---------------------------------------------------------------------------


def lock_passport(db_path: str, slug: str) -> None:
    """Setzt Vault-Lock fuer Slug. Vault wird read-only."""
    db = VaultDB(db_path)
    db.init_schema()
    db.lock_vault(slug=slug)


def is_locked(db_path: str, slug: str) -> bool:
    """Gibt True zurueck wenn Vault fuer Slug gelockt ist."""
    db = VaultDB(db_path)
    db.init_schema()
    return db.is_locked(slug=slug)


def export_material_passport(
    db_path: str,
    slug: str,
    output_dir: str = ".",
    score_algo_version: str = "1.0",
    plugin_version: str = "6.4",
    model_versions: dict | None = None,
    per_uni_profile_hash: str | None = None,
) -> str:
    """Exportiert Material-Passport als material-passport.json.

    Gibt den Pfad zur erzeugten Datei zurueck.
    """
    from .material_passport import build_passport, validate_passport

    db = VaultDB(db_path)
    db.init_schema()

    conn = VaultDB._open(db_path)
    try:
        paper_rows = conn.execute(
            "SELECT paper_id, doi, csl_json FROM papers ORDER BY paper_id"
        ).fetchall()
    finally:
        conn.close()

    paper_ids = [r["paper_id"] for r in paper_rows]
    dois = [r["doi"] for r in paper_rows if r["doi"]]
    decisions = db.list_decisions(active_only=True)

    scores_5d: dict = {}
    for pid in paper_ids:
        history = db.get_score_history(pid, k=1)
        if history:
            scores_5d[pid] = json.loads(history[0]["scores_json"])

    pdf_hashes = _compute_pdf_hashes(db_path)

    passport = build_passport(
        slug=slug,
        paper_ids=paper_ids,
        dois=dois,
        scores_5d=scores_5d,
        score_algo_version=score_algo_version,
        plugin_version=plugin_version,
        model_versions=model_versions or {},
        per_uni_profile_hash=per_uni_profile_hash,
        decisions_snapshot=decisions,
        pdf_hashes=pdf_hashes,
    )

    validate_passport(passport)

    out_path = str(Path(output_dir) / "material-passport.json")
    Path(out_path).write_text(json.dumps(passport, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def _compute_pdf_hashes(db_path: str) -> dict:
    """SHA-256-Hashes aller vorhandenen PDFs. Gibt {paper_id: hex_hash} zurueck."""
    import hashlib

    conn = VaultDB._open(db_path)
    try:
        rows = conn.execute(
            "SELECT paper_id, pdf_path FROM papers WHERE pdf_path IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    hashes = {}
    for row in rows:
        pdf_path = row["pdf_path"]
        if pdf_path and Path(pdf_path).exists():
            sha = hashlib.sha256()
            with open(pdf_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    sha.update(chunk)
            hashes[row["paper_id"]] = sha.hexdigest()
    return hashes


# ---------------------------------------------------------------------------
# Snapshot-Export / Restore Funktionen (v6.4, #91)
# ---------------------------------------------------------------------------


def export_snapshot(
    db_path: str,
    slug: str,
    project_dir: str = ".",
    snapshots_dir: str | None = None,
) -> str | None:
    """Exportiert State-Dateien + Vault-DB als .tgz-Snapshot.

    Schreibt: <snapshots_dir>/<slug>/<YYYYMMDD-HHMM>.tgz

    Args:
        db_path:       Pfad zur Vault-DB (wird in Tarball eingeschlossen).
        slug:          Projekt-Slug fuer Verzeichnis-Benennung.
        project_dir:   Quell-Verzeichnis mit den State-Dateien.
        snapshots_dir: Ziel-Basisverzeichnis (default: ~/.academic-research/snapshots).

    Returns:
        Pfad zur erstellten .tgz-Datei oder None bei Fehler.
    """
    import tarfile
    import tempfile
    from datetime import datetime

    if snapshots_dir is None:
        snapshots_dir = str(Path.home() / ".academic-research" / "snapshots")

    project_path = Path(project_dir)
    if not project_path.exists():
        return None

    # Timestamp im Format YYYYMMDD-HHMM
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    slug_dir = Path(snapshots_dir) / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    out_path = slug_dir / f"{ts}.tgz"

    state_files = [
        "academic_context.md",
        "literature_state.md",
        "writing_state.md",
    ]

    try:
        with tarfile.open(str(out_path), "w:gz") as tar:
            found_any = False
            for name in state_files:
                src = project_path / name
                if src.exists():
                    tar.add(str(src), arcname=name)
                    found_any = True

            # Vault-DB einschliessen wenn vorhanden
            vault_path = Path(db_path)
            if vault_path.exists():
                tar.add(str(vault_path), arcname="vault.db")
                found_any = True

            if not found_any:
                # Leerer Tarball mit Platzhalter
                with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                    f.write("Keine State-Dateien vorhanden.\n")
                    tmp_name = f.name
                try:
                    tar.add(tmp_name, arcname="snapshot-empty.txt")
                finally:
                    Path(tmp_name).unlink(missing_ok=True)

        return str(out_path)
    except Exception:
        return None


def restore_snapshot(
    slug: str,
    ts: str,
    snapshots_dir: str | None = None,
    target_dir: str = ".",
) -> bool:
    """Stellt Snapshot zurueck: Entpackt <slug>/<ts>.tgz in target_dir.

    Args:
        slug:          Projekt-Slug.
        ts:            Timestamp-String (Dateiname ohne .tgz).
        snapshots_dir: Basisverzeichnis der Snapshots.
        target_dir:    Zielverzeichnis fuer Extraktion.

    Returns:
        True bei Erfolg, False bei Fehler.
    """
    import tarfile

    if snapshots_dir is None:
        snapshots_dir = str(Path.home() / ".academic-research" / "snapshots")

    tar_path = Path(snapshots_dir) / slug / f"{ts}.tgz"
    if not tar_path.exists():
        return False

    target_path = Path(target_dir)
    target_path.mkdir(parents=True, exist_ok=True)

    try:
        dest = target_path.resolve()
        with tarfile.open(str(tar_path), "r:gz") as tar:
            # Sicher extrahieren (CVE-2007-4559 / CWE-22, Issue #192).
            # Schicht 1: Symlink-/Hardlink-Member und Path-Traversal pro
            # Member explizit ablehnen — funktioniert auch auf Python < 3.12
            # ohne PEP-706-Filter.
            safe_members = []
            for m in tar.getmembers():
                if m.issym() or m.islnk():
                    # Symlinks/Hardlinks erlauben Escapes aus dem Zielverzeichnis.
                    raise ValueError(f"symlink/hardlink not allowed: {m.name}")
                if m.name.startswith("/"):
                    raise ValueError(f"absolute path not allowed: {m.name}")
                resolved = (dest / m.name).resolve()
                if resolved != dest and dest not in resolved.parents:
                    raise ValueError(f"path traversal: {m.name}")
                safe_members.append(m)
            # Schicht 2: PEP-706-data-Filter (Python 3.12+, backportiert auf
            # 3.9.17+/3.10.12+/3.11.4+). Blockiert Symlink-Escape und
            # Path-Traversal zusaetzlich auf C-Ebene. Wenn nicht verfuegbar,
            # greift nur Schicht 1.
            try:
                tar.extractall(str(target_path), members=safe_members, filter="data")
            except TypeError:
                # filter-Argument auf aelteren Pythons nicht vorhanden
                tar.extractall(str(target_path), members=safe_members)
        return True
    except Exception:
        return False


def get_printed_page(db_path: str, paper_id: str, pdf_page: int) -> int | None:
    """Berechnet gedruckte Seitenzahl: printed_page = pdf_page - page_offset.

    Args:
        db_path: Pfad zur Vault-DB.
        paper_id: Paper-ID im Vault.
        pdf_page: Seitenzahl aus Citations-API (1-basiert ab erster PDF-Seite).

    Returns:
        Gedruckte Seitenzahl (>= 1), oder None wenn pdf_page vor dem
        Textbeginn liegt (Vorspann -- z.B. Titelblatt, Impressum,
        Inhaltsverzeichnis). Wird NICHT auf 1 geklemmt (Issue #464 AC2):
        das waere von einer echten Seite 1 nicht unterscheidbar.
    """
    db = VaultDB(db_path)
    _ensure_schema_for_read(db_path)
    offset = db.get_page_offset(paper_id)
    printed = pdf_page - offset
    if printed < 1:
        return None
    return printed


def extract_fulltext_for_paper(
    db_path: str,
    paper_id: str,
    backend: str = "auto",
) -> dict:
    """Extrahiert den PDF-Volltext eines Papers und indiziert ihn (Issue #373).

    Args:
        db_path: Pfad zur Vault-DB.
        paper_id: Paper mit hinterlegtem ``pdf_path``.
        backend: ``"auto"`` (GROBID falls ``GROBID_URL`` gesetzt, sonst pypdf),
            ``"grobid"`` oder ``"pypdf"``.

    Returns:
        ``{"paper_id", "extractor", "chars", "indexed"}``. Bei einem PDF ohne
        Text-Layer (Scan) ist ``indexed`` False und ``chars`` 0 — dann ist erst
        ein OCR-Lauf noetig.

    Raises:
        ValueError: Paper unbekannt oder ohne ``pdf_path``.
        FileNotFoundError: Hinterlegter ``pdf_path`` existiert nicht.
    """
    from .fulltext import extract_fulltext

    db = VaultDB(db_path)
    db.init_schema()
    paper = db.get_paper(paper_id)
    if paper is None:
        raise ValueError(f"Paper unbekannt: {paper_id}")
    pdf_path = (paper.get("pdf_path") or "").strip()
    if not pdf_path:
        raise ValueError(f"Paper '{paper_id}' hat keinen pdf_path -- nichts zu extrahieren.")

    text, extractor = extract_fulltext(pdf_path, backend=backend)
    indexed = db.set_fulltext(paper_id, text, extractor) if text else False
    return {
        "paper_id": paper_id,
        "extractor": extractor,
        "chars": len(text),
        "indexed": indexed,
    }


# ---------------------------------------------------------------------------
# MCP-Server (optional: nur wenn mcp-SDK verfuegbar)
# ---------------------------------------------------------------------------


def _build_mcp_server():
    """Erstellt FastMCP-Server-Instanz. Gibt None zurueck wenn mcp nicht installiert."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        return None

    mcp = FastMCP("academic-vault")
    db_path = _DEFAULT_DB

    @mcp.tool(name="vault.search")
    def _vault_search(
        query: str, type: str | None = None, k: int = 5, rerank: bool = False
    ) -> list[dict]:
        """Hybrid-Suche in papers. rerank=True aktiviert RRF + optionalen Voyage/Cohere-Reranker."""
        return search_papers(db_path, query, type_filter=type, k=k, rerank=rerank)

    @mcp.tool(name="vault.get_paper")
    def _vault_get_paper(paper_id: str) -> dict | None:
        """Paper-Metadata + pdf_status."""
        return get_paper(db_path, paper_id)

    @mcp.tool(name="vault.list_papers_by_provenance")
    def _vault_list_papers_by_provenance(provenance: str) -> list[dict]:
        """Audit: alle Papers mit gegebenem Herkunfts-Tag (z.B. "scihub")."""
        return list_papers_by_provenance(db_path, provenance)

    @mcp.tool(name="vault.add_paper")
    def _vault_add_paper(
        paper_id: str,
        csl_json: str,
        pdf_path: str | None | _Unset = _UNSET,
        doi: str | None | _Unset = _UNSET,
        isbn: str | None | _Unset = _UNSET,
        page_offset: int | _Unset = _UNSET,
        editor: str | None | _Unset = _UNSET,
        chapter: str | None | _Unset = _UNSET,
        page_first: int | None | _Unset = _UNSET,
        page_last: int | None | _Unset = _UNSET,
        container_title: str | None | _Unset = _UNSET,
        parent_paper_id: str | None | _Unset = _UNSET,
        provenance: str | None | _Unset = _UNSET,
    ) -> None:
        """Upsert eines Papers. type aus csl_json; book|chapter|article-journal erlaubt.

        provenance: Herkunfts-Tag (z.B. "scihub") fuer Provenance-Audit (#195).

        Nicht uebergebene optionale Felder lassen ihren Bestandswert beim
        Upsert unangetastet statt ihn zu leeren (Issue #455).
        """
        add_paper(
            db_path,
            paper_id,
            csl_json,
            pdf_path=pdf_path,
            doi=doi,
            isbn=isbn,
            page_offset=page_offset,
            editor=editor,
            chapter=chapter,
            page_first=page_first,
            page_last=page_last,
            container_title=container_title,
            parent_paper_id=parent_paper_id,
            provenance=provenance,
        )

    @mcp.tool(name="vault.add_chapter")
    def _vault_add_chapter(
        parent_paper_id: str,
        chapter_number: int,
        csl_json: str,
        paper_id: str | None = None,
        pdf_path: str | None = None,
        page_first: int | None = None,
        page_last: int | None = None,
    ) -> str:
        """Legt Kapitel als Kind-Paper an. Gibt paper_id zurueck."""
        return add_chapter(
            db_path=db_path,
            parent_paper_id=parent_paper_id,
            chapter_number=chapter_number,
            csl_json=csl_json,
            paper_id=paper_id,
            pdf_path=pdf_path,
            page_first=page_first,
            page_last=page_last,
        )

    @mcp.tool(name="vault.ensure_file")
    def _vault_ensure_file(paper_id: str) -> str:
        """Gibt gecachte file_id zurueck oder laedt PDF hoch."""
        return ensure_file(db_path, paper_id, api_key=_ANTHROPIC_KEY)

    @mcp.tool(name="vault.add_quote")
    def _vault_add_quote(
        paper_id: str,
        verbatim: str,
        extraction_method: str,
        api_response_id: str | None = None,
        pdf_page: int | None = None,
        printed_page: int | None = None,
        section: str | None = None,
        context_before: str | None = None,
        context_after: str | None = None,
        stance: str | None = None,
    ) -> str:
        """Fuegt Quote ein. extraction_method='citations-api' erfordert api_response_id.

        stance (optional): 'supports' | 'contrasts' | 'mentions' | None (#400).
        """
        return add_quote(
            db_path=db_path,
            paper_id=paper_id,
            verbatim=verbatim,
            extraction_method=extraction_method,
            api_response_id=api_response_id,
            pdf_page=pdf_page,
            printed_page=printed_page,
            section=section,
            context_before=context_before,
            context_after=context_after,
            stance=stance,
        )

    @mcp.tool(name="vault.search_quote_text")
    def _vault_search_quote_text(verbatim: str, k: int = 5) -> list[dict]:
        """LIKE-Suche in quotes.verbatim. Prueft ob ein Zitat im Vault existiert."""
        return search_quote_text(db_path, verbatim, k)

    @mcp.tool(name="vault.find_quotes")
    def _vault_find_quotes(paper_id: str, query: str | None = None, k: int = 10) -> list[dict]:
        """Gibt Quotes fuer ein Paper zurueck."""
        return find_quotes(db_path, paper_id, query=query, k=k)

    @mcp.tool(name="vault.get_quote")
    def _vault_get_quote(quote_id: str) -> dict | None:
        """Gibt vollstaendigen Quote-Record zurueck."""
        return get_quote(db_path, quote_id)

    @mcp.tool(name="vault.add_note")
    def _vault_add_note(
        paper_id: str,
        text: str,
        tags: str | None = None,
        page: int | None = None,
    ) -> str:
        """Fuegt eine Notiz/ein Exzerpt zu einer Quelle hinzu. page optional (#462)."""
        return add_note(db_path, paper_id=paper_id, text=text, tags=tags, page=page)

    @mcp.tool(name="vault.find_notes")
    def _vault_find_notes(paper_id: str, query: str | None = None, k: int = 10) -> list[dict]:
        """Gibt Notizen fuer ein Paper zurueck, optional per Text-Filter."""
        return find_notes(db_path, paper_id, query=query, k=k)

    @mcp.tool(name="vault.search_notes")
    def _vault_search_notes(query: str, k: int = 5) -> list[dict]:
        """FTS5-Volltextsuche ueber alle Notizen (fuer Kapitelschreiben, #462)."""
        return search_notes(db_path, query, k=k)

    @mcp.tool(name="vault.stats")
    def _vault_stats() -> dict:
        """Counts + Token-Ersparnis-Schaetzung."""
        return get_stats(db_path)

    @mcp.tool(name="vault.set_ocr_done")
    def _vault_set_ocr_done(paper_id: str, value: int = 1) -> None:
        """Setzt ocr_done-Flag (1=OCR durchgefuehrt) fuer ein Paper."""
        set_ocr_done(db_path, paper_id, value)

    @mcp.tool(name="vault.update_pdf_path")
    def _vault_update_pdf_path(paper_id: str, new_path: str) -> None:
        """Aktualisiert den PDF-Pfad nach OCR."""
        update_pdf_path(db_path, paper_id, new_path)

    @mcp.tool(name="vault.set_page_offset")
    def _vault_set_page_offset(paper_id: str, offset: int) -> None:
        """Setzt page_offset fuer ein Paper (Buecher mit Vorseiten/Vorwort)."""
        set_page_offset(db_path, paper_id, offset)

    @mcp.tool(name="vault.get_printed_page")
    def _vault_get_printed_page(paper_id: str, pdf_page: int) -> int | None:
        """Berechnet gedruckte Seitenzahl: printed_page = pdf_page - page_offset.

        None, wenn pdf_page vor dem Textbeginn liegt (Vorspann)."""
        return get_printed_page(db_path, paper_id, pdf_page)

    @mcp.tool(name="vault.extract_fulltext")
    def _vault_extract_fulltext(paper_id: str, backend: str = "auto") -> dict:
        """Extrahiert den PDF-Volltext und indiziert ihn in papers_fts (#373).

        backend: "auto" (GROBID falls GROBID_URL gesetzt, sonst pypdf), "grobid", "pypdf".
        """
        return extract_fulltext_for_paper(db_path, paper_id, backend=backend)

    @mcp.tool(name="vault.add_figure")
    def _vault_add_figure(
        paper_id: str,
        page: int | None = None,
        caption: str | None = None,
        vlm_description: str | None = None,
        data_extracted_json: str | None = None,
    ) -> str:
        """Fuegt Figure/Tabelle in Vault ein. Gibt figure_id zurueck."""
        return add_figure(db_path, paper_id, page, caption, vlm_description, data_extracted_json)

    @mcp.tool(name="vault.get_figure")
    def _vault_get_figure(figure_id: str) -> dict | None:
        """Gibt Figure-Record zurueck oder None."""
        return get_figure(db_path, figure_id)

    @mcp.tool(name="vault.list_figures")
    def _vault_list_figures(paper_id: str) -> list[dict]:
        """Gibt alle Figures fuer ein Paper, nach page sortiert."""
        return list_figures(db_path, paper_id)

    # -----------------------------------------------------------------------
    # v6.4: Decision-Log Tools (#90)
    # -----------------------------------------------------------------------

    @mcp.tool(name="vault.add_decision")
    def _vault_add_decision(
        category: str | None = None,
        text: str = "",
        rationale: str | None = None,
    ) -> str:
        """Fuegt Decision in den Vault ein. Gibt decision_id zurueck."""
        return add_decision(db_path, category=category, text=text, rationale=rationale)

    @mcp.tool(name="vault.list_decisions")
    def _vault_list_decisions(
        category: str | None = None,
        active_only: bool = True,
    ) -> list[dict]:
        """Gibt Decisions zurueck. Optionaler category-Filter, active_only-Flag."""
        return list_decisions(db_path, category=category, active_only=active_only)

    @mcp.tool(name="vault.supersede_decision")
    def _vault_supersede_decision(decision_id: str, superseded_by: str) -> None:
        """Markiert eine Decision als superseded (verweist auf Nachfolge-Decision)."""
        supersede_decision(db_path, decision_id=decision_id, superseded_by=superseded_by)

    @mcp.tool(name="vault.add_excluded_source")
    def _vault_add_excluded_source(paper_id: str, reason: str | None = None) -> None:
        """Fuegt paper_id zu excluded_sources hinzu (verhindert Re-Vorschlag)."""
        add_excluded_source(db_path, paper_id=paper_id, reason=reason)

    @mcp.tool(name="vault.list_excluded_sources")
    def _vault_list_excluded_sources() -> list[dict]:
        """Gibt alle excluded_sources zurueck."""
        return list_excluded_sources(db_path)

    @mcp.tool(name="vault.is_excluded")
    def _vault_is_excluded(paper_id: str) -> bool:
        """Prueft ob paper_id in excluded_sources ist."""
        return is_excluded(db_path, paper_id=paper_id)

    # -----------------------------------------------------------------------
    # v6.4: Risk-of-Bias Tools (#100)
    # -----------------------------------------------------------------------

    @mcp.tool(name="vault.add_risk_of_bias")
    def _vault_add_risk_of_bias(
        paper_id: str,
        study_type: str,
        domain_scores: str,
    ) -> str:
        """Fuegt RoB-Assessment ein. domain_scores als JSON-String. Gibt assessment_id zurueck."""
        return add_risk_of_bias(
            db_path, paper_id=paper_id, study_type=study_type, domain_scores=domain_scores
        )

    @mcp.tool(name="vault.list_risk_of_bias")
    def _vault_list_risk_of_bias(paper_id: str | None = None) -> list[dict]:
        """Gibt RoB-Assessments zurueck, optional nach paper_id gefiltert."""
        return list_risk_of_bias(db_path, paper_id=paper_id)

    # -----------------------------------------------------------------------
    # v6.4: Score-Trajectory Tools (#102)
    # -----------------------------------------------------------------------

    @mcp.tool(name="vault.add_score_snapshot")
    def _vault_add_score_snapshot(
        paper_id: str,
        session_id: str,
        scores: str,
    ) -> str:
        """Fuegt Score-Snapshot ein. scores als JSON-String. Gibt snapshot_id zurueck."""
        return add_score_snapshot(db_path, paper_id=paper_id, session_id=session_id, scores=scores)

    @mcp.tool(name="vault.get_score_history")
    def _vault_get_score_history(paper_id: str, k: int | None = None) -> list[dict]:
        """Gibt Score-History fuer ein Paper zurueck (neueste zuerst)."""
        return get_score_history(db_path, paper_id=paper_id, k=k)

    # -----------------------------------------------------------------------
    # v6.4: Material Passport Tools (#104)
    # -----------------------------------------------------------------------

    @mcp.tool(name="vault.export_material_passport")
    def _vault_export_material_passport(
        slug: str,
        output_dir: str = ".",
        score_algo_version: str = "1.0",
        plugin_version: str = "6.4",
    ) -> str:
        """Exportiert material-passport.json. Gibt Dateipfad zurueck."""
        return export_material_passport(
            db_path,
            slug=slug,
            output_dir=output_dir,
            score_algo_version=score_algo_version,
            plugin_version=plugin_version,
        )

    @mcp.tool(name="vault.lock_passport")
    def _vault_lock_passport(slug: str) -> None:
        """Setzt Vault-Lock fuer Slug (macht Vault read-only)."""
        lock_passport(db_path, slug=slug)

    @mcp.tool(name="vault.is_locked")
    def _vault_is_locked(slug: str) -> bool:
        """Prueft ob Vault fuer Slug gelockt ist."""
        return is_locked(db_path, slug=slug)

    @mcp.tool(name="vault.export_snapshot")
    def _vault_export_snapshot(
        slug: str,
        project_dir: str = ".",
        snapshots_dir: str | None = None,
    ) -> str | None:
        """Exportiert State-Dateien + Vault-DB als .tgz-Snapshot.

        Schreibt <snapshots_dir>/<slug>/<YYYYMMDD-HHMM>.tgz und gibt den Pfad
        zurueck (None bei Fehler). snapshots_dir default: ~/.academic-research/snapshots.
        """
        return export_snapshot(db_path, slug, project_dir=project_dir, snapshots_dir=snapshots_dir)

    @mcp.tool(name="vault.restore_snapshot")
    def _vault_restore_snapshot(
        slug: str,
        ts: str,
        snapshots_dir: str | None = None,
        target_dir: str = ".",
    ) -> bool:
        """Stellt einen Snapshot zurueck: entpackt <slug>/<ts>.tgz nach target_dir.

        ts ist der Timestamp-String (Dateiname ohne .tgz). Gibt True bei Erfolg,
        False bei Fehler. snapshots_dir default: ~/.academic-research/snapshots.
        """
        return restore_snapshot(slug, ts, snapshots_dir=snapshots_dir, target_dir=target_dir)

    return mcp


mcp = _build_mcp_server()


if __name__ == "__main__":
    if mcp is None:
        raise RuntimeError("mcp SDK nicht installiert. Bitte 'pip install mcp>=1.0' ausfuehren.")
    mcp.run()
