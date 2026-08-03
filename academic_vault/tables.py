"""Strukturerhaltende Tabellenextraktion aus PDFs (Issue #630).

Der Volltextpfad des Vaults kollabiert jede Whitespace-Folge zu einem
einzelnen Leerzeichen. Fuer den FTS5-Index ist das richtig — fuer eine
Ergebnistabelle vernichtet es genau die Information, aus der Effektstaerken,
Stichprobengroessen und Konfidenzintervalle ablesbar waeren. Dieses Modul
laeuft deshalb **neben** dem Volltextpfad, nicht hindurch: es importiert das
Volltextmodul nicht, nutzt dessen Whitespace-Normalisierung nicht und
schreibt nichts in den FTS5-Index. Der Importguard dazu steht in
``tests/test_issue_630_table_extraction.py``.

Backend ist **pdfplumber** — ein optionales Extra (``uv sync --extra tables``),
keine Pflichtabhaengigkeit. Fehlt es, ist das Ergebnis ein sichtbarer Status
mit Installationsanweisung; der bestehende Volltextpfad laeuft unveraendert
weiter. Die Backend-Abwaegung gegen camelot, Docling und Marker steht in
``docs/reference/vault.md``, Abschnitt „Tabellenextraktion".

Das Statusmodell kennt vier Ausgaenge — „nichts gefunden" ist nie eine leere
Liste ohne Begruendung:

  * ``ok``               mindestens eine Tabelle erkannt
  * ``no-tables``        Text-Layer vorhanden, aber kein Tabellengitter
  * ``no-textlayer``     keine Zeichen im PDF (Scan) — erst OCR, dann wieder her
  * ``backend-missing``  pdfplumber nicht installiert
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_NO_TABLES = "no-tables"
STATUS_NO_TEXTLAYER = "no-textlayer"
STATUS_BACKEND_MISSING = "backend-missing"

#: Name des einzigen derzeit unterstuetzten Backends.
BACKEND_PDFPLUMBER = "pdfplumber"
BACKENDS = ("auto", BACKEND_PDFPLUMBER)

#: Installationsanweisung, die im ``backend-missing``-Fall sichtbar wird.
INSTALL_HINT = (
    "Tabellen-Backend 'pdfplumber' ist nicht installiert -- es werden keine "
    "Tabellen extrahiert. Der PDF-Volltextpfad laeuft davon unberuehrt weiter. "
    "Nachinstallation: uv sync --extra tables (bzw. pip install 'pdfplumber>=0.11')."
)

#: Obergrenze pro Paper. Ein Anhang mit hunderten Messtabellen wuerde sonst in
#: jedem Snapshot-Export und jedem Ingest-Lauf mitgeschleppt.
MAX_TABLES_PER_PDF = 200


def _import_pdfplumber() -> Any:
    """Laedt pdfplumber lazy.

    Eigene Funktion, damit Tests den Fehlerfall gezielt herstellen koennen
    (``monkeypatch.setattr(tables, "_import_pdfplumber", ...)``), ohne am
    Import-System zu drehen.
    """
    import pdfplumber

    return pdfplumber


def normalize_cell_value(raw: str | None) -> str | None:
    """Normalisiert einen einzelnen Zellwert — bewusst schwaecher als der Volltext.

    Innerhalb *einer* Zelle sind Zeilenumbrueche Layout-Rauschen und werden zu
    einem Leerzeichen; die Grenze zwischen zwei Zellen bleibt dagegen unangetastet,
    weil sie in der Datenstruktur steckt und nicht im Text.

    ``None`` bleibt ``None``: eine Zelle, die pdfplumber nicht aufloesen konnte
    (etwa unter einer verbundenen Kopfzelle), ist etwas anderes als eine leere
    Zelle und darf nicht zu ``""`` verwischt werden.
    """
    if raw is None:
        return None
    return " ".join(raw.split())


def _result(
    status: str,
    message: str,
    backend: str = "",
    tables: list[dict] | None = None,
) -> dict:
    return {
        "status": status,
        "message": message,
        "backend": backend,
        "tables": tables if tables is not None else [],
    }


def _cells_of_table(table: Any, rows: list[list[str | None]]) -> list[dict]:
    """Verbindet die Textmatrix mit den Bounding-Boxen der Zellen.

    ``Table.rows`` liefert je Zeile eine Liste von Bounding-Boxen, in der
    ``None`` fuer eine Position steht, die von einer verbundenen Nachbarzelle
    geschluckt wurde. Genau diese Positionen tauchen hier nicht als Zelle auf —
    ein Beleg auf eine Zelle ohne Koordinaten waere keiner.
    """
    cells: list[dict] = []
    for row_index, row in enumerate(table.rows):
        if row_index >= len(rows):  # pragma: no cover - Defensive gegen Backend-Drift
            break
        values = rows[row_index]
        for col_index, bbox in enumerate(row.cells):
            if bbox is None:
                continue
            value = values[col_index] if col_index < len(values) else None
            cells.append(
                {
                    "row": row_index,
                    "col": col_index,
                    "value": value,
                    "bbox": [float(coordinate) for coordinate in bbox],
                }
            )
    return cells


def extract_tables(pdf_path: str, backend: str = "auto") -> dict:
    """Liest die Tabellen eines PDFs strukturerhaltend aus.

    Args:
        pdf_path: Pfad zur PDF-Datei.
        backend: ``"auto"`` oder ``"pdfplumber"`` (derzeit dasselbe).

    Returns:
        ``{"status", "message", "backend", "tables"}``. Jede Tabelle ist
        ``{"page", "table_index", "n_rows", "n_cols", "bbox", "rows", "cells"}``
        mit 1-basierter ``page``, 0-basiertem ``table_index`` und ``rows`` als
        Textmatrix (``None`` = von einer verbundenen Zelle geschluckte Position).
        ``cells`` traegt zusaetzlich je Zelle die Bounding-Box.

    Raises:
        FileNotFoundError: Die PDF-Datei existiert nicht.
        ValueError: Unbekanntes ``backend``.
    """
    if backend not in BACKENDS:
        raise ValueError(f"Unbekanntes Backend '{backend}' -- erlaubt: {list(BACKENDS)}")
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"PDF nicht gefunden: {pdf_path}")

    try:
        pdfplumber = _import_pdfplumber()
    except ImportError:
        logger.info("pdfplumber nicht verfuegbar -- keine Tabellenextraktion fuer %s", pdf_path)
        return _result(STATUS_BACKEND_MISSING, INSTALL_HINT)

    extracted: list[dict] = []
    has_chars = False

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            if page.chars:
                has_chars = True
            for table_index, table in enumerate(page.find_tables()):
                if len(extracted) >= MAX_TABLES_PER_PDF:
                    logger.info(
                        "Tabellenextraktion bei %d Tabellen gekappt (%s)",
                        MAX_TABLES_PER_PDF,
                        pdf_path,
                    )
                    break
                raw_rows = table.extract()
                rows = [[normalize_cell_value(value) for value in row] for row in raw_rows]
                cells = _cells_of_table(table, rows)
                extracted.append(
                    {
                        "page": page_number,
                        "table_index": table_index,
                        "n_rows": len(rows),
                        "n_cols": max((len(row) for row in rows), default=0),
                        "bbox": [float(coordinate) for coordinate in table.bbox],
                        "rows": rows,
                        "cells": cells,
                    }
                )

    if extracted:
        return _result(
            STATUS_OK,
            f"{len(extracted)} Tabelle(n) erkannt.",
            backend=BACKEND_PDFPLUMBER,
            tables=extracted,
        )
    if not has_chars:
        return _result(
            STATUS_NO_TEXTLAYER,
            "Kein Text-Layer im PDF (Scan) -- ohne OCR ist keine Tabelle auslesbar.",
            backend=BACKEND_PDFPLUMBER,
        )
    return _result(
        STATUS_NO_TABLES,
        "Keine Tabelle erkannt: das PDF hat einen Text-Layer, aber kein "
        "auswertbares Tabellengitter.",
        backend=BACKEND_PDFPLUMBER,
    )
