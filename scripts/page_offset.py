"""page_offset.py — Ermittelt page_offset fuer Buecher mit Vorseiten.

Logik (in dieser Reihenfolge, #384):
  0. Zuerst wird der PDF-eigene `/PageLabels`-Baum ausgelesen (autoritative
     Quelle, sofern vorhanden). Liefert er einen Offset, wird dieser direkt
     zurueckgegeben.
  1. Nur als Fallback (kein Label-Baum / kein passendes Decimal-Segment /
     Parse-Fehler): Iteriere ueber die ersten sample_pages PDF-Seiten
     (0-basiert), extrahiere Text jeder Seite via pypdf und suche nach
     isolierter arabischer Ziffer "1" als erste oder letzte Zeile des
     extrahierten Textes (typische Seitenzahl-Position).
     offset = gefundene_pdf_seite_1basiert - 1
     (d.h. pdf_page_1basiert - offset = printed_page)

Kein LLM-Aufruf. Deterministisch und schnell.

CLI: python scripts/page_offset.py <pdf_path> [--sample-pages N]
"""

import re


def _get_pdf_reader():
    """Gibt die pypdf-PdfReader-Klasse zurueck."""
    try:
        from pypdf import PdfReader

        return PdfReader
    except ImportError:
        raise ImportError("Kein PDF-Lesemodul verfuegbar. Bitte 'pip install pypdf' ausfuehren.")


def _extract_page_number(text: str) -> int | None:
    """Extrahiert arabische Seitenzahl aus Seiten-Text.

    Sucht nach einer isolierten arabischen Ziffer als erste oder letzte
    nicht-leere Zeile des Textes (typische Seitenzahl-Position oben/unten).

    Gibt None zurueck wenn keine eindeutige arabische Seitenzahl gefunden.
    Ignoriert roemische Ziffern (i, ii, iii, iv, v, vi, etc.).
    """
    if not text or not text.strip():
        return None

    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return None

    # Roemische Ziffern (kleine und grosse) ausschliessen
    roman_pattern = re.compile(
        r"^(i{1,3}|iv|v?i{0,3}|ix|xl|l?x{0,3}|xc|cd|d?c{0,3}|cm|m{0,4})$",
        re.IGNORECASE,
    )

    # Erste und letzte Zeile pruefen (Seitenzahlen stehen oben oder unten)
    candidates = [lines[0], lines[-1]]

    for candidate in candidates:
        # Roemische Ziffer explizit ueberspringen
        if roman_pattern.match(candidate):
            continue
        # Nur reine arabische Zahl akzeptieren
        if re.match(r"^\d+$", candidate):
            num = int(candidate)
            if 1 <= num <= 9999:
                return num

    return None


def _detect_offset_from_page_labels(pdf_path: str) -> int | None:
    """Liest den PDF-eigenen `/PageLabels`-Baum aus (autoritative Quelle).

    Sucht das *erste* Segment mit Decimal-Stil (`/S == "/D"`) ohne Prefix
    (`/P`) im `/Nums`-Array (`trailer["/Root"]["/PageLabels"]["/Nums"]`) und
    berechnet daraus den Offset:

        offset = (segment_start_index + 1) - segment_start_wert

    `segment_start_index` ist der 0-basierte PDF-Seitenindex, ab dem das
    Segment beginnt (`+1` macht ihn 1-basiert); `segment_start_wert` ist der
    Wert des ersten Labels in diesem Segment (`/St`, Default 1 laut PDF-Spec).

    Ist bei mehreren Decimal-Segmenten (z.B. Anhang startet erneut bei 1) das
    *erste* gefundene Segment massgeblich -- konsistent mit der bestehenden
    Text-Heuristik, die ebenfalls die erste gefundene arabische "1" nimmt.

    Gibt None zurueck wenn kein `/PageLabels`-Baum vorhanden ist, kein
    passendes Decimal-Segment gefunden wird, oder der Baum defekt/
    inkonsistent ist (fehlender `/Root`, leeres/fehlerhaftes `/Nums`). Wirft
    bewusst keine Exception weiter, damit der Aufrufer verlustfrei auf die
    Text-Heuristik zurueckfallen kann (AC2).
    """
    try:
        PdfReader = _get_pdf_reader()
        reader = PdfReader(pdf_path)
        root = reader.trailer["/Root"]
        page_labels = root["/PageLabels"].get_object()
        nums = page_labels["/Nums"]
    except (KeyError, TypeError):
        return None

    try:
        for i in range(0, len(nums) - 1, 2):
            segment_start = nums[i]
            segment = nums[i + 1].get_object()
            style = segment.get("/S")
            prefix = segment.get("/P")
            if style == "/D" and not prefix:
                start_value = segment.get("/St", 1)
                return (int(segment_start) + 1) - int(start_value)
    except (IndexError, TypeError, KeyError, AttributeError):
        return None

    return None


