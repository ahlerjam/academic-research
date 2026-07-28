"""analyze_repo.py -- GitHub-Repo-Research Skill (Issue #401).

Liest README und CITATION.cff eines GitHub-Repos AUSSCHLIESSLICH ueber die
oeffentliche GitHub-REST-API (Metadaten-/Text-Lektuere). Keine Klon-Operation,
kein Checkout, keine Ausfuehrung von Inhalten des Zielrepos. Extrahiert
arXiv-IDs und DOIs per Regex aus dem README-Freitext bzw. strukturiert aus
CITATION.cff (YAML), loest sie ueber die arXiv-API bzw. Crossref zu CSL-JSON
auf und schreibt Treffer mit provenance="github-repo" in den Vault. Ohne
jeden Treffer: strukturiertes Leer-Ergebnis statt Exception oder Fabrikation.

Epistemische Grundregel dieses Moduls (Review-Fund PR #433): "nicht gelesen"
ist NICHT "nicht vorhanden". Ein fehlgeschlagener Fetch (403/429/5xx, Timeout,
fehlendes `requests`) liefert kein Wissen ueber den Repo-Inhalt und darf
niemals als belegte Aussage "das Repo enthaelt keine Referenz" ausgegeben
werden. Nur ein sauberes HTTP 404 belegt echte Abwesenheit einer Datei.

CLI:
    python skills/github-repo-research/scripts/analyze_repo.py \
        --url https://github.com/<owner>/<repo> --db vault.db

Verwendbar auch als Modul (fuer Tests und den Skill selbst).
"""

from __future__ import annotations

import base64
import json
import re
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Optional-Dependencies (graceful fallback, analog zu reading-list-import)
# ---------------------------------------------------------------------------

try:
    import requests

    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

try:
    import yaml

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

# academic_vault fuer Vault-Zugriff (optionale Laufzeit-Abhaengigkeit)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from academic_vault.server import add_paper as _vault_add_paper_native

    _VAULT_NATIVE = True
except ImportError:
    _VAULT_NATIVE = False


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

GITHUB_API = "https://api.github.com"
ARXIV_API = "https://export.arxiv.org/api/query"
CROSSREF_API = "https://api.crossref.org/works/{doi}"
_TIMEOUT = 10
_USER_AGENT = "academic-research-github-repo-research/1.0"
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

