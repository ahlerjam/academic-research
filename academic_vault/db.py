"""VaultDB — SQLite-Datenbankschicht fuer academic_vault.

Context-Manager-Klasse mit sqlite-vec-Fallback und FTS5-Volltext-Suche.
"""

import contextlib
import json
import logging
import math
import os
import re
import sqlite3
import time
import unicodedata
from collections.abc import Iterator, Sequence
from pathlib import Path
from uuid import uuid4

from .embedding_model import (
    DEFAULT_EMBEDDING_DIM,
    deserialize_f32,
    dimension_mismatch_error,
    serialize_f32,
)

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


# vec0-Spiegel der chunk_embeddings-Vektoren (Issue #372). Die DDL steht hier
# statt in schema.sql, weil sie die geladene sqlite-vec-Extension voraussetzt.
# Seit #629 ist die Breite ein Parameter statt einer Konstante: sie kommt aus
# `embedding_meta` (Bestand) und nicht mehr aus dem Modell-Default.
def _chunk_vectors_ddl(dim: int) -> str:
    return (
        "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors "
        f"USING vec0(chunk_id TEXT PRIMARY KEY, embedding FLOAT[{dim}])"
    )


# vec0-Tabelle fuer verifizierte Zitat-Embeddings (Issue #521). Anders als
# chunk_vectors gibt es KEINE BLOB-Basistabelle -- ist die sqlite-vec-
# Extension in diesem Prozess nicht ladbar, ist Embedding fuer Quotes ein
# vollstaendiges No-Op (bewusste Scope-Entscheidung, s. Plan-Kommentar #521).
def _quote_embeddings_ddl(dim: int) -> str:
    return (
        "CREATE VIRTUAL TABLE IF NOT EXISTS quote_embeddings "
        f"USING vec0(quote_id TEXT PRIMARY KEY, embedding FLOAT[{dim}])"
    )


VALID_PAPER_TYPES = frozenset({"article-journal", "book", "chapter"})

# Erlaubte Werte fuer `quotes.stance` (Issue #400): Haltung eines Zitats zur
# zitierenden Aussage. Gespiegelt vom CHECK-Constraint in schema.sql bzw.
# migrate.add_stance_column() -- der Constraint ist die zweite
# Verteidigungslinie fuer Direkt-Inserts, die Python-Validierung in
# `add_quote()` liefert die lesbare Fehlermeldung. Die automatische Befuellung
# per lokaler NLI-Klassifikation ist ein Folge-Issue; bis dahin bleibt das Feld
# NULL, sofern es nicht manuell gesetzt wird.
VALID_STANCES = frozenset({"supports", "contrasts", "mentions"})

# Erlaubte Werte fuer `quotes.extraction_method`: Herkunftsnachweis des
# Wortlauts. Gespiegelt vom CHECK-Constraint in schema.sql bzw.
# migrate.widen_extraction_method_check().
#   citations-api  Wortlaut stammt aus der Anthropic-Citations-API
#                  (`api_response_id` ist Pflicht, geprueft in server.add_quote).
#   manual         Wortlaut von Hand belegt -- keine maschinelle Pruefung.
#                  Bleibt der dokumentierte Ausweichweg, wenn die lokale
#                  Verifikation an ihre Grenzen stoesst (seitenuebergreifende
#                  Zitate, Wort-Auslassungen).
#   local-verbatim Wortlaut gegen den lokalen PDF-Volltext verifiziert
#                  (Issue #512). server.add_quote() prueft fail-closed VOR dem
#                  Schreiben; ein nicht belegbarer Kandidat landet nie im Vault.
# BEWUSST KEINE Python-Validierung dieser Menge in `add_quote()`: fuer
# unbekannte Werte bleibt der CHECK-Constraint zustaendig (sqlite3.IntegrityError),
# sonst verschoebe sich das bestehende Fehlerverhalten der Altpfade.
VALID_EXTRACTION_METHODS = frozenset({"citations-api", "manual", "local-verbatim"})

# Erlaubte Werte fuer `papers.source_kind` (Issue #473): unterscheidet fremde
# Literatur von eigenem Erhebungsmaterial (Transkript, Beobachtungsprotokoll).
# Beides liegt in derselben Tabelle, weil nur so die Belegkette greift
# (`quotes.paper_id` -> `papers`, verbatim-guard ueber `search_quote_text()`) --
# ein Interviewzitat unterliegt damit derselben Nachweispflicht wie ein
# Literaturzitat. Gespiegelt vom CHECK-Constraint in schema.sql bzw.
# migrate.add_source_kind_column(); die Python-Validierung in `add_paper()`
# liefert die lesbare Fehlermeldung.
VALID_SOURCE_KINDS = frozenset({"literature", "primary"})

# Dateisuffix des Sidecar-Markers, mit dem der scihub-fetcher-Agent einen
# erfolgreichen Download kennzeichnet (Issue #627). add_paper() erzwingt
# provenance="scihub" fuer jeden pdf_path, neben dem eine Datei mit diesem
# Suffix liegt -- unabhaengig davon, was der aufrufende Prompt als
# provenance-Parameter uebergibt oder wegläßt. Das verlagert die
# Durchsetzung von einer Prompt-Anweisung (agents/scihub-fetcher.md) an die
# einzige tatsaechliche Schreibstelle fuer die papers-Tabelle. Bewusst kein
# Wildcard-Suffix (z.B. nur ".provenance"), um keine fremden Dateien
# fehlzuinterpretieren.
SCIHUB_PROVENANCE_SIDECAR_SUFFIX = ".provenance-scihub"

# Erlaubte Werte fuer `codings.category_origin` (Issue #473): ob eine Kategorie
# am Material entwickelt (induktiv) oder aus der Theorie abgeleitet (deduktiv)
# wurde. Die Herkunft gehoert zur Methodendokumentation und wird deshalb
# erzwungen statt optional gefuehrt.
VALID_CATEGORY_ORIGINS = frozenset({"induktiv", "deduktiv"})

# Schema-Versions-Gate (Issue #368): ueber PRAGMA user_version verfolgt.
# Unversionierte/Legacy-DBs haben user_version=0 (SQLite-Default) und liegen
# damit garantiert unter diesem Wert. Hochzaehlen, sobald schema.sql um
# Spalten/Tabellen erweitert wird, die eine Bestands-Migration brauchen --
# und der neue migrate.py-Helfer in apply_pending_migrations() ergaenzt wird.
# 2 = quotes.stance (Issue #400).
# 3 = notes.page + notes_fts-Backfill fuer Bestandsnotizen (Issue #462).
# 4 = Drop der toten Tabellen aus migrate.DEAD_TABLES (Issue #539).
# 5 = papers.source_kind + transcript_segments/codings (Issue #473).
#     Dieser Zweig entstand parallel zu #539 und beanspruchte urspruenglich
#     ebenfalls die 4. Beim Zusammenfuehren muss er eine Generation
#     hoeherruecken: eine DB, die #539 bereits auf 4 gestempelt hat, wuerde
#     `apply_pending_migrations()` sonst nie wieder betreten und bliebe ohne
#     source_kind und ohne die Empirie-Tabellen zurueck.
# 6 = quotes.extraction_method CHECK um 'local-verbatim' erweitert (Issue #512).
#     Erste Migration, die KEINE Spalte hinzufuegt, sondern einen Constraint
#     aendert -- verifiziert wird sie deshalb nicht ueber
#     `_LEGACY_MIGRATION_COLUMNS`, sondern ueber die CHECK-SQL der Tabelle
#     (siehe `init_schema()`).
# 7 = quotes.context_source (Issue #520): Herkunftsnachweis fuer
#     context_before/context_after ('fulltext' oder NULL), gesetzt von
#     server.resolve_quote_context().
# 8 = papers.retraction_checked_at (Issue #604): Zeitpunkt der letzten
#     Crossref-Retraction-Pruefung, Grundlage fuer server.check_retractions().
# 9 = embedding_meta (Issue #629): Modell-ID und Dimension des Bestands.
#     Beanspruchte urspruenglich ebenfalls die 8 (Entwicklung parallel zu
#     #604) und musste beim Zusammenfuehren eine Generation hoeherruecken --
#     sonst wuerde eine DB, die #604 bereits auf 8 gestempelt hat,
#     `apply_pending_migrations()` nie wieder betreten und bliebe ohne
#     embedding_meta zurueck (derselbe Fall wie #473 vs. #539 oben, Version 5).
#     Erste Migration, die eine ganze TABELLE nachtraegt statt einer Spalte --
#     verifiziert wird sie deshalb ueber `_REQUIRED_MIGRATION_TABLES`
#     (siehe `init_schema()`), nicht ueber `_LEGACY_MIGRATION_COLUMNS`.
CURRENT_SCHEMA_VERSION = 9

# Spalten, die `migrate.apply_pending_migrations()` je Tabelle nachziehen muss
# (Review-Fund zu PR #427, `db.py`-Zeile bei der `user_version`-Stempelung):
# jeder Helfer kapselt sein `ALTER TABLE` in `except sqlite3.OperationalError:
# pass` (migrate.py) -- das faengt nicht nur "duplicate column name", sondern
# z. B. auch "database is locked". Vor dem Stempeln wird deshalb per
# `PRAGMA table_info(<tabelle>)` verifiziert, dass die Migration tatsaechlich
# gegriffen hat, statt dem Rueckgabewert (`None`, kein Erfolgssignal) blind zu
# vertrauen -- sonst schliesst sich das Versions-Gate unwiderruflich, obwohl
# die Spalten weiterhin fehlen.
_LEGACY_MIGRATION_COLUMNS: dict[str, frozenset[str]] = {
    "papers": frozenset(
        {
            "parent_paper_id",
            "provenance",
            "source_kind",
            "editor",
            "chapter",
            "page_first",
            "page_last",
            "container_title",
            "retraction_checked_at",
        }
    ),
    "quotes": frozenset({"stance", "context_source"}),
    "notes": frozenset({"page"}),
}

# Tabellen, die `migrate.apply_pending_migrations()` auf einer Bestands-DB
# anlegen muss (Issue #629). Eigene Verifikationsart neben
# `_LEGACY_MIGRATION_COLUMNS` (Spalten) und `DEAD_TABLES` (Drops): eine fehlende
# Tabelle waere ueber `PRAGMA table_info()` unsichtbar, und der
# `user_version`-Stempel wuerde sich irrtuemlich schliessen -- exakt der
# Review-Fund aus PR #427, nur eine Ebene hoeher.
_REQUIRED_MIGRATION_TABLES = frozenset({"embedding_meta"})


