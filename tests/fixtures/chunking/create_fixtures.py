"""Erzeugt die PDF-Fixture fuer das generische Chunking-Modul (Issue #374).

Aufruf: python tests/fixtures/chunking/create_fixtures.py

Bewusst OHNE reportlab (gleiches Muster wie tests/fixtures/fulltext/create_fixtures.py
und tests/fixtures/ocr/create_fixtures.py): die Fixture wird als minimale, von Hand
gebaute PDF-1.4-Datei geschrieben (nur Standardbibliothek). reportlab ist keine
Dependency des Projekts.

Eine Fixture: multi_section_paper.pdf
  - 6 physische Seiten, je eine Ueberschrift + ein langer Fliesstext-Absatz
  - Ueberschriften: "Abstract", "1 Introduction", "2 Related Work", "3 Method",
    "4 Experiments", "5 Conclusion" -- erkennbar per Regex-Heuristik in
    academic_vault.chunking
  - Body-Woerter sind global eindeutig (Wortstamm + laufender Index, z.B.
    "retrieval0", "systems1", ...), damit Tests die Wort-Ueberlappung zwischen
    benachbarten Chunks EXAKT und ohne Mehrdeutigkeit (keine zufaelligen
    Wiederholungen) nachweisen koennen.
  - Gesamtwortzahl (1520) ist bewusst so gewaehlt, dass bei TARGET_TOKENS=512 /
    OVERLAP_RATIO=0.125 mehrere Chunks inkl. eines kuerzeren letzten Chunks
    entstehen (siehe tests/test_chunking.py).
"""

from pathlib import Path

OUT = Path(__file__).parent

# Wortstamm-Pool fuer den Fliesstext -- rein lesbare, deterministische Woerter.
# Jedes tatsaechlich geschriebene Wort bekommt zusaetzlich den globalen Index
# angehaengt (siehe _words_for_page), damit kein Wort im gesamten Dokument
# zufaellig ein zweites Mal vorkommt.
WORD_POOL = [
    "retrieval",
    "systems",
    "combine",
    "dense",
    "and",
    "sparse",
    "representations",
    "to",
    "improve",
    "semantic",
    "search",
    "over",
    "large",
    "document",
    "collections",
    "researchers",
    "evaluate",
    "different",
    "chunking",
    "strategies",
    "observe",
    "that",
    "overlapping",
    "windows",
    "preserve",
    "context",
    "across",
    "boundaries",
    "the",
    "proposed",
    "approach",
    "uses",
    "a",
    "sliding",
    "window",
    "with",
    "fixed",
    "overlap",
    "ratio",
    "balance",
    "redundancy",
    "against",
    "recall",
]

# (Ueberschrift, Wortanzahl) je physischer Seite.
SECTIONS: list[tuple[str, int]] = [
    ("Abstract", 80),
    ("1 Introduction", 320),
    ("2 Related Work", 320),
    ("3 Method", 320),
    ("4 Experiments", 320),
    ("5 Conclusion", 160),
]


def _words_for_page(start_index: int, count: int) -> list[str]:
    return [f"{WORD_POOL[i % len(WORD_POOL)]}{i}" for i in range(start_index, start_index + count)]


def build_pages() -> list[list[str]]:
    """Baut je physischer Seite eine Zeilenliste [Ueberschrift, Fliesstext]."""
    pages: list[list[str]] = []
    cursor = 0
    for title, count in SECTIONS:
        words = _words_for_page(cursor, count)
        cursor += count
        pages.append([title, " ".join(words)])
    return pages


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
    """Baut ein minimales PDF mit einer Textseite je Eintrag in ``pages``."""
    page_count = len(pages)
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


def create_multi_section_pdf(path: Path) -> None:
    path.write_bytes(_build_pdf(build_pages()))


if __name__ == "__main__":
    create_multi_section_pdf(OUT / "multi_section_paper.pdf")
    print(f"Fixture erstellt in {OUT}")
