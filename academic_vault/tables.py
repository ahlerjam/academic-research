"""Strukturerhaltende Tabellenextraktion aus PDFs (Issue #630, gehaertet in #847).

Der Volltextpfad des Vaults kollabiert jede Whitespace-Folge zu einem
einzelnen Leerzeichen. Fuer den FTS5-Index ist das richtig — fuer eine
Ergebnistabelle vernichtet es genau die Information, aus der Effektstaerken,
Stichprobengroessen und Konfidenzintervalle ablesbar waeren. Dieses Modul
laeuft deshalb **neben** dem Volltextpfad, nicht hindurch: es importiert das
Volltextmodul nicht, nutzt dessen Whitespace-Normalisierung nicht und
schreibt nichts in den FTS5-Index. Der Importguard dazu steht in
``tests/test_issue_630_table_extraction.py``.

Backend ist **pdfplumber** — seit Issue #723 Pflicht-Dependency, keine
optionale Installation mehr. Fehlt das Paket in einer realen Installation
dennoch (z. B. manuell entfernt), ist das Ergebnis ein sichtbarer Status mit
Installationsanweisung statt einer Exception; der bestehende Volltextpfad
laeuft unveraendert weiter. Die Backend-Abwaegung gegen camelot, Docling und
Marker steht in ``docs/reference/vault.md``, Abschnitt „Tabellenextraktion".

Das Statusmodell kennt vier Ausgaenge — „nichts gefunden" ist nie eine leere
Liste ohne Begruendung:

  * ``ok``               mindestens eine Tabelle erkannt
  * ``no-tables``        Text-Layer vorhanden, aber kein Tabellengitter
  * ``no-textlayer``     keine Zeichen im PDF (Scan) — erst OCR, dann wieder her
  * ``backend-missing``  pdfplumber nicht installiert

Seit Issue #847 traegt jede einzelne Tabelle zusaetzlich ein
``detection``/``confidence``-Paar statt eines einzigen PDF-weiten Status:

  * ``detection="lines"``, ``confidence="high"``
    pdfplumber hat gezeichnete Linien gefunden (Default-Pfad, unveraendert
    gegenueber #630).
  * ``detection="text-strategy"``, ``confidence="low"``
    Fallback nur, wenn eine Seite ueber Linien NICHTS liefert: pdfplumber
    erkennt Spalten dann ueber Textausrichtung (``vertical_strategy="text"``,
    ``horizontal_strategy="text"``). Heuristisch und deshalb nie
    gleichwertig zum Linien-Pfad — ein Kandidat wird verworfen (die Seite
    bleibt bei ``no-tables``), wenn eine Zelle mehr als zwei Woerter traegt
    (typisches Merkmal von Fliesstext, nicht von Tabellenzellen) oder wenn
    nach Abzug leerer Zwischenzeilen weniger als zwei Datenzeilen oder
    weniger als zwei Spalten uebrig bleiben.

Eine verbundene Kopfzelle (Spannweite ueber mehrere Spalten) liefert
weiterhin keinen erratenen Wert fuer die geschluckte Position, aber nicht
mehr stillschweigend gar nichts: die Zelle taucht in ``cells`` mit
``value=None`` und ``merged_into=<Spalte der breiten Nachbarzelle>`` auf statt
komplett zu fehlen.
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
    "Nachinstallation: pip install 'pdfplumber>=0.11' (bzw. erneut uv sync)."
)

#: Obergrenze pro Paper. Ein Anhang mit hunderten Messtabellen wuerde sonst in
#: jedem Snapshot-Export und jedem Ingest-Lauf mitgeschleppt.
MAX_TABLES_PER_PDF = 200

DETECTION_LINES = "lines"
DETECTION_TEXT_STRATEGY = "text-strategy"
CONFIDENCE_HIGH = "high"
CONFIDENCE_LOW = "low"

#: pdfplumber-``table_settings`` fuer den Fallback ohne Gitterlinien (#847).
#: Verifiziert gegen die pdfplumber-Doku (context7 ``/jsvine/pdfplumber``):
#: ``vertical_strategy``/``horizontal_strategy`` ∈ {"lines", "lines_strict",
#: "text", "explicit"}. Bewusst die pdfplumber-Defaults fuer alle uebrigen
#: Toleranzen -- ein enger getunter Wert liess in Versuchen zwar die
#: Leerzeilen zwischen Textzeilen verschwinden, unterdrueckte aber auch
#: echte Tabellen (Zeilenabstand-abhaengig, keine stabile Grundlage).
TEXT_STRATEGY_SETTINGS: dict[str, str] = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
}

#: Zellen mit mehr Woertern als diesem Schwellenwert gelten als Fliesstext,
#: nicht als Tabellenzelle -- der Text-Strategie-Kandidat wird verworfen statt
#: Prosa als Tabelle misszudeuten (Ehrlichkeitsgebot, siehe Modul-Docstring).
_TEXT_STRATEGY_MAX_WORDS_PER_CELL = 2


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


def _cells_of_table(
    table: Any,
    rows: list[list[str | None]],
    row_indices: list[int] | None = None,
) -> list[dict]:
    """Verbindet die Textmatrix mit den Bounding-Boxen der Zellen.

    ``Table.rows`` liefert je Zeile eine Liste von Bounding-Boxen, in der
    ``None`` fuer eine Position steht, die von einer verbundenen Nachbarzelle
    geschluckt wurde (z. B. eine ueber zwei Spalten laufende Kopfzelle). Eine
    solche Position wird NICHT stillschweigend ausgelassen (#847): sie taucht
    mit ``value=None`` und ``merged_into=<Spalte der breiten Nachbarzelle>``
    auf, sofern in derselben Zeile links davon bereits eine echte Zelle stand
    -- ein expliziter Hinweis statt eines stummen Luecken.

    Args:
        table: pdfplumber-``Table``.
        rows: Textmatrix, ggf. bereits um leere Zwischenzeilen bereinigt
            (Text-Strategie-Pfad).
        row_indices: Ordnet jede Position in ``rows`` auf den zugehoerigen
            Index in ``table.rows`` ab -- Identitaet, wenn ``None`` (Default,
            Linien-Pfad ohne Zeilenfilterung).
    """
    mapping = row_indices if row_indices is not None else list(range(len(rows)))
    cells: list[dict] = []
    for new_row_index, old_row_index in enumerate(mapping):
        if new_row_index >= len(rows) or old_row_index >= len(
            table.rows
        ):  # pragma: no cover - Defensive gegen Backend-Drift
            break
        row = table.rows[old_row_index]
        values = rows[new_row_index]
        last_real_col: int | None = None
        for col_index, bbox in enumerate(row.cells):
            if bbox is None:
                if last_real_col is not None:
                    cells.append(
                        {
                            "row": new_row_index,
                            "col": col_index,
                            "value": None,
                            "bbox": None,
                            "merged_into": last_real_col,
                        }
                    )
                continue
            last_real_col = col_index
            value = values[col_index] if col_index < len(values) else None
            cells.append(
                {
                    "row": new_row_index,
                    "col": col_index,
                    "value": value,
                    "bbox": [float(coordinate) for coordinate in bbox],
                }
            )
    return cells


def _is_blank_row(row: list[str | None]) -> bool:
    return all(value is None or value == "" for value in row)


def _has_overlong_cells(rows: list[list[str | None]]) -> bool:
    """Prueft, ob eine Zelle mehr Woerter traegt, als eine Tabellenzelle plausibel hat.

    Diskriminator gegen Fliesstext, der bei der Text-Strategie faelschlich als
    Spaltenraster erkannt wird: Tabellenzellen sind kurz (Kennzahlen, Labels),
    Prosa-Fragmente sind es nicht. Schwellenwert und Begruendung siehe
    ``_TEXT_STRATEGY_MAX_WORDS_PER_CELL``.
    """
    for row in rows:
        for value in row:
            if value and len(value.split()) > _TEXT_STRATEGY_MAX_WORDS_PER_CELL:
                return True
    return False


def _text_strategy_candidate(table: Any) -> tuple[list[list[str | None]], list[int]] | None:
    """Bereitet einen Text-Strategie-Tabellenkandidaten auf oder verwirft ihn.

    Returns:
        ``(rows_ohne_leerzeilen, row_indices)`` bei einem plausiblen Kandidaten,
        sonst ``None`` -- dann bleibt die Seite bei ``no-tables``, statt Prosa
        als Tabelle zu melden.
    """
    raw_rows = table.extract()
    normalized = [[normalize_cell_value(value) for value in row] for row in raw_rows]
    row_indices = [index for index, row in enumerate(normalized) if not _is_blank_row(row)]
    if len(row_indices) < 2:
        return None
    kept_rows = [normalized[index] for index in row_indices]
    n_cols = max((len(row) for row in kept_rows), default=0)
    if n_cols < 2:
        return None
    if _has_overlong_cells(kept_rows):
        return None
    return kept_rows, row_indices


def extract_tables(pdf_path: str, backend: str = "auto") -> dict:
    """Liest die Tabellen eines PDFs strukturerhaltend aus.

    Args:
        pdf_path: Pfad zur PDF-Datei.
        backend: ``"auto"`` oder ``"pdfplumber"`` (derzeit dasselbe).

    Returns:
        ``{"status", "message", "backend", "tables"}``. Jede Tabelle ist
        ``{"page", "table_index", "n_rows", "n_cols", "bbox", "rows", "cells",
        "detection", "confidence"}`` mit 1-basierter ``page``, 0-basiertem
        ``table_index`` und ``rows`` als Textmatrix (``None`` = von einer
        verbundenen Zelle geschluckte Position). ``cells`` traegt zusaetzlich
        je Zelle die Bounding-Box, und -- fuer eine geschluckte Position mit
        einer echten Nachbarzelle links davon -- ``merged_into`` statt einer
        Bounding-Box. ``detection``/``confidence`` (Issue #847) sind
        ``"lines"``/``"high"`` oder ``"text-strategy"``/``"low"``, siehe
        Modul-Docstring.

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

            lines_tables = list(page.find_tables())
            if lines_tables:
                page_tables: list[tuple[Any, list[list[str | None]], list[int]]] = []
                for table in lines_tables:
                    raw_rows = table.extract()
                    rows = [[normalize_cell_value(value) for value in row] for row in raw_rows]
                    page_tables.append((table, rows, list(range(len(rows)))))
                detection, confidence = DETECTION_LINES, CONFIDENCE_HIGH
            else:
                # Fallback nur, wenn der Linien-Pfad auf dieser Seite NICHTS
                # liefert (AC2-Nebenbedingung: der Linien-Pfad fuer einfache
                # Tabellen darf dadurch nicht veraendert werden).
                page_tables = []
                for table in page.find_tables(table_settings=TEXT_STRATEGY_SETTINGS):
                    candidate = _text_strategy_candidate(table)
                    if candidate is None:
                        continue
                    rows, row_indices = candidate
                    page_tables.append((table, rows, row_indices))
                detection, confidence = DETECTION_TEXT_STRATEGY, CONFIDENCE_LOW

            for table_index, (table, rows, row_indices) in enumerate(page_tables):
                if len(extracted) >= MAX_TABLES_PER_PDF:
                    logger.info(
                        "Tabellenextraktion bei %d Tabellen gekappt (%s)",
                        MAX_TABLES_PER_PDF,
                        pdf_path,
                    )
                    break
                cells = _cells_of_table(table, rows, row_indices)
                extracted.append(
                    {
                        "page": page_number,
                        "table_index": table_index,
                        "n_rows": len(rows),
                        "n_cols": max((len(row) for row in rows), default=0),
                        "bbox": [float(coordinate) for coordinate in table.bbox],
                        "rows": rows,
                        "cells": cells,
                        "detection": detection,
                        "confidence": confidence,
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
