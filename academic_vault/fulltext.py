"""PDF-Volltext-Extraktion fuer den Vault-Index (Issue #373).

Zwei Backends hinter einer Funktion:

  * **pypdf** — Default, keine Zusatzinfrastruktur, laeuft offline. Liefert bei
    reinen Scan-PDFs (kein Text-Layer) einen leeren String.
  * **GROBID** — Opt-in ueber die Umgebungsvariable ``GROBID_URL``. Der Server
    (Apache-2.0, lokal per Docker betreibbar) liefert strukturiertes TEI-XML;
    daraus wird der ``<text>``-Baum als Fliesstext gezogen. Jeder Fehler —
    kein Server erreichbar, Timeout, kaputtes XML — faellt still auf pypdf
    zurueck, damit die Extraktion nie an der optionalen Infrastruktur haengt.

Der Rueckgabewert ist immer ``(text, extractor)``. Konnte kein Text gewonnen
werden, ist beides leer: ein leerer Volltext darf nicht als "extrahiert"
persistiert werden (sonst gilt ein Scan-PDF als erledigt und wird nach einem
spaeteren OCR-Lauf nie nachgeholt).
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

# Umgebungsvariable, die den GROBID-Pfad aktiviert (z. B. http://localhost:8070).
ENV_GROBID_URL = "GROBID_URL"
ENV_GROBID_TIMEOUT = "GROBID_TIMEOUT"

GROBID_ENDPOINT = "/api/processFulltextDocument"
DEFAULT_GROBID_TIMEOUT = 60.0

# Obergrenze pro Paper. Ein 600-Seiten-Buch erzeugt sonst mehrere MB, die in
# FTS5, in jedem Snapshot-Export und in jedem Ingest-Lauf mitgeschleppt werden.
MAX_FULLTEXT_CHARS = 2_000_000

TEI_NS = "{http://www.tei-c.org/ns/1.0}"

BACKENDS = ("auto", "grobid", "pypdf")


def normalize_whitespace(text: str) -> str:
    """Kollabiert jede Whitespace-Folge zu einem einzelnen Leerzeichen.

    PDF-Extraktion erzeugt reihenweise Zeilenumbrueche mitten im Satz und
    Spaltenfuellzeichen. Fuer einen FTS5-Index ist das irrelevantes Rauschen,
    das den Index nur aufblaeht.
    """
    return " ".join(text.split())


def _truncate(text: str) -> str:
    if len(text) <= MAX_FULLTEXT_CHARS:
        return text
    logger.info("Volltext auf %d Zeichen gekuerzt", MAX_FULLTEXT_CHARS)
    return text[:MAX_FULLTEXT_CHARS]


def extract_pypdf(pdf_path: str) -> str:
    """Extrahiert den Text-Layer eines PDFs via pypdf. Nie None."""
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    parts: list[str] = []
    for page in reader.pages:
        try:
            page_text = page.extract_text()
        except Exception:  # pragma: no cover - defekte Einzelseite
            logger.warning("Seite in %s nicht extrahierbar", pdf_path, exc_info=True)
            continue
        if page_text:
            parts.append(page_text)
    return normalize_whitespace("\n".join(parts))


def parse_tei_fulltext(tei_xml: str | bytes) -> str:
    """Zieht den Fliesstext aus einer GROBID-TEI-Antwort.

    Genommen wird der ``<text>``-Baum (Body + Back), nicht der ``teiHeader``:
    Titel und Abstract stehen bereits ueber ``csl_json`` im FTS-Index, hier
    geht es um den PDF-Inhalt.
    """
    from lxml import etree

    if isinstance(tei_xml, str):
        payload = tei_xml.encode("utf-8")
    else:
        payload = tei_xml

    # resolve_entities/no_network: TEI kommt von einem externen Dienst und ist
    # damit untrusted Input (XXE/Billion-Laughs).
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    root = etree.fromstring(payload, parser=parser)

    body = root.find(f".//{TEI_NS}text")
    if body is None:
        return ""
    return normalize_whitespace("".join(body.itertext()))


def _grobid_timeout() -> float:
    raw = os.environ.get(ENV_GROBID_TIMEOUT, "").strip()
    if not raw:
        return DEFAULT_GROBID_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_GROBID_TIMEOUT
    return value if value > 0 else DEFAULT_GROBID_TIMEOUT


def extract_grobid(pdf_path: str, base_url: str, timeout: float | None = None) -> str:
    """Schickt das PDF an einen GROBID-Server und gibt den TEI-Fliesstext zurueck.

    Wirft die httpx-/lxml-Fehler durch; die Fallback-Entscheidung trifft
    :func:`extract_fulltext`.
    """
    url = base_url.rstrip("/") + GROBID_ENDPOINT
    with open(pdf_path, "rb") as handle:
        response = httpx.post(
            url,
            files={"input": (os.path.basename(pdf_path), handle, "application/pdf")},
            # consolidate*=0: sonst fragt GROBID per Default CrossRef an — das
            # macht aus einem lokalen Lauf einen Netzwerk-Roundtrip pro Paper.
            data={
                "consolidateHeader": "0",
                "consolidateCitations": "0",
            },
            timeout=timeout if timeout is not None else _grobid_timeout(),
        )
    response.raise_for_status()
    return _truncate(parse_tei_fulltext(response.text))


def extract_fulltext(pdf_path: str, backend: str = "auto") -> tuple[str, str]:
    """Extrahiert den Volltext eines PDFs.

    Args:
        pdf_path: Pfad zur PDF-Datei.
        backend: ``"auto"`` (GROBID falls ``GROBID_URL`` gesetzt, sonst pypdf),
            ``"grobid"`` (nur GROBID) oder ``"pypdf"`` (nur pypdf).

    Returns:
        ``(text, extractor)``. ``extractor`` ist ``"grobid"`` bzw. ``"pypdf"``;
        bei leerem Ergebnis (z. B. Scan-PDF ohne Text-Layer) sind beide Werte
        leere Strings.

    Raises:
        FileNotFoundError: Die PDF-Datei existiert nicht.
        ValueError: Unbekanntes ``backend``.
    """
    if backend not in BACKENDS:
        raise ValueError(f"Unbekanntes Backend '{backend}' -- erlaubt: {list(BACKENDS)}")
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"PDF nicht gefunden: {pdf_path}")

    grobid_url = os.environ.get(ENV_GROBID_URL, "").strip()

    if backend == "grobid" and not grobid_url:
        raise ValueError(f"backend='grobid' erfordert die Umgebungsvariable {ENV_GROBID_URL}")

    if grobid_url and backend in ("auto", "grobid"):
        try:
            text = extract_grobid(pdf_path, grobid_url)
        except Exception:
            if backend == "grobid":
                raise
            logger.warning(
                "GROBID-Extraktion fehlgeschlagen (%s) -- Fallback auf pypdf",
                grobid_url,
                exc_info=True,
            )
        else:
            if text:
                return text, "grobid"
            if backend == "grobid":
                return "", ""

    text = _truncate(extract_pypdf(pdf_path))
    if not text:
        return "", ""
    return text, "pypdf"
