"""PDF-Volltext-Extraktion fuer den Vault-Index (Issues #373, #709).

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

**Zwei TEI-Parser, ein Request-Bauplan (#709).** Neben dem Fliesstext-Pfad
(:func:`parse_tei_fulltext`, unveraendert — er speist den FTS5-Index) gibt es
einen strukturerhaltenden Pfad: :func:`parse_tei_sections` liefert die
``<div>``/``<head>``/``<p>``-Struktur des ``<body>`` als :class:`TeiSection`.
``academic_vault.chunking`` schneidet damit an echten Sektions- und
Absatzgrenzen statt an einer Title-Case-Regex. Der Fliesstext wird bewusst
NICHT aus den Sektionen neu abgeleitet: er zieht auch ``<back>`` mit, eine
Neuableitung wuerde den indizierten Volltext still veraendern.
"""

import logging
import os
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# Umgebungsvariable, die den GROBID-Pfad aktiviert (z. B. http://localhost:8070).
ENV_GROBID_URL = "GROBID_URL"
ENV_GROBID_TIMEOUT = "GROBID_TIMEOUT"

GROBID_ENDPOINT = "/api/processFulltextDocument"
DEFAULT_GROBID_TIMEOUT = 60.0

# Strukturen, fuer die GROBID Koordinaten liefern soll (#709). Ohne diesen
# Parameter traegt das TEI keine Seiteninformation: laut GROBID-Doku
# (doc/Coordinates-in-PDF.md) ist die Seitenzahl ausschliesslich ueber das
# ``@coords``-Attribut zu bekommen, dessen erstes Feld sie enthaelt. Der
# Parameter wird als WIEDERHOLTES Formularfeld gesendet
# (``--form teiCoordinates=head --form teiCoordinates=p``).
GROBID_COORD_ELEMENTS = ("head", "p")

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


@dataclass
class TeiParagraph:
    """Ein ``<p>`` aus dem TEI-``<body>`` samt Seitenzahl (#709)."""

    text: str
    page: int


@dataclass
class TeiSection:
    """Ein ``<div>`` aus dem TEI-``<body>``: Ueberschrift plus seine Absaetze.

    ``title`` ist der Text des ``<head>`` oder ``""``, wenn das ``<div>``
    keinen hat. Das Ersetzen durch einen Platzhalter ist bewusst NICHT Aufgabe
    des Parsers, sondern des Konsumenten (``chunking.DEFAULT_SECTION_TITLE``).
    """

    title: str
    paragraphs: list[TeiParagraph] = field(default_factory=list)


@dataclass
class _TeiParseState:
    """Laufender Zustand beim Sektions-Parsing (Seiten, Zeichen-Deckel, Warnung)."""

    chars: int = 0
    last_page: int = 1
    missing_coords_warned: bool = False
    truncated: bool = False


def _coords_page(element: object) -> int | None:
    """Seitenzahl aus dem ersten ``@coords``-Kasten, oder ``None``.

    Format laut GROBID-Doku: ``page,x,y,w,h``, mehrere Kaesten durch ``;``
    getrennt (ein Element ueber mehrere Zeilen/Seiten). Genommen wird der
    ERSTE Kasten — er markiert den Beginn des Elements.
    """
    raw = element.get("coords")  # type: ignore[attr-defined]
    if not raw:
        return None
    first_field = raw.split(";")[0].split(",")[0].strip()
    try:
        page = int(first_field)
    except ValueError:
        return None
    return page if page >= 1 else None


def _element_page(element: object) -> int | None:
    """Seitenzahl des Elements selbst oder seines ersten Nachfahren mit ``@coords``."""
    for node in element.iter():  # type: ignore[attr-defined]
        if not isinstance(node.tag, str):
            continue
        page = _coords_page(node)
        if page is not None:
            return page
    return None


def _tei_paragraph(element: object, state: _TeiParseState) -> TeiParagraph | None:
    """Baut einen :class:`TeiParagraph`; ``None`` bei leerem Absatz oder Deckel."""
    text = normalize_whitespace("".join(element.itertext()))  # type: ignore[attr-defined]
    if not text:
        return None

    remaining = MAX_FULLTEXT_CHARS - state.chars
    if remaining <= 0:
        state.truncated = True
        return None
    if len(text) > remaining:
        text = text[:remaining]
        state.truncated = True
    state.chars += len(text)

    page = _element_page(element)
    if page is None:
        page = state.last_page
        if not state.missing_coords_warned:
            state.missing_coords_warned = True
            logger.warning(
                "TEI-Absatz ohne @coords — Seitenzahl wird von der zuletzt bekannten "
                "Seite fortgeschrieben (Start: 1). GROBID mit teiCoordinates=%s "
                "aufrufen, sonst sind die Seitenangaben der Chunks geraten.",
                ",".join(GROBID_COORD_ELEMENTS),
            )
    else:
        state.last_page = page

    return TeiParagraph(text=text, page=page)


def _head_title(container: object) -> str:
    head = container.find(f"{TEI_NS}head")  # type: ignore[attr-defined]
    if head is None:
        return ""
    return normalize_whitespace("".join(head.itertext()))


