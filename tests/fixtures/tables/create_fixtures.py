"""Erzeugt die PDF-Fixtures fuer die Tabellenextraktion (Issue #630).

Aufruf: python tests/fixtures/tables/create_fixtures.py

Bewusst OHNE reportlab -- analog zu tests/fixtures/fulltext/create_fixtures.py
(#373) und tests/fixtures/verbatim/create_fixtures.py (#511): minimale, von
Hand gebaute PDF-1.4-Dateien, nur Standardbibliothek. Ein Fixture-Generator,
der eine Zusatz-Lib braucht, ist praktisch nicht reproduzierbar.

TECHNIK: pdfplumber erkennt Tabellen per Default ueber *gezeichnete Linien*
(``vertical_strategy="lines"``). Die Fixtures zeichnen ihr Gitter deshalb als
echte Stroke-Pfade (``m``/``l``/``S``) in den Content-Stream — ein reines
Text-PDF wie die verbatim-Fixtures wuerde ohne Linien gar nicht als Tabelle
erkannt und die Tests haengen sonst an einer Text-Heuristik (flaky).

Vier Fixtures:
  - results_table.pdf     mehrspaltige Ergebnistabelle mit vollstaendigem
                          Gitter (Studie / N / d / 95%-CI)
  - two_column_layout.pdf zweispaltiger Fliesstext mit einer Tabelle in der
                          linken Spalte (Layout-Stressfall)
  - merged_header.pdf     Tabelle mit verbundener Kopfzelle: in der Kopfzeile
                          fehlt die mittlere Trennlinie
  - no_table.pdf          reiner Fliesstext ohne jede Linie
  - scan_no_textlayer.pdf leere Seite ohne Text-Layer (Scan-Simulation)

Alle Koordinaten sind PDF-Nutzerkoordinaten: Ursprung unten links, y waechst
nach oben. Die Zeilen einer Tabelle werden hier deshalb von oben nach unten
mit *fallendem* y angelegt.
"""

from pathlib import Path

OUT = Path(__file__).parent

# Seitenmasse (US Letter, wie in den fulltext-Fixtures).
PAGE_WIDTH = 612
PAGE_HEIGHT = 792

#: Abstand der Textgrundlinie vom oberen Rand einer Tabellenzeile.
CELL_BASELINE_DROP = 14
#: Linker Innenabstand des Zelltextes zur Zellkante.
CELL_PADDING = 4

# --- Ergebnistabelle (results_table.pdf) -----------------------------------
# 4 Spalten x 4 Zeilen (Kopfzeile + 3 Datenzeilen).
RESULTS_COLUMN_X = [72.0, 220.0, 300.0, 380.0, 500.0]
RESULTS_ROW_Y = [720.0, 696.0, 672.0, 648.0, 624.0]
RESULTS_ROWS: list[list[str]] = [
    ["Studie", "N", "d", "95%-CI"],
    ["Smith 2020", "120", "0.42", "0.18 bis 0.66"],
    ["Jones 2021", "84", "0.31", "0.05 bis 0.57"],
    ["Lee 2019", "210", "0.55", "0.34 bis 0.76"],
]

# --- Verbundene Kopfzelle (merged_header.pdf) ------------------------------
MERGED_COLUMN_X = [72.0, 240.0, 360.0, 480.0]
MERGED_ROW_Y = [720.0, 696.0, 672.0, 648.0, 624.0]
MERGED_ROWS: list[list[str]] = [
    ["Studie", "Effekt", ""],
    ["", "d", "SE"],
    ["Smith 2020", "0.42", "0.12"],
    ["Jones 2021", "0.31", "0.13"],
]

# --- Zweispaltiges Layout (two_column_layout.pdf) --------------------------
LEFT_COLUMN_TEXT = [
    "Ergebnisse der Primaerstudien",
    "Die berichteten Effekte streuen deutlich",
    "zwischen den eingeschlossenen Studien.",
]
RIGHT_COLUMN_TEXT = [
    "Diskussion",
    "Die Heterogenitaet laesst sich nur zum Teil",
    "durch das Erhebungsjahr erklaeren. Weitere",
    "Moderatoren bleiben offen.",
]
TWO_COL_COLUMN_X = [72.0, 170.0, 240.0]
TWO_COL_ROW_Y = [640.0, 616.0, 592.0]
TWO_COL_TABLE_ROWS: list[list[str]] = [
    ["Studie", "N"],
    ["Smith 2020", "120"],
]

NO_TABLE_TEXT = [
    "Ein Abschnitt ohne jede Tabelle",
    "Dieser Text enthaelt keine gezeichneten Linien und",
    "damit auch kein Tabellengitter. Die Extraktion muss",
    "das sichtbar melden statt eine leere Liste zu liefern.",
]