class _Unset:
    """Sentinel-Typ fuer optionale ``add_paper()``-Parameter (Issue #455).

    Unterscheidet "Parameter nicht uebergeben" (Wert bleibt beim Upsert
    unangetastet) von "bewusst auf None/0 gesetzt" (Wert wird explizit
    geleert). Ein nacktes ``object()`` waere hierfuer ungeeignet, weil sich
    damit kein praeziser Typ (``str | None | _Unset``) fuer mypy formulieren
    laesst. Muss durch alle drei Aufrufebenen durchgereicht werden
    (``VaultDB.add_paper`` -> ``server.add_paper`` -> MCP-Tool-Wrapper
    ``_vault_add_paper``), sonst geht die Unterscheidung auf einer
    Zwischenschicht verloren.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "<UNSET>"


_UNSET = _Unset()

# Optionale papers-Spalten, die von add_paper()'s Sentinel-Logik erfasst
# werden, in der Reihenfolge, in der sie im INSERT/UPDATE auftauchen.
_OPTIONAL_PAPER_COLUMNS: tuple[str, ...] = (
    "doi",
    "isbn",
    "pdf_path",
    "page_offset",
    "editor",
    "chapter",
    "page_first",
    "page_last",
    "container_title",
    "parent_paper_id",
    "provenance",
    "source_kind",
)

# Defaults fuer eine echte Neuanlage (Sentinel -> dieser Wert), identisch zu
# den frueheren Funktions-Defaults -- bei einer Erstanlage ohne uebergebenen
# Wert soll sich am Ergebnis nichts aendern.
_OPTIONAL_PAPER_DEFAULTS: dict[str, object] = {
    "doi": None,
    "isbn": None,
    "pdf_path": None,
    "page_offset": 0,
    "editor": None,
    "chapter": None,
    "page_first": None,
    "page_last": None,
    "container_title": None,
    "parent_paper_id": None,
    "provenance": None,
    "source_kind": "literature",
}


class VaultLockedError(RuntimeError):
    """Material-Passport ist gesperrt -- Schreiboperation wurde verweigert.

    Wird geworfen sobald ein Eintrag in ``vault_locked_status`` existiert
    (siehe ``VaultDB._raise_if_locked``, Issue #380).
    """


# Typ-Alias-Map fuer Figure-Referenzen (Issue #379): alle Schreibweisen
# normalisieren auf "figure" bzw. "table", damit In-Text-Label
# ("Abb. 3.4") und Caption ("Abbildung 3.4: ...") strukturiert statt per
# Freitext-Teilstring verglichen werden koennen.
_FIGURE_REF_TYPE_ALIASES = {
    "abb": "figure",
    "abbildung": "figure",
    "fig": "figure",
    "figure": "figure",
    "tab": "table",
    "tabelle": "table",
}

_FIGURE_REF_RE = re.compile(
    r"\b(Abb|Abbildung|Fig|Figure|Tab|Tabelle)\.?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _parse_figure_reference(text: str) -> tuple[str, str] | None:
    """Parst Referenz-/Caption-Text in ``(kind, number)``.

    ``kind`` ist ``"figure"`` oder ``"table"`` (normalisiert ueber die
    Typ-Alias-Map), ``number`` das Nummern-Label als String (z. B. ``"3.4"``).
    Gibt ``None`` zurueck, wenn kein Typ+Nummer-Muster gefunden wird.
    """
    match = _FIGURE_REF_RE.search(text)
    if match is None:
        return None
    kind = _FIGURE_REF_TYPE_ALIASES[match.group(1).lower()]
    number = match.group(2)
    return (kind, number)


# ---------------------------------------------------------------------------
# Autorennamen-Normalisierung (Issue #378)
# ---------------------------------------------------------------------------

# Deutsche Umlaut-/Ligatur-Faltung. Muss identisch in hooks/lib/citation-parse.mjs
# gepflegt werden, damit Hook und Vault denselben Vergleich anstellen.
_UMLAUT_FOLD = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ß": "ss",
    "æ": "ae",
    "ø": "oe",
    "å": "aa",
}


# Namenspartikel. Muss mit hooks/lib/citation-parse.mjs::NAME_PARTICLES uebereinstimmen.
_NAME_PARTICLES = frozenset(
    {"von", "van", "de", "del", "della", "di", "du", "da", "le", "la", "ten", "ter"}
)


def _strip_leading_particles(lowered: str) -> str:
    """Entfernt fuehrende Namenspartikel; der letzte Token bleibt immer stehen."""
    tokens = lowered.split()
    while len(tokens) > 1 and "".join(c for c in tokens[0] if c.isalpha()) in _NAME_PARTICLES:
        tokens = tokens[1:]
    return " ".join(tokens)


def normalize_family_name(name: str) -> set[str]:
    """Normalisiert einen Familiennamen zu einer Menge von Vergleichsvarianten.

    Zwei Varianten sind noetig, weil beide Schreibkonventionen real vorkommen:
      * Umlaut-Faltung  ("Müller" -> "mueller")
      * Diakritika-Strip ("Müller" -> "muller", "Sørensen" -> "sorensen")

    Beide werden zusaetzlich OHNE fuehrendes Namenspartikel gebildet: im
    Kapiteltext steht ``(von Neumann 1945)``, CSL-JSON fuehrt das Partikel
    dagegen in ``non-dropping-particle`` und laesst ``family`` auf ``Neumann``.
    Ohne diese Variante fand der Lookup ein eingepflegtes Paper nicht wieder.

    Zwei Namen gelten als gleich, wenn sich ihre Variantenmengen schneiden.
    Die Partikel-Variante macht den Vergleich bewusst etwas weiter (``De
    Angelis`` trifft ``Angelis``) — ein zu weiter Vergleich laesst durch, ein zu
    enger blockt korrekte Belege.
    """
    lowered = (name or "").strip().lower()
    if not lowered:
        return set()
    variants: set[str] = set()
    for form in {lowered, _strip_leading_particles(lowered)}:
        folded = "".join(_UMLAUT_FOLD.get(ch, ch) for ch in form)
        stripped = "".join(
            ch for ch in unicodedata.normalize("NFD", form) if not unicodedata.combining(ch)
        )
        variants |= {re.sub(r"[^a-z]", "", v) for v in (folded, stripped)}
    return variants - {""}


def family_names_match(left: str, right: str) -> bool:
    """True, wenn zwei Familiennamen nach Normalisierung als gleich gelten."""
    left_variants = normalize_family_name(left)
    return bool(left_variants and left_variants & normalize_family_name(right))


def csl_families(csl: dict) -> list[str]:
    """Extrahiert alle Autoren-Familiennamen aus einem CSL-JSON-Objekt."""
    families: list[str] = []
    for author in csl.get("author") or []:
        if not isinstance(author, dict):
            continue
        family = author.get("family") or author.get("literal") or author.get("name")
        if family:
            families.append(str(family))
    return families


def csl_year(csl: dict) -> int | None:
    """Extrahiert das Erscheinungsjahr aus ``issued`` (date-parts, literal, raw)."""
    issued = csl.get("issued")
    if not isinstance(issued, dict):
        return None
    parts = issued.get("date-parts")
    if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
        try:
            return int(str(parts[0][0])[:4])
        except (TypeError, ValueError):
            pass
    for key in ("literal", "raw"):
        value = issued.get(key)
        if isinstance(value, str):
            match = re.search(r"\b(1[0-9]{3}|2[0-9]{3})\b", value)
            if match:
                return int(match.group(1))
    return None


_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _normalized_words(text: str) -> set[str]:
    """Tokenisiert Text und faltet jedes Wort wie ``normalize_family_name()``.

    Baustein der Kapitelzitat-Heuristik (Issue #604, AC5): dieselbe
    Umlaut-/Diakritika-Faltung wie bei Autorennamen wird auf jedes Wort des
    Kapiteltexts angewendet, damit ``family_names_match``-kompatible
    Varianten (``Müller``/``Mueller``/``Muller``) als Wort-Treffer erkannt
    werden -- ohne Namenspartikel-Behandlung, die ist bei Fliesstext nicht
    sinnvoll (kein "von"/"van" isoliert am Satzanfang zu erwarten).
    """
    variants: set[str] = set()
    for token in _WORD_RE.findall(text):
        lowered = token.lower()
        folded = "".join(_UMLAUT_FOLD.get(ch, ch) for ch in lowered)
        stripped = "".join(
            ch for ch in unicodedata.normalize("NFD", lowered) if not unicodedata.combining(ch)
        )
        variants |= {re.sub(r"[^a-z]", "", v) for v in (folded, stripped)}
    return variants - {""}


def paper_cited_in_chapters(csl: dict, kapitel_dir: str | Path) -> bool:
    """Heuristische Pruefung: taucht das Paper in einem Kapiteltext auf? (#604, AC5)

    Ein Paper gilt als "im Kapiteltext zitiert", wenn mindestens eine
    ``*.md``-Datei unter ``kapitel_dir`` (Unterordner eingeschlossen, Ordner-
    konvention aus ``scripts/bootstrap/CLAUDE.md``) sowohl das Erscheinungs-
    jahr des Papers als String ENTHAELT als auch mindestens einen seiner
    Autoren-Familiennamen als Wort-Treffer aufweist.

    Bewusst approximativ (Autor-Familienname + Jahr statt echtem
    Zitat-Parsing): False Negatives bei reiner Paraphrase ohne Klammerbeleg,
    False Positives bei Namensgleichheit unterschiedlicher Autoren. Das ist
    fuer diesen Anwendungsfall tragbar, weil das Ergebnis dem Nutzer nur
    vorgelegt wird (AC4) -- keine automatische Aktion haengt daran; der
    Aufrufer kennzeichnet das Ergebnis entsprechend als heuristisch.

    Gibt ``False`` zurueck, wenn das Paper keine Autoren/kein Jahr im
    CSL-JSON traegt oder ``kapitel_dir`` nicht existiert -- kein Fehler, denn
    ohne Kapitelordner ist "ungenutzter Vault-Eintrag" die korrekte Auskunft.
    """
    year = csl_year(csl)
    families = csl_families(csl)
    if not families or year is None:
        return False

    kapitel_path = Path(kapitel_dir)
    if not kapitel_path.is_dir():
        return False

    year_str = str(year)
    family_variant_sets = [normalize_family_name(family) for family in families]

    for md_file in sorted(kapitel_path.glob("**/*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if year_str not in text:
            continue
        words = _normalized_words(text)
        if any(variants & words for variants in family_variant_sets):
            return True
    return False


def format_table_evidence(
    paper_id: str,
    page: int,
    table_index: int,
    row: int,
    col: int,
) -> str:
    """Formatiert den Beleg zu einer Tabellenzelle (Issue #630 AC2).

    Intern sind ``table_index``, ``row`` und ``col`` 0-basiert; im Beleg stehen
    sie 1-basiert, weil ihn ein Mensch gegen das PDF haelt. ``page`` ist die
    PDF-Seite und bereits 1-basiert.
    """
    return f"{paper_id}, S. {page}, Tabelle {table_index + 1}, Zeile {row + 1}, Spalte {col + 1}"


# Escape-Zeichen fuer LIKE-Patterns (siehe escape_like / ESCAPE-Klauseln unten).
_LIKE_ESCAPE_CHAR = "\\"


def escape_like(value: str) -> str:
    """Escaped LIKE-Wildcards (``%`` und ``_``) sowie das Escape-Zeichen selbst.

    SQLite-LIKE behandelt ``%`` und ``_`` als Wildcards. Ohne Escaping veraendert
    User-Input mit diesen Zeichen das Suchverhalten still. Mit dem Rueckgabewert
    laesst sich ein literales LIKE-Pattern bauen, das per ``ESCAPE '\\'`` an die
    Query gebunden wird. Backslash muss zuerst escaped werden, damit die spaeter
    eingefuegten Escape-Backslashes nicht doppelt escaped werden.
    """
    return (
        value.replace(_LIKE_ESCAPE_CHAR, _LIKE_ESCAPE_CHAR * 2)
        .replace("%", _LIKE_ESCAPE_CHAR + "%")
        .replace("_", _LIKE_ESCAPE_CHAR + "_")
    )


_FTS5_OPERATOR_KEYWORDS = re.compile(r"\b(?:NEAR|AND|OR|NOT)\b")


def _sanitize_fts5_query(query: str) -> str:
    """Bereinigt Query fuer sichere FTS5-MATCH-Ausfuehrung.

    FTS5-Sonderzeichen die Probleme verursachen: - / ^ * " ( ) sowie der
    Column-Filter-Operator ':'. Zusaetzlich werden die booleschen
    Operator-Keywords NEAR/AND/OR/NOT (nur in Grossschreibung
    operatorwirksam) neutralisiert, damit usergenerierte Strings nicht
    versehentlich als FTS5-Syntax interpretiert werden und einen
    Query-Crash ausloesen.

    Strategie: Sonderzeichen und Operator-Keywords durch Leerzeichen
    ersetzen, Mehrfach-Leerzeichen kollabieren. Kleingeschriebene Woerter
    wie 'android' oder 'and' bleiben unangetastet — nur die in FTS5
    operatorwirksamen Grossschreibungen werden entfernt.

    Gemeinsam genutzt von server.search_papers() und VaultDB.search_notes()
    (Issue #462) -- lebt hier statt in server.py, weil VaultDB (db.py) nicht
    von server.py importieren darf (Zirkularimport).
    """
    # FTS5-Sonderzeichen entfernen/ersetzen: -, ^, /, *, (, ), ", :
    sanitized = re.sub(r'[-^/*():"]', " ", query)
    # Boolesche Operator-Keywords (Grossschreibung) neutralisieren
    sanitized = _FTS5_OPERATOR_KEYWORDS.sub(" ", sanitized)
    # Mehrfache Leerzeichen zusammenfassen
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized


def project_slug(cwd: str | None = None) -> str:
    """Kanonischer Projekt-Slug fuer den DB-Pfad: basename(CLAUDE_PROJECT_DIR || CWD).

    Eine einzige Quelle der Wahrheit (Issue #190). Hooks (hooks/verbatim-guard.mjs)
    und MCP-Server muessen denselben Algorithmus verwenden, damit alle
    Komponenten gegen dieselbe vault.db schreiben.

    Praezedenz (Issue #365 -- muss mit hooks/verbatim-guard.mjs:34 uebereinstimmen):
      1. Expliziter ``cwd``-Parameter (Escape-Hatch fuer bestehende Aufrufer/Tests).
      2. ``CLAUDE_PROJECT_DIR``-Umgebungsvariable, falls gesetzt.
      3. ``Path.cwd()``.
    """
    if cwd is not None:
        base = Path(cwd)
    else:
        env_project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        base = Path(env_project_dir) if env_project_dir else Path.cwd()
    return base.name or "default"


def default_db_path() -> str:
    """Kanonischer Default-Pfad zur vault.db (Single Source of Truth, Issue #190).

    Reihenfolge:
      1. Falls ``VAULT_DB_PATH`` gesetzt ist, wird dieser Pfad verwendet.
      2. Sonst ``~/.academic-research/projects/<slug>/vault.db`` mit
         ``slug = basename(CWD)``.

    Bewusst NICHT das CWD direkt ("vault.db") und NICHT das Plugin-Verzeichnis
    (``CLAUDE_PLUGIN_ROOT``/``REPO_ROOT``), um Datenverlust bei Plugin-Updates
    und das versehentliche Committen von Forschungs-PII zu vermeiden (CWE-538).
    """
    env = os.environ.get("VAULT_DB_PATH")
    if env:
        return env
    return str(Path.home() / ".academic-research" / "projects" / project_slug() / "vault.db")


class VaultDB:
    """SQLite-Datenbankzugriff fuer den academic_vault MCP-Server."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.vec_available: bool = False
        # Fehlerursache des letzten load_vec_extension()-Fehlschlags (Issue
        # #624): vorher wurde die Exception in zwei der drei Fehlschlagszweigen
        # stillschweigend verschluckt. ``None`` heisst "kein Fehler bekannt" --
        # entweder laedt die Extension, oder es gab noch keinen Ladeversuch.
        self.vec_unavailable_reason: str | None = None
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Context-Manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "VaultDB":
        self._conn = self._open(self.db_path)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conn is None:
            return
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        self._conn.close()
        self._conn = None

    # ------------------------------------------------------------------
    # Schema-Initialisierung
    # ------------------------------------------------------------------

    @staticmethod
    def _open(db_path: str) -> sqlite3.Connection:
        """Oeffnet eine neue Verbindung mit Standard-Pragmas.

        Legt das Elternverzeichnis von ``db_path`` an, falls es noch nicht
        existiert (Issue #365): ``~/.academic-research/projects/<slug>/``
        wird von keiner anderen Komponente vorab erzeugt, daher scheiterte
        jeder erste Schreibzugriff eines neuen Projekt-Slugs bislang mit
        ``sqlite3.OperationalError: unable to open database file``.
        In-Memory-DBs (":memory:") haben kein Elternverzeichnis und werden
        uebersprungen.
        """
        if db_path != ":memory:":
            parent = Path(db_path).parent
            if str(parent) not in ("", "."):
                parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _get_conn(self) -> sqlite3.Connection:
        """Gibt bestehende oder neue Verbindung zurueck."""
        if self._conn is not None:
            return self._conn
        return self._open(self.db_path)

    @contextlib.contextmanager
    def _connection(self, commit: bool = False) -> Iterator[sqlite3.Connection]:
        """Stellt eine Connection bereit und schliesst sie garantiert.

        Verhindert SQLite-Connection-Leaks bei Exceptions (Issue #237). Wird die
        Connection in dieser Methode selbst geoeffnet (``self._conn is None``,
        also ausserhalb des Context-Managers), so wird sie im ``finally``-Block
        immer geschlossen — auch wenn ``conn.execute()`` z. B. einen
        ``IntegrityError`` wirft. Bei ``commit=True`` wird im Erfolgsfall vorher
        committet. Eine geteilte Connection (``self._conn`` gesetzt) wird hier
        weder committet noch geschlossen; das uebernimmt ``__exit__``.

        Args:
            commit: Bei True wird die selbst geoeffnete Connection im Erfolgsfall
                committet (fuer write-Methoden).
        """
        own_conn = self._conn is None
        conn = self._get_conn()
        try:
            yield conn
            if own_conn and commit:
                conn.commit()
        finally:
            if own_conn:
                conn.close()

    def load_vec_extension(self, conn: sqlite3.Connection | None = None) -> bool:
        """Versucht sqlite_vec Extension zu laden. Gibt True bei Erfolg zurueck.

        Default-Ladepfad ist ``sqlite_vec.loadable_path()`` (das pip-installierte
        Wheel liefert die Dylib an einem Paketpfad aus, den ein Bare-Name-Load
        ``load_extension("sqlite_vec")`` nie findet, Issue #371).
        ``SQLITE_VEC_PATH`` ist nur noch ein Override fuer Custom-Builds.

        Python-Builds ohne ``--enable-loadable-sqlite-extensions`` (z.B. das
        macOS-System-Python und die macOS-Builds von actions/setup-python)
        haben ``enable_load_extension`` nicht bzw. werfen beim Aufruf. Dann ist
        die Vektor-Suche schlicht nicht verfuegbar (optionales Feature) und
        ``vec_available`` bleibt False — der Rest des Vault funktioniert weiter.
        """
        vec_path = os.environ.get("SQLITE_VEC_PATH", "")
        target = conn if conn is not None else self._get_conn()

        if not hasattr(target, "enable_load_extension"):
            self.vec_available = False
            self.vec_unavailable_reason = (
                "Python-Interpreter unterstuetzt keine ladbaren SQLite-Erweiterungen "
                "(kein enable_load_extension) -- typisch fuer System-Python ohne "
                "--enable-loadable-sqlite-extensions."
            )
            return False

        try:
            target.enable_load_extension(True)
        except (AttributeError, sqlite3.OperationalError, sqlite3.NotSupportedError) as exc:
            self.vec_available = False
            self.vec_unavailable_reason = (
                f"enable_load_extension() nicht nutzbar ({type(exc).__name__}: {exc})"
            )
            return False

        try:
            if vec_path:
                target.load_extension(vec_path)
            else:
                import sqlite_vec

                target.load_extension(sqlite_vec.loadable_path())
            self.vec_available = True
            self.vec_unavailable_reason = None
        except Exception as exc:
            self.vec_available = False
            self.vec_unavailable_reason = (
                f"sqlite-vec-Extension nicht ladbar ({type(exc).__name__}: {exc})"
            )
        finally:
            try:
                target.enable_load_extension(False)
            except Exception:
                pass
        return self.vec_available

    def init_schema(self) -> None:
        """Erstellt alle Tabellen gemaess schema.sql, migriert Bestands-DBs (#368).

        `CREATE TABLE IF NOT EXISTS` (schema.sql) deckt neue Tabellen und
        frische DBs bereits vollstaendig ab, kann aber bestehende Tabellen
        nicht um neue Spalten erweitern. Ein Versions-Gate ueber
        `PRAGMA user_version` schliesst diese Luecke: Eine DB, deren
        `papers`-Tabelle schon vor dem DDL-Lauf existierte (Legacy-Schema,
        z.B. prae-#195 ohne `parent_paper_id`/`provenance`) und deren
        `user_version` noch unter `CURRENT_SCHEMA_VERSION` liegt, bekommt
        einmalig die additiven `migrate.py`-Helfer nachgezogen -- statt bei
        `add_paper()` mit `sqlite3.OperationalError` abzustuerzen. Ueber
        dieselbe Schleuse laeuft seit #539 auch der eine subtraktive Schritt
        (`migrate.drop_dead_v64_tables()`).

        Bei bereits aktueller `user_version` ist der Aufruf ein billiger
        PRAGMA-Read ohne weitere Schreiboperation: `init_schema()` ist ein
        Hot-Path (server.py ruft ihn ~17x auf), wiederholte Aufrufe duerfen
        keine ALTER-Versuche o.ae. wiederholen.
        """
        ddl = _SCHEMA_PATH.read_text(encoding="utf-8")
        with self._connection(commit=True) as conn:
            # vec-Extension auf derselben Connection laden (optional)
            self.load_vec_extension(conn)

            # Fresh-DB-Erkennung *vor* dem DDL-Lauf: existierte "papers" schon,
            # koennte es sich um ein Legacy-Schema handeln, das Migrationshelfer
            # braucht. Eine echte Neuanlage bekommt schema.sql komplett (inkl.
            # aller Spalten) und braucht keine Helfer.
            papers_existed_before = (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='papers'"
                ).fetchone()
                is not None
            )

            # Basis-Schema ausfuehren (ohne vec0-Block — der ist auskommentiert)
            conn.executescript(ddl)

            # quote_embeddings via vec0 versuchen (nur wenn Extension geladen).
            # Breite aus dem Bestand (embedding_meta), nicht aus dem
            # Modell-Default: eine DB, die per Re-Index auf ein 1024d-Modell
            # umgestellt wurde, bekaeme sonst bei jedem init_schema()-Aufruf
            # wieder 384er-Tabellen angeboten (#629).
            if self.vec_available:
                dim = self._expected_embedding_dim(conn)
                try:
                    conn.execute(_quote_embeddings_ddl(dim))
                    conn.execute(_chunk_vectors_ddl(dim))
                except sqlite3.OperationalError:
                    self.vec_available = False

        if not papers_existed_before:
            # Echte Neuanlage: schema.sql deckt alle Spalten bereits ab,
            # Migrationshelfer sind nicht noetig -- Version direkt setzen.
            with self._connection(commit=True) as conn:
                conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
            return

        with self._connection() as conn:
            current_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if current_version >= CURRENT_SCHEMA_VERSION:
            return  # bereits migriert -- kein weiterer Schreibzugriff

        # Legacy-DB unter der aktuellen Schema-Version: Migrationshelfer
        # ausserhalb jeder offenen self._connection() ausfuehren. Die Helfer
        # oeffnen ihre eigenen kurzlebigen sqlite3-Connections (migrate.py);
        # das darf sich nicht mit einer hier noch offenen Schreibtransaktion
        # ueberschneiden (Issue #368, Plan-Risikonotiz).
        from . import migrate

        migrate.apply_pending_migrations(self.db_path)

        # Nicht blind vertrauen: apply_pending_migrations() gibt kein
        # Erfolgssignal zurueck, und jeder Helfer schluckt *jeden*
        # sqlite3.OperationalError (nicht nur "duplicate column name") als
        # vermeintliche Idempotenz. Erst per PRAGMA table_info(papers)
        # verifizieren, dass die Migration tatsaechlich gegriffen hat, bevor
        # der Stempel gesetzt wird -- sonst schliesst sich das Versions-Gate
        # unwiderruflich (Review-Fund PR #427: user_version wuerde auch nach
        # fehlgeschlagener Migration gestempelt, AC1 dauerhaft verletzt).
        with self._connection(commit=True) as conn:
            missing: list[str] = []
            for table, required in _LEGACY_MIGRATION_COLUMNS.items():
                present = {
                    row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                }
                missing += [f"{table}.{col}" for col in sorted(required - present)]

            # Symmetrisch zur Spalten-Verifikation, nur andersherum (#539):
            # `migrate.drop_dead_v64_tables()` laesst eine tote Tabelle bewusst
            # stehen, wenn sie wider Erwarten Zeilen enthaelt -- dann darf auch
            # nicht gestempelt werden, sonst bliebe sie fuer immer liegen.
            existing_tables = {
                row["name"]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            undropped = sorted(migrate.DEAD_TABLES & existing_tables)

            # Vierte Verifikationsart (#629): `add_embedding_meta_table()` legt
            # eine ganze Tabelle an. Fehlt sie hinterher, darf nicht gestempelt
            # werden -- sonst bliebe der Bestandsnachweis fuer immer aus und
            # jeder Modellwechsel liefe wieder ins Stille.
            uncreated = sorted(_REQUIRED_MIGRATION_TABLES - existing_tables)

            # Dritte Verifikationsart (#512): `widen_extraction_method_check()`
            # aendert einen CHECK-Constraint statt eine Spalte -- ein
            # fehlgeschlagener Tabellen-Rebuild waere ueber
            # `PRAGMA table_info()` unsichtbar und wuerde trotzdem gestempelt
            # (exakt der Review-Fund aus PR #427, nur eine Ebene tiefer).
            quotes_sql_row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='quotes'"
            ).fetchone()
            unwidened = (
                []
                if migrate.quotes_check_accepts_local_verbatim(
                    quotes_sql_row["sql"] if quotes_sql_row is not None else None
                )
                else ["quotes.extraction_method CHECK ohne 'local-verbatim'"]
            )

            if not missing and not undropped and not unwidened and not uncreated:
                conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
            else:
                # Stempel bewusst auslassen: user_version bleibt unter
                # CURRENT_SCHEMA_VERSION, damit der naechste init_schema()-Aufruf
                # die Migration erneut versucht statt sie faelschlich als
                # erledigt zu betrachten. Kein `raise` -- eine Exception aus
                # init_schema() wuerde den kompletten MCP-Server lahmlegen.
                logger.warning(
                    "Migration auf Schema-Version %d nicht verifizierbar -- "
                    "es fehlen weiterhin Spalten %s, diese toten Tabellen "
                    "sind nicht leer und daher nicht gedroppt: %s, diese "
                    "Constraints wurden nicht erweitert: %s, und diese Tabellen "
                    "fehlen weiterhin: %s. user_version bleibt unveraendert, "
                    "naechster init_schema()-Aufruf migriert erneut "
                    "(#368, #539, #512, #629).",
                    CURRENT_SCHEMA_VERSION,
                    missing,
                    undropped,
                    unwidened,
                    uncreated,
                )

    # ------------------------------------------------------------------
    # Papers CRUD
    # ------------------------------------------------------------------

    def add_paper(
        self,
        paper_id: str,
        csl_json: str,
        doi: str | None | _Unset = _UNSET,
        isbn: str | None | _Unset = _UNSET,
        pdf_path: str | None | _Unset = _UNSET,
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
        """Upsert eines Papers in die papers-Tabelle.

        type wird aus csl_json extrahiert. Erlaubte Werte: article-journal, book, chapter.

        provenance: Herkunfts-Tag (z.B. "scihub", "oa") fuer Audit-Zwecke (#195).

        source_kind: ``"literature"`` (Default) oder ``"primary"`` fuer eigenes
        Erhebungsmaterial (Issue #473). Beantwortet eine andere Frage als
        ``provenance`` ("woher bezogen") -- naemlich, ob der Eintrag ueberhaupt
        Literatur ist. Wird der Parameter beim Upsert weggelassen, bleibt der
        Bestandswert erhalten; ein Transkript wird also nicht durch ein
        spaeteres Metadaten-Update zur Literaturquelle.

        Malformed JSON wird NICHT mehr stillschweigend zu 'article-journal'
        defaulted (Issue #213, Security Round-2 M3), sondern als ValueError
        gemeldet. Fehlt das Feld 'type' komplett, gilt weiterhin der
        DB-Default 'article-journal'.

        Alle optionalen Parameter defaulten auf das Sentinel ``_UNSET``
        statt auf ``None``/``0`` (Issue #455): Ein zweiter Upsert-Aufruf fuer
        dieselbe ``paper_id``, der ein optionales Feld nicht mit uebergibt,
        laesst dessen Bestandswert unangetastet -- vorher wurde jedes nicht
        uebergebene Feld stillschweigend auf seinen Default zurueckgesetzt.
        Ein bewusst geleertes Feld (explizit ``None``/``0`` uebergeben) wird
        weiterhin geleert, weil dieser Wert von ``_UNSET`` unterscheidbar ist.
        """
        try:
            csl = json.loads(csl_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"csl_json ist kein valides JSON: {exc}") from exc
        if not isinstance(csl, dict):
            raise ValueError("csl_json muss ein JSON-Objekt sein.")
        paper_type = csl.get("type", "article-journal")

        if paper_type not in VALID_PAPER_TYPES:
            raise ValueError(
                f"Ungueltiger type '{paper_type}' -- erlaubt: {sorted(VALID_PAPER_TYPES)}"
            )

        if not isinstance(source_kind, _Unset) and source_kind not in VALID_SOURCE_KINDS:
            raise ValueError(
                f"Ungueltiger source_kind '{source_kind}' -- erlaubt: {sorted(VALID_SOURCE_KINDS)}"
            )

        # Sci-Hub-Provenance-Durchsetzung (Issue #627): Wird in diesem Aufruf
        # ein pdf_path uebergeben und liegt daneben der Sidecar-Marker des
        # scihub-fetcher-Agenten, wird provenance hart auf "scihub" gesetzt --
        # auch wenn der Aufrufer provenance weglaesst (_UNSET) oder einen
        # abweichenden Wert uebergibt. Ohne uebergebenen pdf_path (Sentinel
        # oder None) gibt es nichts zu pruefen; der Bestandswert bleibt dann
        # ohnehin unangetastet. Der Marker wird nach erfolgreicher
        # Persistierung in der DB konsumiert (gelöscht), damit er keinen
        # Einfluss auf einen späteren Überschreibvorgang derselben PDF hat
        # (Issue #627 Audit P1).
        sidecar_path_to_consume: Path | None = None
        if not isinstance(pdf_path, _Unset) and pdf_path is not None:
            sidecar_path = Path(str(pdf_path) + SCIHUB_PROVENANCE_SIDECAR_SUFFIX)
            if sidecar_path.is_file():
                provenance = "scihub"
                sidecar_path_to_consume = sidecar_path

        supplied: dict[str, object] = {
            "doi": doi,
            "isbn": isbn,
            "pdf_path": pdf_path,
            "page_offset": page_offset,
            "editor": editor,
            "chapter": chapter,
            "page_first": page_first,
            "page_last": page_last,
            "container_title": container_title,
            "parent_paper_id": parent_paper_id,
            "provenance": provenance,
            "source_kind": source_kind,
        }
        # Werte fuer den INSERT-Zweig (Neuanlage): bei nicht uebergebenen
        # (Sentinel-)Feldern der bisherige Default -- fuer eine echte
        # Neuanlage aendert sich dadurch nichts am Ergebnis.
        insert_values = {
            col: (_OPTIONAL_PAPER_DEFAULTS[col] if val is _UNSET else val)
            for col, val in supplied.items()
        }
        # Nur tatsaechlich uebergebene Spalten landen im UPDATE SET -- das
        # ist der Kern des Fixes: nicht uebergebene optionale Felder
        # behalten beim Upsert ihren Bestandswert.
        provided_columns = [col for col, val in supplied.items() if val is not _UNSET]

        now = int(time.time())
        set_clauses = ["type = excluded.type", "csl_json = excluded.csl_json"]
        set_clauses += [f"{col} = excluded.{col}" for col in provided_columns]
        set_clauses.append("updated_at = excluded.updated_at")

        columns = [
            "paper_id",
            "type",
            "csl_json",
            *_OPTIONAL_PAPER_COLUMNS,
            "added_at",
            "updated_at",
        ]
        placeholders = ", ".join("?" for _ in columns)
        values = (
            paper_id,
            paper_type,
            csl_json,
            *(insert_values[col] for col in _OPTIONAL_PAPER_COLUMNS),
            now,
            now,
        )

        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                f"""
                INSERT INTO papers ({", ".join(columns)})
                VALUES ({placeholders})
                ON CONFLICT(paper_id) DO UPDATE SET
                  {", ".join(set_clauses)}
                """,
                values,
            )

        # Marker nach Persistierung konsumieren (Issue #627 Audit P1):
        # Verhindert, dass ein Marker einen späteren Überschreibvorgang
        # derselben PDF beeinflusst.
        if sidecar_path_to_consume is not None:
            sidecar_path_to_consume.unlink(missing_ok=True)

    def get_paper(self, paper_id: str) -> dict | None:
        """Gibt Paper-Record als dict zurueck oder None."""
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM papers WHERE paper_id = ?", (paper_id,)).fetchone()
        if row is None:
            return None
        return dict(row)

    def set_page_offset(self, paper_id: str, offset: int) -> None:
        """Setzt page_offset fuer ein Paper."""
        with self._connection(commit=True) as conn:
            conn.execute(
                "UPDATE papers SET page_offset = ?, updated_at = ? WHERE paper_id = ?",
                (offset, int(time.time()), paper_id),
            )

    def get_page_offset(self, paper_id: str) -> int:
        """Gibt page_offset fuer ein Paper zurueck. Fallback: 0."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT page_offset FROM papers WHERE paper_id = ?", (paper_id,)
            ).fetchone()
        if row is None:
            return 0
        return int(row["page_offset"] or 0)

    def list_papers_by_provenance(self, provenance: str) -> list[dict]:
        """Gibt alle Papers mit dem angegebenen provenance-Tag zurueck (Audit, #195).

        Beispiel: ``list_papers_by_provenance("scihub")`` liefert alle aus dem
        SciHub-Tier bezogenen Papers fuer ein Provenance-Audit.
        """
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM papers WHERE provenance = ? ORDER BY added_at",
                (provenance,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_literature_papers(self) -> list[dict]:
        """Gibt alle Papers mit ``source_kind='literature'`` zurueck (#604).

        Grundlage fuer ``server.check_retractions()``: unabhaengig vom
        Importweg (zotero-import, reading-list-import, anchor-paper-survey,
        github-repo-research, fetch, ...) liefert diese Abfrage jedes
        Literatur-Paper -- eigenes Erhebungsmaterial (``source_kind='primary'``,
        Transkripte etc.) ist bewusst ausgeschlossen, ein Retraction-Check
        ergibt dafuer keinen Sinn.
        """
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM papers WHERE source_kind = 'literature' ORDER BY added_at",
            ).fetchall()
        return [dict(r) for r in rows]

    def update_retraction_checked_at(self, paper_id: str, checked_at: int) -> None:
        """Setzt ``retraction_checked_at`` fuer ein Paper (#604).

        Wird nur nach einer erfolgreichen Crossref-Pruefung aufgerufen
        (``server.check_retractions()``) -- ein Crossref-Ausfall darf den
        Zeitstempel nicht vorruecken, sonst wuerde der naechste Lauf faelschlich
        annehmen, das Paper sei bereits aktuell geprueft.
        """
        with self._connection(commit=True) as conn:
            conn.execute(
                "UPDATE papers SET retraction_checked_at = ? WHERE paper_id = ?",
                (checked_at, paper_id),
            )

    # ------------------------------------------------------------------
    # Quotes CRUD
    # ------------------------------------------------------------------

    def add_quote(
        self,
        quote_id: str,
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
    ) -> None:
        """INSERT eines Quotes in die quotes-Tabelle.

        Args:
            stance: Optionale Haltung des Zitats zur zitierenden Aussage
                (`VALID_STANCES`), sonst `None` (Issue #400). Die Validierung
                liegt hier statt allein im CHECK-Constraint, damit jeder
                Aufrufweg (MCP-Tool wie direkte ``VaultDB``-Nutzung) dieselbe
                lesbare Meldung bekommt statt eines rohen
                ``sqlite3.IntegrityError``.

        Raises:
            ValueError: Wenn ``stance`` weder ``None`` noch einer der Werte aus
                ``VALID_STANCES`` ist.
        """
        if stance is not None and stance not in VALID_STANCES:
            raise ValueError(
                f"Ungueltiger stance '{stance}' -- erlaubt: {sorted(VALID_STANCES)} oder None"
            )

        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO quotes
                  (quote_id, paper_id, verbatim, pdf_page, printed_page,
                   section, context_before, context_after,
                   extraction_method, api_response_id, created_at, stance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    quote_id,
                    paper_id,
                    verbatim,
                    pdf_page,
                    printed_page,
                    section,
                    context_before,
                    context_after,
                    extraction_method,
                    api_response_id,
                    now,
                    stance,
                ),
            )

    def update_quote_context(
        self,
        quote_id: str,
        context_before: str,
        context_after: str,
        context_source: str,
    ) -> None:
        """Schreibt echten Quellkontext auf einen bestehenden Quote (Issue #520).

        Wird ausschliesslich von :func:`academic_vault.server.resolve_quote_context`
        aufgerufen, NACHDEM eine Fundstelle im ``paper_fulltext`` nachgewiesen
        wurde -- kein Aufrufweg hier rate irgendetwas, das ist Aufgabe des
        Aufrufers. ``context_source`` wird bewusst nicht gegen
        ``VALID_...``-Konstante validiert (analog zu ``extraction_method``):
        der CHECK-Constraint auf ``quotes.context_source`` ist die zweite
        Verteidigungslinie fuer unbekannte Werte.

        Raises:
            VaultLockedError: Vault ist gesperrt (Material-Passport-Lock).
        """
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                UPDATE quotes
                SET context_before = ?, context_after = ?, context_source = ?
                WHERE quote_id = ?
                """,
                (context_before, context_after, context_source, quote_id),
            )

    def get_quote(self, quote_id: str) -> dict | None:
        """Gibt Quote-Record als dict zurueck oder None."""
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM quotes WHERE quote_id = ?", (quote_id,)).fetchone()
        return dict(row) if row is not None else None

    def set_quote_stance(self, quote_id: str, stance: str) -> None:
        """Aktualisiert ``stance`` eines BESTEHENDEN Quotes (Issue #523).

        Ergaenzt ``add_quote(stance=...)`` um einen nachtraeglichen
        Audit-Schreibpfad: der `quote-fidelity-auditor`-Agent legt keine neuen
        Zitate an, sondern urteilt ueber bereits im Vault vorhandene.

        Args:
            quote_id: Referenz auf ``quotes.quote_id``.
            stance: Einer der Werte aus ``VALID_STANCES`` (``None`` ist hier
                bewusst NICHT erlaubt -- ein Audit-Urteil loescht keine
                bestehende Einstufung, das waere ein stiller Datenverlust).

        Raises:
            ValueError: Wenn ``stance`` nicht in ``VALID_STANCES`` liegt, oder
                wenn ``quote_id`` auf kein bestehendes Zitat verweist.
        """
        if stance not in VALID_STANCES:
            raise ValueError(f"Ungueltiger stance '{stance}' -- erlaubt: {sorted(VALID_STANCES)}")
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            cursor = conn.execute(
                "UPDATE quotes SET stance = ? WHERE quote_id = ?",
                (stance, quote_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"vault.set_quote_stance: Quote '{quote_id}' nicht gefunden")

    def search_quote_text(self, verbatim: str, k: int = 5) -> list[dict]:
        """LIKE-Suche in quotes.verbatim. Gibt [{quote_id, verbatim, paper_id}] zurueck."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT quote_id, verbatim, paper_id FROM quotes "
                "WHERE verbatim LIKE ? ESCAPE '\\' LIMIT ?",
                (f"%{escape_like(verbatim)}%", k),
            ).fetchall()
        return [dict(r) for r in rows]

    def find_quotes(
        self,
        paper_id: str,
        query: str | None = None,
        k: int = 10,
    ) -> list[dict]:
        """Suche Quotes fuer ein Paper, optional per verbatim-LIKE-Filter."""
        with self._connection() as conn:
            if query:
                rows = conn.execute(
                    "SELECT * FROM quotes WHERE paper_id = ? "
                    "AND verbatim LIKE ? ESCAPE '\\' LIMIT ?",
                    (paper_id, f"%{escape_like(query)}%", k),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM quotes WHERE paper_id = ? LIMIT ?",
                    (paper_id, k),
                ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Quote-Embeddings (Issue #521)
    # ------------------------------------------------------------------

    def vec_extension_loadable(self) -> bool:
        """Prueft, ob die sqlite-vec-Extension in diesem Prozess ladbar ist.

        Oeffnet dafuer kurz eine eigene Connection (ueber ``_connection()``,
        die sie garantiert wieder schliesst) -- fuer Aufrufer, die VOR einer
        teuren Operation (Embedding-Modell-Load) pruefen wollen, ob am Ende
        ueberhaupt gespeichert werden koennte (Plan-Risiko #521/4).
        """
        with self._connection() as conn:
            return self.load_vec_extension(conn)

    def add_quote_embedding(self, quote_id: str, embedding_vector: bytes) -> bool:
        """Schreibt (oder ersetzt) den Embedding-Vektor eines Quotes in vec0.

        Best effort in einer Hinsicht (Issue #521, bewusste
        Scope-Entscheidung): bei leerem Vektor oder ohne ladbare
        sqlite-vec-Extension ist der Aufruf ein No-Op mit Rueckgabe ``False``
        -- anders als bei Chunks gibt es fuer Quotes keine BLOB-Basistabelle.

        NICHT mehr best effort ist die Dimension (Issue #629): ein Vektor
        fremder Breite wurde frueher stillschweigend verworfen und der Quote
        blieb ohne Embedding, ohne dass die Ursache irgendwo auftauchte.

        Raises:
            VaultLockedError: Vault ist gesperrt (Material-Passport-Lock).
            EmbeddingDimensionMismatchError: Vektorbreite passt nicht zum
                Bestand (``embedding_meta``).
        """
        if not embedding_vector:
            return False
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            self._assert_vector_dim(conn, embedding_vector)
            if not self.load_vec_extension(conn):
                return False
            try:
                conn.execute(_quote_embeddings_ddl(self._expected_embedding_dim(conn)))
                conn.execute(
                    "INSERT OR REPLACE INTO quote_embeddings (quote_id, embedding) VALUES (?, ?)",
                    (quote_id, embedding_vector),
                )
            except sqlite3.OperationalError:
                return False
        return True

    def get_quote_embedding(self, quote_id: str) -> list[float] | None:
        """Liest den gespeicherten Embedding-Vektor eines Quotes (Issue #522).

        Rein lesendes Gegenstueck zu :meth:`add_quote_embedding`. ``None``
        bedeutet in jedem Fall "keine Zahl verfuegbar" und nie "Aehnlichkeit
        null": fehlende sqlite-vec-Extension, fehlende ``quote_embeddings``-
        Tabelle oder kein Eintrag zu dieser ``quote_id``. Aufrufer duerfen
        daraus nichts ableiten (Muster :meth:`quotes_missing_embedding`).
        """
        with self._connection() as conn:
            if not self.load_vec_extension(conn):
                return None
            try:
                row = conn.execute(
                    "SELECT embedding FROM quote_embeddings WHERE quote_id = ?",
                    (quote_id,),
                ).fetchone()
            except sqlite3.OperationalError:
                return None
        if row is None:
            return None
        blob = row["embedding"]
        if not isinstance(blob, bytes | bytearray):
            return None
        try:
            return deserialize_f32(bytes(blob))
        except ValueError:
            # Abgeschnittener Altbestand: lieber "keine Zahl" als halbe Floats.
            logger.warning(
                "vault.get_quote_embedding: Embedding von Quote '%s' ist beschaedigt (#522).",
                quote_id,
            )
            return None

    def quotes_missing_embedding(self, limit: int | None = None) -> list[dict]:
        """Quotes ohne Eintrag in ``quote_embeddings``. Kandidatenliste fuer den Backfill.

        Leere Liste, wenn die sqlite-vec-Extension in diesem Prozess nicht
        ladbar ist -- sonst wuerde der LEFT JOIN gegen die fehlende Virtual
        Table mit ``sqlite3.OperationalError: no such table`` abbrechen
        (Plan-Risiko #521/5), statt sauber zu degradieren.
        """
        with self._connection() as conn:
            if not self.load_vec_extension(conn):
                return []
            try:
                conn.execute(_quote_embeddings_ddl(self._expected_embedding_dim(conn)))
            except sqlite3.OperationalError:
                return []
            sql = """
                SELECT q.quote_id, q.paper_id, q.verbatim, q.context_before, q.context_after
                FROM quotes q
                LEFT JOIN quote_embeddings e ON e.quote_id = q.quote_id
                WHERE e.quote_id IS NULL
                ORDER BY q.created_at, q.quote_id
            """
            params: list = []
            if limit is not None and limit > 0:
                sql += " LIMIT ?"
                params.append(limit)
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                return []
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Notes CRUD + FTS5-Suche (Issue #462)
    # ------------------------------------------------------------------

    def add_note(
        self,
        paper_id: str,
        text: str,
        tags: str | None = None,
        page: int | None = None,
    ) -> str:
        """INSERT einer Notiz/eines Exzerpts. Gibt note_id (UUID) zurueck.

        Args:
            page: Optionale Seitenangabe (AC2) -- Notizen ohne konkreten
                Seitenbezug (z. B. quellenuebergreifende Synthese) bleiben
                zulaessig, ``page`` defaultet auf ``None``.
        """
        note_id = str(uuid4())
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO notes (note_id, paper_id, text, tags, created_at, page)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (note_id, paper_id, text, tags, now, page),
            )
        return note_id

    def get_note(self, note_id: str) -> dict | None:
        """Gibt Note-Record als dict zurueck oder None."""
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM notes WHERE note_id = ?", (note_id,)).fetchone()
        return dict(row) if row is not None else None

    def find_notes(
        self,
        paper_id: str,
        query: str | None = None,
        k: int = 10,
    ) -> list[dict]:
        """Notizen fuer ein Paper, optional per text-LIKE-Filter (Muster find_quotes)."""
        with self._connection() as conn:
            if query:
                rows = conn.execute(
                    "SELECT * FROM notes WHERE paper_id = ? "
                    "AND text LIKE ? ESCAPE '\\' ORDER BY created_at LIMIT ?",
                    (paper_id, f"%{escape_like(query)}%", k),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM notes WHERE paper_id = ? ORDER BY created_at LIMIT ?",
                    (paper_id, k),
                ).fetchall()
        return [dict(r) for r in rows]

    def search_notes(self, query: str, k: int = 5) -> list[dict]:
        """FTS5-Volltextsuche in notes_fts. Gibt [{note_id, paper_id, snippet, score}] zurueck.

        Analog zu ``server.search_papers()``, aber ohne Rerank-/Hybrid-Pfad
        (Issue #462 AC3+AC4): Notizen sind kurze, manuell verfasste
        Exzerpte -- BM25 allein deckt "Exzerpte beim Kapitelschreiben
        auffindbar" bereits ab, eine vec0-Embedding-Pipeline waere hier
        unverhaeltnismaessig. Leere/rein aus FTS5-Sonderzeichen bestehende
        Queries liefern ``[]`` statt ``sqlite3.OperationalError`` (Muster
        Issue #369).
        """
        sanitized = _sanitize_fts5_query(query)
        if not sanitized:
            return []
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT note_id,
                       paper_id,
                       snippet(notes_fts, -1, '<b>', '</b>', '...', 10) AS snippet,
                       rank AS score
                FROM notes_fts
                WHERE notes_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (sanitized, k),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Klammer-Zitat-Verifikation (Issue #378)
    # ------------------------------------------------------------------

    def _papers_snapshot(self) -> list[dict]:
        """Liest die komplette ``papers``-Tabelle einmal und parst ``csl_json``.

        Extrahiert aus :meth:`find_papers_by_author_year` (Issue #501), damit
        Aufrufer mit mehreren Belegen (:func:`academic_vault.server.verify_citations`)
        sich einen Scan + Parse-Durchlauf ueber die komplette Tabelle teilen
        koennen, statt ihn je Beleg zu wiederholen. Zeilen mit kaputtem oder
        nicht-dict ``csl_json`` werden stillschweigend uebersprungen (wie bisher
        in :meth:`find_papers_by_author_year`). Ergebnis enthaelt zusaetzlich
        das bereits geparste ``csl``-Feld.
        """
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT paper_id, csl_json, page_first, page_last FROM papers"
            ).fetchall()
        snapshot: list[dict] = []
        for row in rows:
            record = dict(row)
            try:
                csl = json.loads(record["csl_json"])
            except (TypeError, ValueError):
                continue
            if not isinstance(csl, dict):
                continue
            record["csl"] = csl
            snapshot.append(record)
        return snapshot

    def _match_papers_in_snapshot(
        self, snapshot: list[dict], family: str, year: int | None
    ) -> list[dict]:
        """Matcht ``family``/``year`` gegen einen bereits gelesenen :meth:`_papers_snapshot`.

        Reine In-Memory-Filterung (kein DB-Zugriff) -- Kern von
        :meth:`find_papers_by_author_year`, extrahiert (Issue #501), damit
        :func:`academic_vault.server.verify_citations` denselben Snapshot fuer
        mehrere Belege wiederverwenden kann, statt ihn je Beleg neu einzulesen.
        Der Namensvergleich laeuft ueber :func:`normalize_family_name`
        (Umlaut-Faltung + Diakritika-Strip), damit ``Müller``/``Mueller``/
        ``Muller`` denselben Eintrag treffen.
        """
        wanted = normalize_family_name(family)
        if not wanted or year is None:
            return []
        matches: list[dict] = []
        for record in snapshot:
            csl = record["csl"]
            if csl_year(csl) != int(year):
                continue
            if any(normalize_family_name(f) & wanted for f in csl_families(csl)):
                matches.append(
                    {
                        "paper_id": record["paper_id"],
                        "csl_json": record["csl_json"],
                        "page_first": record["page_first"],
                        "page_last": record["page_last"],
                    }
                )
        return matches

    def find_papers_by_author_year(self, family: str, year: int) -> list[dict]:
        """Findet Papers, deren CSL-Autorenliste ``family`` enthaelt und deren
        Erscheinungsjahr exakt ``year`` ist.

        Es gibt bewusst keine SQL-seitige Vorfilterung: ``csl_json`` ist ein
        Textblob, dessen Autorenfelder sich nicht zuverlaessig per LIKE
        eingrenzen lassen, ohne genau diese Schreibvarianten zu verlieren.
        Fuer Aufrufer mit mehreren Belegen (Batch) siehe
        :meth:`_papers_snapshot` + :meth:`_match_papers_in_snapshot`.
        """
        return self._match_papers_in_snapshot(self._papers_snapshot(), family, year)

    def page_coverage(self, paper_id: str, page: int) -> str:
        """Prueft, ob ``page`` von den im Vault bekannten Seitendaten gedeckt ist.

        Die beiden Quellen sind bewusst NICHT gleichwertig:

        * ``papers.page_first``/``page_last`` beschreiben den vollstaendigen
          Seitenumfang und koennen eine Seite deshalb auch widerlegen.
        * ``quotes.printed_page`` ist eine punktuelle Stichprobe der bereits
          extrahierten Stellen. Sie kann eine Seite nur BESTAETIGEN, niemals
          widerlegen: dass aus S. 47 noch nichts extrahiert wurde, sagt nichts
          darueber aus, ob das Werk eine S. 47 hat.

        Rueckgabe:
          ``"covered"``  — Seite liegt in ``[page_first, page_last]`` oder
                            entspricht einer ``quotes.printed_page``.
          ``"outside"``  — vollstaendiger Seitenumfang bekannt und Seite liegt
                            ausserhalb. Nur dieser Fall ist blockierbar.
          ``"unknown"``  — kein vollstaendiger Seitenumfang hinterlegt
                            (dokumentierter Soft-Pass; sonst waeren
                            Massen-False-Positives die Folge).
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT page_first, page_last FROM papers WHERE paper_id = ?",
                (paper_id,),
            ).fetchone()
            pages = [
                r["printed_page"]
                for r in conn.execute(
                    "SELECT printed_page FROM quotes WHERE paper_id = ? AND printed_page IS NOT NULL",
                    (paper_id,),
                ).fetchall()
            ]
        if row is None:
            return "unknown"
        # Stichprobe zuerst: eine belegte Quote-Seite bestaetigt auch dann,
        # wenn sie ausserhalb eines (ggf. fehlerhaften) Seitenumfangs liegt.
        if page in pages:
            return "covered"
        first, last = row["page_first"], row["page_last"]
        if first is None or last is None:
            return "unknown"
        return "covered" if first <= page <= last else "outside"

    def set_ocr_done(self, paper_id: str, value: int = 1) -> None:
        """Setzt ocr_done-Flag fuer ein Paper."""
        with self._connection(commit=True) as conn:
            conn.execute(
                "UPDATE papers SET ocr_done = ?, updated_at = ? WHERE paper_id = ?",
                (value, int(time.time()), paper_id),
            )

    def update_pdf_path(self, paper_id: str, new_path: str) -> None:
        """Aktualisiert pdf_path fuer ein Paper."""
        with self._connection(commit=True) as conn:
            conn.execute(
                "UPDATE papers SET pdf_path = ?, updated_at = ? WHERE paper_id = ?",
                (new_path, int(time.time()), paper_id),
            )

    # ------------------------------------------------------------------
    # Volltext-Index (Issue #373)
    # ------------------------------------------------------------------

    def set_fulltext(self, paper_id: str, text: str, extractor: str = "pypdf") -> bool:
        """Persistiert den extrahierten PDF-Volltext und indiziert ihn in FTS5.

        Geschrieben wird an zwei Stellen in einer Transaktion: ``paper_fulltext``
        ist der kanonische Speicher (ueberlebt den Trigger-Rebuild von
        ``papers_au``), ``papers_fts.fulltext`` der Suchindex.

        Args:
            paper_id: Referenz auf ``papers.paper_id``.
            text: Extrahierter Volltext.
            extractor: Herkunft des Textes ("pypdf", "grobid", ...).

        Returns:
            ``True`` wenn geschrieben wurde, ``False`` bei leerem Text. Ein
            leerer Extraktionsversuch (Scan-PDF ohne Text-Layer) darf nicht als
            erledigt gelten, sonst wird er nach einem OCR-Lauf nie nachgeholt.
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return False
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO paper_fulltext (paper_id, text, extractor, extracted_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(paper_id) DO UPDATE SET
                  text         = excluded.text,
                  extractor    = excluded.extractor,
                  extracted_at = excluded.extracted_at
                """,
                (paper_id, cleaned, extractor, now),
            )
            updated = conn.execute(
                "UPDATE papers_fts SET fulltext = ? WHERE paper_id = ?",
                (cleaned, paper_id),
            ).rowcount
            if updated == 0:
                # Kein FTS-Eintrag (z. B. DB aus einer Zeit vor den Triggern):
                # Zeile aus papers nachziehen, damit die Suche den Text sieht.
                row = conn.execute(
                    "SELECT csl_json FROM papers WHERE paper_id = ?", (paper_id,)
                ).fetchone()
                if row is not None:
                    conn.execute(
                        """
                        INSERT INTO papers_fts (paper_id, title, abstract, fulltext)
                        VALUES (?, json_extract(?, '$.title'), json_extract(?, '$.abstract'), ?)
                        """,
                        (paper_id, row["csl_json"], row["csl_json"], cleaned),
                    )
        return True

    def get_fulltext(self, paper_id: str) -> str | None:
        """Gibt den gespeicherten Volltext zurueck oder None."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT text FROM paper_fulltext WHERE paper_id = ?", (paper_id,)
            ).fetchone()
        return None if row is None else str(row["text"])

    def papers_missing_fulltext(self, limit: int | None = None) -> list[dict]:
        """Papers mit hinterlegtem PDF-Pfad, aber ohne Volltext-Eintrag.

        Kandidatenliste fuer den Backfill (``migrate.backfill_fulltext``).
        """
        sql = """
            SELECT p.paper_id, p.pdf_path
            FROM papers p
            LEFT JOIN paper_fulltext f ON f.paper_id = p.paper_id
            WHERE p.pdf_path IS NOT NULL AND trim(p.pdf_path) != ''
              AND f.paper_id IS NULL
            ORDER BY p.added_at, p.paper_id
        """
        params: list = []
        if limit is not None and limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        with self._connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Strukturerhaltend extrahierte Tabellen (Issue #630)
    # ------------------------------------------------------------------

    def set_paper_tables(self, paper_id: str, tables: list[dict], backend: str) -> int:
        """Ersetzt die gespeicherten Tabellen eines Papers. Gibt deren Anzahl zurueck.

        Ersetzen statt Anhaengen: eine zweite Extraktion desselben PDFs soll
        denselben Stand ergeben und nicht die alte Fassung daneben stehen
        lassen. ``papers``, ``paper_fulltext`` und ``papers_fts`` werden dabei
        nicht angefasst -- der FTS5-Volltext bleibt byteweise unveraendert.

        Args:
            paper_id: Referenz auf ``papers.paper_id``.
            tables: Tabellen aus :func:`academic_vault.tables.extract_tables`.
            backend: Herkunft der Struktur (z. B. ``"pdfplumber"``).

        Returns:
            Anzahl geschriebener Tabellen.
        """
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute("DELETE FROM paper_tables WHERE paper_id = ?", (paper_id,))
            for table in tables:
                conn.execute(
                    """
                    INSERT INTO paper_tables
                      (table_id, paper_id, page, table_index, backend,
                       n_rows, n_cols, bbox_json, rows_json, cells_json, extracted_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        paper_id,
                        int(table["page"]),
                        int(table["table_index"]),
                        backend,
                        int(table["n_rows"]),
                        int(table["n_cols"]),
                        json.dumps(table["bbox"]),
                        json.dumps(table["rows"], ensure_ascii=False),
                        json.dumps(table["cells"], ensure_ascii=False),
                        now,
                    ),
                )
        return len(tables)

    def list_paper_tables(self, paper_id: str, page: int | None = None) -> list[dict]:
        """Gibt die gespeicherten Tabellen eines Papers zurueck (Struktur inklusive).

        Auf einer Bestands-DB ohne ``paper_tables`` ist das Ergebnis eine leere
        Liste statt eines ``sqlite3.OperationalError``: ein Vault, in dem nie
        eine Tabelle extrahiert wurde, hat schlicht keine.
        """
        sql = "SELECT * FROM paper_tables WHERE paper_id = ?"
        params: list = [paper_id]
        if page is not None:
            sql += " AND page = ?"
            params.append(int(page))
        sql += " ORDER BY page, table_index"
        with self._connection() as conn:
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                return []
        return [self._table_row_to_dict(row) for row in rows]

    @staticmethod
    def _table_row_to_dict(row: sqlite3.Row) -> dict:
        record = dict(row)
        record["rows"] = json.loads(record.pop("rows_json"))
        record["cells"] = json.loads(record.pop("cells_json"))
        record["bbox"] = json.loads(record.pop("bbox_json"))
        return record

    def get_table_cell(
        self,
        paper_id: str,
        page: int,
        table_index: int,
        row: int,
        col: int,
    ) -> dict | None:
        """Loest eine einzelne Zelle zu Wert **und** Beleg auf (Issue #630 AC2).

        Returns:
            ``{"paper_id", "page", "table_index", "row", "col", "value", "bbox",
            "backend", "evidence"}`` oder ``None``, wenn es die Zelle nicht
            gibt. ``None`` statt eines Naeherungstreffers: ein geratener Beleg
            waere schlimmer als gar keiner.
        """
        with self._connection() as conn:
            try:
                found = conn.execute(
                    """
                    SELECT * FROM paper_tables
                    WHERE paper_id = ? AND page = ? AND table_index = ?
                    """,
                    (paper_id, int(page), int(table_index)),
                ).fetchone()
            except sqlite3.OperationalError:
                return None
        if found is None:
            return None

        for cell in json.loads(found["cells_json"]):
            if cell["row"] != row or cell["col"] != col:
                continue
            return {
                "paper_id": paper_id,
                "page": int(found["page"]),
                "table_index": int(found["table_index"]),
                "row": row,
                "col": col,
                "value": cell["value"],
                "bbox": cell["bbox"],
                "backend": str(found["backend"]),
                "evidence": format_table_evidence(
                    paper_id, int(found["page"]), int(found["table_index"]), row, col
                ),
            }
        return None

    # ------------------------------------------------------------------
    # Figures CRUD
    # ------------------------------------------------------------------

    def add_figure(
        self,
        paper_id: str,
        page: int | None,
        caption: str | None,
        vlm_description: str | None,
        data_extracted_json: str | None,
    ) -> str:
        """INSERT einer Figure. Gibt figure_id (UUID) zurueck."""
        figure_id = str(uuid4())
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO figures
                  (figure_id, paper_id, page, caption, vlm_description, data_extracted_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (figure_id, paper_id, page, caption, vlm_description, data_extracted_json, now),
            )
        return figure_id

    def get_figure(self, figure_id: str) -> dict | None:
        """Gibt Figure-Record als dict zurueck oder None."""
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM figures WHERE figure_id = ?", (figure_id,)).fetchone()
        return dict(row) if row is not None else None

    def list_figures(self, paper_id: str) -> list[dict]:
        """Alle Figures fuer ein Paper, nach page sortiert."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM figures WHERE paper_id = ? ORDER BY page",
                (paper_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def find_figures_by_caption(
        self,
        caption_fragment: str,
        paper_id: str | None = None,
    ) -> list[dict]:
        """LIKE-Suche in figures.caption. Optionaler paper_id-Filter."""
        with self._connection() as conn:
            if paper_id is not None:
                rows = conn.execute(
                    "SELECT * FROM figures WHERE caption LIKE ? ESCAPE '\\' AND paper_id = ?",
                    (f"%{escape_like(caption_fragment)}%", paper_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM figures WHERE caption LIKE ? ESCAPE '\\'",
                    (f"%{escape_like(caption_fragment)}%",),
                ).fetchall()
        return [dict(r) for r in rows]

    def find_figures_by_reference(
        self,
        reference_text: str,
        paper_id: str | None = None,
    ) -> list[dict]:
        """Matcht ein In-Text-Referenz-Label (z. B. ``"Abb. 3.4"``) gegen
        Figure-Captions per Typ+Nummer-Vergleich (Issue #379).

        Anders als :meth:`find_figures_by_caption` (Freitext-LIKE-Suche,
        unveraendert fuer bestehende Aufrufer) parst diese Methode sowohl
        ``reference_text`` als auch jede Kandidaten-Caption strukturiert in
        ``(kind, number)`` und vergleicht diese Tupel. Das In-Text-Label ist
        selten wortidentischer Teilstring der vollen Caption (z. B. ist
        ``"Abb. 3.4"`` kein Teilstring von ``"Abbildung 3.4: ..."``), daher
        schlaegt reines LIKE-Matching hier praktisch immer fehl.

        Liefert ``[]`` wenn ``reference_text`` kein Typ+Nummer-Muster enthaelt
        oder kein Kandidat mit uebereinstimmendem Tupel existiert.
        """
        reference = _parse_figure_reference(reference_text)
        if reference is None:
            return []

        with self._connection() as conn:
            if paper_id is not None:
                rows = conn.execute(
                    "SELECT * FROM figures WHERE paper_id = ?", (paper_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM figures").fetchall()

        matches = []
        for row in rows:
            record = dict(row)
            caption = record.get("caption")
            if caption is None:
                continue
            if _parse_figure_reference(caption) == reference:
                matches.append(record)
        return matches

    # ------------------------------------------------------------------
    # Empirischer Teil: Transkript-Segmente + Kodierungen (Issue #473)
    # ------------------------------------------------------------------

    @staticmethod
    def _segment_id(paper_id: str, seq: int) -> str:
        """Deterministische ``segment_id`` aus (paper_id, seq).

        Bewusst kein ``uuid4()``: ein zweiter Import derselben Transkriptdatei
        muss dieselbe Stelle wiedertreffen statt eine zweite anzulegen -- die
        Stellenangabe "Abs. 12" waere sonst nicht mehr eindeutig.
        """
        return f"{paper_id}#seg-{seq}"

    def add_transcript_segment(
        self,
        paper_id: str,
        seq: int,
        text: str,
        speaker: str | None = None,
        timecode: str | None = None,
    ) -> str:
        """Upsert eines Transkript-Segments. Gibt die ``segment_id`` zurueck.

        ``seq`` ist die zitierfaehige Absatznummer innerhalb des Transkripts
        und zugleich der Idempotenz-Schluessel (UNIQUE(paper_id, seq)): ein
        erneuter Import derselben Datei aktualisiert die Zeile, statt eine
        zweite anzulegen.

        Raises:
            ValueError: Wenn ``seq`` kleiner als 1 ist -- eine Stellenangabe
                "Abs. 0" waere im Fliesstext nicht auffindbar.
        """
        if seq < 1:
            raise ValueError(f"seq muss >= 1 sein (bekommen: {seq})")

        segment_id = self._segment_id(paper_id, seq)
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO transcript_segments
                  (segment_id, paper_id, seq, speaker, timecode, text, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(paper_id, seq) DO UPDATE SET
                  speaker  = excluded.speaker,
                  timecode = excluded.timecode,
                  text     = excluded.text
                """,
                (segment_id, paper_id, seq, speaker, timecode, text, now),
            )
        return segment_id

    def list_transcript_segments(self, paper_id: str) -> list[dict]:
        """Gibt alle Segmente eines Transkripts in ``seq``-Reihenfolge zurueck."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM transcript_segments WHERE paper_id = ? ORDER BY seq",
                (paper_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def add_coding(
        self,
        paper_id: str,
        category: str,
        category_origin: str,
        segment_id: str | None = None,
        quote_id: str | None = None,
        memo: str | None = None,
    ) -> str:
        """INSERT einer Kategorienzuordnung. Gibt ``coding_id`` (UUID) zurueck.

        Args:
            category_origin: ``"induktiv"`` (am Material entwickelt) oder
                ``"deduktiv"`` (aus der Theorie abgeleitet). Die Validierung
                liegt hier statt allein im CHECK-Constraint, damit jeder
                Aufrufweg dieselbe lesbare Meldung bekommt statt eines rohen
                ``sqlite3.IntegrityError`` (Muster ``add_quote(stance=...)``).
            quote_id: Ankerbeispiel. Bleibt ``None``, solange keines
                ausgewaehlt ist -- ein Ankerzitat wird nie erfunden.

        Raises:
            ValueError: Bei leerer ``category`` oder unbekannter
                ``category_origin``.
        """
        if not category.strip():
            raise ValueError("category darf nicht leer sein")
        if category_origin not in VALID_CATEGORY_ORIGINS:
            raise ValueError(
                f"Ungueltiger category_origin '{category_origin}' -- "
                f"erlaubt: {sorted(VALID_CATEGORY_ORIGINS)}"
            )

        coding_id = str(uuid4())
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO codings
                  (coding_id, paper_id, segment_id, quote_id, category,
                   category_origin, memo, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    coding_id,
                    paper_id,
                    segment_id,
                    quote_id,
                    category.strip(),
                    category_origin,
                    memo,
                    now,
                ),
            )
        return coding_id

    def list_codings(
        self,
        paper_id: str | None = None,
        category: str | None = None,
    ) -> list[dict]:
        """Gibt Kodierungen zurueck, optional nach Paper und/oder Kategorie gefiltert."""
        clauses = []
        params: list = []
        if paper_id is not None:
            clauses.append("paper_id = ?")
            params.append(paper_id)
        if category is not None:
            clauses.append("category = ?")
            params.append(category)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM codings {where} ORDER BY category, created_at",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Decisions CRUD (v6.4)
    # ------------------------------------------------------------------

    def add_decision(
        self,
        category: str | None,
        text: str,
        rationale: str | None = None,
    ) -> str:
        """INSERT einer Decision. Gibt decision_id (UUID) zurueck."""
        decision_id = str(uuid4())
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO decisions (decision_id, category, text, rationale, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (decision_id, category, text, rationale, now),
            )
        return decision_id

    def supersede_decision(self, decision_id: str, superseded_by: str) -> None:
        """Setzt superseded_by fuer eine Decision."""
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                "UPDATE decisions SET superseded_by = ? WHERE decision_id = ?",
                (superseded_by, decision_id),
            )

    def list_decisions(
        self,
        category: str | None = None,
        active_only: bool = True,
    ) -> list[dict]:
        """Gibt Decisions zurueck, optional nach Kategorie und/oder active gefiltert."""
        clauses = []
        params: list = []
        if category is not None:
            clauses.append("category = ?")
            params.append(category)
        if active_only:
            clauses.append("superseded_by IS NULL")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM decisions {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Excluded Sources (v6.4)
    # ------------------------------------------------------------------

    def add_excluded_source(self, paper_id: str, reason: str | None = None) -> None:
        """INSERT or REPLACE eines excluded_source-Eintrags."""
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO excluded_sources (paper_id, reason, excluded_at)
                VALUES (?, ?, ?)
                """,
                (paper_id, reason, now),
            )

    def list_excluded_sources(self) -> list[dict]:
        """Gibt alle excluded_sources zurueck."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM excluded_sources ORDER BY excluded_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def is_excluded(self, paper_id: str) -> bool:
        """Prueft ob paper_id in excluded_sources ist."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM excluded_sources WHERE paper_id = ?", (paper_id,)
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Risk-of-Bias Assessments (v6.4)
    # ------------------------------------------------------------------

    def add_risk_of_bias(
        self,
        paper_id: str,
        study_type: str,
        domain_scores_json: str,
    ) -> str:
        """INSERT eines RoB-Assessments. Gibt assessment_id (UUID) zurueck."""
        assessment_id = str(uuid4())
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO risk_of_bias_assessments
                  (assessment_id, paper_id, study_type, domain_scores_json, ts)
                VALUES (?, ?, ?, ?, ?)
                """,
                (assessment_id, paper_id, study_type, domain_scores_json, now),
            )
        return assessment_id

    def list_risk_of_bias(
        self,
        paper_id: str | None = None,
    ) -> list[dict]:
        """Gibt RoB-Assessments zurueck, optional nach paper_id gefiltert."""
        with self._connection() as conn:
            if paper_id is not None:
                rows = conn.execute(
                    "SELECT * FROM risk_of_bias_assessments WHERE paper_id = ? ORDER BY ts DESC",
                    (paper_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM risk_of_bias_assessments ORDER BY ts DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Score History (v6.4)
    # ------------------------------------------------------------------

    def add_score_snapshot(
        self,
        paper_id: str,
        session_id: str,
        scores_json: str,
    ) -> str:
        """INSERT eines Score-Snapshots. Gibt snapshot_id (UUID) zurueck."""
        snapshot_id = str(uuid4())
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO score_history (snapshot_id, paper_id, session_id, ts, scores_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (snapshot_id, paper_id, session_id, now, scores_json),
            )
        return snapshot_id

    def get_score_history(
        self,
        paper_id: str,
        k: int | None = None,
    ) -> list[dict]:
        """Gibt Score-History fuer ein Paper zurueck, nach ts DESC sortiert."""
        with self._connection() as conn:
            if k is not None:
                rows = conn.execute(
                    "SELECT * FROM score_history WHERE paper_id = ? ORDER BY ts DESC LIMIT ?",
                    (paper_id, k),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM score_history WHERE paper_id = ? ORDER BY ts DESC",
                    (paper_id,),
                ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Vault Lock (v6.4)
    # ------------------------------------------------------------------

    def _raise_if_locked(self, conn: sqlite3.Connection) -> None:
        """Wirft ``VaultLockedError``, falls der Material-Passport gesperrt ist.

        Bewusst *unscoped* (Issue #380): geprueft wird nur, ob ueberhaupt ein
        Eintrag in ``vault_locked_status`` existiert -- nicht slug-genau. Eine
        ``vault.db`` bedient in der Praxis genau ein Projekt (``db_path`` wird
        ueber ``project_slug()``/``--slug`` beim Anlegen fest verdrahtet) und
        die Schreib-Tools in ``server.py`` fuehren aktuell keinen
        ``slug``-Parameter. Das slug-scoped ``is_locked(slug)``/
        ``lock_vault(slug)`` bleibt fuer diesen Zweck unveraendert; dieser
        Guard ist ein separater, bewusst grober Mechanismus.

        Wird als erste Anweisung innerhalb des jeweiligen
        ``with self._connection(commit=True) as conn:``-Blocks der
        betroffenen Schreib-Methoden aufgerufen, damit Pruefung und
        INSERT/UPDATE atomar in derselben SQLite-Transaktion liegen (kein
        TOCTOU-Fenster, keine Teil-Schreibung bei Verstoss).
        """
        row = conn.execute("SELECT slug FROM vault_locked_status LIMIT 1").fetchone()
        if row is not None:
            raise VaultLockedError(
                f"Vault ist gesperrt (Material-Passport-Lock fuer Slug "
                f"'{row['slug']}') -- Schreiboperationen sind nicht mehr erlaubt."
            )

    # ------------------------------------------------------------------
    # Chunk Embeddings (v6.5 — Contextual Retrieval #109)
    # ------------------------------------------------------------------

    def add_chunk_embedding(
        self,
        paper_id: str,
        chunk_text: str,
        context_sentence: str,
        embedding_text: str,
        embedding_vector: bytes | None,
    ) -> str:
        """INSERT eines Chunk-Embeddings. Gibt chunk_id (UUID) zurueck.

        Args:
            paper_id: Referenz auf papers.paper_id.
            chunk_text: Originaler Chunk-Text.
            context_sentence: 1-Satz-Kontext generiert via Anthropic API.
            embedding_text: Kombinierter Text (context_sentence + chunk_text).
            embedding_vector: Serialisierter Embedding-Vektor (bytes) oder None.

        Raises:
            VaultLockedError: Vault ist gesperrt (Material-Passport-Lock).
            EmbeddingDimensionMismatchError: ``embedding_vector`` hat nicht die
                Breite des Bestands (Issue #629). Frueher landete so ein Vektor
                in ``chunk_embeddings``, waehrend der vec0-Spiegel ihn still
                verwarf -- der Vault trug danach zwei unvergleichbare
                Vektorraeume, und jede Suche sah nur einen davon.
        """
        chunk_id = str(uuid4())
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            if embedding_vector:
                self._assert_vector_dim(conn, embedding_vector)
            conn.execute(
                """
                INSERT INTO chunk_embeddings
                  (chunk_id, paper_id, chunk_text, context_sentence, embedding_text,
                   embedding_vector, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    paper_id,
                    chunk_text,
                    context_sentence,
                    embedding_text,
                    embedding_vector,
                    now,
                ),
            )
            self._mirror_chunk_vector(conn, chunk_id, embedding_vector)
        return chunk_id

    def get_chunk_embeddings(self, paper_id: str) -> list[dict]:
        """Gibt alle Chunk-Embeddings fuer ein Paper zurueck."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM chunk_embeddings WHERE paper_id = ? ORDER BY created_at",
                (paper_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_chunk_embeddings(self, paper_id: str) -> int:
        """Loescht alle Chunks eines Papers (inkl. vec0-Spiegel). Gibt die Anzahl zurueck.

        Wird vom Ingest vor dem Neuschreiben aufgerufen, damit ein wiederholter
        ``add_paper``-Upsert die Chunk-Tabelle nicht endlos aufblaeht.
        """
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            chunk_ids = [
                row["chunk_id"]
                for row in conn.execute(
                    "SELECT chunk_id FROM chunk_embeddings WHERE paper_id = ?", (paper_id,)
                ).fetchall()
            ]
            if not chunk_ids:
                return 0
            conn.execute("DELETE FROM chunk_embeddings WHERE paper_id = ?", (paper_id,))
            if self.load_vec_extension(conn):
                with contextlib.suppress(sqlite3.OperationalError):
                    conn.executemany(
                        "DELETE FROM chunk_vectors WHERE chunk_id = ?",
                        [(cid,) for cid in chunk_ids],
                    )
        return len(chunk_ids)

    # ------------------------------------------------------------------
    # Embedding-Bestand: Modell-ID + Dimension (Issue #629)
    # ------------------------------------------------------------------

    def _expected_embedding_dim(self, conn: sqlite3.Connection) -> int:
        """Dimension des Bestands auf einer bestehenden Connection.

        Quelle ist ``embedding_meta``; fehlt die Zeile (frischer Vault) oder
        die Tabelle (Bestands-DB vor der Migration auf Schema 8), gilt die
        Breite, in der vec0-Tabellen bislang angelegt wurden:
        ``DEFAULT_EMBEDDING_DIM``. Bewusst ohne jeden Embedder-Zugriff -- ein
        Modell-Load haengt hier an jedem Lesepfad (u. a.
        ``quote_context_similarity`` im PreToolUse-Hook) und waere ein
        Timeout-Kandidat.
        """
        try:
            row = conn.execute("SELECT dim FROM embedding_meta WHERE id = 1").fetchone()
        except sqlite3.OperationalError:
            return DEFAULT_EMBEDDING_DIM
        if row is None or not row["dim"]:
            return DEFAULT_EMBEDDING_DIM
        return int(row["dim"])

    def expected_embedding_dim(self) -> int:
        """Dimension, die dieser Vault von einem Embedder erwartet (#629)."""
        with self._connection() as conn:
            return self._expected_embedding_dim(conn)

    def embedding_inventory(self) -> dict | None:
        """Modell-ID, Dimension und Zeitstempel des Bestands -- oder ``None``.

        ``None`` heisst "noch nie ein Embedding geschrieben" (bzw. Bestands-DB
        vor Schema 8), nicht "Dimension unbekannt": die erwartete Breite
        liefert in dem Fall :meth:`expected_embedding_dim`.
        """
        with self._connection() as conn:
            try:
                row = conn.execute(
                    "SELECT model_id, dim, updated_at FROM embedding_meta WHERE id = 1"
                ).fetchone()
            except sqlite3.OperationalError:
                return None
        return dict(row) if row is not None else None

    def _embedding_inventory_is_empty(self, conn: sqlite3.Connection) -> bool:
        """Ob im Vault ueberhaupt Vektoren liegen, die ein Wechsel entwerten koennte."""
        row = conn.execute(
            "SELECT 1 FROM chunk_embeddings WHERE embedding_vector IS NOT NULL LIMIT 1"
        ).fetchone()
        if row is not None:
            return False
        if not self.load_vec_extension(conn):
            return True
        try:
            return conn.execute("SELECT count(*) FROM quote_embeddings").fetchone()[0] == 0
        except sqlite3.OperationalError:
            return True

    def _write_embedding_meta(
        self, conn: sqlite3.Connection, model_id: str | None, dim: int
    ) -> None:
        """Schreibt die Singleton-Zeile in ``embedding_meta`` (Upsert)."""
        conn.execute(
            "INSERT INTO embedding_meta (id, model_id, dim, updated_at) VALUES (1, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET model_id = excluded.model_id, "
            "dim = excluded.dim, updated_at = excluded.updated_at",
            (model_id, dim, int(time.time())),
        )

    def _rebuild_vector_tables(self, conn: sqlite3.Connection, dim: int) -> None:
        """Legt die vec0-Tabellen in neuer Breite an (DROP + CREATE).

        vec0 kann die Spaltenbreite nicht aendern, also ist der Neuaufbau der
        einzige Weg. Aufrufer muessen sicherstellen, dass der Inhalt entweder
        leer oder rekonstruierbar ist (``migrate.reindex_embeddings``).
        """
        if not self.load_vec_extension(conn):
            return
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute("DROP TABLE IF EXISTS chunk_vectors")
            conn.execute("DROP TABLE IF EXISTS quote_embeddings")
            conn.execute(_chunk_vectors_ddl(dim))
            conn.execute(_quote_embeddings_ddl(dim))

    def register_embedding_inventory(self, model_id: str | None, dim: int) -> None:
        """Meldet Modell und Dimension an, bevor Vektoren geschrieben werden (#629).

        Drei Ausgaenge:

        * **Leerer Bestand** -- die Dimension wird uebernommen, die vec0-Tabellen
          werden in dieser Breite neu angelegt. Ein frischer Vault laesst sich so
          ohne Re-Index mit jedem Modell betreiben.
        * **Gleiche Dimension** -- nur die Modell-ID wird nachgefuehrt.
        * **Abweichende Dimension bei vorhandenem Bestand** --
          ``EmbeddingDimensionMismatchError``. Das ist der Fall, den #629
          adressiert: stillschweigend weiterzuschreiben ergaebe zwei
          unvergleichbare Vektorraeume in derselben Tabelle.

        Raises:
            ValueError: ``dim`` ist kein positiver Wert.
            EmbeddingDimensionMismatchError: Bestand hat eine andere Breite.
            VaultLockedError: Vault ist gesperrt (nur wenn geschrieben wuerde).
        """
        if dim <= 0:
            raise ValueError(f"Embedding-Dimension muss positiv sein, war {dim}")
        with self._connection(commit=True) as conn:
            try:
                row = conn.execute(
                    "SELECT model_id, dim FROM embedding_meta WHERE id = 1"
                ).fetchone()
            except sqlite3.OperationalError:
                # Bestands-DB vor Schema 8: init_schema() legt die Tabelle an.
                return
            vault_dim = int(row["dim"]) if row is not None and row["dim"] else None
            if vault_dim is None:
                # Kein Bestandsnachweis: Legacy-Vaults sind per Definition in
                # DEFAULT_EMBEDDING_DIM gebaut -- alles andere braucht einen
                # leeren Bestand oder einen Re-Index.
                vault_dim = DEFAULT_EMBEDDING_DIM
                inventory_empty = self._embedding_inventory_is_empty(conn)
            else:
                inventory_empty = (
                    self._embedding_inventory_is_empty(conn) if dim != vault_dim else False
                )

            if dim != vault_dim and not inventory_empty:
                raise dimension_mismatch_error(
                    model_id=model_id,
                    model_dim=dim,
                    vault_dim=vault_dim,
                    vault_model_id=row["model_id"] if row is not None else None,
                )

            if row is not None and int(row["dim"] or 0) == dim and row["model_id"] == model_id:
                return  # nichts zu tun -- kein Schreibzugriff, kein Lock-Check

            self._raise_if_locked(conn)
            if dim != vault_dim:
                self._rebuild_vector_tables(conn, dim)
            self._write_embedding_meta(conn, model_id, dim)

    def raise_if_locked(self) -> None:
        """Oeffentlicher Lock-Check ohne Schreibzugriff (Issue #629).

        Fuer Ablaeufe, die VOR der ersten Aenderung wissen muessen, ob sie
        ueberhaupt schreiben duerfen -- ``migrate.reindex_embeddings()`` raeumt
        vec0-Tabellen ab und darf einen gesperrten Vault nicht halb
        abgeraeumt zuruecklassen.
        """
        with self._connection() as conn:
            self._raise_if_locked(conn)

    def all_chunk_embedding_texts(self) -> list[dict]:
        """``chunk_id`` + ``embedding_text`` aller Chunks (Re-Index-Quelle, #629)."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT chunk_id, embedding_text FROM chunk_embeddings ORDER BY created_at, chunk_id"
            ).fetchall()
        return [dict(r) for r in rows]

    def all_quotes_for_embedding(self) -> list[dict]:
        """Alle Quotes mit ihrem Kontext (Re-Index-Quelle fuer ``quote_embeddings``)."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT quote_id, verbatim, context_before, context_after FROM quotes "
                "ORDER BY created_at, quote_id"
            ).fetchall()
        return [dict(r) for r in rows]

    def replace_chunk_vectors(
        self,
        vectors: Sequence[tuple[str, bytes]],
        model_id: str | None,
        dim: int,
    ) -> int:
        """Ersetzt ALLE Chunk-Vektoren durch die uebergebenen (Issue #629).

        Ein Transaktionsblock: Bestand leeren, vec0-Tabellen in der neuen
        Breite neu anlegen, neue Vektoren schreiben und spiegeln,
        ``embedding_meta`` fortschreiben. Chunks, fuer die kein Vektor
        uebergeben wurde, bleiben bewusst ohne (``NULL``) -- ein Vektor aus dem
        alten Modell waere nach dem Wechsel schlicht falsch.

        Returns:
            Anzahl geschriebener Vektoren.
        """
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            for _, blob in vectors:
                if len(blob) != dim * 4:
                    raise dimension_mismatch_error(
                        model_id=model_id,
                        model_dim=len(blob) // 4,
                        vault_dim=dim,
                    )
            conn.execute("UPDATE chunk_embeddings SET embedding_vector = NULL")
            self._rebuild_vector_tables(conn, dim)
            self._write_embedding_meta(conn, model_id, dim)
            for chunk_id, blob in vectors:
                conn.execute(
                    "UPDATE chunk_embeddings SET embedding_vector = ? WHERE chunk_id = ?",
                    (blob, chunk_id),
                )
                self._mirror_chunk_vector(conn, chunk_id, blob)
        return len(vectors)

    def _assert_vector_dim(self, conn: sqlite3.Connection, embedding_vector: bytes) -> None:
        """Wirft, wenn ein Vektor nicht die Breite des Bestands hat (#629).

        Zweite Verteidigungslinie hinter :meth:`register_embedding_inventory`:
        greift auch fuer Aufrufer, die direkt schreiben, und kennt dafuer nur
        die Byte-Laenge -- die Modell-ID steht in der Meldung nur, wenn sie im
        Bestand hinterlegt ist.
        """
        if len(embedding_vector) % 4 != 0:
            raise ValueError(
                f"Embedding-BLOB hat Laenge {len(embedding_vector)} (kein Vielfaches von 4 Bytes)"
            )
        dim = len(embedding_vector) // 4
        expected = self._expected_embedding_dim(conn)
        if dim == expected:
            return
        try:
            row = conn.execute("SELECT model_id FROM embedding_meta WHERE id = 1").fetchone()
        except sqlite3.OperationalError:
            row = None
        raise dimension_mismatch_error(
            model_id=None,
            model_dim=dim,
            vault_dim=expected,
            vault_model_id=row["model_id"] if row is not None else None,
        )

    # ------------------------------------------------------------------
    # Vektor-Suche ueber Chunks (Issue #372)
    # ------------------------------------------------------------------

    def _mirror_chunk_vector(
        self,
        conn: sqlite3.Connection,
        chunk_id: str,
        embedding_vector: bytes | None,
    ) -> bool:
        """Spiegelt einen Chunk-Vektor in die vec0-Tabelle. Best effort.

        Gibt False zurueck, wenn kein (passender) Vektor vorliegt oder die
        sqlite-vec-Extension nicht ladbar ist — dann uebernimmt der
        Python-Fallback in :meth:`knn_chunks` die Suche. Die Breite wird gegen
        den Bestand geprueft, nicht gegen eine Konstante (#629); der laute
        Fehler bei Abweichung kommt von den aufrufenden Schreibpfaden.
        """
        if not embedding_vector:
            return False
        dim = self._expected_embedding_dim(conn)
        if len(embedding_vector) != dim * 4:
            return False
        if not self.load_vec_extension(conn):
            return False
        try:
            conn.execute(_chunk_vectors_ddl(dim))
            conn.execute(
                "INSERT OR REPLACE INTO chunk_vectors (chunk_id, embedding) VALUES (?, ?)",
                (chunk_id, embedding_vector),
            )
        except sqlite3.OperationalError:
            return False
        return True

    def sync_chunk_vectors(self) -> int:
        """Legt die vec0-Tabelle an und spiegelt vorhandene Chunk-Vektoren hinein.

        Idempotent; ohne ladbare sqlite-vec-Extension ein No-op (Rueckgabe 0).
        Gibt die Anzahl gespiegelter Vektoren zurueck.
        """
        mirrored = 0
        with self._connection(commit=True) as conn:
            if not self.load_vec_extension(conn):
                return 0
            dim = self._expected_embedding_dim(conn)
            try:
                conn.execute(_chunk_vectors_ddl(dim))
            except sqlite3.OperationalError:
                return 0
            rows = conn.execute(
                "SELECT chunk_id, embedding_vector FROM chunk_embeddings "
                "WHERE embedding_vector IS NOT NULL AND length(embedding_vector) = ?",
                (dim * 4,),
            ).fetchall()
            for row in rows:
                if self._mirror_chunk_vector(conn, row["chunk_id"], row["embedding_vector"]):
                    mirrored += 1
        return mirrored

    def knn_chunks(self, query_vector: Sequence[float], k: int = 10) -> list[dict]:
        """K-Nearest-Neighbour-Suche ueber chunk_embeddings.

        Primaerpfad ist die vec0-Virtual-Table ``chunk_vectors``; ist die
        sqlite-vec-Extension nicht ladbar (Python-Builds ohne
        ``--enable-loadable-sqlite-extensions``, u. a. auf macOS) oder der
        vec0-Spiegel unvollstaendig, wird dieselbe Suche in Python ueber die
        BLOBs in ``chunk_embeddings`` gerechnet.

        Beide Pfade nutzen die euklidische Distanz. Da alle Vektoren
        L2-normalisiert gespeichert werden, ist deren Rangfolge identisch zur
        Kosinus-Rangfolge — und beide Pfade liefern dieselbe Reihenfolge.

        Passt die Breite des Query-Vektors nicht zum Bestand, wirft die Methode
        ``EmbeddingDimensionMismatchError`` (Issue #629), statt lautlos eine
        leere Trefferliste zu liefern: beide Pfade filtern die Kandidaten nach
        Byte-Laenge, ein 1024d-Query auf einem 384d-Bestand haette also
        schlicht "nichts gefunden" gemeldet -- ununterscheidbar von "es gibt
        keine passenden Chunks".

        Returns:
            Liste aus ``{chunk_id, paper_id, chunk_text, distance}``,
            aufsteigend nach Distanz (nahester Treffer zuerst).

        Raises:
            EmbeddingDimensionMismatchError: Query-Dimension passt nicht zum
                Bestand.
        """
        if not query_vector or k <= 0:
            return []
        dim = len(query_vector)
        with self._connection() as conn:
            expected = self._expected_embedding_dim(conn)
            if dim != expected and not self._embedding_inventory_is_empty(conn):
                inventory = conn.execute(
                    "SELECT model_id FROM embedding_meta WHERE id = 1"
                ).fetchone()
                raise dimension_mismatch_error(
                    model_id=None,
                    model_dim=dim,
                    vault_dim=expected,
                    vault_model_id=inventory["model_id"] if inventory is not None else None,
                )
            total = conn.execute(
                "SELECT count(*) FROM chunk_embeddings "
                "WHERE embedding_vector IS NOT NULL AND length(embedding_vector) = ?",
                (dim * 4,),
            ).fetchone()[0]
            if total == 0:
                return []
            hits: list[dict] | None = None
            if dim == expected and self.load_vec_extension(conn):
                hits = self._knn_chunks_vec0(conn, query_vector, k, total)
            if hits is None:
                hits = self._knn_chunks_python(conn, query_vector, k)
        return hits

    def _knn_chunks_vec0(
        self,
        conn: sqlite3.Connection,
        query_vector: Sequence[float],
        k: int,
        expected_total: int,
    ) -> list[dict] | None:
        """vec0-KNN. Gibt None zurueck, wenn der Pfad nicht verlaesslich ist."""
        try:
            mirrored = conn.execute("SELECT count(*) FROM chunk_vectors").fetchone()[0]
        except sqlite3.OperationalError:
            return None
        if mirrored < expected_total:
            # Spiegel unvollstaendig (z. B. DB aus einer Umgebung ohne
            # Extension): lieber vollstaendig in Python rechnen als still
            # Treffer verlieren. `migrate.add_chunk_vectors_table` repariert das.
            return None
        try:
            rows = conn.execute(
                "SELECT chunk_id, distance FROM chunk_vectors "
                "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (serialize_f32(query_vector), k),
            ).fetchall()
        except sqlite3.OperationalError:
            return None

        hits: list[dict] = []
        for row in rows:
            meta = conn.execute(
                "SELECT paper_id, chunk_text FROM chunk_embeddings WHERE chunk_id = ?",
                (row["chunk_id"],),
            ).fetchone()
            if meta is None:
                continue
            hits.append(
                {
                    "chunk_id": row["chunk_id"],
                    "paper_id": meta["paper_id"],
                    "chunk_text": meta["chunk_text"],
                    "distance": float(row["distance"]),
                }
            )
        # Gleicher Tiebreaker wie im Python-Fallback: bei exakt gleicher Distanz
        # (z. B. zwei zur Query orthogonale Chunks) wuerde vec0 sonst nach
        # interner rowid ordnen und beide Pfade lieferten verschiedene
        # Reihenfolgen fuer dieselben Daten.
        hits.sort(key=lambda hit: (hit["distance"], hit["chunk_id"]))
        return hits

    def _knn_chunks_python(
        self,
        conn: sqlite3.Connection,
        query_vector: Sequence[float],
        k: int,
    ) -> list[dict]:
        """Reiner Python-Fallback: euklidische Distanz ueber alle Chunk-BLOBs."""
        dim = len(query_vector)
        rows = conn.execute(
            "SELECT chunk_id, paper_id, chunk_text, embedding_vector FROM chunk_embeddings "
            "WHERE embedding_vector IS NOT NULL AND length(embedding_vector) = ?",
            (dim * 4,),
        ).fetchall()

        hits: list[dict] = []
        for row in rows:
            try:
                vector = deserialize_f32(row["embedding_vector"])
            except ValueError:
                continue
            distance = math.sqrt(
                sum((a - b) ** 2 for a, b in zip(query_vector, vector, strict=True))
            )
            hits.append(
                {
                    "chunk_id": row["chunk_id"],
                    "paper_id": row["paper_id"],
                    "chunk_text": row["chunk_text"],
                    "distance": distance,
                }
            )
        # chunk_id als Tiebreaker: deterministische Reihenfolge bei Gleichstand.
        hits.sort(key=lambda hit: (hit["distance"], hit["chunk_id"]))
        return hits[:k]

    def lock_vault(self, slug: str) -> None:
        """Setzt Vault-Lock fuer einen Slug. Idempotent."""
        now = int(time.time())
        with self._connection(commit=True) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO vault_locked_status (slug, locked_at)
                VALUES (?, ?)
                """,
                (slug, now),
            )

    def is_locked(self, slug: str) -> bool:
        """Prueft ob Vault-Lock fuer Slug gesetzt ist."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM vault_locked_status WHERE slug = ?", (slug,)
            ).fetchone()
        return row is not None