def _collect_sections(
    container: object, title: str, sections: list[TeiSection], state: _TeiParseState
) -> None:
    """Sammelt ``<p>`` je ``<div>`` in Dokumentreihenfolge, rekursiv.

    Ein verschachteltes ``<div>`` beendet die laufende Sektion und oeffnet eine
    eigene — sonst wuerden Unterabschnitte unter dem Titel des Elternteils
    verschwinden.
    """
    paragraphs: list[TeiParagraph] = []
    for child in container:  # type: ignore[attr-defined]
        if not isinstance(child.tag, str):  # Kommentare, Processing Instructions
            continue
        if child.tag == f"{TEI_NS}div":
            if paragraphs:
                sections.append(TeiSection(title=title, paragraphs=paragraphs))
                paragraphs = []
            _collect_sections(child, _head_title(child), sections, state)
        elif child.tag == f"{TEI_NS}p":
            paragraph = _tei_paragraph(child, state)
            if paragraph is not None:
                paragraphs.append(paragraph)
    if paragraphs:
        sections.append(TeiSection(title=title, paragraphs=paragraphs))


def parse_tei_sections(tei_xml: str | bytes) -> list[TeiSection]:
    """Zieht die Sektionsstruktur des ``<body>`` aus einer GROBID-TEI-Antwort.

    Nur der ``<body>`` — ``teiHeader`` und ``<back>`` (Literaturverzeichnis,
    Anhaenge) sind kein Argumentationstext und haben im Chunking nichts zu
    suchen.

    Der Gesamttext ist wie im Fliesstext-Pfad auf :data:`MAX_FULLTEXT_CHARS`
    gedeckelt; sonst haette der Strukturpfad keine Obergrenze.

    Returns:
        Sektionen in Dokumentreihenfolge. Leer, wenn kein ``<body>`` mit
        Absaetzen vorhanden ist.
    """
    from lxml import etree

    payload = tei_xml.encode("utf-8") if isinstance(tei_xml, str) else tei_xml

    # Identisch gehaertet wie parse_tei_fulltext: TEI kommt von einem externen
    # Dienst und ist damit untrusted Input (XXE/Billion-Laughs).
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    root = etree.fromstring(payload, parser=parser)

    body = root.find(f".//{TEI_NS}text/{TEI_NS}body")
    if body is None:
        return []

    sections: list[TeiSection] = []
    state = _TeiParseState()
    _collect_sections(body, _head_title(body), sections, state)
    if state.truncated:
        logger.info("TEI-Sektionen auf %d Zeichen gekuerzt", MAX_FULLTEXT_CHARS)
    return sections


def _grobid_timeout() -> float:
    raw = os.environ.get(ENV_GROBID_TIMEOUT, "").strip()
    if not raw:
        return DEFAULT_GROBID_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_GROBID_TIMEOUT
    return value if value > 0 else DEFAULT_GROBID_TIMEOUT


def _post_grobid(
    pdf_path: str,
    base_url: str,
    timeout: float | None,
    extra_data: dict[str, str | list[str]] | None = None,
) -> str:
    """Ein ``processFulltextDocument``-Request, gemeinsam fuer beide TEI-Pfade.

    Wirft die httpx-Fehler durch; die Fallback-Entscheidung treffen die
    Aufrufer (:func:`extract_fulltext`, ``chunking.chunk_pdf``).
    """
    url = base_url.rstrip("/") + GROBID_ENDPOINT
    # consolidate*=0: sonst fragt GROBID per Default CrossRef an — das macht
    # aus einem lokalen Lauf einen Netzwerk-Roundtrip pro Paper.
    data: dict[str, str | list[str]] = {
        "consolidateHeader": "0",
        "consolidateCitations": "0",
    }
    if extra_data:
        data.update(extra_data)
    with open(pdf_path, "rb") as handle:
        response = httpx.post(
            url,
            files={"input": (os.path.basename(pdf_path), handle, "application/pdf")},
            data=data,
            timeout=timeout if timeout is not None else _grobid_timeout(),
        )
    response.raise_for_status()
    return response.text


def extract_grobid(pdf_path: str, base_url: str, timeout: float | None = None) -> str:
    """Schickt das PDF an einen GROBID-Server und gibt den TEI-Fliesstext zurueck.

    Wirft die httpx-/lxml-Fehler durch; die Fallback-Entscheidung trifft
    :func:`extract_fulltext`.
    """
    return _truncate(parse_tei_fulltext(_post_grobid(pdf_path, base_url, timeout)))


def extract_grobid_sections(
    pdf_path: str, base_url: str, timeout: float | None = None
) -> list[TeiSection]:
    """Wie :func:`extract_grobid`, aber strukturerhaltend (#709).

    Fordert zusaetzlich Koordinaten fuer ``<head>`` und ``<p>`` an — nur so
    traegt das TEI eine Seitenzahl. Wirft die httpx-/lxml-Fehler durch; die
    Fallback-Entscheidung trifft ``chunking.chunk_pdf``.
    """
    tei = _post_grobid(
        pdf_path,
        base_url,
        timeout,
        {"teiCoordinates": list(GROBID_COORD_ELEMENTS)},
    )
    return parse_tei_sections(tei)


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