def _escape(text: str) -> str:
    """Escaped die PDF-String-Sonderzeichen fuer literale ``(...)``-Strings."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _text_op(x: float, y: float, text: str, size: int = 10) -> str:
    """Setzt einen Textblock an eine absolute Position."""
    return f"BT /F1 {size} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({_escape(text)}) Tj ET"


def _line_op(x0: float, y0: float, x1: float, y1: float) -> str:
    """Zeichnet eine gestrichene Linie (Stroke-Pfad, kein Rechteck)."""
    return f"{x0:.2f} {y0:.2f} m {x1:.2f} {y1:.2f} l S"


def _grid_ops(
    column_x: list[float],
    row_y: list[float],
    skip_vertical: set[tuple[int, int]] | None = None,
) -> list[str]:
    """Zeichnet ein Tabellengitter aus Spalten- und Zeilenkanten.

    Args:
        column_x: x-Koordinaten aller Spaltenkanten (Anzahl Spalten + 1).
        row_y: y-Koordinaten aller Zeilenkanten, absteigend (Zeilen + 1).
        skip_vertical: ``(zeilen_index, kanten_index)``-Paare, deren senkrechtes
            Segment ausgelassen wird — so entsteht eine verbundene Kopfzelle.
    """
    skip = skip_vertical or set()
    ops: list[str] = ["0.75 w"]
    for y in row_y:
        ops.append(_line_op(column_x[0], y, column_x[-1], y))
    for row_index in range(len(row_y) - 1):
        top = row_y[row_index]
        bottom = row_y[row_index + 1]
        for edge_index, x in enumerate(column_x):
            if (row_index, edge_index) in skip:
                continue
            ops.append(_line_op(x, top, x, bottom))
    return ops


def _table_text_ops(
    column_x: list[float],
    row_y: list[float],
    rows: list[list[str]],
) -> list[str]:
    """Setzt die Zelltexte an die linke obere Ecke ihrer jeweiligen Zelle."""
    ops: list[str] = []
    for row_index, row in enumerate(rows):
        baseline = row_y[row_index] - CELL_BASELINE_DROP
        for col_index, value in enumerate(row):
            if not value:
                continue
            ops.append(_text_op(column_x[col_index] + CELL_PADDING, baseline, value))
    return ops


def _column_text_ops(x: float, top_y: float, lines: list[str]) -> list[str]:
    """Setzt eine Folge von Textzeilen mit festem Zeilenabstand."""
    return [_text_op(x, top_y - 14.0 * index, line) for index, line in enumerate(lines)]


def _build_pdf(pages: list[list[str]]) -> bytes:
    """Baut ein minimales PDF; jede Seite ist eine Liste von Content-Operatoren."""
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

    for index, ops in enumerate(pages):
        page_id = page_obj_ids[index]
        contents_id = page_id + 1
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {contents_id} 0 R >>"
        ).encode("latin-1")
        stream = "\n".join(ops).encode("latin-1")
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


def create_results_table_pdf(path: Path) -> None:
    """Mehrspaltige Ergebnistabelle mit vollstaendigem Gitter (AC1)."""
    ops = [_text_op(72, 750, "Tabelle 1: Effektstaerken der Primaerstudien", size=12)]
    ops += _grid_ops(RESULTS_COLUMN_X, RESULTS_ROW_Y)
    ops += _table_text_ops(RESULTS_COLUMN_X, RESULTS_ROW_Y, RESULTS_ROWS)
    path.write_bytes(_build_pdf([ops]))


def create_merged_header_pdf(path: Path) -> None:
    """Tabelle mit verbundener Kopfzelle: Kopfzeile ohne mittlere Trennlinie (AC3)."""
    ops = [_text_op(72, 750, "Tabelle 2: verbundene Kopfzelle", size=12)]
    # Zeile 0 ist die Kopfzeile; Kante 2 (die mittlere) faellt dort weg, damit
    # sich "Effekt" ueber die Spalten d und SE erstreckt.
    ops += _grid_ops(MERGED_COLUMN_X, MERGED_ROW_Y, skip_vertical={(0, 2)})
    ops += _table_text_ops(MERGED_COLUMN_X, MERGED_ROW_Y, MERGED_ROWS)
    path.write_bytes(_build_pdf([ops]))


def create_two_column_layout_pdf(path: Path) -> None:
    """Zweispaltiges Layout mit einer kleinen Tabelle in der linken Spalte (AC3)."""
    ops = [_text_op(72, 750, "Zweispaltiges Layout", size=12)]
    ops += _column_text_ops(72, 720, LEFT_COLUMN_TEXT)
    ops += _column_text_ops(330, 720, RIGHT_COLUMN_TEXT)
    ops += _grid_ops(TWO_COL_COLUMN_X, TWO_COL_ROW_Y)
    ops += _table_text_ops(TWO_COL_COLUMN_X, TWO_COL_ROW_Y, TWO_COL_TABLE_ROWS)
    path.write_bytes(_build_pdf([ops]))


def create_no_table_pdf(path: Path) -> None:
    """Reiner Fliesstext ohne Linien: 'keine Tabelle erkannt' muss sichtbar sein."""
    ops = _column_text_ops(72, 720, NO_TABLE_TEXT)
    path.write_bytes(_build_pdf([ops]))


def create_scan_pdf(path: Path) -> None:
    """Leere Seite ohne Text-Layer (Scan-Simulation): Status 'no-textlayer'."""
    path.write_bytes(_build_pdf([[]]))


if __name__ == "__main__":
    create_results_table_pdf(OUT / "results_table.pdf")
    create_merged_header_pdf(OUT / "merged_header.pdf")
    create_two_column_layout_pdf(OUT / "two_column_layout.pdf")
    create_no_table_pdf(OUT / "no_table.pdf")
    create_scan_pdf(OUT / "scan_no_textlayer.pdf")
    print(f"Fixtures erstellt in {OUT}")
