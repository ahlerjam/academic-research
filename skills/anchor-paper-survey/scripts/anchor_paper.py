"""anchor_paper.py -- Anchor-Paper-Survey Skill (Issue #394).

Alternativer Recherche-Einstieg: statt eines Themas gibt der User ein
Ausgangspaper an (arXiv-URL/-ID oder lokaler PDF-Pfad). Der Skill loest daraus
Titel/Autoren auf, legt GENAU EIN Anker-Paper im Vault an
(``provenance="anchor-paper"``) und stoesst darauf eine Folge-Suche an, um
verwandte Arbeiten zu finden. Die Folge-Suche liefert nur Kandidaten zur
Anzeige -- Treffer werden NICHT automatisch in den Vault geschrieben (keine
neue Zitations-Graph-Datenbank, siehe Issue-Scope "Out").

Folge-Suche, zweigleisig (PR #440 Review, P1; erweitert um DOI-Anker fuer
PDF in Issue #599):
  - **arXiv-Anker** und **PDF-Anker mit auffindbarer DOI**: echte Zitations-/
    Referenz-Traversierung ueber die Semantic-Scholar-Graph-API
    (``/paper/{id}/citations`` + ``/paper/{id}/references``,
    ``run_citation_search()``). Der arXiv-Anker liefert mit seiner ID einen
    stabilen, direkt referenzierbaren Semantic-Scholar-Identifier
    (``ARXIV:<id>``); ein PDF-Anker bekommt denselben stabilen Identifier
    ueber seine DOI (``DOI:<doi>``) -- aus dem Vault (falls der Anker dort
    schon liegt) oder per Best-Effort-Regex aus einem Zeichenfenster am
    Anfang des PDF-Volltexts (``extract_doi_from_text()``). Das erfuellt
    Issue-Scope "In" woertlich ("referenzierte/zitierende Arbeiten ...
    nachlädt"; kein neuer externer Dienst, da Semantic Scholar bereits Teil
    des ``network_allowlist`` ist).
  - **PDF-Anker ohne auffindbare DOI** (und jeder Fall, in dem Semantic
    Scholar eine vorhandene DOI/arXiv-ID nicht kennt oder nicht erreichbar
    ist): die Folge-Suche faellt auf eine Titel-Stichwortsuche ueber die
    bestehenden Fetcher (``scripts/search.py::run_search``) zurueck --
    dokumentierte Einschraenkung, siehe SKILL.md "Bekannte Einschraenkungen".
    Das Ergebnis weist ueber ``search.method`` (``"citation"``/``"keyword"``)
    und die Message aus, welcher der beiden Faelle vorliegt -- eine
    nachgewiesene Zitationsbeziehung und eine thematische Titel-Naeherung
    sind NICHT gleichwertig und duerfen beim Schreiben nicht verwechselt
    werden.
  - In beiden Faellen wird die Rohtrefferliste VOR der Anzeige durch
    ``_filter_and_dedupe()`` geschickt: das Anker-Paper selbst wird aus der
    Trefferliste entfernt (sonst zaehlt es sich als eigene "verwandte
    Arbeit") und Mehrfachtreffer werden ueber die kanonische Repo-Pipeline
    ``scripts/dedup.py::deduplicate()`` zusammengefuehrt (sonst ist die
    gemeldete Trefferzahl systematisch zu hoch).

Musterhinweis: Konzept-Idee lose angelehnt an
JeanDiable/academic-research-plugin (MIT) -- keine Code-Uebernahme,
eigenstaendige Implementierung analog zum Muster in ``github-repo-research``
(Issue #401).

Epistemische Grundregel (analog PR #433 fuer github-repo-research): ein
fehlgeschlagener Netzwerk-Request oder ein PDF ohne Textlayer liefert KEIN
Wissen -- die Pipeline darf daraus niemals einen Titel/Autor fabrizieren.
Scheitert die Extraktion, ist das Ergebnis ein strukturierter Fehler
(``status="error"``) statt eines Crashs oder erfundener Daten.

CLI:
    python skills/anchor-paper-survey/scripts/anchor_paper.py \
        --input https://arxiv.org/abs/2005.14165 --db vault.db

    python skills/anchor-paper-survey/scripts/anchor_paper.py \
        --input /pfad/zu/paper.pdf --db vault.db

Verwendbar auch als Modul (fuer Tests und den Skill selbst).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path

# ---------------------------------------------------------------------------
# Pfad-Setup: Repo-Root UND Repo-Root/scripts auf sys.path, damit sowohl
# `academic_vault` (Package) als auch `pdf`/`search` (Top-Level-Module aus
# scripts/) importierbar sind -- analog tests/conftest.py.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
for _p in (_REPO_ROOT, _SCRIPTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# ---------------------------------------------------------------------------
# Optional-Dependencies (graceful fallback, analog github-repo-research)
# ---------------------------------------------------------------------------

try:
    import requests

    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

try:
    from pdf import detect_needs_ocr, extract_text_from_pdf

    _PDF_UTILS_AVAILABLE = True
except ImportError:
    _PDF_UTILS_AVAILABLE = False

try:
    from search import run_search as _run_search_native

    _SEARCH_AVAILABLE = True
except ImportError:
    _SEARCH_AVAILABLE = False

try:
    from dedup import deduplicate as _deduplicate_papers

    _DEDUP_AVAILABLE = True
except ImportError:
    _DEDUP_AVAILABLE = False

try:
    from text_utils import normalize_doi, normalize_paper

    _TEXT_UTILS_AVAILABLE = True
except ImportError:
    _TEXT_UTILS_AVAILABLE = False

try:
    from academic_vault.db import _UNSET as _VAULT_DOI_UNSET
    from academic_vault.server import add_paper as _vault_add_paper_native
    from academic_vault.server import get_paper as _vault_get_paper_native

    _VAULT_NATIVE = True
except ImportError:
    _VAULT_NATIVE = False
    _VAULT_DOI_UNSET = None  # Platzhalter: vault_add_paper() wirft ohnehin
    # RuntimeError, bevor dieser Wert je benutzt wird (siehe unten).


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

ARXIV_API = "https://export.arxiv.org/api/query"
_TIMEOUT = 10
_USER_AGENT = "academic-research-anchor-paper-survey/1.0"
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

# Bewusst ohne die deutschsprachigen Nischen-Module (econbiz/econstor) und
# ohne 'base' -- die Folge-Suche eines Anker-Papers soll breite, generische
# Fetcher treffen, keine domaenenspezifische Vorauswahl.
DEFAULT_SEARCH_MODULES: list[str] = ["arxiv", "semantic_scholar", "openalex", "crossref"]
DEFAULT_SEARCH_LIMIT = 20

# Semantic-Scholar-Graph-API fuer echte Zitations-/Referenz-Traversierung
# (arXiv-Anker-Fall) -- bereits Teil des SKILL.md network_allowlist.
_S2_PAPER_API = "https://api.semanticscholar.org/graph/v1/paper"
_S2_RELATION_FIELDS = "title,year,authors,externalIds,abstract,venue,citationCount"
# Nested Objekt-Key je Relation in der S2-Antwort (real verifiziert):
# {"data": [{"citingPaper": {...}}]} bzw. {"data": [{"citedPaper": {...}}]}.
_S2_RELATIONS: tuple[tuple[str, str], ...] = (
    ("citations", "citingPaper"),
    ("references", "citedPaper"),
)

# Schwelle fuer "ist dieser Treffer das Anker-Paper selbst" -- bewusst
# identisch zu dedup.py's Titel-Schwelle (Level 2), weil es dieselbe Frage
# ist: "beschreiben zwei Titel dieselbe Arbeit?" (siehe _filter_and_dedupe).
_ANCHOR_TITLE_SIMILARITY_THRESHOLD = 0.85

_ARXIV_ABS_PDF_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_ARXIV_BARE_ID_RE = re.compile(r"^(\d{4}\.\d{4,5})(?:v\d+)?$")


# ---------------------------------------------------------------------------
# Input-Erkennung: arXiv-URL/-ID vs. lokaler PDF-Pfad vs. ungueltig
# ---------------------------------------------------------------------------


def parse_arxiv_id(value: str) -> str | None:
    """Extrahiert eine arXiv-ID aus einer arXiv-URL/-ID.

    Gibt None zurueck, wenn `value` keine arXiv-URL/-ID ist -- das ist KEIN
    Fehler, sondern das Signal fuer den Aufrufer, stattdessen einen PDF-Pfad
    zu pruefen (siehe detect_input()).
    """
    if not value:
        return None
    value = value.strip()
    m = _ARXIV_ABS_PDF_RE.search(value)
    if m:
        return m.group(1)
    m = _ARXIV_BARE_ID_RE.match(value)
    if m:
        return m.group(1)
    return None


def detect_input(value: str) -> tuple[str, str]:
    """Erkennt die Eingabeart: ('arxiv', arxiv_id) oder ('pdf', abs_path).

    Wirft ValueError, wenn `value` weder eine gueltige arXiv-URL/-ID noch ein
    existierender PDF-Pfad ist (AC3: verstaendliche Fehlermeldung, keine
    Vault-Mutation -- der Aufruf erfolgt VOR jedem Vault-Zugriff).
    """
    arxiv_id = parse_arxiv_id(value)
    if arxiv_id:
        return "arxiv", arxiv_id

    stripped = (value or "").strip()
    if stripped:
        path = Path(stripped).expanduser()
        if path.is_file():
            return "pdf", str(path)

    raise ValueError(
        f"Eingabe ist weder eine gueltige arXiv-URL/-ID noch ein existierender PDF-Pfad: {value!r}"
    )


# ---------------------------------------------------------------------------
# arXiv-Resolution (eigenstaendig implementiert, kein Cross-Skill-Import aus
# github-repo-research -- analoges, aber getrenntes Muster, Praezedenzfall
# Issue #401)
# ---------------------------------------------------------------------------


def resolve_arxiv_id(arxiv_id: str) -> str | None:
    """Holt CSL-JSON fuer eine arXiv-ID via arXiv-API (id_list=).

    Gibt None zurueck bei Netzwerkfehler, HTTP != 200 oder keinem Treffer --
    niemals eine Exception (Evidence before assertions: kein Fake-Paper).
    """
    if not arxiv_id or not _REQUESTS_AVAILABLE:
        return None
    try:
        resp = requests.get(
            ARXIV_API,
            params={"id_list": arxiv_id},
            timeout=_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
        )
    except Exception:
        return None
    if resp.status_code != 200:
        return None

    try:
        root = ET.fromstring(resp.text)
    except Exception:
        return None

    entry = root.find("atom:entry", _ATOM_NS)
    if entry is None:
        return None

    # arXiv beantwortet eine unbekannte/ungueltige ID NICHT mit HTTP != 200,
    # sondern mit einem regulaeren Atom-Feed (HTTP 200), dessen einziger
    # <entry> auf "arxiv.org/api/errors" zeigt und <title>Error</title>
    # traegt (arXiv-API-Manual). Ohne diesen Guard wuerde ein Fake-Paper mit
    # Titel "Error" im Vault landen -- Regression aus PR #440 Review (P1).
    entry_id = (entry.findtext("atom:id", namespaces=_ATOM_NS) or "").strip()
    if "arxiv.org/api/errors" in entry_id:
        return None

    title = (entry.findtext("atom:title", namespaces=_ATOM_NS) or "").strip()
    title = re.sub(r"\s+", " ", title)
    if not title or title == "Error":
        return None

    authors = []
    for a in entry.findall("atom:author", _ATOM_NS):
        name = a.findtext("atom:name", namespaces=_ATOM_NS)
        if name and name.strip():
            authors.append({"literal": name.strip()})

    published = entry.findtext("atom:published", namespaces=_ATOM_NS) or ""
    year = int(published[:4]) if len(published) >= 4 and published[:4].isdigit() else None

    csl: dict = {
        "type": "article-journal",
        "title": title,
        "author": authors,
        "DOI": f"10.48550/arXiv.{arxiv_id}",
    }
    if year:
        csl["issued"] = {"date-parts": [[year]]}
    return json.dumps(csl, ensure_ascii=False)


# ---------------------------------------------------------------------------
# DOI-Extraktion aus PDF-Volltext (Issue #599)
#
# Textquellenagnostisch, eigenstaendige Implementierung analog zu
# skills/github-repo-research/scripts/analyze_repo.py::extract_dois()
# (kein Cross-Skill-Import, Praezedenzfall Issue #401).
# ---------------------------------------------------------------------------

_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\]\)\"'<>?#%]+)", re.IGNORECASE)

# Ein PDF-DOI sitzt so gut wie immer auf der Titelseite/im Header (Zeitschriften-
# Impressum, Kopfzeile) -- ein Scan des VOLLEN Textes traefe eher eine zitierte
# Fremd-DOI aus der Bibliographie als die eigene DOI des Papers (Issue #599
# Plan, Risiko 1). Fenster grosszuegig bemessen (mehrspaltige Layouts, lange
# Header), aber bewusst kein Vollscan.
_DOI_SEARCH_WINDOW_CHARS = 2000


def extract_doi_from_text(text: str | None) -> str | None:
    """Best-Effort-DOI-Extraktion aus einem Zeichenfenster am Textanfang.

    Gibt die erste im Fenster gefundene, normalisierte DOI zurueck oder None
    (kein Treffer). Bewusst kein Vollscan und keine Mehrfach-Kandidaten-
    Bewertung -- "korrekt genug fuer eine Folge-Suche" (Issue #394-Massstab),
    keine zitierfaehige Bibliographie-Extraktion.
    """
    if not text:
        return None
    window = text[:_DOI_SEARCH_WINDOW_CHARS]
    m = _DOI_RE.search(window)
    if not m:
        return None
    raw = m.group(1).rstrip(").,;”’")
    return normalize_doi(raw) if _TEXT_UTILS_AVAILABLE else raw


# ---------------------------------------------------------------------------
# Titel/Autoren-Heuristik aus PDF-Volltext (Best-Effort, siehe SKILL.md)
# ---------------------------------------------------------------------------

_AUTHOR_LINE_SPLIT_RE = re.compile(r",|\band\b|\bund\b|&", re.IGNORECASE)
_MAX_AUTHOR_NAME_CHARS = 80  # Guard gegen Fliesstext-Fehltreffer als "Autor"


def _extract_title_and_authors(text: str) -> tuple[str, list[dict]]:
    """Best-Effort-Heuristik: erste nicht-leere Zeile = Titel, zweite = Autoren.

    KEIN Anspruch auf belegte Bibliographie-Extraktion (Issue #394, AC2:
    "korrekt genug" fuer eine Folge-Suche -- nicht mehr). Layouts ohne diese
    Zeilenreihenfolge (z.B. Konferenz-Header vor dem Titel) werden nicht
    erkannt; das ist eine dokumentierte Einschraenkung, kein Bug.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "", []

    title = lines[0]
    authors: list[dict] = []
    if len(lines) > 1:
        for part in _AUTHOR_LINE_SPLIT_RE.split(lines[1]):
            name = part.strip(" .")
            if name and len(name) <= _MAX_AUTHOR_NAME_CHARS:
                authors.append({"literal": name})
    return title, authors


# ---------------------------------------------------------------------------
# Folge-Suche (bestehende Fetcher, kein neuer externer Dienst)
# ---------------------------------------------------------------------------


def run_search(
    query: str,
    modules: list[str],
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> tuple[list[dict], list[str]]:
    """Wrapper um scripts/search.py::run_search(). Wird in Tests via patch() ersetzt."""
    if not _SEARCH_AVAILABLE:
        return [], list(modules)
    return _run_search_native(query, modules, limit=limit)


# Ohne API-Key rate-limitet Semantic Scholar aggressiv (real beobachtet
# waehrend der Implementierung von #394); mit dem in #599-Praezisierung
# geforderten SS_API_KEY-Header (analog scripts/search.py:271-272) mehr
# Kopfraum, aber immer noch Retry-faehig statt eines einmaligen festen
# sleep(2.0) -- ohne DOI-Anker traf run_citation_search() bisher fast nur
# arXiv-Papers (Informatik), mit DOI-Ankern skaliert der Traffic auf jedes
# Journal-PDF (#599-Gegenpruefung, Skalierungsrisiko).
_S2_MAX_RETRIES = 4
_S2_BASE_DELAY = 2.0


def _fetch_s2_relation(paper_ref: str, relation: str, limit: int) -> dict | None:
    """Einzelner GET gegen /paper/{paper_ref}/{relation}, mit exponentiellem
    Retry bei HTTP 429 -- requests-basiert nachgebaut analog
    scripts/search.py::_retry_on_429 (dort httpx, hier requests: andere
    Exception-Semantik, kein Cross-Library-Import).

    Gibt das geparste JSON zurueck, oder None bei Netzwerkfehler/HTTP!=200
    nach allen Retries -- niemals eine Exception (Evidence before assertions).
    """
    # paper_ref stammt aus _DOI_RE (erlaubt '/' im DOI-Suffix) bzw. direkt vom
    # Aufrufer -- ungequotet in den URL-Pfad interpoliert liesse sich damit
    # theoretisch ein Pfad-Segment (z.B. "..") einschleusen (Issue #599,
    # Operator-Review Runde 4, P2). quote(..., safe=":.") kodiert '/' zu
    # '%2F', laesst aber das erwartete "DOI:"/"ARXIV:"-Praefix lesbar.
    url = f"{_S2_PAPER_API}/{urllib.parse.quote(paper_ref, safe=':.')}/{relation}"
    params = {"fields": _S2_RELATION_FIELDS, "limit": limit}
    headers = {"User-Agent": _USER_AGENT}
    if api_key := os.environ.get("SS_API_KEY"):
        headers["x-api-key"] = api_key
    for attempt in range(_S2_MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=_TIMEOUT, headers=headers)
        except Exception:
            return None
        if resp.status_code == 429 and attempt < _S2_MAX_RETRIES - 1:
            time.sleep(_S2_BASE_DELAY * (2**attempt))
            continue
        if resp.status_code != 200:
            return None
        try:
            return resp.json()
        except Exception:
            return None
    return None


def run_citation_search(
    paper_ref: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> tuple[list[dict], list[str]]:
    """Echte Zitations-/Referenz-Traversierung ueber die
    Semantic-Scholar-Graph-API fuer ein S2-referenzierbares Anker-Paper
    (z.B. ``paper_ref="ARXIV:2005.14165"``).

    Erfuellt Issue-#394-Scope "In" woertlich: "anschliessend
    referenzierte/zitierende Arbeiten ... nachlädt" -- im Unterschied zu
    ``run_search()`` (Titel-Stichwortsuche) sind das hier tatsaechlich
    verifizierte Zitationsbeziehungen, kein Text-Match (P1 aus PR #440
    Review: SKILL.md versprach Zitations-Recherche, geliefert wurde nur
    Titel-Keyword-Suche).

    Ruft beide Relationen ab (Arbeiten, die den Anker zitieren UND Arbeiten,
    die der Anker zitiert). Ein Netzwerkfehler/HTTP!=200 einer einzelnen
    Relation liefert KEINE Exception, sondern landet als Eintrag (z.B.
    "citations") in der zurueckgegebenen Fehlerliste -- analog zu
    ``failed_modules`` bei ``run_search()``, damit beide Pfade in
    ``anchor_paper_survey()`` gleich behandelt werden koennen.

    Wird in Tests via patch() ersetzt.
    """
    if not paper_ref or not _REQUESTS_AVAILABLE:
        return [], [relation for relation, _ in _S2_RELATIONS]

    hits: list[dict] = []
    failed: list[str] = []
    for relation, nested_key in _S2_RELATIONS:
        payload = _fetch_s2_relation(paper_ref, relation, limit)
        if payload is None:
            failed.append(relation)
            continue
        items = payload.get("data") or []
        for item in items:
            paper = item.get(nested_key) or {}
            title = (paper.get("title") or "").strip()
            if not title:
                continue
            ext = paper.get("externalIds") or {}
            raw = {
                "doi": ext.get("DOI"),
                "title": title,
                "authors": [a.get("name") for a in paper.get("authors", []) if a.get("name")],
                "year": paper.get("year"),
                "abstract": paper.get("abstract"),
                "venue": paper.get("venue"),
                "citations": paper.get("citationCount", 0),
                "url": f"https://www.semanticscholar.org/paper/{paper.get('paperId')}"
                if paper.get("paperId")
                else None,
            }
            source_module = f"semantic_scholar_{relation}"
            hit = normalize_paper(raw, source_module) if _TEXT_UTILS_AVAILABLE else raw
            hits.append(hit)
        time.sleep(0.5)  # S2-Rate-Limit-Hoeflichkeit, analog scripts/search.py
    return hits, failed


def _verify_extracted_doi_title_match(
    paper_ref: str,
    anchor_title: str,
) -> bool:
    """Verifiziert, dass der S2-Titel der DOI dem Anker-Titel ähnelt.

    Extrahierte DOIs werden nur persistiert, wenn der S2-Titel dem extrahierten
    Titel ähnelt (≥85% Schwelle). Das verhindert, dass fremde DOIs (Erratum-
    Header, Deckblatt) persistiert werden, auch wenn Semantic Scholar sie kennt.

    Gibt True zurück bei erfolgreicher Verifikation, False bei Fehler/Mismatch.
    Wird in Tests via patch() ersetzt.
    """
    if not paper_ref or not _REQUESTS_AVAILABLE:
        return False

    # Selbes Quoting-Muster wie in _fetch_s2_relation() (Issue #599, Operator-
    # Review Runde 4, P2) -- konsistent an beiden Stellen, die paper_ref in
    # eine S2-URL interpolieren.
    url = f"{_S2_PAPER_API}/{urllib.parse.quote(paper_ref, safe=':.')}"
    params = {"fields": "title"}
    headers = {"User-Agent": _USER_AGENT}
    if api_key := os.environ.get("SS_API_KEY"):
        headers["x-api-key"] = api_key
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT, headers=headers)
        if resp.status_code != 200:
            return False
        payload = resp.json()
        s2_title = (payload.get("title") or "").strip()
        if not s2_title:
            return False
        # Nutze die gleiche Ähnlichkeitsschwelle wie bei _filter_and_dedupe()
        ratio = SequenceMatcher(None, s2_title.lower(), anchor_title.lower()).ratio()
        return ratio >= _ANCHOR_TITLE_SIMILARITY_THRESHOLD
    except Exception:
        return False


def _filter_and_dedupe(
    hits: list[dict],
    anchor_title: str,
    anchor_doi: str | None = None,
) -> list[dict]:
    """Entfernt das Anker-Paper aus der Rohtrefferliste und dedupliziert den
    Rest ueber die kanonische Repo-Pipeline (``scripts/dedup.py::deduplicate``,
    siehe auch ``commands/search.md`` Schritt 5).

    Ohne diesen Schritt zaehlt sich das Anker-Paper als eigene "verwandte
    Arbeit" (die Folge-Suche fragt woertlich nach dem Anker-Titel bzw. holt
    dessen Zitations-Nachbarschaft, der Anker selbst taucht darin fast immer
    auf) und Mehrfachtreffer aus mehreren Modulen/Relationen blaehen die
    gemeldete Trefferzahl systematisch auf (P1 aus PR #440 Review).
    """
    anchor_doi_norm = (
        normalize_doi(anchor_doi)
        if (_TEXT_UTILS_AVAILABLE and anchor_doi)
        else (anchor_doi or None)
    )
    anchor_title_norm = (anchor_title or "").strip().lower()

    filtered: list[dict] = []
    for hit in hits:
        hit_doi = hit.get("doi")
        hit_doi_norm = normalize_doi(hit_doi) if (_TEXT_UTILS_AVAILABLE and hit_doi) else hit_doi
        if anchor_doi_norm and hit_doi_norm and hit_doi_norm == anchor_doi_norm:
            continue
        hit_title = (hit.get("title") or "").strip()
        if hit_title and anchor_title_norm:
            ratio = SequenceMatcher(None, hit_title.lower(), anchor_title_norm).ratio()
            if ratio >= _ANCHOR_TITLE_SIMILARITY_THRESHOLD:
                continue
        filtered.append(hit)

    if _DEDUP_AVAILABLE:
        filtered = _deduplicate_papers(filtered)
    return filtered


# ---------------------------------------------------------------------------
# Vault-Integration
# ---------------------------------------------------------------------------


def vault_add_paper(
    db_path: str,
    paper_id: str,
    csl_json: str,
    doi=_VAULT_DOI_UNSET,
    pdf_path: str | None = None,
) -> None:
    """Wrapper um academic_vault.server.add_paper mit provenance='anchor-paper'.

    ``doi`` defaultet auf das Vault-Sentinel ``academic_vault.db._UNSET``
    (Issue #599, Plan-Risiko 2) statt auf ``None``: ein Aufruf ohne
    explizites ``doi``-Kwarg laesst einen ggf. bereits gespeicherten DOI
    unangetastet, statt ihn auf NULL zurueckzusetzen. Vorher wurde ``doi=None``
    von ``_handle_pdf()`` bei jedem Lauf explizit durchgereicht -- ein
    zweiter Lauf auf demselben PDF ohne neu gefundene DOI haette einen
    zuvor gefundenen/gespeicherten DOI stillschweigend geloescht.

    Wird in Tests via patch() ersetzt.
    """
    if _VAULT_NATIVE:
        _vault_add_paper_native(
            db_path=db_path,
            paper_id=paper_id,
            csl_json=csl_json,
            doi=doi,
            pdf_path=pdf_path,
            provenance="anchor-paper",
        )
    else:
        raise RuntimeError(
            "vault_add_paper: academic_vault.server nicht verfuegbar. "
            "Stelle sicher dass der MCP-Server im PYTHONPATH ist."
        )


def vault_get_paper(db_path: str, paper_id: str) -> dict | None:
    """Wrapper um academic_vault.server.get_paper (Issue #599, AC2: ein
    bereits im Vault vorhandener DOI hat Vorrang vor erneuter Text-Extraktion).

    Graceful Fallback analog vault_add_paper(): fehlt academic_vault.server,
    liefert dieser Wrapper None statt zu crashen -- der Aufrufer behandelt
    das identisch zu "kein Vault-Eintrag vorhanden".

    Wird in Tests via patch() ersetzt.
    """
    if _VAULT_NATIVE:
        return _vault_get_paper_native(db_path, paper_id)
    return None


# ---------------------------------------------------------------------------
# Anker-Fall-Handler
# ---------------------------------------------------------------------------


def _handle_arxiv(arxiv_id: str, db_path: str) -> dict:
    csl_json = resolve_arxiv_id(arxiv_id)
    if not csl_json:
        return {
            "status": "error",
            "message": (
                f"arXiv-ID '{arxiv_id}' konnte nicht aufgeloest werden "
                f"(Netzwerkfehler, Rate-Limit oder kein Treffer bei arXiv) -- "
                f"kein Paper wurde angelegt."
            ),
        }
    data = json.loads(csl_json)
    title = data.get("title") or arxiv_id
    paper_id = f"arxiv-{arxiv_id.replace('.', '-')}"
    doi = f"10.48550/arXiv.{arxiv_id}"
    vault_add_paper(db_path=db_path, paper_id=paper_id, csl_json=csl_json, doi=doi)
    return {
        "status": "ok",
        "paper_id": paper_id,
        "source": "arxiv",
        "title": title,
        "doi": doi,
        # Semantic-Scholar-Graph-API akzeptiert arXiv-IDs direkt in diesem
        # Format als {paper_id} (real verifiziert) -- damit ist eine echte
        # Zitations-/Referenz-Traversierung moeglich (run_citation_search()),
        # ohne den arXiv-Treffer vorher erneut per Titel-Suche wiederzufinden.
        "s2_ref": f"ARXIV:{arxiv_id}",
    }


def _handle_pdf(pdf_path: str, db_path: str) -> dict:
    if not _PDF_UTILS_AVAILABLE:
        return {
            "status": "error",
            "message": (
                "PDF-Extraktion nicht verfuegbar: scripts/pdf.py konnte nicht "
                "importiert werden (fehlende Abhaengigkeit pypdf/httpx?)."
            ),
        }

    # Deterministisch aus dem absoluten PDF-Pfad ableiten (nicht uuid4()),
    # damit vault_add_paper() ein Upsert ist: ein zweiter Lauf auf demselben
    # PDF aktualisiert denselben Eintrag statt ein Duplikat anzulegen --
    # analog zum arXiv-Pfad (paper_id=arxiv-<id>). P2 aus PR #440 Review.
    # Vor der Textextraktion berechnet (Issue #599 Plan, Task 4), damit
    # vault_get_paper() unten einen ggf. bereits gespeicherten DOI abfragen
    # kann, BEVOR erneut aus dem PDF-Text extrahiert wird (AC2).
    abs_path = str(Path(pdf_path).expanduser().resolve())
    path_hash = hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:12]
    paper_id = f"anchor-{path_hash}"

    if detect_needs_ocr(pdf_path):
        return {
            "status": "error",
            "message": (
                f"PDF '{pdf_path}' hat keinen ausreichenden Textlayer (OCR "
                f"noetig) -- Titel/Autoren koennen nicht extrahiert werden. "
                f"Siehe scripts/ocr.py fuer eine OCR-Vorverarbeitung, dann "
                f"erneut versuchen."
            ),
        }

    text = extract_text_from_pdf(pdf_path)
    title, authors = _extract_title_and_authors(text)
    if not title:
        return {
            "status": "error",
            "message": f"Kein extrahierbarer Text in PDF '{pdf_path}' -- kein Titel gefunden.",
        }

    # DOI-Aufloesung (Issue #599, AC1/AC2): ein bereits im Vault liegender
    # DOI hat Vorrang -- er wird NICHT erneut aus dem PDF-Text gezogen, auch
    # wenn dort inzwischen eine andere/keine DOI zu finden waere. Erst wenn
    # kein Vault-Eintrag existiert (oder er keinen DOI traegt), greift die
    # Best-Effort-Extraktion aus dem Textfenster (extract_doi_from_text()).
    existing_paper = vault_get_paper(db_path, paper_id)
    existing_doi = (existing_paper or {}).get("doi") if existing_paper else None
    doi = existing_doi if existing_doi else extract_doi_from_text(text)
    # P1 fix (flowkit review): extrahierte DOI wird erst nach S2-Verifikation
    # persistiert (siehe anchor_paper_survey). Vault-DOI wird immer persistiert.
    doi_source = "vault" if existing_doi else ("extracted" if doi else None)

    csl: dict = {"type": "article-journal", "title": title, "author": authors}
    # P1 fix: nur Vault-DOIs werden ins CSL geschrieben. Extrahierte DOIs werden
    # erst nach S2-Verifikation hinzugefuegt (siehe anchor_paper_survey).
    if existing_doi:
        csl["DOI"] = existing_doi
    csl_json = json.dumps(csl, ensure_ascii=False)

    if existing_doi:
        # Explizites doi=... setzt/erhaelt den Wert fuer Vault-DOI. Ohne DOI wird der
        # doi-Kwarg bewusst WEGGELASSEN (Sentinel-Default in vault_add_paper()
        # statt doi=None) -- sonst wuerde ein zuvor gespeicherter DOI bei
        # einem Lauf ohne neuen Fund auf NULL zurueckgesetzt (Risiko 2).
        vault_add_paper(
            db_path=db_path,
            paper_id=paper_id,
            csl_json=csl_json,
            doi=existing_doi,
            pdf_path=pdf_path,
        )
    else:
        # Extrahierte DOI wird NICHT persistiert -- nur fuer s2_ref benutzt.
        # Sie wird erst in anchor_paper_survey() gespeichert, nachdem Semantic
        # Scholar sie verifiziert hat (mindestens eine Relation != failed).
        vault_add_paper(db_path=db_path, paper_id=paper_id, csl_json=csl_json, pdf_path=pdf_path)

    result: dict = {"status": "ok", "paper_id": paper_id, "source": "pdf", "title": title}
    if authors:
        # Authoren speichern fuer naechstliche Vault-Updates, falls DOI persistiert werden soll
        result["authors"] = authors
    if doi_source == "extracted":
        # PDF-Pfad speichern fuer den Nachtrags-Upsert nach S2-Verifikation (Daten-Verlust vermeiden)
        result["pdf_path"] = abs_path
    if doi:
        result["doi"] = doi
        result["doi_source"] = doi_source
        # Wie beim arXiv-Anker (s2_ref="ARXIV:<id>") akzeptiert die
        # Semantic-Scholar-Graph-API DOIs direkt als {paper_ref} in diesem
        # Format (real verifiziert, Issue #599) -- damit bekommt auch der
        # PDF-Anker die echte Zitations-/Referenz-Traversierung statt der
        # Titel-Stichwortsuche.
        result["s2_ref"] = f"DOI:{doi}"
    return result


# ---------------------------------------------------------------------------
# Haupt-Pipeline
# ---------------------------------------------------------------------------


def anchor_paper_survey(
    input_value: str,
    db_path: str = "vault.db",
    search_modules: list[str] | None = None,
    search_limit: int = DEFAULT_SEARCH_LIMIT,
) -> dict:
    """Legt ein Anker-Paper (arXiv-URL/-ID oder PDF-Pfad) im Vault an und
    stoesst darauf eine Folge-Suche nach verwandten Arbeiten an.

    Wirft ValueError bei ungueltiger Eingabe (AC3) -- VOR jedem Vault-Zugriff,
    also garantiert ohne Vault-Mutation.

    Scheitert die Anker-Extraktion selbst (arXiv-Resolution ohne Treffer,
    PDF ohne Textlayer/Text), ist das Ergebnis ``{"status": "error",
    "message": ...}`` -- kein Crash, kein fabriziertes Paper, keine
    Folge-Suche (AC2/AC3: "kein Vault verändern" bzw. "sauberer Fehlertext").

    Bei erfolgreich angelegtem Anker-Paper wird IMMER genau ein Vault-Eintrag
    geschrieben (AC1); die Folge-Suche liefert nur Kandidaten zur Anzeige --
    ihre Treffer werden NICHT automatisch in den Vault geschrieben (kein
    neuer externer Dienst, keine Zitations-Graph-DB, siehe Issue-Scope "Out").
    Ein leeres oder fehlgeschlagenes Suchergebnis ist daher kein Grund, das
    bereits angelegte Anker-Paper zu verwerfen -- es wird als sauberer
    Fehlertext in der Nachricht gemeldet.

    Folge-Suche, zweigleisig (PR #440 Review, P1; erweitert um PDF-DOI-Anker
    in Issue #599 -- siehe Modul-Docstring): arXiv-Anker und PDF-Anker mit
    auffindbarer DOI (Vault oder ``extract_doi_from_text()``) nutzen
    ``run_citation_search()`` (echte Zitations-/Referenz-Traversierung ueber
    Semantic Scholar). PDF-Anker ohne DOI -- sowie jeder Fall, in dem Semantic
    Scholar eine vorhandene Referenz nicht kennt/nicht erreichbar ist, ODER
    eine aus dem PDF extrahierte (noch unverifizierte) DOI beim S2-Titelabgleich
    nicht zum Anker-Titel passt -- fallen auf ``run_search()``
    (Titel-Stichwortsuche) zurueck, niemals auf einen Abbruch. Die
    Titel-Verifikation laeuft dabei bewusst VOR ``run_citation_search()``:
    sonst wuerde bei einer fremden DOI (Verlags-/Aggregator-Deckblatt,
    Erratum-Header) bereits der Zitationsgraph des falschen Papers abgefragt
    und faelschlich als nachgewiesene Zitationsbeziehung DIESES Ankers
    gemeldet (Issue #599, Operator-Review Runde 4). In allen Faellen entfernt
    ``_filter_and_dedupe()`` das Anker-Paper aus der Rohtrefferliste und
    dedupliziert den Rest ueber die kanonische Repo-Pipeline
    (``scripts/dedup.py``), bevor gezaehlt/gemeldet wird.

    Returns:
        {"status": "ok"|"error", "paper_id"?, "source"?, "title"?, "doi"?,
         "search"?: {"hits", "count", "failed_modules",
                      "method": "citation"|"keyword"}, "message"}
        ``search.method == "citation"`` heisst: die Treffer stammen aus einer
        nachgewiesenen Zitations-/Referenz-Beziehung (Semantic Scholar).
        ``"keyword"`` heisst: reine thematische Titel-Naeherung, KEINE
        nachgewiesene Zitationsbeziehung (Issue #599, AC4).
    """
    kind, normalized = detect_input(input_value)

    anchor = (
        _handle_arxiv(normalized, db_path) if kind == "arxiv" else _handle_pdf(normalized, db_path)
    )
    if anchor["status"] == "error":
        return anchor

    # method + fallback_reason (Issue #599, AC4/AC5): "citation" nur bei
    # echter Zitations-/Referenz-Traversierung (arXiv- ODER DOI-Anker),
    # "keyword" sowohl beim urspruenglichen PDF-ohne-DOI-Fall als auch beim
    # Rueckfall, wenn Semantic Scholar einen vorhandenen s2_ref nicht kennt
    # (oder nicht erreichbar war) -- BEIDE Relationen ("citations" UND
    # "references") schlagen dann fehl, waehrend ein einzelner fehlgeschlagener
    # Relation-Call (siehe test_partial_relation_failure_is_reported) weiterhin
    # ein reiner Fehlerbericht ohne Fallback bleibt.
    s2_ref = anchor.get("s2_ref")
    fallback_reason: str | None = None

    # Titel-Verifikation VOR run_citation_search() (Issue #599, Operator-
    # Entscheidung Runde 4/Konvergenz-Regel): eine extrahierte DOI (im
    # Unterschied zu einer bereits im Vault liegenden bzw. der arXiv-eigenen)
    # ist unverifiziert -- Verlags-/Aggregator-Deckblaetter oder Erratum-Header
    # koennen eine fremde DOI ins Textfenster gebracht haben. Wuerde
    # run_citation_search() trotzdem zuerst laufen, meldet das Ergebnis den
    # Zitationsgraphen des FALSCHEN Papers als "nachgewiesene
    # Zitationsbeziehung" dieses Ankers -- genau der P1-Fund aus Review-Runde
    # 4 (der bisherige Code verifizierte nur als Gate fuer den Vault-Upsert,
    # NACHDEM die falsche Abfrage schon gelaufen war). Deshalb hier: bei
    # fehlgeschlagener Verifikation wird der Zitationsgraph gar nicht erst
    # abgefragt, sondern derselbe Rueckfall wie beim "S2 kennt die DOI
    # nicht"-Fall genommen.
    doi_mismatch = False
    if s2_ref and anchor.get("doi_source") == "extracted" and anchor.get("doi"):
        doi_verified = _verify_extracted_doi_title_match(s2_ref, anchor["title"])
        if not doi_verified:
            doi_mismatch = True

    if doi_mismatch:
        fallback_reason = "S2-Titel der extrahierten DOI passt nicht zum Anker-Titel"
        modules = list(search_modules) if search_modules else list(DEFAULT_SEARCH_MODULES)
        raw_hits, failed = run_search(anchor["title"], modules, limit=search_limit)
        method = "keyword"
        # Die nie verifizierte DOI darf weder im Ergebnis auftauchen noch
        # (ueber anchor.get("doi") in _filter_and_dedupe() unten) als
        # Anker-DOI behandelt werden -- sie wurde bereits in _handle_pdf()
        # NICHT in den Vault geschrieben (Sentinel-Default), hier wird sie
        # zusaetzlich aus dem In-Memory-Ergebnis entfernt.
        anchor.pop("doi", None)
    elif s2_ref:
        raw_hits, failed = run_citation_search(s2_ref, limit=search_limit)
        if set(failed) == {"citations", "references"}:
            fallback_reason = f"Semantic Scholar kennt '{s2_ref}' nicht oder war nicht erreichbar"
            modules = list(search_modules) if search_modules else list(DEFAULT_SEARCH_MODULES)
            raw_hits, failed = run_search(anchor["title"], modules, limit=search_limit)
            method = "keyword"
        else:
            method = "citation"
            # Extrahierte DOI wird erst hier persistiert -- die Titel-
            # Verifikation ist zu diesem Zeitpunkt bereits erfolgreich
            # durchlaufen (sonst waeren wir im doi_mismatch-Zweig oben
            # gelandet und run_citation_search() waere gar nicht aufgerufen
            # worden).
            if anchor.get("doi_source") == "extracted" and anchor.get("doi"):
                authors = anchor.get("authors", [])
                csl_with_doi: dict = {
                    "type": "article-journal",
                    "title": anchor["title"],
                    "author": authors,
                    "DOI": anchor["doi"],
                }
                vault_add_paper(
                    db_path=db_path,
                    paper_id=anchor["paper_id"],
                    csl_json=json.dumps(csl_with_doi, ensure_ascii=False),
                    doi=anchor["doi"],
                    pdf_path=anchor.get("pdf_path"),  # Vermeidet Datenverlust der PDF-Pfad-Spalte
                )
    else:
        modules = list(search_modules) if search_modules else list(DEFAULT_SEARCH_MODULES)
        raw_hits, failed = run_search(anchor["title"], modules, limit=search_limit)
        method = "keyword"
        if kind == "pdf":
            fallback_reason = "kein DOI im PDF-Text bzw. Vault-Eintrag gefunden"

    hits = _filter_and_dedupe(raw_hits, anchor["title"], anchor.get("doi"))

    # AC4: nachgewiesene Zitationsbeziehung vs. thematische Naeherung muessen
    # im Ergebnis literal unterscheidbar sein -- bewusst disjunkte Formulierungen
    # (keine gemeinsame Teilphrase), damit Nutzer/Tests sie nicht verwechseln.
    method_note = (
        "beruht auf einer nachgewiesenen Zitationsbeziehung (Semantic Scholar "
        "/citations + /references)"
        if method == "citation"
        else "beruht auf einer thematischen Titel-Naeherung, keine gepruefte Zitationsbeziehung"
    )
    reason_note = f" ({fallback_reason})" if fallback_reason else ""

    if hits:
        message = (
            f"Anker-Paper '{anchor['title']}' angelegt (paper_id={anchor['paper_id']}). "
            f"{len(hits)} verwandte Arbeit(en) gefunden -- {method_note}{reason_note}."
        )
    elif failed:
        message = (
            f"Anker-Paper '{anchor['title']}' angelegt (paper_id={anchor['paper_id']}), "
            f"aber die Folge-Suche schlug teilweise fehl ({', '.join(failed)}) -- "
            f"keine verlaessliche Aussage ueber verwandte Arbeiten moeglich.{reason_note}"
        )
    else:
        message = (
            f"Anker-Paper '{anchor['title']}' angelegt (paper_id={anchor['paper_id']}), "
            f"aber die Folge-Suche lieferte keine Treffer -- {method_note}{reason_note}."
        )

    result = {
        "status": "ok",
        "paper_id": anchor["paper_id"],
        "source": anchor["source"],
        "title": anchor["title"],
        "search": {"hits": hits, "count": len(hits), "failed_modules": failed, "method": method},
        "message": message,
    }
    if anchor.get("doi"):
        result["doi"] = anchor["doi"]
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Anchor-Paper-Survey: arXiv-URL/PDF-Pfad -> Vault + Folge-Suche"
    )
    parser.add_argument("--input", required=True, help="arXiv-URL/-ID oder lokaler PDF-Pfad")
    parser.add_argument("--db", default="vault.db", help="Vault-DB-Pfad (default: vault.db)")
    parser.add_argument(
        "--search-modules",
        default=",".join(DEFAULT_SEARCH_MODULES),
        help="Comma-getrennte Suchmodule fuer die Folge-Suche",
    )
    parser.add_argument("--search-limit", type=int, default=DEFAULT_SEARCH_LIMIT)
    args = parser.parse_args()

    try:
        result = anchor_paper_survey(
            args.input,
            db_path=args.db,
            search_modules=[m.strip() for m in args.search_modules.split(",") if m.strip()],
            search_limit=args.search_limit,
        )
    except ValueError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        sys.exit(1)

    if result["status"] == "error":
        print(f"Fehler: {result['message']}", file=sys.stderr)
        sys.exit(2)

    print(result["message"])
    for hit in result["search"]["hits"]:
        print(f"  - {hit.get('title', '(ohne Titel)')}")
    if result["search"]["failed_modules"]:
        for m in result["search"]["failed_modules"]:
            print(f"  ! Suchmodul fehlgeschlagen: {m}", file=sys.stderr)


if __name__ == "__main__":
    _cli()