def detect_page_offset(pdf_path: str, sample_pages: int = 30) -> int:
    """Ermittelt den page_offset eines PDFs.

    Versucht zuerst den PDF-eigenen `/PageLabels`-Baum
    (`_detect_offset_from_page_labels`); liefert dieser ein Ergebnis, wird es
    direkt zurueckgegeben. Andernfalls (kein Baum / kein Decimal-Segment /
    Parse-Fehler) greift die bestehende Text-Heuristik als Fallback: scannt
    die ersten sample_pages Seiten des PDFs und gibt
    offset = (pdf_page_1basiert_der_ersten_arabischen_1) - 1 zurueck.
    Gibt 0 zurueck wenn weder Label-Baum noch arabische '1' gefunden werden.

    Args:
        pdf_path: Pfad zur PDF-Datei.
        sample_pages: Anzahl der zu scannenden Seiten (Standard: 30).

    Returns:
        page_offset (int). Bedeutung: printed_page = pdf_page - offset.
    """
    label_offset = _detect_offset_from_page_labels(pdf_path)
    if label_offset is not None:
        return label_offset

    PdfReader = _get_pdf_reader()

    reader = PdfReader(pdf_path)
    num_pages = min(sample_pages, len(reader.pages))

    for pdf_idx in range(num_pages):
        page = reader.pages[pdf_idx]
        text = page.extract_text() or ""
        page_num = _extract_page_number(text)
        if page_num == 1:
            # pdf_idx ist 0-basiert; pdf_page_1basiert = pdf_idx + 1
            # offset = pdf_page_1basiert - 1 = pdf_idx
            return pdf_idx

    return 0  # Kein Offset erkannt (Buch ohne erkennbare Seitenzahlen)


def validate_offset(
    pdf_path: str,
    offset: int,
    check_pages: list | None = None,
) -> bool:
    """Validiert den page_offset anhand von Stichproben.

    Fuer jede check_page (0-basierter PDF-Index) wird geprueft ob:
        _extract_page_number(text) == (check_page + 1) - offset

    Args:
        pdf_path: Pfad zur PDF-Datei.
        offset: Zu validierender Offset.
        check_pages: Liste von 0-basierten PDF-Seiten-Indizes fuer Stichproben.
                     Standard: [offset+1, offset+2] (zwei Seiten nach der "1").

    Returns:
        True wenn alle Stichproben konsistent, False sonst.
    """
    PdfReader = _get_pdf_reader()

    reader = PdfReader(pdf_path)
    num_pages = len(reader.pages)

    if check_pages is None:
        check_pages = [offset + 1, offset + 2]

    for pdf_idx in check_pages:
        if pdf_idx >= num_pages:
            continue
        page = reader.pages[pdf_idx]
        text = page.extract_text() or ""
        page_num = _extract_page_number(text)
        expected = (pdf_idx + 1) - offset
        if page_num != expected:
            return False

    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ermittelt page_offset fuer ein Buch-PDF.")
    parser.add_argument("pdf_path", help="Pfad zur PDF-Datei")
    parser.add_argument(
        "--sample-pages",
        type=int,
        default=30,
        help="Anzahl der zu scannenden Seiten (Standard: 30)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Offset zusaetzlich anhand von Stichproben validieren",
    )
    args = parser.parse_args()

    offset = detect_page_offset(args.pdf_path, args.sample_pages)
    print(f"page_offset: {offset}")

    if args.validate and offset > 0:
        valid = validate_offset(args.pdf_path, offset)
        print(f"Validierung: {'OK' if valid else 'INKONSISTENT'}")
