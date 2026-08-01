"""Erzeugt die PDF-Fixtures fuer das Verbatim-Verifikationsmodul (Issue #511).

Aufruf: python tests/fixtures/verbatim/create_fixtures.py

Bewusst OHNE reportlab -- analog zu tests/fixtures/fulltext/create_fixtures.py
(Issue #373): minimale, von Hand gebaute PDF-1.4-Dateien, nur Standardbibliothek.

Zwei Fixtures:
  - verbatim_source.pdf  Text-Layer mit Ligatur, Zeilenend-Trennstrich,
                          "krummen" Anfuehrungszeichen und einer Tippfehler-Stelle
  - scan_no_text.pdf     leere Seiten ohne Text-Layer (Scan-Simulation)

TECHNIK (anders als fulltext-Fixtures): die Content-Streams referenzieren einen
Font mit einer /ToUnicode-CMap. pypdf extrahiert Text bevorzugt ueber diese
CMap -- damit laesst sich der von pypdf zurueckgegebene Unicode-Text exakt
kontrollieren, OHNE dass echte Ligatur-/Anfuehrungszeichen-Glyphen im
verwendeten Type1-Font (Helvetica) vorhanden sein muessten. Die Byte-Codes
0x01-0x03 sind reserviert:

  0x01 -> U+FB01 LATIN SMALL LIGATURE FI (ﬁ)
  0x02 -> U+201C LEFT DOUBLE QUOTATION MARK (")
  0x03 -> U+201D RIGHT DOUBLE QUOTATION MARK (")

Alle uebrigen Codes 0x20-0x7E (druckbares ASCII) werden per bfrange 1:1 auf
sich selbst gemappt.
"""

from pathlib import Path

OUT = Path(__file__).parent

# Reservierte Sonder-Byte-Codes -> Zielzeichen (siehe Modul-Docstring).
LIGATURE_FI = "\x01"
LEFT_DQUOTE = "\x02"
RIGHT_DQUOTE = "\x03"

PAGE1_LINES: list[str] = [
    "Vault Verbatim Fixture",
    f"Die Wirksamkeit der Kon{LIGATURE_FI}guration wurde nachgewiesen.",
    "Diese Studie belegt eine gesteigerte innovations-",
    "faehigkeit in den befragten Organisationen.",
    "Der Interviewpartner betonte die Bedeutung von Vertrauen im Team.",
]

PAGE2_LINES: list[str] = [
    "Zweite Seite des Verbatim-Fixtures.",
    f"Die Teilnehmenden beschrieben {LEFT_DQUOTE}implizites Wissen{RIGHT_DQUOTE} "
    "als zentralen Faktor.",
]

TOUNICODE_CMAP = b"""/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
1 begincodespacerange
<00> <ff>
endcodespacerange
1 beginbfrange
<20> <7e> <0020>
endbfrange
3 beginbfchar
<01> <FB01>
<02> <201C>
<03> <201D>
endbfchar
endcmap
CMapName currentdict /CMap defineresource pop
end
end
"""


def _escape_literal(line: str) -> bytes:
    """Encoded eine Zeile als PDF-Literal-String-Body (zwischen ``(`` und ``)``).

    Druckbares ASCII (0x20-0x7E) geht direkt durch (mit Escaping von
    ``\\``/``(``/``)``); die reservierten Sonder-Codes werden als Oktal-Escape
    geschrieben, damit sie als einzelnes Byte im Content-Stream landen.
    """
    out = bytearray()
    for ch in line:
        if ch in (LIGATURE_FI, LEFT_DQUOTE, RIGHT_DQUOTE):
            out += f"\\{ord(ch):03o}".encode("ascii")
        elif ch in ("\\", "(", ")"):
            out += f"\\{ch}".encode("ascii")
        else:
            out += ch.encode("ascii")
    return bytes(out)


def _content_stream(lines: list[str]) -> bytes:
    parts = [b"BT", b"/F1 12 Tf", b"14 TL", b"72 720 Td"]
    for line in lines:
        parts.append(b"(" + _escape_literal(line) + b") Tj")
        parts.append(b"T*")
    parts.append(b"ET")
    return b"\n".join(parts)


def _build_pdf(pages: list[list[str]]) -> bytes:
    """Baut ein minimales PDF mit einer Textseite je Eintrag in ``pages``.

    Leere Zeilenlisten erzeugen eine Seite ohne Text-Layer (Scan-Simulation).
    Jede Seite referenziert denselben Font (Objekt 3) mit /ToUnicode-CMap
    (Objekt 6) -- siehe Modul-Docstring.
    """
    page_count = len(pages)
    # Objekt-Nummern LUECKENLOS (die Xref-Tabelle unten erwartet 1..max_id
    # vollstaendig): 1 Catalog, 2 Pages, 3 Font, 4 ToUnicode-CMap, danach je
    # Seite Page+Contents ab Objekt 5.
    first_page_obj = 5
    page_obj_ids = [first_page_obj + 2 * i for i in range(page_count)]

    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            "<< /Type /Pages /Kids ["
            + " ".join(f"{oid} 0 R" for oid in page_obj_ids)
            + f"] /Count {page_count} >>"
        ).encode("latin-1"),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode 4 0 R >>",
        4: (
            f"<< /Length {len(TOUNICODE_CMAP)} >>\nstream\n".encode("latin-1")
            + TOUNICODE_CMAP
            + b"\nendstream"
        ),
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


def create_source_pdf(path: Path) -> None:
    """PDF mit Text-Layer: Ligatur, Trennstrich-Zeilenumbruch, krumme Quotes."""
    path.write_bytes(_build_pdf([PAGE1_LINES, PAGE2_LINES]))


def create_scan_pdf(path: Path) -> None:
    """PDF ohne Text-Layer (Scan-Simulation): pypdf liefert leeren String."""
    path.write_bytes(_build_pdf([[], []]))


if __name__ == "__main__":
    create_source_pdf(OUT / "verbatim_source.pdf")
    create_scan_pdf(OUT / "scan_no_text.pdf")
    print(f"Fixtures erstellt in {OUT}")
