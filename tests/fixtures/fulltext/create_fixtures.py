"""Erzeugt die PDF-Fixtures fuer die Volltext-Extraktion (Issue #373, #897).

Aufruf: python tests/fixtures/fulltext/create_fixtures.py

Bewusst OHNE reportlab: die Fixtures werden als minimale, von Hand gebaute
PDF-1.4-Dateien geschrieben (nur Standardbibliothek). reportlab ist weder in
pyproject.toml noch in scripts/requirements.txt eine Dependency, und ein
Fixture-Generator, der sich nur mit einer optionalen Zusatz-Lib ausfuehren
laesst, ist praktisch nicht reproduzierbar.

Drei Fixtures:
  - nonce_paper.pdf      Text-Layer mit dem Nonce-Token (pypdf extrahiert Text)
  - scan_no_text.pdf     leere Seiten ohne Text-Layer (Scan-Simulation)
  - hyphenation_897.pdf  Silbentrennung am Zeilenumbruch (Issue #897): jede
    Zeile wird als eigene ``Tj``/``T*``-Operation geschrieben, pypdf gibt sie
    daher als eigene Textzeile mit ``\\n`` an der Trennstelle aus — genau das
    Muster, das ``_merge_hyphenation()`` auflösen muss.

NONCE_TOKEN ist bewusst ein Kunstwort: es darf in keinem Titel und keinem
Abstract der Testdaten vorkommen, damit ein Suchtreffer beweist, dass der
Volltext indiziert wurde (AC 2 von #373).
"""

from pathlib import Path

OUT = Path(__file__).parent

NONCE_TOKEN = "zqxwvfulltextnonce373"

PAGE_LINES: list[list[str]] = [
    [
        "Vault Fulltext Extraction Fixture",
        "Dieses Dokument existiert ausschliesslich fuer die Tests zu Issue 373.",
        f"Kanarienvogel-Token: {NONCE_TOKEN}",
    ],
    [
        "Zweite Seite mit weiterem Fliesstext.",
        "Der Volltext-Index muss auch Seite zwei erfassen.",
        "Schlagwort auf Seite zwei: seitenzweimarker373",
    ],
]


def _escape(text: str) -> str:
    """Escaped die PDF-String-Sonderzeichen fuer literale ``(...)``-Strings."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(lines: list[str]) -> bytes:
    parts = ["BT", "/F1 12 Tf", "14 TL", "72 720 Td"]
    for line in lines:
        parts.append(f"({_escape(line)}) Tj")
        parts.append("T*")
    parts.append("ET")
    return "\n".join(parts).encode("latin-1")


def _build_pdf(pages: list[list[str]]) -> bytes:
    """Baut ein minimales PDF mit einer Textseite je Eintrag in ``pages``.

    Leere Zeilenlisten erzeugen eine Seite ohne Text-Layer (Scan-Simulation).
    """
    page_count = len(pages)
    # Objekt-Nummern: 1 Catalog, 2 Pages, 3 Font, danach je Seite Page+Contents.
    first_page_obj = 4
    page_obj_ids = [first_page_obj + 2 * i for i in range(page_count)]

    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            "<< /Type /Pages /Kids ["
            + " ".join(f"{oid} 0 R" for oid in page_obj_ids)
            + f"] /Count {page_count} >>"
        ).encode("latin-1"),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }

    for index, lines in enumerate(pages):
        page_id = page_obj_ids[index]
        contents_id = page_id + 1
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {contents_id} 0 R >>"
        ).encode("latin-1")
        stream = _content_stream(lines)
        objects[contents_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for obj_id in sorted(objects):
        offsets[obj_id] = len(out)
        out += f"{obj_id} 0 obj\n".encode("latin-1")
        out += objects[obj_id]
        out += b"\nendobj\n"

    xref_offset = len(out)
    max_id = max(objects)
    out += f"xref\n0 {max_id + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for obj_id in range(1, max_id + 1):
        out += f"{offsets[obj_id]:010d} 00000 n \n".encode("latin-1")
    out += f"trailer\n<< /Size {max_id + 1} /Root 1 0 R >>\n".encode("latin-1")
    out += f"startxref\n{xref_offset}\n%%EOF\n".encode("latin-1")
    return bytes(out)


def create_nonce_pdf(path: Path) -> None:
    """PDF mit Text-Layer inkl. Nonce-Token (pypdf extrahiert echten Text)."""
    path.write_bytes(_build_pdf(PAGE_LINES))


def create_scan_pdf(path: Path) -> None:
    """PDF ohne Text-Layer (Scan-Simulation): pypdf liefert leeren String."""
    path.write_bytes(_build_pdf([[], []]))


# Jede Zeichenkette wird als eigene Textzeile geschrieben (Tj + T*), pypdf
# trennt sie daher per "\n" -- genau das Layout eines zweispaltigen Satzes,
# der am Zeilenende trennt. Deckt AC1 (Belegfaelle), AC2 (echter Bindestrich
# ohne Umbruch) und die Gegenprobe fuer AC4 (indizierbares Zitat) ab.
HYPHENATION_LINES: list[list[str]] = [
    [
        "In-",
        "equality ist das erste Belegwort aus dem Lauf vom 12.08.2026.",
        "Das betrifft jedes individ-",
        "uelle Beispiel aus dem Bericht.",
        "Auch consul-",
        "tancy und reproducibil-",
        "ity sowie compu-",
        "tation gehoeren dazu.",
        "Multi-Agent-Systeme sind hier ein echter Bindestrich ohne Umbruch.",
    ],
]


def create_hyphenation_pdf(path: Path) -> None:
    """PDF mit Silbentrennungen am Zeilenumbruch (Issue #897)."""
    path.write_bytes(_build_pdf(HYPHENATION_LINES))


if __name__ == "__main__":
    create_nonce_pdf(OUT / "nonce_paper.pdf")
    create_scan_pdf(OUT / "scan_no_text.pdf")
    create_hyphenation_pdf(OUT / "hyphenation_897.pdf")
    print(f"Fixtures erstellt in {OUT}")
