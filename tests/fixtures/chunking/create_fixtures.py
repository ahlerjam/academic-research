"""Erzeugt die Fixtures fuer das generische Chunking-Modul (Issues #374, #709).

Aufruf: python tests/fixtures/chunking/create_fixtures.py

Bewusst OHNE reportlab (gleiches Muster wie tests/fixtures/fulltext/create_fixtures.py
und tests/fixtures/ocr/create_fixtures.py): die Fixture wird als minimale, von Hand
gebaute PDF-1.4-Datei geschrieben (nur Standardbibliothek). reportlab ist keine
Dependency des Projekts.

Fixture 1: multi_section_paper.pdf (#374)
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

Fixture 2: grobid_tei_sample.xml (#709)
  - TEI-XML, wie GROBID es fuer ``POST /api/processFulltextDocument`` mit
    ``teiCoordinates=head`` und ``teiCoordinates=p`` liefert. Damit laeuft der
    GROBID-Pfad im Test OHNE laufenden Server.
  - Vier ``<div>`` im ``<body>``, jeweils mit ``<head>``:
      1. "Abstract"                                          (440 Woerter)
      2. "3.1 Effekte auf die Governance-Praxis, ein Ueberblick"  (341 Woerter,
         3 Absaetze) -- diese Ueberschrift matcht ``_HEADING_RE`` bewusst NICHT
         (Kleinschreibung + Komma), waehrend ihr erster Absatz mit "However"
         beginnt: genau das Wort, das die Regex-Heuristik faelschlich fuer eine
         Ueberschrift haelt.
      3. "4 Ergebnisse der Fallstudie"  (EIN Absatz mit 1519 Woertern, also
         deutlich ueber dem Tokenbudget -- erzwingt mehrere Chunks mit Overlap)
      4. "5 Fazit"                                           (300 Woerter)
  - ``@coords`` deckt drei Faelle ab: eine Box, mehrere durch ';' getrennte
    Boxen mit Seitenwechsel (die ERSTE Box bestimmt die Seite) und einen Absatz
    ganz ohne ``@coords`` (Seitenzahl wird fortgeschrieben).
  - Ein ``<back>``-Bereich mit Literaturverzeichnis belegt, dass der Parser nur
    den ``<body>`` in Sektionen zerlegt.
  - Alle Body-Woerter sind wie in Fixture 1 global eindeutig.
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


# ---------------------------------------------------------------------------
# TEI-Fixture (#709)
# ---------------------------------------------------------------------------

# Ueberschrift, die _HEADING_RE NICHT matcht (Kleinschreibung + Komma) --
# der Regex-Pfad verliert sie, der GROBID-Pfad liefert sie.
TEI_HEAD_MISSED_BY_REGEX = "3.1 Effekte auf die Governance-Praxis, ein Ueberblick"

# Fliesstext-Wort, das _HEADING_RE faelschlich fuer eine Ueberschrift haelt,
# sobald die PDF-Textextraktion es auf eine eigene Zeile umbricht.
TEI_REGEX_FALSE_POSITIVE = "However"

# Die uebergrosse Sektion: EIN Absatz, ~3.4x TARGET_TOKENS (448) -- erzwingt
# mehrere budgetgetriebene Schnitte samt Overlap (AK5 in Issue #709).
TEI_OVERSIZED_HEAD = "4 Ergebnisse der Fallstudie"
TEI_OVERSIZED_WORDS = 1519

# (Ueberschrift, [(coords, Wortanzahl), ...]) je <div> im <body>.
# ``coords`` ist der Wert des @coords-Attributs; ``None`` = Attribut fehlt.
TEI_SECTIONS: list[tuple[str, list[tuple[str | None, int]]]] = [
    ("Abstract", [("1,72.00,120.00,451.00,11.00", 440)]),
    (
        TEI_HEAD_MISSED_BY_REGEX,
        [
            ("1,72.00,240.00,451.00,11.00", 101),
            # Mehrere Boxen mit Seitenwechsel: die ERSTE Box gibt die Seite (1).
            ("1,72.00,320.00,451.00,11.00;2,72.00,90.00,451.00,11.00", 150),
            # Ohne @coords -- die zuletzt bekannte Seite wird fortgeschrieben.
            (None, 90),
        ],
    ),
    (TEI_OVERSIZED_HEAD, [("2,72.00,150.00,451.00,11.00", TEI_OVERSIZED_WORDS)]),
    ("5 Fazit", [("3,72.00,400.00,451.00,11.00", 300)]),
]

# Steht ausschliesslich im <back> und darf in keiner Sektion auftauchen.
TEI_BACK_MARKER = "Literaturverzeichnismarker"


def _tei_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_tei_sections() -> list[tuple[str, list[tuple[str | None, list[str]]]]]:
    """Baut ``[(head, [(coords, woerter), ...]), ...]`` mit global eindeutigen Woertern."""
    sections: list[tuple[str, list[tuple[str | None, list[str]]]]] = []
    cursor = 0
    for head, paragraphs in TEI_SECTIONS:
        built: list[tuple[str | None, list[str]]] = []
        for coords, count in paragraphs:
            if head == TEI_HEAD_MISSED_BY_REGEX and not built:
                # Erster Absatz der Sektion beginnt mit dem Regex-False-Positive.
                words = [TEI_REGEX_FALSE_POSITIVE, *_words_for_page(cursor, count - 1)]
                cursor += count - 1
            else:
                words = _words_for_page(cursor, count)
                cursor += count
            built.append((coords, words))
        sections.append((head, built))
    return sections


def build_tei_xml() -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">',
        "  <teiHeader>",
        "    <fileDesc>",
        "      <titleStmt>",
        '        <title level="a" type="main">Governance-Praxis in DevOps-Organisationen</title>',
        "      </titleStmt>",
        "    </fileDesc>",
        "  </teiHeader>",
        '  <text xml:lang="de">',
        "    <body>",
    ]
    for head, paragraphs in build_tei_sections():
        lines.append("      <div>")
        lines.append(f"        <head>{_tei_escape(head)}</head>")
        for coords, words in paragraphs:
            attr = f' coords="{coords}"' if coords else ""
            lines.append(f"        <p{attr}>{_tei_escape(' '.join(words))}</p>")
        lines.append("      </div>")
    lines += [
        "    </body>",
        "    <back>",
        '      <div type="references">',
        "        <listBibl>",
        f"          <biblStruct><note>{TEI_BACK_MARKER}</note></biblStruct>",
        "        </listBibl>",
        "      </div>",
        "    </back>",
        "  </text>",
        "</TEI>",
        "",
    ]
    return "\n".join(lines)


def create_grobid_tei_sample(path: Path) -> None:
    path.write_text(build_tei_xml(), encoding="utf-8")


if __name__ == "__main__":
    create_multi_section_pdf(OUT / "multi_section_paper.pdf")
    create_grobid_tei_sample(OUT / "grobid_tei_sample.xml")
    print(f"Fixtures erstellt in {OUT}")
