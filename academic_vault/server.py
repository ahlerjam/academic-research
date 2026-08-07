"""academic_vault MCP-Server.

Stellt MCP-Tools vault.search/get_paper/add_paper/
add_quote/verify_verbatim/find_quotes/get_quote/add_note/find_notes/
search_notes/stats bereit.

Start via: python -m academic_vault.server
"""

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

from . import retraction as _retraction
from .db import (
    _UNSET,
    VALID_PAPER_TYPES,
    VaultDB,
    _sanitize_fts5_query,
    _Unset,
    default_db_path,
    paper_cited_in_chapters,
)
from .decision_log import AUTO_CATEGORY as _AUTO_DECISION_CATEGORY
from .decision_log import MODEL_VERSION_CATEGORY as _MODEL_VERSION_CATEGORY
from .decision_log import parse_model_version_text as _parse_model_version_text
from .embedding_model import REINDEX_HINT, EmbeddingDimensionMismatchError, get_embedder
from .health import get_component_status

logger = logging.getLogger(__name__)

# Kanonischer DB-Default (Single Source of Truth, Issue #190):
# VAULT_DB_PATH aus Env, sonst ~/.academic-research/projects/<slug>/vault.db.
_DEFAULT_DB = default_db_path()

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


# Tabellen, ohne die ein reiner Lesepfad in einen rohen
# sqlite3.OperationalError laeuft statt ein leeres Ergebnis zu liefern.
# Fehlt eine davon, zieht _ensure_schema_for_read() die Migration einmalig
# nach. Jede kuenftige Tabelle mit eigenem Lesepfad gehoert hier hinein.
_READ_REQUIRED_TABLES = frozenset(
    {"papers", "notes_fts", "transcript_segments", "codings", "paper_tables", "papers_trgm"}
)


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

    Dieselbe Lage gilt fuer ``transcript_segments``/``codings`` (Issue #473):
    auch sie fehlen auf jedem Vault, der vorher angelegt wurde, und
    ``list_codings``/``list_transcript_segments`` sind reine Lesepfade. Die zu
    pruefenden Tabellen stehen deshalb in ``_READ_REQUIRED_TABLES`` -- wer eine
    neue Tabelle mit eigenem Lesepfad ergaenzt, traegt sie dort ein, statt eine
    weitere Einzelabfrage danebenzustellen.
    """
    conn = VaultDB._open(db_path)
    try:
        present = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                f"({','.join('?' * len(_READ_REQUIRED_TABLES))})",
                tuple(sorted(_READ_REQUIRED_TABLES)),
            ).fetchall()
        }
    finally:
        conn.close()
    if present != _READ_REQUIRED_TABLES:
        VaultDB(db_path).init_schema()


def _resolve_verbatim_pdf_path(caller: str, db_path: str, paper_id: str) -> str:
    """Loest Paper -> lesbaren ``pdf_path`` auf, sonst fail-closed ``ValueError``.

    Gemeinsamer Helfer fuer :func:`_verify_local_verbatim` (#512, Schreib-Gate
    in ``add_quote``) und :func:`verify_verbatim_preview` (#513, reine
    Read-only-Vorschau) -- beide brauchen dieselbe Paper-/pdf_path-Aufloesung.
    ``caller`` (z. B. ``"vault.add_quote"``/``"vault.verify_verbatim"``)
    landet in der Fehlermeldung, damit die Ursache im jeweiligen Tool-Kontext
    erkennbar bleibt.

    Raises:
        ValueError: Paper unbekannt oder ``pdf_path`` fehlt/nicht lesbar. Das
            sind Bedienfehler des Aufrufers, keine Zitat-Pruefergebnisse.
    """
    paper = get_paper(db_path, paper_id)
    if paper is None:
        raise ValueError(
            f"{caller}: Paper '{paper_id}' nicht gefunden -- "
            "eine lokale Verbatim-Pruefung braucht ein Paper mit hinterlegtem PDF."
        )

    pdf_path = (paper.get("pdf_path") or "").strip()
    if not pdf_path:
        raise ValueError(
            f"{caller}: Paper '{paper_id}' hat keinen pdf_path -- "
            "eine lokale Verbatim-Pruefung ist ohne lokales PDF nicht moeglich. "
            "Entweder pdf_path nachtragen (vault.update_pdf_path) oder das "
            "Zitat mit extraction_method='manual' und eigenem Beleg erfassen."
        )
    if not Path(pdf_path).is_file():
        raise ValueError(
            f"{caller}: hinterlegter pdf_path '{pdf_path}' von Paper "
            f"'{paper_id}' existiert nicht -- eine lokale Verbatim-Pruefung "
            "ist damit nicht moeglich. Pfad korrigieren (vault.update_pdf_path) "
            "oder das Zitat mit extraction_method='manual' erfassen."
        )
    return pdf_path


def verify_verbatim_preview(db_path: str, paper_id: str, candidate: str) -> dict:
    """Prueft ``candidate`` read-only gegen den lokalen PDF-Volltext (#513).

    Anders als :func:`_verify_local_verbatim` (das Schreib-Gate von
    ``add_quote``) wirft diese Funktion bei den Pruefstatus ``no-match``/
    ``no-textlayer`` KEINE Exception -- sie liefert IMMER ein Ergebnis-dict
    zurueck, damit Agenten Kandidaten iterativ pruefen und korrigieren
    koennen, bevor ``add_quote()`` endgueltig ablehnt. Die Paper-/
    pdf_path-Aufloesung (unbekanntes Paper, fehlender/nicht lesbarer
    ``pdf_path``) bleibt ``ValueError`` -- das sind Bedienfehler des
    Aufrufers, keine Zitat-Pruefergebnisse.

    Schreibt nichts in die Datenbank (reiner Lesepfad ueber ``get_paper``).

    Returns:
        dict mit ``status`` (``"exact"``/``"snapped"``/``"no-match"``/
        ``"no-textlayer"``), ``verbatim`` (Quelltext bei Treffer, sonst
        ``""``), ``pdf_page`` (``int`` oder ``None``) und ``ratio``
        (``float`` 0.0-1.0).

    Raises:
        ValueError: Paper unbekannt oder ``pdf_path`` fehlt/nicht lesbar.
    """
    # Lazy import: `verbatim.verify_verbatim` zieht pypdf + rapidfuzz nach.
    from .verbatim import verify_verbatim

    pdf_path = _resolve_verbatim_pdf_path("vault.verify_verbatim", db_path, paper_id)
    result = verify_verbatim(pdf_path, candidate)
    return {
        "status": result.status,
        "verbatim": result.verbatim,
        "pdf_page": result.pdf_page,
        "ratio": result.ratio,
    }


def _verify_local_verbatim(
    db_path: str,
    paper_id: str,
    verbatim: str,
    pdf_page: int | None,
) -> tuple[str, int]:
    """Verifiziert einen Kandidaten fail-closed gegen das lokale PDF (#512).

    Wird ausschliesslich aus :func:`add_quote` fuer
    ``extraction_method='local-verbatim'`` aufgerufen -- VOR jedem
    Schreibzugriff auf ``quotes``.

    Returns:
        ``(verbatim, pdf_page)`` aus der QUELLE: der an der Fundstelle
        stehende Wortlaut und die verifizierte Seite.

    Raises:
        ValueError: Paper unbekannt, kein/kein lesbarer ``pdf_path``, oder
            Pruefstatus ``no-match``/``no-textlayer``. In allen Faellen wurde
            nichts gespeichert.
    """
    # Lazy import: `verbatim.verify_verbatim` zieht pypdf + rapidfuzz nach.
    # Die Pfade 'manual' und 'citations-api' duerfen davon nichts merken.
    from .verbatim import verify_verbatim

    pdf_path = _resolve_verbatim_pdf_path("vault.add_quote", db_path, paper_id)

    result = verify_verbatim(pdf_path, verbatim)
    if result.status not in ("exact", "snapped") or result.pdf_page is None:
        raise ValueError(
            f"vault.add_quote: Verbatim-Pruefung fehlgeschlagen (status="
            f"'{result.status}', beste Aehnlichkeit {result.ratio:.2f}) fuer Paper "
            f"'{paper_id}' -- das Zitat wurde NICHT gespeichert. Der Wortlaut ist "
            "im lokalen PDF nicht auffindbar (z. B. Halluzination, Seitenumbruch "
            "mitten im Zitat oder fehlender Text-Layer). Wortlaut korrigieren oder "
            "das Zitat mit extraction_method='manual' und eigenem Beleg erfassen."
        )

    if pdf_page is not None and pdf_page != result.pdf_page:
        logger.warning(
            "vault.add_quote: uebergebenes pdf_page=%s weicht von der verifizierten "
            "Seite %s ab (Paper '%s') -- gespeichert wird die verifizierte Seite (#512).",
            pdf_page,
            result.pdf_page,
            paper_id,
        )

    return result.verbatim, result.pdf_page


def resolve_quote_context(db_path: str, quote_id: str, window: int = 600) -> bool:
    """Ermittelt ECHTEN Quellkontext (+-``window`` Zeichen) aus ``paper_fulltext`` (#520).

    Sucht die Fundstelle von ``quotes.verbatim`` im (mit
    :func:`academic_vault.verbatim.normalize_text` normalisierten) Volltext
    des zugehoerigen Papers -- erst exakter Substring-Treffer, sonst
    Fuzzy-Fallback via ``rapidfuzz.fuzz.partial_ratio_alignment``. Der
    Fuzzy-Fallback ist noetig, weil der Volltext-Extraktor
    (:func:`academic_vault.fulltext.extract_fulltext`, Issue #373) vom
    Seiten-Extraktor abweichen kann, den ``verify_verbatim`` fuer die
    Verifikation selbst nutzt (:func:`academic_vault.chunking.extract_pages`,
    Issue #511/#512) -- Ligaturen, Trennstriche, Whitespace. Bei
    nachgewiesener Fundstelle werden ``context_before``/``context_after``
    (je bis zu ``window`` Zeichen, an Textanfang/-ende entsprechend kuerzer)
    persistiert und ``context_source='fulltext'`` gesetzt.

    Geraten wird NIE: ohne ``paper_fulltext``-Eintrag oder ohne Fundstelle
    (Fuzzy-Score unter :data:`academic_vault.verbatim.SNAP_RATIO_THRESHOLD`)
    bleibt der Quote-Datensatz unveraendert -- No-Op, Rueckgabe ``False``.
    Kommt der Wortlaut mehrfach im Volltext vor, gewinnt bei exaktem
    Substring-Treffer deterministisch die ERSTE Fundstelle (``str.find``);
    fuer den Fuzzy-Fallback bestimmt ``rapidfuzz`` den besten Treffer.

    Args:
        db_path: Pfad zur Vault-DB.
        quote_id: Referenz auf ``quotes.quote_id``.
        window: Anzahl Zeichen vor/nach der Fundstelle (Default 600).

    Returns:
        ``True`` wenn Kontext persistiert wurde, sonst ``False`` (No-Op).

    Raises:
        ValueError: ``quote_id`` ist unbekannt.
        VaultLockedError: Vault ist gesperrt (Material-Passport-Lock).
    """
    # Lazy import: rapidfuzz wird nur gebraucht, wenn tatsaechlich Kontext
    # aufgeloest wird (Muster wie _verify_local_verbatim/#512).
    from rapidfuzz import fuzz

    from .verbatim import SNAP_RATIO_THRESHOLD, normalize_text

    db = VaultDB(db_path)
    db.init_schema()
    quote = db.get_quote(quote_id)
    if quote is None:
        raise ValueError(f"vault.resolve_quote_context: Quote '{quote_id}' nicht gefunden.")

    fulltext = db.get_fulltext(quote["paper_id"])
    if not fulltext:
        return False

    normalized_candidate = normalize_text(quote["verbatim"])
    if not normalized_candidate:
        return False
    normalized_fulltext = normalize_text(fulltext)

    match_start = normalized_fulltext.find(normalized_candidate)
    if match_start != -1:
        match_end = match_start + len(normalized_candidate)
    else:
        alignment = fuzz.partial_ratio_alignment(normalized_candidate, normalized_fulltext)
        # alignment ist nur None, wenn ein score_cutoff uebergeben wird (hier
        # nicht der Fall) -- der Guard ist reine mypy-Absicherung.
        if alignment is None or alignment.score / 100.0 < SNAP_RATIO_THRESHOLD:
            return False
        match_start, match_end = alignment.dest_start, alignment.dest_end

    context_before = normalized_fulltext[max(0, match_start - window) : match_start]
    context_after = normalized_fulltext[match_end : match_end + window]

    db.update_quote_context(
        quote_id=quote_id,
        context_before=context_before,
        context_after=context_after,
        context_source="fulltext",
    )
    return True


def _maybe_resolve_quote_context(db_path: str, quote_id: str) -> bool:
    """Best-effort-Wrapper um :func:`resolve_quote_context` (#520).

    Fehler werden geloggt, nie geworfen -- das Zitat wurde bereits erfolgreich
    committet (``VaultDB.add_quote`` hat seine eigene Transaktion laengst
    abgeschlossen); ein Fehlschlag hier darf ``vault.add_quote`` nicht als
    fehlgeschlagen erscheinen lassen und den bereits gespeicherten,
    verifizierten Datensatz nicht unsichtbar machen.
    """
    try:
        return resolve_quote_context(db_path, quote_id)
    except Exception as exc:  # Kontext-Backfill ist optional -- nie fatal fuer add_quote
        logger.warning(
            "vault.add_quote: resolve_quote_context() fuer Quote '%s' fehlgeschlagen: %s (#520)",
            quote_id,
            exc,
        )
        return False


def _quote_embedding_text(quote: dict) -> str:
    """Baut den Embedding-Text: ``context_before + verbatim + context_after`` (#521).

    Fallback auf nur ``verbatim``, wenn kein Kontext vorliegt (Quote hat
    ``context_source IS NULL``, z. B. ``extraction_method='manual'`` oder
    ``resolve_quote_context`` fand keine Fundstelle).
    """
    before = quote.get("context_before") or ""
    after = quote.get("context_after") or ""
    return before + quote["verbatim"] + after


def embed_quote(db_path: str, quote_id: str, embedder: object | None = None) -> bool:
    """Erzeugt und speichert das Embedding eines verifizierten Zitats (Issue #521).

    Backend- UND Extension-Verfuegbarkeit werden VOR dem teuren
    ``embed_documents()``-Aufruf geprueft (Plan-Risiko #521/4): ist die
    vec0-Extension in diesem Prozess nicht ladbar, kann ohnehin nirgends
    gespeichert werden -- kein unnoetiger Modell-Load. Embedding-Text ist
    ``context_before + verbatim + context_after`` (:func:`_quote_embedding_text`).

    Args:
        db_path: Pfad zur Vault-DB.
        quote_id: Referenz auf ``quotes.quote_id``.
        embedder: Embedder-Instanz. ``None`` = ``get_embedder()``.

    Returns:
        ``True`` wenn ein Embedding geschrieben wurde, sonst ``False``
        (Degradationspfad: fehlendes Backend oder fehlende Extension --
        beide Faelle werden geloggt, nie stillschweigend uebersprungen).

    Raises:
        ValueError: ``quote_id`` ist unbekannt.
        VaultLockedError: Vault ist gesperrt (Material-Passport-Lock).
    """
    db = VaultDB(db_path)
    db.init_schema()

    if not db.vec_extension_loadable():
        logger.warning(
            "vault.embed_quote: sqlite-vec-Extension nicht ladbar -- Quote '%s' "
            "bleibt ohne Embedding (#521).",
            quote_id,
        )
        return False

    active_embedder = embedder if embedder is not None else get_embedder()
    if active_embedder is None:
        logger.warning(
            "vault.embed_quote: kein Embedding-Backend verfuegbar -- Quote '%s' "
            "bleibt ohne Embedding (#521).",
            quote_id,
        )
        return False

    quote = db.get_quote(quote_id)
    if quote is None:
        raise ValueError(f"vault.embed_quote: Quote '{quote_id}' nicht gefunden.")

    # Bestandsabgleich vor der Inferenz (#629): passt die Dimension nicht,
    # wirft das hier, statt den Vektor spaeter stillschweigend zu verwerfen.
    db.register_embedding_inventory(
        getattr(active_embedder, "model_id", None),
        int(active_embedder.dim),  # type: ignore[attr-defined]
    )

    text = _quote_embedding_text(quote)
    vectors = active_embedder.embed_documents([text])  # type: ignore[attr-defined]
    if not vectors:
        return False

    from .embedding_model import serialize_f32

    return db.add_quote_embedding(quote_id, serialize_f32(vectors[0]))


def _maybe_embed_quote(db_path: str, quote_id: str) -> bool:
    """Best-effort-Wrapper um :func:`embed_quote` (#521).

    Faengt unerwartete Fehler ab (Muster ``_maybe_resolve_quote_context``,
    #520) -- das Zitat wurde bereits erfolgreich committet, ein Fehlschlag
    hier darf ``vault.add_quote`` nicht als fehlgeschlagen erscheinen lassen.
    Die erwarteten Degradationspfade (kein Backend/keine Extension) loggen
    bereits in :func:`embed_quote` selbst und werfen nicht.
    """
    try:
        return embed_quote(db_path, quote_id)
    except EmbeddingDimensionMismatchError:
        raise  # Carve-out (#629), siehe _maybe_ingest_embeddings
    except Exception as exc:  # Embedding ist optional -- nie fatal fuer add_quote
        logger.warning(
            "vault.add_quote: embed_quote() fuer Quote '%s' fehlgeschlagen: %s (#521)",
            quote_id,
            exc,
        )
        return False


def quote_context_similarity(
    db_path: str,
    quote_id: str,
    text: str,
    embedder: object | None = None,
) -> float | None:
    """Kosinus zwischen einem Kapitelfenster und dem gespeicherten Quote-Embedding (#522).

    Kein MCP-Tool: die Funktion wird aus ``hooks/context-fidelity-guard.mjs``
    per ``python -c``-Subprozess aufgerufen (Muster :func:`search_quote_text`)
    und ist so mit injiziertem Embedder unit-testbar, ohne den Node-Hook zu
    starten.

    Das gespeicherte Embedding stammt aus ``embed_documents`` (Passage-Seite),
    das Kapitelfenster wird mit ``embed_query`` vektorisiert -- e5 ist
    asymmetrisch, beide Seiten brauchen ihr eigenes Praefix. Beide Vektoren
    werden L2-normiert, der Kosinus ist dann das Skalarprodukt.

    Das gespeicherte Embedding wird VOR dem Embedder geholt: fehlt es, gibt es
    nichts zu vergleichen und kein Modell muss geladen werden (relevant im
    PreToolUse-Pfad, wo ein Modell-Load das Hook-Timeout sprengen wuerde).

    Returns:
        Kosinus in ``[-1, 1]`` oder ``None``. ``None`` heisst ausschliesslich
        "nicht bestimmbar" (kein gespeichertes Embedding, kein
        Embedding-Backend, Dimensionen passen nicht) -- nie "unaehnlich".
    """
    from .embedding_model import l2_normalize

    db = VaultDB(db_path)
    _ensure_schema_for_read(db_path)
    stored = db.get_quote_embedding(quote_id)
    if not stored:
        return None

    active_embedder = embedder if embedder is not None else get_embedder()
    if active_embedder is None:
        logger.warning(
            "vault.quote_context_similarity: kein Embedding-Backend verfuegbar -- "
            "Quote '%s' bleibt ungeprueft (#522).",
            quote_id,
        )
        return None

    query_vector = active_embedder.embed_query(text)  # type: ignore[attr-defined]
    if not query_vector:
        return None
    if len(query_vector) != len(stored):
        # Kein harter Fehler wie in den Schreibpfaden (#629): diese Funktion
        # haengt im PreToolUse-Hook, wo eine Exception das Schreiben blockieren
        # wuerde, obwohl der Beleg selbst in Ordnung ist. Der Grund wird aber
        # benannt, statt als "nicht bestimmbar" unterzugehen.
        logger.warning(
            "vault.quote_context_similarity: gespeichertes Embedding von Quote '%s' hat "
            "%d Dimensionen, das aktuelle Modell liefert %d -- der Vergleich entfaellt. "
            "%s",
            quote_id,
            len(stored),
            len(query_vector),
            REINDEX_HINT,
        )
        return None

    left = l2_normalize(query_vector)
    right = l2_normalize(stored)
    return float(sum(a * b for a, b in zip(left, right, strict=True)))


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

    Halluzinationsschutz, je nach ``extraction_method`` (``VALID_EXTRACTION_METHODS``):

    * ``'citations-api'`` erfordert ``api_response_id``; bei Fehlen ``ValueError``.
    * ``'local-verbatim'`` (Issue #512) wird HIER fail-closed gegen den lokalen
      PDF-Volltext des Papers verifiziert (:func:`academic_vault.verbatim.verify_verbatim`),
      bevor irgendetwas geschrieben wird. Unbekanntes Paper, fehlender oder
      nicht lesbarer ``pdf_path`` sowie die Pruefstatus ``no-match`` und
      ``no-textlayer`` werfen ``ValueError`` -- der Vault bleibt unveraendert.
      Bei ``exact``/``snapped`` wird der QUELLTEXT (nicht der uebergebene
      Kandidat) samt der VERIFIZIERTEN Seite gespeichert; ein abweichend
      uebergebenes ``pdf_page`` wird verworfen und per ``logger.warning``
      sichtbar gemacht, weil die verifizierte Seite der Beweis ist.
      Danach wird -- non-fatal, Issue #520 -- versucht, echten Quellkontext
      aus ``paper_fulltext`` aufzuloesen (:func:`resolve_quote_context`) und
      ``context_before``/``context_after``/``context_source`` zu befuellen.
      Ohne Volltext oder ohne Fundstelle bleibt das No-Op; ein Fehler dabei
      wird nur geloggt, das bereits gespeicherte Zitat bleibt unberuehrt.
    * ``'manual'`` bleibt ungeprueft -- und damit der dokumentierte
      Ausweichweg, wenn die lokale Verifikation an ihre Grenzen stoesst.

    Grenzen der lokalen Verifikation (Issue #511, hier zur harten Blockade
    verschaerft): seitenuebergreifende Zitate liefern ``no-match``, und die
    Fuzzy-Suche fixiert die Fensterlaenge auf die Kandidatenlaenge -- bei
    Wort-Auslassungen sind damit falsch-negative Ergebnisse moeglich. In
    solchen Faellen ist ``extraction_method='manual'`` mit eigenem Beleg der
    richtige Weg, nicht das Aufweichen dieser Pruefung.

    ``stance`` (optional, Issue #400) haelt die Haltung des Zitats zur
    zitierenden Aussage fest -- einer der Werte aus ``VALID_STANCES``
    (``supports``/``contrasts``/``mentions``) oder ``None``. Ungueltige Werte
    weist ``VaultDB.add_quote`` mit ``ValueError`` ab. Das Feld wird derzeit nur
    manuell gesetzt; die automatische Klassifikation per lokalem NLI-Modell
    (Konzept-Anleihe: scite Smart Citations / SemanticCite, jeweils nur als
    Idee uebernommen -- keine API-Anbindung) ist ein separates Folge-Issue.

    Nach dem Insert wird -- non-fatal, Issue #521 -- fuer JEDE der drei
    gueltigen ``extraction_method``-Werte (der CHECK-Constraint laesst nur
    'citations-api'/'manual'/'local-verbatim' zu, alle drei gelten als
    "bestandene Pruefung") versucht, ein Embedding zu erzeugen und in
    ``quote_embeddings`` (vec0) zu schreiben (:func:`embed_quote`). Fehlendes
    Embedding-Backend oder nicht ladbare sqlite-vec-Extension degradieren
    sauber (geloggt, kein Absturz) -- der bereits gespeicherte, verifizierte
    Quote-Datensatz bleibt davon unberuehrt.
    """
    if extraction_method == "citations-api" and not api_response_id:
        raise ValueError(
            "vault.add_quote: api_response_id required for extraction_method='citations-api'"
        )
    if extraction_method == "local-verbatim":
        verbatim, pdf_page = _verify_local_verbatim(db_path, paper_id, verbatim, pdf_page)
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
    if extraction_method == "local-verbatim":
        _maybe_resolve_quote_context(db_path, quote_id)
    _maybe_embed_quote(db_path, quote_id)
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


def set_quote_stance(db_path: str, quote_id: str, stance: str) -> None:
    """Aktualisiert ``stance`` eines bestehenden Zitats (Issue #523).

    Schreibpfad fuer nachtraegliche Audits (z.B. `quote-fidelity-auditor`):
    `add_quote(stance=...)` deckt nur die Neuanlage ab. `stance` muss einer der
    Werte aus ``VALID_STANCES`` sein; ``ValueError`` bei ungueltigem Wert oder
    unbekannter ``quote_id``.
    """
    db = VaultDB(db_path)
    db.init_schema()
    db.set_quote_stance(quote_id, stance)


def record_quote_audit(
    db_path: str,
    quote_id: str,
    verdict: str,
    severity: str | None = None,
) -> None:
    """Protokolliert ein Audit-Urteil eines bestehenden Zitats (Issue #737).

    Additiver Schreibpfad neben ``set_quote_stance``: der
    `quote-fidelity-auditor`-Agent ruft nach jedem Urteil BEIDE Tools auf
    (Ausnahme keine -- auch bei ``verdict='unsupported'``, wo `set_quote_stance`
    bewusst NICHT aufgerufen wird). ``verdict`` muss einer der Werte aus
    ``VALID_AUDIT_VERDICTS`` sein, ``severity`` einer der Werte aus
    ``VALID_AUDIT_SEVERITIES`` -- ausser bei ``verdict='faithful'``, dort MUSS
    ``severity`` ``None`` bleiben (kein Befund). ``ValueError`` bei ungueltiger
    Kombination oder unbekannter ``quote_id``.
    """
    db = VaultDB(db_path)
    db.init_schema()
    db.record_quote_audit(quote_id, verdict, severity)


def chapter_quote_balance(db_path: str, chapter_path: str) -> dict:
    """Prüfbilanz für ein Kapitel: geprüft, Befund offen, nicht geprüft (Issue #737).

    Liest die Kapiteldatei von der Platte, findet ALLE darin belegten
    Vault-Zitate über ``nli_prefilter.scan_chapter_quotes`` (Wiederverwendung
    des Issue #592-Mechanismus -- deckt das GESAMTE Kapitel ab, nicht nur die
    letzte Schreib-Sitzung, AC5) und bucketet jedes Zitat anhand seiner
    Audit-Historie (``quotes.audited_at``/``audit_verdict``/``audit_severity``,
    additiv zu ``stance``, siehe :func:`record_quote_audit`):

      - ``geprueft_unauffaellig``: ``audited_at`` gesetzt, Verdict ``faithful``.
      - ``befund_offen``: ``audited_at`` gesetzt, Verdict != ``faithful``.
      - ``nicht_geprueft``: ``audited_at`` ist NULL -- kein Audit-Datensatz
        vorhanden. Das ist die einzige Kategorie, die dieser Vault-Stand
        unterscheiden kann; Altbestand (vor Issue #737 auditiert) landet
        unvermeidlich hier, auch wenn ``stance`` bereits gesetzt ist (siehe
        Kommentar bei ``quotes.audited_at`` in schema.sql).

    Die drei Zähler ergeben zusammen ``total_quotes`` (Summe-Invariante, AC1).
    Ein Kapitel ohne ein einziges belegtes Zitat liefert alle Zähler als 0,
    kein Fehler (AC4). ``findings`` enthält die offenen Befunde, nach Schwere
    sortiert (kritisch -> hoch -> mittel, AC3).

    WICHTIG (Nicht-Beweis, AC6): Die Bilanz stellt fest, sie beweist nicht --
    ein Verdikt ``faithful`` heißt "vom Auditor als unauffällig eingestuft",
    nicht "mit letzter Sicherheit korrekt verwendet". Sie priorisiert die
    Prüfkette, ersetzt sie nicht.

    Zusaetzlich zu den Zitat-Zaehlern (Issue #741, additiv): ``erfasste_kennzahlen``
    zaehlt, wie viele belegte Kennzahlen (:func:`add_table_value`) zu den im
    Kapitel referenzierten Papers im Vault stehen -- gesammelt ueber dieselben
    Paper-IDs, die ``scan_chapter_quotes`` aus den Zitat-Belegen des Kapitels
    ermittelt hat (KEIN eigener Zahlen-Scan im Kapiteltext, das waere die
    bewusst ausgeschlossene automatische Zahlenerkennung, siehe Issue #741
    Scope-Out). ``erfasste_kennzahlen`` fliesst NICHT in ``total_quotes`` ein
    -- eigene, unabhaengige Kategorie, die Summeninvariante der drei
    Zitat-Zaehler bleibt unberuehrt.

    Args:
        db_path: Pfad zur Vault-SQLite-Datei.
        chapter_path: Pfad zur Kapiteldatei (Markdown) auf der Platte.

    Returns:
        Dict mit ``chapter_path``, ``total_quotes``, den drei Zitat-Zählern,
        ``not_audited`` (je Eintrag mit ``reason``), ``findings`` (offene
        Befunde, schwerste zuerst), ``erfasste_kennzahlen`` (Anzahl belegter
        Kennzahlen zu den referenzierten Papers) und ``table_values`` (die
        zugehörigen Datensätze).

    Raises:
        FileNotFoundError: ``chapter_path`` existiert nicht.
    """
    from .nli_prefilter import scan_chapter_quotes

    content = Path(chapter_path).read_text(encoding="utf-8")
    items = scan_chapter_quotes(content, db_path)

    audited_ok = 0
    findings: list[dict] = []
    not_audited: list[dict] = []

    _SEVERITY_ORDER = {"kritisch": 0, "hoch": 1, "mittel": 2}

    for item in items:
        quote_id = item["quote_id"]
        record = get_quote(db_path, quote_id)
        if record is None:
            continue  # Zwischen Scan und Lookup geloescht -- nicht bilanzierbar
        audited_at = record.get("audited_at")
        if audited_at is None:
            not_audited.append(
                {
                    "quote_id": quote_id,
                    "paper_id": item["paper_id"],
                    "verbatim": item["verbatim"],
                    "chapter_claim": item["chapter_claim"],
                    "reason": "kein Audit-Datensatz vorhanden",
                }
            )
            continue
        verdict = record.get("audit_verdict")
        if verdict == "faithful":
            audited_ok += 1
            continue
        findings.append(
            {
                "quote_id": quote_id,
                "paper_id": item["paper_id"],
                "verbatim": item["verbatim"],
                "chapter_claim": item["chapter_claim"],
                "verdict": verdict,
                "severity": record.get("audit_severity"),
            }
        )

    findings.sort(key=lambda f: _SEVERITY_ORDER.get(f["severity"], len(_SEVERITY_ORDER)))

    referenced_paper_ids = {item["paper_id"] for item in items}
    db = VaultDB(db_path)
    _ensure_schema_for_read(db_path)
    table_values = [tv for tv in db.list_table_values() if tv["paper_id"] in referenced_paper_ids]

    return {
        "chapter_path": chapter_path,
        "total_quotes": len(items),
        "geprueft_unauffaellig": audited_ok,
        "befund_offen": len(findings),
        "nicht_geprueft": len(not_audited),
        "not_audited": not_audited,
        "findings": findings,
        "erfasste_kennzahlen": len(table_values),
        "table_values": table_values,
    }


# Ab dieser Tokenlaenge darf der Teilwort-Zweig (papers_trgm) mitsuchen
# (Issue #703). Der FTS5-Trigram-Tokenizer indiziert Zeichenfolgen ab drei
# Zeichen -- ein 3-Zeichen-Token IST damit genau ein Trigram und traefe jede
# Wortmitte ("KMU" in "Werkmuseum", "IoT" in "Biotechnologie"). Vier ist die
# erste Laenge, ab der ein Token mehr als ein Trigram erzwingt; darunter
# bleibt jede Suche bitgleich auf dem alten, exakten Pfad. Als Konstante und
# nicht als Literal, damit die Schwelle testbar ist und nicht still
# verrutscht (tests/test_issue_703_fts_komposita.py).
_TRIGRAM_MIN_TOKEN_LEN = 4


def _trigram_match_expression(sanitized_query: str) -> str:
    """Reduziert eine bereits sanitisierte Query auf ihre trigram-tauglichen Tokens.

    Gibt einen MATCH-Ausdruck fuer ``papers_trgm`` zurueck (implizites AND
    ueber die verbleibenden Tokens) oder ``""``, wenn kein Token die
    Mindestlaenge erreicht -- dann bleibt der Teilwort-Zweig aus.
    """
    tokens = [t for t in sanitized_query.split() if len(t) >= _TRIGRAM_MIN_TOKEN_LEN]
    return " ".join(tokens)


def _fts_exact_hits(
    conn: sqlite3.Connection,
    query: str,
    type_filter: str | None,
    k: int,
) -> list[dict]:
    """Der unveraenderte unicode61-Zweig ueber ``papers_fts`` (Wort-Treffer).

    Bewusst als eigene Funktion herausgezogen (Issue #703): so laesst sich
    beweisen, dass der Teilwort-Zweig die bestehenden Treffer weder verdraengt
    noch umsortiert.
    """
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
    return [dict(r) for r in rows]


def _fts_trigram_hits(
    conn: sqlite3.Connection,
    query: str,
    type_filter: str | None,
    k: int,
) -> list[dict]:
    """Der Teilwort-Zweig ueber ``papers_trgm`` (Issue #703).

    Findet deutsche Komposita, von denen nur ein Bestandteil gesucht wurde
    (``Mittelstand`` -> ``Mittelstandsdigitalisierung``). Liefert ``[]``,
    wenn kein Token die Mindestlaenge erreicht oder ``papers_trgm`` auf einem
    Bestands-Vault noch fehlt -- ein fehlender Teilwort-Index darf eine Suche
    nie zum Absturz bringen, nur um ihre Zusatztreffer bringen.

    Die ``score``-Werte stammen aus dem bm25 EINER ANDEREN Tabelle und sind
    mit denen aus :func:`_fts_exact_hits` nicht vergleichbar. Deshalb werden
    die beiden Mengen in :func:`search_papers` blockweise aneinandergehaengt
    statt gemeinsam sortiert.
    """
    match = _trigram_match_expression(query)
    if not match:
        return []
    try:
        if type_filter:
            rows = conn.execute(
                """
                SELECT t.paper_id,
                       snippet(papers_trgm, -1, '<b>', '</b>', '...', 10) AS snippet,
                       rank AS score
                FROM papers_trgm t
                JOIN papers p ON p.paper_id = t.paper_id
                WHERE papers_trgm MATCH ?
                  AND p.type = ?
                ORDER BY rank
                LIMIT ?
                """,
                (match, type_filter, k),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT paper_id,
                       snippet(papers_trgm, -1, '<b>', '</b>', '...', 10) AS snippet,
                       rank AS score
                FROM papers_trgm
                WHERE papers_trgm MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (match, k),
            ).fetchall()
    except sqlite3.OperationalError:
        # Bestands-Vault ohne papers_trgm (Migration noch nicht gelaufen) oder
        # SQLite-Build ohne Trigram-Tokenizer: exakte Suche allein ist ein
        # gueltiges Ergebnis, ein roher OperationalError waere keins.
        return []
    return [dict(r) for r in rows]


def search_papers(
    db_path: str,
    query: str,
    type_filter: str | None = None,
    k: int = 5,
    rerank: bool = False,
) -> list[dict]:
    """FTS5/Hybrid-Suche in papers_fts. Gibt [{paper_id, snippet, score}] zurueck.

    Seit Issue #703 haengt die Funktion hinter die exakten Wort-Treffer aus
    ``papers_fts`` einen zweiten Block: Teilwort-Treffer aus ``papers_trgm``,
    damit `Mittelstand` auch `Mittelstandsdigitalisierung` findet. Der zweite
    Block fuellt nur auf, was der erste an ``k`` uebrig laesst -- die exakten
    Treffer bleiben damit Praefix des Ergebnisses, in unveraenderter
    Reihenfolge.

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
        fts_results = _fts_exact_hits(conn, query, type_filter, k)
        # Teilwort-Zweig nur, solange `k` noch nicht ausgeschoepft ist
        # (Issue #703): so kann er einen exakten Treffer weder verdraengen
        # noch umsortieren, und eine Suche, die schon vorher `k` volle
        # Treffer hatte, bleibt bitgleich.
        if len(fts_results) < k:
            seen = {r["paper_id"] for r in fts_results}
            for row in _fts_trigram_hits(conn, query, type_filter, k):
                if row["paper_id"] in seen:
                    continue
                fts_results.append(row)
                seen.add(row["paper_id"])
                if len(fts_results) >= k:
                    break
    finally:
        conn.close()

    if not rerank:
        return fts_results

    from .retrieval import apply_reranker, reciprocal_rank_fusion

    # Der Vektorpfad bekommt die UNSANITIERTE Query: das FTS5-Sanitizing
    # entfernt Bindestriche und Operator-Keywords und verfaelscht damit die
    # Semantik, auf die das Embedding-Modell reagiert.
    fused = reciprocal_rank_fusion(
        _vec0_search(db_path, raw_query, k=k), fts_results, k=60, top_n=k
    )
    _fill_missing_reranker_text(db_path, fused)

    voyage_key = os.environ.get("VOYAGE_API_KEY") or None
    cohere_key = os.environ.get("COHERE_API_KEY") or None

    # Kein Gate mehr auf "irgendein Cloud-Key gesetzt" (#376): apply_reranker
    # wird immer aufgerufen, damit auch ohne Cloud-Keys der kostenfreie lokale
    # bge-reranker-v2-m3-Fallback greifen kann. Ohne diesen Aufruf bliebe der
    # lokale Fallback in retrieval.py toter Code.
    #
    # query=raw_query statt der FTS5-sanitisierten Variante (#702): das
    # Sanitizing entfernt Bindestriche und Operator-Keywords und verfaelscht
    # damit die Semantik, gegen die ein Cross-Encoder bewertet -- derselbe
    # Grund, aus dem _vec0_search oben bereits raw_query bekommt.
    return apply_reranker(
        query=raw_query,
        candidates=fused,
        voyage_api_key=voyage_key,
        cohere_api_key=cohere_key,
    )


def _fill_missing_reranker_text(db_path: str, fused: list[dict]) -> None:
    """Ergaenzt fehlenden Reranker-Text fuer rein per FTS5 gefundene Kandidaten (#702).

    vec0-Treffer bringen ueber ``_vec0_search`` bereits den vollen Chunk-Text
    als ``text`` mit. FTS5-only-Treffer haben das Feld nie -- ohne diese
    Ergaenzung faellt ``apply_reranker`` auf sein eigenes 10-Token-Snippet mit
    '<b>'-Markup zurueck (der gemeldete Bug). Prioritaet: Abstract > erster
    gespeicherter Chunk-Text > Snippet (mit Log, AC5). Mutiert die
    uebergebenen Dicts in-place.

    Ein zusaetzlicher DB-Zugriff pro FTS5-only-Treffer ist bewusst in Kauf
    genommen: ``k`` ist klein (Standard 5), ein Batch-Lookup wuerde hier keinen
    messbaren Unterschied machen.
    """
    missing = [entry for entry in fused if not entry.get("text")]
    if not missing:
        return
    db = VaultDB(db_path)
    for entry in missing:
        paper_id = entry["paper_id"]
        paper = db.get_paper(paper_id)
        abstract = ""
        if paper is not None:
            try:
                csl = json.loads(paper.get("csl_json") or "{}")
            except json.JSONDecodeError:
                csl = {}
            abstract = csl.get("abstract") or ""
        if abstract.strip():
            entry["text"] = abstract
            continue
        chunk_text = db.get_first_chunk_text(paper_id)
        if chunk_text:
            entry["text"] = chunk_text
            continue
        logger.warning(
            "Kein Abstract und kein Chunk-Text fuer Reranker-Kandidat %s "
            "gefunden -- Fallback auf das FTS5-Snippet (moeglicherweise "
            "gekuerzt und mit Markup, apply_reranker haertet das ab).",
            paper_id,
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
    except EmbeddingDimensionMismatchError:
        # Carve-out (#629): hier still auf FTS5-only zurueckzufallen waere die
        # teuerste Variante des Fehlers -- die Suche liefe weiter und lieferte
        # ploetzlich nur noch Volltext-Treffer, ohne dass jemand erfaehrt,
        # dass der halbe Index unerreichbar ist.
        raise
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
    except EmbeddingDimensionMismatchError:
        # Carve-out (#629): ein falsch konfiguriertes Modell ist kein
        # Degradationsfall. Bliebe es hier eine Log-Zeile, liefe der Vault
        # weiter voll mit Papern ohne Vektoren -- genau die stille Variante,
        # die #629 abstellt. Das Paper selbst ist bereits committet.
        raise
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


def verify_citations(db_path: str, items: list[dict]) -> list[dict]:
    """Batch-Variante von :func:`verify_citation` (Issue #501).

    Prueft mehrere Belege (Autor/Jahr/Seite) gegen den Vault in EINEM
    Papers-Scan statt N: ``VaultDB.find_papers_by_author_year()`` liest und
    parst je Aufruf die komplette ``papers``-Tabelle. Bei N Belegen pro Write
    (bis ``ACADEMIC_CITATION_MAX_PER_WRITE``, Default 100) summiert sich das
    innerhalb des 10-s-Timeouts von ``hooks/verbatim-guard.mjs``. Diese
    Funktion teilt sich eine ``VaultDB``-Instanz und einen einzigen
    :meth:`~academic_vault.db.VaultDB._papers_snapshot`-Aufruf ueber alle
    Items; das Matching pro Item laeuft danach nur noch in-memory ueber den
    bereits geparsten Snapshot (kein O(1)-Lookup, siehe Docstring von
    :meth:`~academic_vault.db.VaultDB._match_papers_in_snapshot` --
    ``normalize_family_name()`` liefert ein Set aus Schreibvarianten, das sich
    nicht per Dict-Key exakt cachen laesst).

    ``items``: Liste von ``{"family": str, "year": int, "page": int | None,
    "page_end": int | None}`` — ``page_end`` beschreibt einen Seitenbereich
    (z. B. "S. 45-47", Issue #724) und ist optional/fehlend gleichbedeutend mit
    einer Einzelseite.
    Rueckgabe: Liste von ``{"status": ..., "paper_ids": [...]}``, bei
    ``"page-mismatch"`` zusaetzlich ``{"vault_pages": [...], "vault_ranges":
    [[first, last], ...]}`` mit den im Vault hinterlegten Seiten fuer die
    Blockmeldung (Issue #724, AC1) -- in derselben Reihenfolge wie ``items``.
    Status-Bedeutung siehe :func:`verify_citation`.
    """
    db = VaultDB(db_path)
    snapshot = db._papers_snapshot()
    results: list[dict] = []
    for item in items:
        papers = db._match_papers_in_snapshot(snapshot, item["family"], int(item["year"]))
        if not papers:
            results.append({"status": "no-match", "paper_ids": []})
            continue

        paper_ids = [p["paper_id"] for p in papers]
        page = item.get("page")
        if page is None:
            results.append({"status": "verified", "paper_ids": paper_ids})
            continue

        page_end = item.get("page_end")
        coverages = [
            db.page_coverage(pid, int(page), None if page_end is None else int(page_end))
            for pid in paper_ids
        ]
        if any(c in ("covered", "unknown") for c in coverages):
            results.append({"status": "verified", "paper_ids": paper_ids})
        else:
            vault_pages: set[int] = set()
            vault_ranges: list[list[int]] = []
            for pid in paper_ids:
                samples, first, last = db.known_page_markers(pid)
                vault_pages.update(samples)
                if first is not None and last is not None:
                    vault_ranges.append([first, last])
            results.append(
                {
                    "status": "page-mismatch",
                    "paper_ids": paper_ids,
                    "vault_pages": sorted(vault_pages),
                    "vault_ranges": vault_ranges,
                }
            )
    return results


def verify_citation(
    db_path: str,
    family: str,
    year: int,
    page: int | None = None,
    page_end: int | None = None,
) -> dict:
    """Prueft einen Klammer-Beleg (Autor/Jahr/Seite) gegen den Vault (Issue #378).

    Kein MCP-Tool-Dekorator: die Funktion wird ausschliesslich aus
    ``hooks/verbatim-guard.mjs`` per ``python3 -c``-Subprozess aufgerufen
    (analog zu :func:`search_quote_text` und :func:`find_figure_by_caption`).
    Duenner Ein-Item-Wrapper ueber :func:`verify_citations` (Issue #501).

    ``page_end`` beschreibt einen Seitenbereich ("S. 45-47", Issue #724);
    ``None`` bedeutet eine Einzelseite.

    Rueckgabe ``{"status": ..., "paper_ids": [...]}`` (bei "page-mismatch"
    zusaetzlich ``vault_pages``/``vault_ranges``, siehe :func:`verify_citations`)
    mit Status:
      ``"verified"``      — Autor/Jahr im Vault und (falls angegeben) Seite gedeckt
                            bzw. mangels Seitendaten nicht widerlegbar.
      ``"page-mismatch"`` — Autor/Jahr im Vault, Seite liegt nachweislich
                            ausserhalb aller bekannten Seitenbereiche/-stichproben.
                            Der Vault ist hier autoritativ; die externe Kaskade
                            kann Seitenzahlen nicht pruefen und wird uebersprungen.
      ``"no-match"``      — kein Paper mit dieser Autor/Jahr-Kombination.
    """
    return verify_citations(
        db_path, [{"family": family, "year": year, "page": page, "page_end": page_end}]
    )[0]


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
# Empirischer Teil: Transkript-Segmente + Kodierungen (Issue #473)
# ---------------------------------------------------------------------------


def add_transcript_segment(
    db_path: str,
    paper_id: str,
    seq: int,
    text: str,
    speaker: str | None = None,
    timecode: str | None = None,
) -> str:
    """Upsert eines Transkript-Segments. Gibt die segment_id zurueck.

    ``seq`` ist die zitierfaehige Absatznummer und zugleich der
    Idempotenz-Schluessel: ein erneuter Import derselben Datei aktualisiert
    die Zeile, statt eine zweite anzulegen.
    """
    db = VaultDB(db_path)
    db.init_schema()
    return db.add_transcript_segment(
        paper_id=paper_id, seq=seq, text=text, speaker=speaker, timecode=timecode
    )


def list_transcript_segments(db_path: str, paper_id: str) -> list[dict]:
    """Gibt alle Segmente eines Transkripts in seq-Reihenfolge zurueck."""
    db = VaultDB(db_path)
    _ensure_schema_for_read(db_path)
    return db.list_transcript_segments(paper_id)


def add_coding(
    db_path: str,
    paper_id: str,
    category: str,
    category_origin: str,
    segment_id: str | None = None,
    quote_id: str | None = None,
    memo: str | None = None,
) -> str:
    """Ordnet einer Stelle eine Kategorie zu. Gibt coding_id zurueck.

    ``category_origin`` ist Pflicht (``induktiv``/``deduktiv``) — ohne die
    Herkunft ist die Kategorienbildung nicht dokumentiert.
    """
    db = VaultDB(db_path)
    db.init_schema()
    return db.add_coding(
        paper_id=paper_id,
        category=category,
        category_origin=category_origin,
        segment_id=segment_id,
        quote_id=quote_id,
        memo=memo,
    )


def list_codings(
    db_path: str,
    paper_id: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """Gibt Kodierungen zurueck, optional nach Paper und/oder Kategorie gefiltert."""
    db = VaultDB(db_path)
    _ensure_schema_for_read(db_path)
    return db.list_codings(paper_id=paper_id, category=category)


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
    source_kind: str | _Unset = _UNSET,
) -> None:
    """Upsert eines Papers in den Vault. Unterstuetzt type=book|chapter.

    source_kind: ``"literature"`` (Default) oder ``"primary"`` fuer eigenes
    Erhebungsmaterial wie Transkripte (#473).

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
        source_kind=source_kind,
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


def get_stats(db_path: str) -> dict:
    """Gibt Statistik-Dict zurueck: paper_count, quote_count, embedding_model, embedding_dim.

    Keine Token-Ersparnis-Schaetzung (#534) und seit #632 auch kein
    ``cached_files`` mehr: der Files-API-Upload-Cache ist mit dem
    Anthropic-SDK entfallen, ein dauerhaft auf 0 stehendes Feld waere genau
    die Phantomgroesse, die die Honesty-Linie #387/#453 verbietet.

    ``embedding_model``/``embedding_dim`` (Issue #629) machen den Bestand
    ablesbar, ohne in den Code zu sehen: mit welchem Modell und in welcher
    Breite die Vektoren dieses Vaults entstanden sind. Beide sind ``None``,
    solange noch nie ein Embedding geschrieben wurde -- das ist eine Aussage
    ueber den Bestand, keine ueber die Konfiguration, und es wird dafuer
    ausdruecklich kein Modell geladen.
    """
    conn = VaultDB._open(db_path)
    try:
        paper_count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        quote_count = conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]
    finally:
        conn.close()

    inventory = VaultDB(db_path).embedding_inventory()

    return {
        "paper_count": paper_count,
        "quote_count": quote_count,
        "embedding_model": inventory["model_id"] if inventory else None,
        "embedding_dim": inventory["dim"] if inventory else None,
    }


def component_status(db_path: str) -> dict:
    """Zustandsausgabe fuer die optionalen Vault-Bestandteile (Issue #624).

    Meldet je Embedding-Modell, sqlite-vec und FTS5, ob geladen und welche
    Funktion bei Nichtladen fehlt -- siehe :func:`academic_vault.health.get_component_status`.
    """
    return get_component_status(db_path)


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
# Vault-weite Retraction-Pruefung (Issue #604)
# ---------------------------------------------------------------------------

_DEFAULT_KAPITEL_DIRNAME = "kapitel"


def check_retractions(
    db_path: str,
    max_age_days: int = 90,
    force: bool = False,
    project_dir: str = ".",
) -> dict:
    """Prueft alle Vault-Papers mit DOI vault-weit auf Rueckzug (Issue #604).

    Iteriert ueber alle Papers mit ``source_kind='literature'`` -- unabhaengig
    davon, ueber welchen Weg sie in den Vault kamen (zotero-import,
    reading-list-import, anchor-paper-survey, github-repo-research, fetch,
    ...; AC1). Nutzt die geteilte Crossref-Logik aus
    ``academic_vault.retraction`` (AC2, dieselbe Logik wie
    ``reading-list-import``).

    Ein Paper wird nur erneut geprueft, wenn es noch nie geprueft wurde oder
    die letzte Pruefung laenger als ``max_age_days`` zurueckliegt;
    ``force=True`` erzwingt eine erneute Pruefung fuer alle Papers mit DOI
    (AC3). Ein Crossref-Ausfall aktualisiert den Zeitstempel NICHT -- der
    naechste Lauf versucht das betroffene Paper automatisch erneut.

    Ein gefundener Rueckzug wird nur VORGELEGT, nie automatisch nach
    ``excluded_sources`` geschrieben (AC4) -- das unterscheidet diesen Weg
    bewusst von ``reading-list-import.check_retraction()``, der weiterhin
    automatisch ausschliesst (Plan-Kommentar zu #604, Widerspruch 1). Jeder
    Treffer traegt seine Fundstelle (``source``, der Crossref-DOI der
    Retraction-Notiz) sowie ein ``cited_in_chapter``-Flag: eine heuristische
    (Autor-Familienname + Jahr, s. ``db.paper_cited_in_chapters``) Pruefung,
    ob das Paper bereits in einem Kapiteltext unter ``<project_dir>/kapitel/``
    vorkommt (AC5).

    Papers ohne DOI erscheinen unter ``no_doi`` -- "nicht pruefbar", nicht
    stillschweigend uebergangen (AC6). Ein Crossref-Ausfall pro Paper landet
    unter ``error`` mit Klartext-Ursache; ``error_count`` macht einen
    Teilausfall im Gesamtergebnis sichtbar statt ihn wie ein leeres "keine
    Rueckzuege"-Resultat aussehen zu lassen (AC7).

    Rueckgabe:
        {
          "retracted": [{"paper_id", "doi", "source", "cited_in_chapter"}, ...],
          "clean": [paper_id, ...],
          "error": [{"paper_id", "doi", "error_message"}, ...],
          "no_doi": [paper_id, ...],
          "checked_count": int,   # tatsaechlich gegen Crossref geprueft
          "skipped_fresh_count": int,  # uebersprungen, da noch nicht "stale"
          "error_count": int,
        }
    """
    db = VaultDB(db_path)
    db.init_schema()

    papers = db.list_literature_papers()
    now = int(time.time())
    stale_cutoff = now - max_age_days * 86400
    kapitel_dir = Path(project_dir) / _DEFAULT_KAPITEL_DIRNAME

    result: dict = {
        "retracted": [],
        "clean": [],
        "error": [],
        "no_doi": [],
        "checked_count": 0,
        "skipped_fresh_count": 0,
    }

    for paper in papers:
        paper_id = paper["paper_id"]
        doi = paper.get("doi")
        if not doi:
            result["no_doi"].append(paper_id)
            continue

        checked_at = paper.get("retraction_checked_at")
        is_fresh = not force and checked_at is not None and checked_at >= stale_cutoff
        if is_fresh:
            result["skipped_fresh_count"] += 1
            continue

        check = _retraction.check_retraction(doi)
        result["checked_count"] += 1

        if check.status == "error":
            result["error"].append(
                {"paper_id": paper_id, "doi": doi, "error_message": check.error_message}
            )
            continue  # kein Timestamp-Update -- naechster Lauf versucht erneut.

        if check.status == "clean":
            db.update_retraction_checked_at(paper_id, now)
            result["clean"].append(paper_id)
            continue

        # status == "retracted"
        # Timestamp NICHT aktualisieren -- der Rückzug soll in jedem Lauf
        # angezeigt werden, bis der Nutzer eine Entscheidung trifft (AC4).
        # Analog zum Nicht-Update bei "error".
        try:
            csl = json.loads(paper.get("csl_json") or "{}")
        except json.JSONDecodeError:
            csl = {}
        cited = paper_cited_in_chapters(csl, kapitel_dir)
        result["retracted"].append(
            {
                "paper_id": paper_id,
                "doi": doi,
                "source": check.source,
                "cited_in_chapter": cited,
            }
        )

    result["error_count"] = len(result["error"])
    return result


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
    plugin_version: str | None = None,
    model_versions: dict | None = None,
    per_uni_profile_hash: str | None = None,
) -> str:
    """Exportiert Material-Passport als material-passport.json.

    Gibt den Pfad zur erzeugten Datei zurueck.
    """
    from .material_passport import build_passport, read_plugin_version, validate_passport

    if plugin_version is None:
        plugin_version = read_plugin_version()

    db = VaultDB(db_path)
    db.init_schema()

    conn = VaultDB._open(db_path)
    try:
        paper_rows = conn.execute("SELECT paper_id, doi FROM papers ORDER BY paper_id").fetchall()
    finally:
        conn.close()

    paper_ids = [r["paper_id"] for r in paper_rows]
    dois = [r["doi"] for r in paper_rows if r["doi"]]
    # Nur methodische Entscheidungen. Die Auto-Eintraege der Kategorie
    # `file-change`, die der PostToolUse-Hook seit #527 bei jedem `.md`-Write
    # schreibt, sind kein Material: sie wuerden den Snapshot fluten und den
    # `passport_hash` bei jeder Kapitel-Aenderung bewegen, obwohl sich am
    # Material nichts geaendert hat (#380). Symmetrisch dazu ist die Kategorie
    # `model-version` (#617) Material-Herkunft, keine methodische Entscheidung
    # -- sie fliesst stattdessen in `model_versions` (siehe unten).
    decisions = [
        d
        for d in db.list_decisions(active_only=True)
        if d.get("category") not in (_AUTO_DECISION_CATEGORY, _MODEL_VERSION_CATEGORY)
    ]

    # model_versions aus den `model-version`-Decisions herleiten (#617):
    # Text-Konvention "<schritt>: <modell>". Malformed Eintraege werden
    # uebersprungen statt den Export scheitern zu lassen. Ein explizit
    # uebergebenes `model_versions`-Kwarg gewinnt bei Kollision.
    model_versions_from_decisions: dict[str, str] = {}
    for d in db.list_decisions(category=_MODEL_VERSION_CATEGORY, active_only=True):
        parsed = _parse_model_version_text(d.get("text") or "")
        if parsed is not None:
            step, model_id = parsed
            # Only keep the first (newest) decision per step (list_decisions returns DESC by created_at)
            model_versions_from_decisions.setdefault(step, model_id)
    merged_model_versions = {**model_versions_from_decisions, **(model_versions or {})}

    scores_5d: dict = {}
    for pid in paper_ids:
        history = db.get_score_history(pid, k=1)
        if history:
            scores_5d[pid] = json.loads(history[0]["scores_json"])

    pdf_hashes = _compute_pdf_hashes(db_path)
    quote_extraction_methods, manual_quotes_count, total_quotes_count = (
        _compute_quote_extraction_summary(db_path)
    )
    manual_quotes_ratio = manual_quotes_count / total_quotes_count if total_quotes_count else 0.0

    passport = build_passport(
        slug=slug,
        paper_ids=paper_ids,
        dois=dois,
        scores_5d=scores_5d,
        score_algo_version=score_algo_version,
        plugin_version=plugin_version,
        model_versions=merged_model_versions,
        per_uni_profile_hash=per_uni_profile_hash,
        decisions_snapshot=decisions,
        pdf_hashes=pdf_hashes,
        quote_extraction_methods=quote_extraction_methods,
        manual_quotes_count=manual_quotes_count,
        manual_quotes_ratio=manual_quotes_ratio,
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


def _compute_quote_extraction_summary(db_path: str) -> tuple[dict[str, str], int, int]:
    """Liest ``extraction_method`` je Zitat aus dem Vault (#595).

    Eine Vault-DB entspricht einem Projekt/Slug -- kein WHERE-Filter noetig
    (analog zur ``paper_rows``-Query in :func:`export_material_passport`).

    Gibt ``(quote_extraction_methods, manual_count, total_count)`` zurueck:
    ``quote_extraction_methods`` ist ``{quote_id: extraction_method}`` fuer
    ALLE Zitate im Vault, ``manual_count`` die Anzahl mit
    ``extraction_method == 'manual'``, ``total_count`` die Gesamtzahl.
    """
    conn = VaultDB._open(db_path)
    try:
        rows = conn.execute("SELECT quote_id, extraction_method FROM quotes").fetchall()
    finally:
        conn.close()

    quote_extraction_methods = {row["quote_id"]: row["extraction_method"] for row in rows}
    manual_count = sum(1 for row in rows if row["extraction_method"] == "manual")
    return quote_extraction_methods, manual_count, len(rows)


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


def extract_tables_for_paper(
    db_path: str,
    paper_id: str,
    backend: str = "auto",
) -> dict:
    """Extrahiert die Tabellen eines Papers strukturerhaltend (Issue #630).

    Laeuft **neben** dem Volltextpfad: ``paper_fulltext`` und ``papers_fts``
    werden nicht angefasst, der FTS5-Volltext bleibt byteweise identisch.
    Fehlt das optionale Backend, ist das Ergebnis ein sichtbarer Status mit
    Installationsanweisung statt einer Exception — der Volltextpfad laeuft
    unveraendert weiter.

    Args:
        db_path: Pfad zur Vault-DB.
        paper_id: Paper mit hinterlegtem ``pdf_path``.
        backend: ``"auto"`` oder ``"pdfplumber"``.

    Returns:
        ``{"paper_id", "status", "message", "backend", "tables", "cells"}``.
        ``status`` ist ``"ok"``, ``"no-tables"``, ``"no-textlayer"`` oder
        ``"backend-missing"``; ``tables``/``cells`` sind Anzahlen.

    Raises:
        ValueError: Paper unbekannt oder ohne ``pdf_path``.
        FileNotFoundError: Hinterlegter ``pdf_path`` existiert nicht.
        VaultLockedError: Der Materialpass ist eingefroren.
    """
    from .tables import STATUS_OK, extract_tables

    db = VaultDB(db_path)
    db.init_schema()
    paper = db.get_paper(paper_id)
    if paper is None:
        raise ValueError(f"Paper unbekannt: {paper_id}")
    pdf_path = (paper.get("pdf_path") or "").strip()
    if not pdf_path:
        raise ValueError(f"Paper '{paper_id}' hat keinen pdf_path -- nichts zu extrahieren.")

    result = extract_tables(pdf_path, backend=backend)
    found = result["tables"]
    if result["status"] == STATUS_OK:
        db.set_paper_tables(paper_id, found, result["backend"])
    return {
        "paper_id": paper_id,
        "status": result["status"],
        "message": result["message"],
        "backend": result["backend"],
        "tables": len(found),
        "cells": sum(len(table["cells"]) for table in found),
    }


def add_table_value(
    db_path: str,
    paper_id: str,
    page: int,
    table_index: int,
    row: int,
    col: int,
    claimed_value: str,
) -> str | dict:
    """Erfasst eine Kennzahl aus einer Tabellenzelle belegfaehig (Issue #741).

    Der Weg von einer Zahl in einer Studientabelle in den Kapiteltext, analog
    zu ``add_quote`` fuer Wortlaut: FAIL-CLOSED, vor jedem Schreibzugriff wird
    ``claimed_value`` gegen die tatsaechliche Zelle
    (:func:`get_table_cell`/``VaultDB.get_table_cell``) geprueft
    (:func:`academic_vault.numbers.numbers_equivalent`, toleriert
    Dezimalkomma/-punkt, Tausendertrennzeichen, fuehrende Nullen und ein
    Prozentzeichen -- keine echte Werteabweichung).

    Ist die Tabelle fuer diese ``page``/``table_index``-Kombination noch nicht
    extrahiert, wird :func:`extract_tables_for_paper` einmalig automatisch
    versucht (AC5). Meldet sie ``status="backend-missing"``, gibt dieser
    Aufruf denselben Statusreport als ``dict`` zurueck (Praezedenzfall
    :func:`extract_tables_for_paper` -- ein fehlendes optionales Backend ist
    ein sichtbarer Zustand, keine Ausnahme) und speichert NICHTS. Bleibt die
    Zelle danach unauffindbar (z. B. falsche ``row``/``col``, oder die
    Tabelle enthaelt tatsaechlich keine Tabelle an dieser Stelle), ist das
    weiterhin ein ``ValueError`` OHNE dass etwas gespeichert wird -- das ist
    ein echter Auffindbarkeitsfehler, kein Backend-Zustand.

    Args:
        db_path: Pfad zur Vault-DB.
        paper_id: Bekanntes Paper mit extrahierbarem PDF.
        page: PDF-Seite (1-basiert, wie bei ``vault.get_table_cell``).
        table_index: Tabellenindex auf der Seite (0-basiert).
        row: Zeile in der Tabelle (0-basiert).
        col: Spalte in der Tabelle (0-basiert).
        claimed_value: Die behauptete Kennzahl, so wie sie im Kapiteltext
            stehen soll (roh, vor jeder Normalisierung).

    Returns:
        ``table_value_id`` (``str``) des gespeicherten Datensatzes im
        Erfolgsfall, oder der Statusreport (``dict`` mit ``status``,
        ``message``, ``backend``) von :func:`extract_tables_for_paper`, falls
        das Tabellen-Backend fehlt -- dann wurde NICHTS gespeichert.

    Raises:
        ValueError: Paper unbekannt, die Zelle ist trotz vorhandenem Backend
            nicht auffindbar, oder ``claimed_value`` stimmt nicht mit der
            Zelle ueberein (Meldung nennt gefundenen UND behaupteten Wert).
        VaultLockedError: Vault ist gesperrt (Material-Passport-Lock).
    """
    from .numbers import numbers_equivalent
    from .tables import STATUS_BACKEND_MISSING

    db = VaultDB(db_path)
    db.init_schema()
    paper = db.get_paper(paper_id)
    if paper is None:
        raise ValueError(f"vault.add_table_value: Paper unbekannt: {paper_id}")

    cell = db.get_table_cell(paper_id, page, table_index, row, col)
    if cell is None:
        table_known = any(
            t["table_index"] == table_index for t in db.list_paper_tables(paper_id, page=page)
        )
        if not table_known:
            extraction = extract_tables_for_paper(db_path, paper_id)
            if extraction["status"] == STATUS_BACKEND_MISSING:
                return extraction
            cell = db.get_table_cell(paper_id, page, table_index, row, col)
        if cell is None:
            raise ValueError(
                f"vault.add_table_value: Zelle (page={page}, table_index={table_index}, "
                f"row={row}, col={col}) nicht gefunden fuer Paper '{paper_id}' -- "
                "es wurde NICHTS gespeichert."
            )

    if not numbers_equivalent(claimed_value, cell["value"]):
        raise ValueError(
            f"vault.add_table_value: Kennzahl stimmt nicht mit der Zelle ueberein "
            f"(gefunden='{cell['value']}', behauptet='{claimed_value}') fuer "
            f"{cell['evidence']} -- es wurde NICHTS gespeichert."
        )

    table_value_id = str(uuid4())
    db.add_table_value(
        table_value_id=table_value_id,
        paper_id=paper_id,
        page=cell["page"],
        table_index=cell["table_index"],
        row=row,
        col=col,
        claimed_value=claimed_value,
        cell_value=str(cell["value"]),
        evidence=cell["evidence"],
    )
    return table_value_id


def list_table_values(db_path: str, paper_id: str | None = None) -> list[dict]:
    """Gibt erfasste Kennzahlen zurueck, optional nach Paper gefiltert (#741)."""
    _ensure_schema_for_read(db_path)
    return VaultDB(db_path).list_table_values(paper_id=paper_id)


def list_paper_tables(db_path: str, paper_id: str, page: int | None = None) -> list[dict]:
    """Gibt die gespeicherten Tabellenstrukturen eines Papers zurueck (Issue #630)."""
    _ensure_schema_for_read(db_path)
    return VaultDB(db_path).list_paper_tables(paper_id, page=page)


def get_table_cell(
    db_path: str,
    paper_id: str,
    page: int,
    table_index: int,
    row: int,
    col: int,
) -> dict | None:
    """Loest eine Tabellenzelle zu Wert und Beleg auf (Issue #630 AC2).

    ``None`` bei unbekannter Zelle — ein geratener Beleg waere schlimmer als
    gar keiner.
    """
    _ensure_schema_for_read(db_path)
    return VaultDB(db_path).get_table_cell(paper_id, page, table_index, row, col)


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
        source_kind: str | _Unset = _UNSET,
    ) -> None:
        """Upsert eines Papers. type aus csl_json; book|chapter|article-journal erlaubt.

        provenance: Herkunfts-Tag (z.B. "scihub") fuer Provenance-Audit (#195).
        source_kind: "literature" (Default) oder "primary" fuer eigenes
        Erhebungsmaterial (#473).

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
            source_kind=source_kind,
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
        """Fuegt Quote ein. extraction_method: 'citations-api' | 'manual' | 'local-verbatim'.

        'citations-api' erfordert api_response_id. 'local-verbatim' (#512) wird
        fail-closed gegen den lokalen PDF-Volltext des Papers geprueft: ist der
        Wortlaut dort nicht auffindbar (oder fehlt ein lesbarer pdf_path), wirft
        der Aufruf ValueError und es wird NICHTS gespeichert; bei Erfolg landen
        der Wortlaut AUS DER QUELLE und die VERIFIZIERTE Seite im Vault (ein
        abweichend uebergebenes pdf_page wird verworfen). 'manual' bleibt
        ungeprueft und ist der Ausweichweg fuer seitenuebergreifende Zitate.

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

    @mcp.tool(name="vault.verify_verbatim")
    def _vault_verify_verbatim(paper_id: str, candidate: str) -> dict:
        """Prueft einen Zitat-Kandidaten read-only gegen das lokale PDF (#513).

        Liefert IMMER ein Ergebnis-dict zurueck --
        {status, verbatim, pdf_page, ratio} mit status aus 'exact'/'snapped'/
        'no-match'/'no-textlayer' -- auch bei no-match/no-textlayer, ohne
        ValueError. Schreibt nichts in die DB. Fuer den Schreibpfad siehe
        vault.add_quote(extraction_method='local-verbatim'), das denselben
        Pruefpfad fail-closed durchsetzt. Paper unbekannt oder kein/kein
        lesbarer pdf_path wirft weiterhin ValueError (Bedienfehler, kein
        Pruefergebnis).
        """
        return verify_verbatim_preview(db_path, paper_id, candidate)

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

    @mcp.tool(name="vault.set_quote_stance")
    def _vault_set_quote_stance(quote_id: str, stance: str) -> None:
        """Aktualisiert stance eines bestehenden Zitats (Issue #523).

        stance: 'supports' | 'contrasts' | 'mentions' -- Pflichtfeld, kein
        None. Nachtraeglicher Audit-Schreibpfad fuer den
        quote-fidelity-auditor-Agenten; wirft ValueError bei ungueltigem
        stance-Wert oder unbekannter quote_id.
        """
        set_quote_stance(db_path=db_path, quote_id=quote_id, stance=stance)

    @mcp.tool(name="vault.record_quote_audit")
    def _vault_record_quote_audit(quote_id: str, verdict: str, severity: str | None = None) -> None:
        """Protokolliert ein Audit-Urteil eines bestehenden Zitats (Issue #737).

        Additiv zu vault.set_quote_stance -- IMMER zusaetzlich aufrufen,
        auch bei verdict='unsupported' (dort bleibt set_quote_stance aus).
        severity ist Pflicht ausser bei verdict='faithful' (dann None).
        Wirft ValueError bei ungueltiger Kombination oder unbekannter
        quote_id.
        """
        record_quote_audit(db_path=db_path, quote_id=quote_id, verdict=verdict, severity=severity)

    @mcp.tool(name="vault.chapter_quote_balance")
    def _vault_chapter_quote_balance(chapter_path: str) -> dict:
        """Pruefbilanz fuer ein Kapitel: geprueft/Befund offen/nicht geprueft (Issue #737).

        Deckt das GESAMTE Kapitel ab, nicht nur die letzte Schreib-Sitzung.
        Belegt keine korrekte Verwendung geprueften Zitate -- priorisiert die
        Pruefkette, ersetzt sie nicht.
        """
        return chapter_quote_balance(db_path=db_path, chapter_path=chapter_path)

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

    @mcp.tool(name="vault.add_transcript_segment")
    def _vault_add_transcript_segment(
        paper_id: str,
        seq: int,
        text: str,
        speaker: str | None = None,
        timecode: str | None = None,
    ) -> str:
        """Nimmt einen Transkript-Absatz belegfaehig auf (seq = Stellenangabe, #473)."""
        return add_transcript_segment(
            db_path, paper_id=paper_id, seq=seq, text=text, speaker=speaker, timecode=timecode
        )

    @mcp.tool(name="vault.list_transcript_segments")
    def _vault_list_transcript_segments(paper_id: str) -> list[dict]:
        """Gibt alle Segmente eines Transkripts in seq-Reihenfolge zurueck (#473)."""
        return list_transcript_segments(db_path, paper_id)

    @mcp.tool(name="vault.add_coding")
    def _vault_add_coding(
        paper_id: str,
        category: str,
        category_origin: str,
        segment_id: str | None = None,
        quote_id: str | None = None,
        memo: str | None = None,
    ) -> str:
        """Ordnet einer Stelle eine Kategorie zu (induktiv|deduktiv, #473)."""
        return add_coding(
            db_path,
            paper_id=paper_id,
            category=category,
            category_origin=category_origin,
            segment_id=segment_id,
            quote_id=quote_id,
            memo=memo,
        )

    @mcp.tool(name="vault.list_codings")
    def _vault_list_codings(paper_id: str | None = None, category: str | None = None) -> list[dict]:
        """Gibt Kodierungen zurueck, optional nach Paper/Kategorie gefiltert (#473)."""
        return list_codings(db_path, paper_id=paper_id, category=category)

    @mcp.tool(name="vault.stats")
    def _vault_stats() -> dict:
        """Counts: paper_count, quote_count -- plus embedding_model/embedding_dim (#629)."""
        return get_stats(db_path)

    @mcp.tool(name="vault.component_status")
    def _vault_component_status() -> dict:
        """Zustand optionaler Bestandteile: Embedding-Modell, sqlite-vec, FTS5 (#624)."""
        return component_status(db_path)

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

    @mcp.tool(name="vault.extract_tables")
    def _vault_extract_tables(paper_id: str, backend: str = "auto") -> dict:
        """Extrahiert Tabellen strukturerhaltend (Zeilen/Spalten/Zellen, #630).

        Laeuft neben dem Volltextpfad -- papers_fts bleibt unveraendert. status:
        "ok" | "no-tables" | "no-textlayer" | "backend-missing" (dann nennt
        message die Installation `pip install 'pdfplumber>=0.11'`).
        """
        return extract_tables_for_paper(db_path, paper_id, backend=backend)

    @mcp.tool(name="vault.list_tables")
    def _vault_list_tables(paper_id: str, page: int | None = None) -> list[dict]:
        """Gespeicherte Tabellenstrukturen eines Papers (rows = Textmatrix, #630)."""
        return list_paper_tables(db_path, paper_id, page=page)

    @mcp.tool(name="vault.get_table_cell")
    def _vault_get_table_cell(
        paper_id: str,
        page: int,
        table_index: int,
        row: int,
        col: int,
    ) -> dict | None:
        """Eine Tabellenzelle mit Wert, Bounding-Box und fertigem Beleg (#630).

        table_index/row/col sind 0-basiert, page ist die PDF-Seite (1-basiert).
        None bei unbekannter Zelle -- kein Naeherungstreffer.
        """
        return get_table_cell(db_path, paper_id, page, table_index, row, col)

    @mcp.tool(name="vault.add_table_value")
    def _vault_add_table_value(
        paper_id: str,
        page: int,
        table_index: int,
        row: int,
        col: int,
        claimed_value: str,
    ) -> str | dict:
        """Erfasst eine Kennzahl aus einer Tabellenzelle belegfaehig (#741).

        Fail-closed wie `vault.add_quote`: `claimed_value` wird VOR jedem
        Schreibzugriff gegen die tatsaechliche Zelle geprueft (toleriert
        Dezimalkomma/-punkt, Tausendertrennzeichen, fuehrende Nullen,
        Prozentzeichen -- keine echte Werteabweichung). Stimmt der Wert nicht
        ueberein, wirft der Aufruf ValueError mit gefundenem UND behauptetem
        Wert und es wird NICHTS gespeichert. Fehlt das Tabellen-Backend, wird
        das als "backend-missing" gemeldet statt eine Exception zu werfen.
        Zahlen im Fließtext OHNE diesen Weg bleiben ungeprueft -- es gibt
        keinen Automatismus, der sie einfaengt.
        """
        return add_table_value(
            db_path,
            paper_id=paper_id,
            page=page,
            table_index=table_index,
            row=row,
            col=col,
            claimed_value=claimed_value,
        )

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

    @mcp.tool(name="vault.check_retractions")
    def _vault_check_retractions(
        max_age_days: int = 90,
        force: bool = False,
        project_dir: str = ".",
    ) -> dict:
        """Prueft alle Vault-Papers mit DOI vault-weit auf Rueckzug (#604).

        Legt Treffer nur VOR (Fundstelle in `source`, `cited_in_chapter`
        heuristisch) -- schreibt nie automatisch nach `excluded_sources`.
        `force=True` erzwingt eine erneute Pruefung auch frisch gepruefter
        Papers.
        """
        return check_retractions(
            db_path, max_age_days=max_age_days, force=force, project_dir=project_dir
        )

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
        plugin_version: str | None = None,
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
