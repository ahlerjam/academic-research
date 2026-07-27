"""Erzeugt synthetische PDF-Fixtures fuer page_offset-Tests.

Aufruf: python tests/fixtures/page_offset/create_fixtures.py
Benoetigt: reportlab (pip install reportlab) fuer die Text-Heuristik-Fixtures,
pypdf (bereits im Stack) fuer die /PageLabels-Fixture.
"""

from pathlib import Path

from pypdf import PdfWriter
from pypdf.constants import PageLabelStyle
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent


def create_no_preface(path: Path) -> None:
    """Buch ohne Vorwort: gedruckte Seite 1 auf PDF-Seite 1 (offset=0)."""
    c = canvas.Canvas(str(path), pagesize=A4)
    for i in range(10):
        printed = i + 1
        c.drawString(72, 40, str(printed))  # Seitenzahl unten
        c.drawString(72, 750, f"Inhalt Seite {printed}")
        c.showPage()
    c.save()


def create_ten_prefaces(path: Path) -> None:
    """10 Vorseiten (unnummeriert), dann gedruckte Seite 1 (offset=10)."""
    c = canvas.Canvas(str(path), pagesize=A4)
    for i in range(10):
        c.drawString(72, 750, f"Vorwort Seite {i + 1}")
        # keine Seitenzahl unten
        c.showPage()
    for i in range(10):
        printed = i + 1
        c.drawString(72, 40, str(printed))
        c.drawString(72, 750, f"Kapitel Inhalt {printed}")
        c.showPage()
    c.save()


def create_roman_numerals(path: Path) -> None:
    """Seiten i-vi (roemisch), dann arabisch ab 1 auf PDF-Seite 7 (offset=6)."""
    roman = ["i", "ii", "iii", "iv", "v", "vi"]
    c = canvas.Canvas(str(path), pagesize=A4)
    for r in roman:
        c.drawString(72, 40, r)
        c.drawString(72, 750, f"Vorbemerkung {r}")
        c.showPage()
    for i in range(10):
        printed = i + 1
        c.drawString(72, 40, str(printed))
        c.drawString(72, 750, f"Kapitel {printed}")
        c.showPage()
    c.save()


def create_double_pagination(path: Path) -> None:
    """5 unnummerierte Seiten (Deckblatt etc.), dann arabisch ab 1 (offset=5)."""
    c = canvas.Canvas(str(path), pagesize=A4)
    for i in range(5):
        c.drawString(72, 750, f"Frontmatter {i + 1}")
        c.showPage()
    for i in range(10):
        printed = i + 1
        c.drawString(72, 40, str(printed))
        c.drawString(72, 750, f"Text {printed}")
        c.showPage()
    c.save()


def create_large_offset(path: Path) -> None:
    """25 Vorseiten, arabische 1 auf PDF-Seite 26 (offset=25)."""
    c = canvas.Canvas(str(path), pagesize=A4)
    for i in range(25):
        c.drawString(72, 750, f"Frontmatter {i + 1}")
        c.showPage()
    for i in range(10):
        printed = i + 1
        c.drawString(72, 40, str(printed))
        c.drawString(72, 750, f"Inhalt {printed}")
        c.showPage()
    c.save()


def create_page_labels(path: Path) -> None:
    """PDF mit eingebettetem /PageLabels-Baum (#384): 3 Roemisch-Vorseiten
    (Label-Stil lowercase-roman, Start 1) + Decimal-Segment ab Index 3
    (Start 1), macht 10 Seiten gesamt.

    Seiten sind bewusst leer (kein drawString/extrahierbarer Text), damit ein
    Test-Erfolg nur ueber den /PageLabels-Baum moeglich ist -- kein
    Zufallstreffer der Text-Heuristik. Erwarteter offset=3
    (pdf_page_1basiert(4) - start_value(1) = 3).
    """
    writer = PdfWriter()
    for _ in range(10):
        writer.add_blank_page(width=595, height=842)  # A4 in pt
    writer.set_page_label(0, 2, style=PageLabelStyle.LOWERCASE_ROMAN, start=1)
    writer.set_page_label(3, 9, style=PageLabelStyle.DECIMAL, start=1)
    with open(path, "wb") as f:
        writer.write(f)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    create_no_preface(OUT / "no_preface.pdf")
    create_ten_prefaces(OUT / "ten_prefaces.pdf")
    create_roman_numerals(OUT / "roman_numerals.pdf")
    create_double_pagination(OUT / "double_pagination.pdf")
    create_large_offset(OUT / "large_offset.pdf")
    create_page_labels(OUT / "page_labels.pdf")
    print(f"6 Fixtures erstellt in {OUT}")
