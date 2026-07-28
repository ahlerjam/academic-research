"""anchor_paper.py -- Anchor-Paper-Survey Skill (Issue #394).

Alternativer Recherche-Einstieg: statt eines Themas gibt der User ein
Ausgangspaper an (arXiv-URL/-ID oder lokaler PDF-Pfad). Der Skill loest daraus
Titel/Autoren auf, legt GENAU EIN Anker-Paper im Vault an
(``provenance="anchor-paper"``) und stoesst darauf eine Folge-Suche an, um
verwandte Arbeiten zu finden. Die Folge-Suche liefert nur Kandidaten zur
Anzeige -- Treffer werden NICHT automatisch in den Vault geschrieben (keine
neue Zitations-Graph-Datenbank, siehe Issue-Scope "Out").

Folge-Suche, zweigleisig (PR #440 Review, P1):
  - **arXiv-Anker**: echte Zitations-/Referenz-Traversierung ueber die
    Semantic-Scholar-Graph-API (``/paper/{id}/citations`` +
    ``/paper/{id}/references``, ``run_citation_search()``) -- der arXiv-Anker
    liefert mit seiner ID einen stabilen, direkt referenzierbaren
    Semantic-Scholar-Identifier (``ARXIV:<id>``). Das erfuellt Issue-Scope
    "In" woertlich ("referenzierte/zitierende Arbeiten ... nachlädt"; kein
    neuer externer Dienst, da Semantic Scholar bereits Teil des
    ``network_allowlist`` ist).
  - **PDF-Anker**: mangels stabiler externer Paper-ID faellt die Folge-Suche
    auf eine Titel-Stichwortsuche ueber die bestehenden Fetcher
    (``scripts/search.py::run_search``) zurueck -- dokumentierte
    Einschraenkung, siehe SKILL.md "Bekannte Einschraenkungen".
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
import re
import sys
import time
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
    from academic_vault.server import add_paper as _vault_add_paper_native

    _VAULT_NATIVE = True
except ImportError:
    _VAULT_NATIVE = False


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


def _fetch_s2_relation(paper_ref: str, relation: str, limit: int) -> dict | None:
    """Einzelner GET gegen /paper/{paper_ref}/{relation}, mit einmaligem
    Retry bei HTTP 429 (Semantic Scholar rate-limitet ohne API-Key
    aggressiv -- real beobachtet waehrend der Implementierung).

    Gibt das geparste JSON zurueck, oder None bei Netzwerkfehler/HTTP!=200
    nach dem Retry -- niemals eine Exception (Evidence before assertions).
    """
    url = f"{_S2_PAPER_API}/{paper_ref}/{relation}"
    params = {"fields": _S2_RELATION_FIELDS, "limit": limit}
    headers = {"User-Agent": _USER_AGENT}
    for attempt in range(2):
        try:
            resp = requests.get(url, params=params, timeout=_TIMEOUT, headers=headers)
        except Exception:
            return None
        if resp.status_code == 429 and attempt == 0:
            time.sleep(2.0)
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
    doi: str | None = None,
    pdf_path: str | None = None,
) -> None:
    """Wrapper um academic_vault.server.add_paper mit provenance='anchor-paper'.

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

    csl = {"type": "article-journal", "title": title, "author": authors}
    csl_json = json.dumps(csl, ensure_ascii=False)
    # Deterministisch aus dem absoluten PDF-Pfad ableiten (nicht uuid4()),
    # damit vault_add_paper() ein Upsert ist: ein zweiter Lauf auf demselben
    # PDF aktualisiert denselben Eintrag statt ein Duplikat anzulegen --
    # analog zum arXiv-Pfad (paper_id=arxiv-<id>). P2 aus PR #440 Review.
    abs_path = str(Path(pdf_path).expanduser().resolve())
    path_hash = hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:12]
    paper_id = f"anchor-{path_hash}"
    vault_add_paper(db_path=db_path, paper_id=paper_id, csl_json=csl_json, pdf_path=pdf_path)
    return {"status": "ok", "paper_id": paper_id, "source": "pdf", "title": title}


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

    Folge-Suche, zweigleisig (PR #440 Review, P1 -- siehe Modul-Docstring):
    arXiv-Anker nutzen ``run_citation_search()`` (echte Zitations-/Referenz-
    Traversierung ueber Semantic Scholar), PDF-Anker fallen mangels stabiler
    externer Paper-ID auf ``run_search()`` (Titel-Stichwortsuche) zurueck.
    In beiden Faellen entfernt ``_filter_and_dedupe()`` das Anker-Paper aus
    der Rohtrefferliste und dedupliziert den Rest ueber die kanonische
    Repo-Pipeline (``scripts/dedup.py``), bevor gezaehlt/gemeldet wird.

    Returns:
        {"status": "ok"|"error", "paper_id"?, "source"?, "title"?,
         "search"?: {"hits", "count", "failed_modules"}, "message"}
    """
    kind, normalized = detect_input(input_value)

    anchor = (
        _handle_arxiv(normalized, db_path) if kind == "arxiv" else _handle_pdf(normalized, db_path)
    )
    if anchor["status"] == "error":
        return anchor

    s2_ref = anchor.get("s2_ref")
    if s2_ref:
        raw_hits, failed = run_citation_search(s2_ref, limit=search_limit)
    else:
        modules = list(search_modules) if search_modules else list(DEFAULT_SEARCH_MODULES)
        raw_hits, failed = run_search(anchor["title"], modules, limit=search_limit)

    hits = _filter_and_dedupe(raw_hits, anchor["title"], anchor.get("doi"))

    if hits:
        message = (
            f"Anker-Paper '{anchor['title']}' angelegt (paper_id={anchor['paper_id']}). "
            f"{len(hits)} verwandte Arbeit(en) gefunden."
        )
    elif failed:
        message = (
            f"Anker-Paper '{anchor['title']}' angelegt (paper_id={anchor['paper_id']}), "
            f"aber die Folge-Suche schlug teilweise fehl ({', '.join(failed)}) -- "
            f"keine verlaessliche Aussage ueber verwandte Arbeiten moeglich."
        )
    else:
        message = (
            f"Anker-Paper '{anchor['title']}' angelegt (paper_id={anchor['paper_id']}), "
            f"aber die Folge-Suche lieferte keine Treffer."
        )

    return {
        "status": "ok",
        "paper_id": anchor["paper_id"],
        "source": anchor["source"],
        "title": anchor["title"],
        "search": {"hits": hits, "count": len(hits), "failed_modules": failed},
        "message": message,
    }


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