_GITHUB_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)
_ARXIV_LINK_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_ARXIV_PREFIX_RE = re.compile(r"arxiv:\s*(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\]\)\"'<>]+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# URL-Parsing
# ---------------------------------------------------------------------------


def parse_github_url(url: str) -> tuple[str, str]:
    """Parst eine GitHub-Repo-URL zu (owner, repo). Wirft ValueError bei Fehlformat."""
    m = _GITHUB_URL_RE.match(url.strip())
    if not m:
        raise ValueError(f"Keine gueltige GitHub-Repo-URL: {url!r}")
    return m.group(1), m.group(2)


# ---------------------------------------------------------------------------
# GitHub-REST-API-Zugriff (nur lesend, keine Klon-/Ausfuehr-Operation)
# ---------------------------------------------------------------------------


class FetchResult(NamedTuple):
    """Ergebnis eines GitHub-Fetches mit EXPLIZITER Fehler-Unterscheidung.

    Vor dem Fix (Review-Fund PR #433) gaben die Fetch-Funktionen fuer drei
    voellig verschiedene Ausgaenge dasselbe `None` zurueck:

    1. HTTP 200, Datei gelesen, aber ohne Inhalt
    2. HTTP 404 -- Datei existiert nachweislich nicht (Beleg fuer Abwesenheit)
    3. HTTP 403/429/5xx, Timeout, DNS-Fehler, fehlendes `requests`
       (Fetch fehlgeschlagen -- KEINE Information ueber den Repo-Inhalt)

    analyze_repo() konnte Fall 3 dadurch nicht von Fall 2 unterscheiden und
    meldete einen Rate-Limit-Treffer als belegte Aussage "Repo enthaelt keine
    Referenz". Deshalb trennt dieser Typ beides sauber:

    - `text`  : gelesener Inhalt, oder None (nicht vorhanden bzw. nicht lesbar)
    - `error` : None = Fetch war erfolgreich; sonst Klartext-Grund des Fehlers
    """

    text: str | None
    error: str | None = None

    @property
    def failed(self) -> bool:
        """True, wenn der Fetch fehlschlug -- dann sagt `text is None` NICHTS
        ueber die Existenz der Datei aus."""
        return self.error is not None


_NO_REQUESTS_ERROR = "Python-Paket 'requests' nicht installiert -- kein GitHub-Zugriff moeglich"


def _describe_http_status(status_code: int) -> str:
    """Klartext-Grund fuer einen nicht verwertbaren HTTP-Status."""
    if status_code in (403, 429):
        return f"HTTP {status_code} (GitHub-Rate-Limit; ohne Token 60 Requests/Stunde)"
    if status_code >= 500:
        return f"HTTP {status_code} (GitHub-Serverfehler)"
    return f"HTTP {status_code}"


def _decode_github_content(payload: dict) -> str | None:
    """Dekodiert den 'content'-Wert einer GitHub-Contents-API-Antwort."""
    content = payload.get("content")
    if content is None:
        return None
    if payload.get("encoding") == "base64":
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:
            return None
    return content


def _fetch_github_text(url: str) -> FetchResult:
    """Liest eine GitHub-API-Ressource als Text -- wirft nie eine Exception.

    Unterscheidet strikt zwischen "nachweislich nicht vorhanden" (HTTP 404 ->
    FetchResult(None) ohne Fehler) und "konnte nicht gelesen werden" (alles
    andere -> FetchResult(None, <Grund>)).
    """
    if not _REQUESTS_AVAILABLE:
        return FetchResult(None, _NO_REQUESTS_ERROR)
    try:
        resp = requests.get(
            url,
            timeout=_TIMEOUT,
            headers={"Accept": "application/vnd.github+json", "User-Agent": _USER_AGENT},
        )
    except Exception as exc:  # Timeout, DNS, Connection-Reset, ...
        return FetchResult(None, f"Netzwerkfehler: {exc}")

    # 404 ist die EINZIGE belastbare Negativ-Auskunft: die Datei (bzw. das
    # oeffentliche Repo) existiert nicht. Alles andere ist ein Fehlschlag.
    if resp.status_code == 404:
        return FetchResult(None)
    if resp.status_code != 200:
        return FetchResult(None, _describe_http_status(resp.status_code))

    try:
        payload = resp.json()
    except Exception as exc:
        return FetchResult(None, f"Antwort nicht als JSON lesbar: {exc}")
    if not isinstance(payload, dict):
        return FetchResult(None, "Unerwartetes Antwortformat der GitHub-API")

    text = _decode_github_content(payload)
    if text is None:
        return FetchResult(None, "Inhalt der GitHub-Antwort nicht dekodierbar")
    return FetchResult(text)


def fetch_readme(owner: str, repo: str) -> FetchResult:
    """Holt den README-Text eines Repos ueber die GitHub-REST-API.

    Liefert FetchResult(text) bei Erfolg, FetchResult(None) wenn das Repo
    nachweislich kein README hat (404) und FetchResult(None, <Grund>) wenn der
    Abruf fehlschlug -- niemals eine Exception (AC2: kein Crash).
    """
    return _fetch_github_text(f"{GITHUB_API}/repos/{owner}/{repo}/readme")


def fetch_citation_cff(owner: str, repo: str) -> FetchResult:
    """Holt CITATION.cff eines Repos ueber die GitHub-Contents-API.

    Gleiche Semantik wie fetch_readme(): 404 = Datei nachweislich nicht
    vorhanden (der Normalfall), alles andere = Fehlschlag mit Grund.
    """
    return _fetch_github_text(f"{GITHUB_API}/repos/{owner}/{repo}/contents/CITATION.cff")


# ---------------------------------------------------------------------------
# Extraktion aus README-Freitext
# ---------------------------------------------------------------------------


def extract_arxiv_ids(text: str | None) -> list[str]:
    """Extrahiert arXiv-IDs aus Freitext (abs/pdf-Links + 'arXiv:'-Praefix).

    Dedupliziert unter Beibehaltung der Fundreihenfolge.
    """
    if not text:
        return []
    ids: list[str] = []
    for pattern in (_ARXIV_LINK_RE, _ARXIV_PREFIX_RE):
        for m in pattern.finditer(text):
            arxiv_id = m.group(1)
            if arxiv_id not in ids:
                ids.append(arxiv_id)
    return ids


def extract_dois(text: str | None) -> list[str]:
    """Extrahiert DOIs aus Freitext (doi.org-Links + nackte DOI-Strings).

    Dedupliziert case-insensitiv unter Beibehaltung der Fundreihenfolge.
    """
    if not text:
        return []
    dois: list[str] = []
    lowered_seen: list[str] = []
    for m in _DOI_RE.finditer(text):
        doi = m.group(1).rstrip(").,;”’")
        if doi.lower() not in lowered_seen:
            lowered_seen.append(doi.lower())
            dois.append(doi)
    return dois


# ---------------------------------------------------------------------------
# CITATION.cff-Parsing (robust gegen variierendes Schema)
# ---------------------------------------------------------------------------


def parse_citation_cff(text: str | None) -> dict | None:
    """Parst CITATION.cff (YAML) zu {'doi', 'title', 'authors'} oder None.

    Bevorzugt 'preferred-citation', faellt auf Top-Level-Felder zurueck.
    Rein .get()-basiert -- kein KeyError bei fehlenden/abweichenden Keys.
    Gibt None zurueck bei kaputtem YAML oder ganz ohne DOI/Titel.
    """
    if not text or not _YAML_AVAILABLE:
        return None
    try:
        data = yaml.safe_load(text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    preferred = data.get("preferred-citation")
    source = preferred if isinstance(preferred, dict) else {}

    doi = source.get("doi") or data.get("doi")
    title = source.get("title") or data.get("title")
    if not doi and not title:
        return None

    authors_raw = source.get("authors") or data.get("authors") or []
    authors: list[dict] = []
    if isinstance(authors_raw, list):
        for a in authors_raw:
            if not isinstance(a, dict):
                continue
            given = a.get("given-names", "")
            family = a.get("family-names", "")
            if family or given:
                authors.append({"family": family, "given": given})
            elif a.get("name"):
                authors.append({"literal": a["name"]})

    return {"doi": doi, "title": title, "authors": authors}


# ---------------------------------------------------------------------------
# Resolution: arXiv-API + Crossref (eigenstaendig implementiert, kein
# Cross-Skill-Import aus reading-list-import -- analoges, aber getrenntes
# Muster, siehe Plan-Kommentar zu Issue #401)
# ---------------------------------------------------------------------------


def resolve_arxiv_id(arxiv_id: str) -> str | None:
    """Holt CSL-JSON fuer eine arXiv-ID via arXiv-API (id_list=).

    Gibt None zurueck bei Netzwerkfehler, HTTP != 200 oder keinem Treffer.
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

    title = (entry.findtext("atom:title", namespaces=_ATOM_NS) or "").strip()
    title = re.sub(r"\s+", " ", title)
    if not title:
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


_DOI_URL_RE = re.compile(r"(?:https?://)?(?:dx\.)?doi\.org/(.+)", re.IGNORECASE)


def _normalize_doi(doi: str) -> str:
    """Normalisiert einen DOI: entfernt doi.org-Praefix."""
    doi = doi.strip()
    m = _DOI_URL_RE.match(doi)
    return m.group(1) if m else doi


# Der Vault akzeptiert ausschliesslich {"article-journal", "book", "chapter"}
# als csl_json-'type' (VALID_PAPER_TYPES, academic_vault/db.py -- strikt
# durchgesetzt von validate_csl_json, academic_vault/server.py, Issue #213).
# Crossref benutzt dagegen seine eigene, deutlich feinere Typ-Taxonomie
# (https://api.crossref.org/types, z.B. "journal-article",
# "proceedings-article", "posted-content", ...). Eine 1:1-Uebernahme des
# Crossref-'type'-Feldes crashte vault_add_paper() mit ValueError fuer
# praktisch jeden echten Treffer (Review-Fund PR #433: analyze_repo.py
# vor diesem Fix). Bekannte Crossref-Typen werden daher explizit auf den
# passenden CSL-Typ gemappt; alles Unbekannte/Fehlende faellt sicher auf
# "article-journal" zurueck (haeufigster Fall, entspricht dem bisherigen
# Default) statt eine Exception zu werfen.
_CROSSREF_TYPE_TO_CSL: dict[str, str] = {
    "book": "book",
    "monograph": "book",
    "edited-book": "book",
    "reference-book": "book",
    "book-series": "book",
    "book-set": "book",
    "book-chapter": "chapter",
    "book-part": "chapter",
    "book-section": "chapter",
    "book-track": "chapter",
    "reference-entry": "chapter",
    "journal-article": "article-journal",
}


def _map_crossref_type_to_csl(crossref_type: str | None) -> str:
    """Mappt einen Crossref-'type'-Wert auf einen vault-validen CSL-Typ.

    Siehe Kommentar zu _CROSSREF_TYPE_TO_CSL. Unbekannte oder fehlende Typen
    (z.B. "proceedings-article", "posted-content", "report", "dataset", ...)
    fallen auf "article-journal" zurueck statt vault_add_paper() crashen zu
    lassen -- kein stiller Datenverlust, da 'type' ohnehin kein AC-relevantes
    Feld dieses Skills ist (Kandidat landet trotzdem korrekt im Vault).
    """
    if not crossref_type:
        return "article-journal"
    return _CROSSREF_TYPE_TO_CSL.get(crossref_type, "article-journal")


def resolve_doi(doi: str) -> str | None:
    """Holt CSL-JSON fuer einen DOI via Crossref.

    Gibt None zurueck bei Netzwerkfehler, HTTP != 200 oder keinem Treffer.
    Eigenstaendige Implementierung (kein Import aus reading-list-import).
    """
    if not doi or not _REQUESTS_AVAILABLE:
        return None
    doi_clean = _normalize_doi(doi)
    url = CROSSREF_API.format(doi=doi_clean)
    try:
        resp = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT})
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        msg = resp.json().get("message", {})
    except Exception:
        return None
    if not msg:
        return None

    authors = []
    for a in msg.get("author", []):
        entry: dict = {}
        if "family" in a:
            entry["family"] = a["family"]
        if "given" in a:
            entry["given"] = a["given"]
        if not entry:
            entry = {"literal": a.get("name", "")}
        authors.append(entry)

    issued = msg.get("published") or msg.get("issued") or {}
    date_parts = issued.get("date-parts", [[]])
    year = date_parts[0][0] if date_parts and date_parts[0] else None

    titles = msg.get("title", [])
    title = titles[0] if titles else ""

    csl: dict = {
        "type": _map_crossref_type_to_csl(msg.get("type")),
        "title": title,
        "author": authors,
        "DOI": msg.get("DOI", doi_clean),
    }
    if year:
        csl["issued"] = {"date-parts": [[year]]}

    container = msg.get("container-title", [])
    if container:
        csl["container-title"] = container[0]

    return json.dumps(csl, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Vault-Integration
# ---------------------------------------------------------------------------


def vault_add_paper(
    db_path: str,
    paper_id: str,
    csl_json: str,
    doi: str | None = None,
) -> None:
    """Wrapper um academic_vault.server.add_paper mit provenance='github-repo'.

    Wird in Tests via patch() ersetzt.
    """
    if _VAULT_NATIVE:
        _vault_add_paper_native(
            db_path=db_path,
            paper_id=paper_id,
            csl_json=csl_json,
            doi=doi,
            provenance="github-repo",
        )
    else:
        raise RuntimeError(
            "vault_add_paper: academic_vault.server nicht verfuegbar. "
            "Stelle sicher dass der MCP-Server im PYTHONPATH ist."
        )


def _generate_paper_id(doi: str | None, arxiv_id: str | None) -> str:
    """Generiert eine stabile paper_id aus arXiv-ID/DOI oder UUID-Fallback."""
    if arxiv_id:
        return f"arxiv-{arxiv_id.replace('.', '-')}"
    if doi:
        clean = re.sub(r"[^a-z0-9]", "-", _normalize_doi(doi).lower())
        return f"doi-{clean}"
    return f"ghr-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Haupt-Pipeline
# ---------------------------------------------------------------------------

_ARXIV_DOI_PREFIX_RE = re.compile(r"^10\.48550/arxiv\.", re.IGNORECASE)


def analyze_repo(url: str, db_path: str = "vault.db") -> dict:
    """Analysiert ein GitHub-Repo (README + CITATION.cff) und fuellt den Vault.

    Liest AUSSCHLIESSLICH ueber die oeffentliche GitHub-REST-API -- kein
    Klonen, kein Checkout, keine Ausfuehrung von Inhalten des Zielrepos.
    Ohne erkennbare Referenz: strukturiertes Leer-Ergebnis statt Exception
    oder Fabrikation (AC2).

    Konnte eine Quelle nicht gelesen werden (Rate-Limit, Timeout, fehlendes
    `requests`), ist das Ergebnis `status="incomplete"`: die Analyse sagt dann
    NICHTS darueber aus, ob das Repo eine Referenz enthaelt (Review-Fund
    PR #433). Nur ein sauberes 404 belegt echte Abwesenheit.

    Args:
        url: GitHub-Repo-URL
        db_path: Pfad zur Vault-SQLite-Datenbank

    Returns:
        {"candidates": [{"paper_id", "doi"?, "arxiv_id"?, "source"}, ...],
         "status": "ok" | "incomplete",
         "errors": [str, ...],
         "message": str}
    """
    owner, repo = parse_github_url(url)

    readme = fetch_readme(owner, repo)
    cff = fetch_citation_cff(owner, repo)

    # Fehlgeschlagene Fetches sammeln: sie begrenzen, was ueberhaupt
    # behauptet werden darf.
    errors: list[str] = []
    if readme.failed:
        errors.append(f"README: {readme.error}")
    if cff.failed:
        errors.append(f"CITATION.cff: {cff.error}")
    status = "incomplete" if errors else "ok"

    arxiv_ids = extract_arxiv_ids(readme.text)
    dois = extract_dois(readme.text)

    cff_data = parse_citation_cff(cff.text)
    if cff_data and cff_data.get("doi"):
        cff_doi = cff_data["doi"]
        if cff_doi.lower() not in [d.lower() for d in dois]:
            dois.append(cff_doi)

    if not arxiv_ids and not dois:
        if errors:
            # KEINE Absenz-Aussage: die betroffene Quelle wurde nie gesehen.
            message = (
                f"Unbestaetigt: {owner}/{repo} konnte nicht vollstaendig gelesen werden "
                f"({'; '.join(errors)}). Daraus folgt NICHT, dass das Repo keine "
                f"arXiv-ID oder DOI enthaelt -- bitte spaeter erneut versuchen "
                f"(GitHub-Rate-Limit: mit Token deutlich hoeher)."
            )
        elif readme.text is None and cff.text is None:
            message = (
                f"Kein Kandidaten-Paper gefunden: {owner}/{repo} hat weder ein README "
                f"noch eine CITATION.cff (beide von der GitHub-API als nicht vorhanden "
                f"gemeldet)."
            )
        else:
            message = (
                f"Kein Kandidaten-Paper gefunden: weder README noch CITATION.cff von "
                f"{owner}/{repo} enthalten eine erkennbare arXiv-ID oder DOI."
            )
        return {"candidates": [], "status": status, "errors": errors, "message": message}

    candidates: list[dict] = []

    for arxiv_id in arxiv_ids:
        csl_json = resolve_arxiv_id(arxiv_id)
        if not csl_json:
            continue
        paper_id = _generate_paper_id(doi=None, arxiv_id=arxiv_id)
        doi = f"10.48550/arXiv.{arxiv_id}"
        vault_add_paper(db_path=db_path, paper_id=paper_id, csl_json=csl_json, doi=doi)
        candidates.append({"paper_id": paper_id, "arxiv_id": arxiv_id, "source": "arxiv"})

    for doi in dois:
        if _ARXIV_DOI_PREFIX_RE.match(doi):
            continue  # bereits ueber arxiv_ids abgedeckt
        csl_json = resolve_doi(doi)
        if not csl_json:
            continue
        paper_id = _generate_paper_id(doi=doi, arxiv_id=None)
        vault_add_paper(db_path=db_path, paper_id=paper_id, csl_json=csl_json, doi=doi)
        candidates.append({"paper_id": paper_id, "doi": doi, "source": "crossref"})

    if not candidates:
        return {
            "candidates": [],
            "status": status,
            "errors": errors,
            "message": (
                f"Referenz(en) in {owner}/{repo} erkannt ({len(arxiv_ids)} arXiv-ID(s), "
                f"{len(dois)} DOI(s)), aber keine liess sich aufloesen "
                f"(Netzwerk/Rate-Limit/kein Treffer)."
            ),
        }

    message = f"{len(candidates)} Kandidat(en) aus {owner}/{repo} in den Vault geschrieben."
    if errors:
        # Treffer gefunden, aber nicht alle Quellen gelesen -> die Liste kann
        # unvollstaendig sein; das gehoert offen in die Meldung.
        message += (
            f" Achtung, Ergebnis unvollstaendig: {'; '.join(errors)} -- "
            f"es koennen weitere Referenzen uebersehen worden sein."
        )
    return {
        "candidates": candidates,
        "status": status,
        "errors": errors,
        "message": message,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="GitHub-Repo-Research: README/CITATION.cff -> Vault"
    )
    parser.add_argument("--url", required=True, help="GitHub-Repo-URL")
    parser.add_argument("--db", default="vault.db", help="Vault-DB-Pfad (default: vault.db)")
    args = parser.parse_args()

    result = analyze_repo(args.url, db_path=args.db)
    print(result["message"])
    for c in result["candidates"]:
        print(f"  - {c}")

    # Exit-Code 2 bei unvollstaendigem Ergebnis: ein aufrufendes Skript darf
    # "keine Kandidaten wegen Rate-Limit" nicht als sauberen Negativ-Befund
    # (Exit 0) verbuchen.
    if result.get("status") == "incomplete":
        for err in result.get("errors", []):
            print(f"  ! {err}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    _cli()
