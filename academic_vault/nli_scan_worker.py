"""Abgekoppelter Worker fuer den NLI-Zitatscan (Issue #717).

Aufgerufen wird dieser Worker von ``hooks/nli-quote-scan.mjs`` als
**detachter** Subprozess nach einem Kapitel-Write. Der Hook wartet nicht auf
ihn: er startet ihn und kehrt sofort zurueck. Ein synchroner Scan wuerde beim
ersten Kapitel-Write jeder Installation den Modell-Download in den
Hook-Timeout laufen lassen -- AC1 ("ohne den Write zu verzoegern") und AC5
("die Sitzung laeuft normal weiter") sind nur ohne Inline-Modellladung beide
erfuellbar.

Ergebnisse gehen deshalb nicht ueber stdout zurueck, sondern in ein
**Spool-Verzeichnis**: eine JSON-Datei je Kapitel. Derselbe Hook liest dieses
Verzeichnis beim naechsten Aufruf leer und meldet die Fundstellen.

Datensatzformat (``schema: 1``)::

    {"schema": 1, "chapter": "<pfad>", "created_at": <epoch>,
     "scanned": <int>, "findings": [{...}]}
    {"schema": 1, "chapter": "<pfad>", "created_at": <epoch>,
     "scanned": 0, "findings": [], "error": "<meldung>"}

Jeder Befund traegt Zitat, Kurzbeleg und Kapitelsatz (AC3) -- lesbar, ohne im
Vault nachzuschlagen.

Aufruf::

    python -m academic_vault.nli_scan_worker <vault.db> <kapitel-datei> <spool-dir>

Der Worker beendet sich IMMER mit 0. Ein Fehler wird zum ``error``-Datensatz,
nicht zum Traceback in der Sitzung des Nutzers (AC5).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .nli_prefilter import (
    NliScorer,
    resolve_nli_prefilter_enabled,
    run_batch_prefilter,
    scan_chapter_quotes,
)

#: Schema-Version der Spool-Datensaetze. Der Hook verwirft alles Fremde,
#: statt es zu raten.
SCHEMA_VERSION = 1

#: Laengenbegrenzung fuer die im Befund mitgefuehrten Textfelder. Der Spool
#: liegt auf der Platte des Nutzers; ganze Absaetze muessen dort nicht liegen.
MAX_FIELD_CHARS = 400


def default_spool_dir() -> Path:
    """Ablageort der Befunde (Env-Override ``ACADEMIC_NLI_SCAN_SPOOL``)."""
    env = os.environ.get("ACADEMIC_NLI_SCAN_SPOOL")
    if env:
        return Path(env)
    return Path.home() / ".academic-research" / "nli-scan-spool"


def build_default_scorer() -> NliScorer:
    """Produktiver Scorer. Eigene Funktion, damit Tests sie ersetzen koennen,
    ohne ein Modell zu laden."""
    from .nli_prefilter import MDebertaScorer

    return MDebertaScorer()


def _shorten(value: str | None, limit: int = MAX_FIELD_CHARS) -> str:
    flat = " ".join(str(value or "").split())
    return flat if len(flat) <= limit else f"{flat[: limit - 1]}…"


def paper_reference(db_path: str, paper_id: str) -> str:
    """Kurzbeleg "Nachname (Jahr): Titel" aus dem CSL-JSON des Papers.

    AC3 verlangt, dass eine Fundstelle ohne Nachschlagen im Vault
    nachvollziehbar ist -- eine blosse ``paper_id`` reicht dafuer nicht. Ist
    das Paper nicht auffindbar oder das CSL-JSON unbrauchbar, bleibt die
    ``paper_id`` als Beleg stehen (kein Raten).
    """
    try:
        from .server import get_paper

        record = get_paper(db_path, paper_id)
    except Exception:
        record = None
    if not record:
        return paper_id

    try:
        csl = json.loads(record.get("csl_json") or "{}")
    except (ValueError, TypeError):
        csl = {}
    if not isinstance(csl, dict):
        csl = {}

    authors = csl.get("author")
    family = ""
    if isinstance(authors, list) and authors:
        first = authors[0]
        if isinstance(first, dict):
            family = str(first.get("family") or first.get("literal") or "")
    year = ""
    issued = csl.get("issued")
    if isinstance(issued, dict):
        parts = issued.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            year = str(parts[0][0])
    title = str(csl.get("title") or "")

    head = family or paper_id
    if year:
        head = f"{head} ({year})"
    return f"{head}: {_shorten(title, 120)}" if title else head


def _spool_name(chapter_path: Path) -> str:
    """Ein Dateiname je Kapitelpfad: der letzte Lauf gewinnt, statt dass sich
    Befunde derselben Datei im Spool stapeln."""
    digest = hashlib.sha256(str(chapter_path).encode("utf-8")).hexdigest()[:16]
    return f"{chapter_path.stem}-{digest}.json"


def _write_record(spool_dir: Path, chapter_path: Path, record: dict[str, Any]) -> Path:
    spool_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(spool_dir, 0o700)
    target = spool_dir / _spool_name(chapter_path)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(target)
    return target


def scan_chapter(
    chapter_path: str | Path,
    db_path: str,
    scorer: NliScorer | None = None,
    enabled: bool | None = None,
    config_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Scannt ein Kapitel und gibt den Ergebnis-Datensatz zurueck.

    ``None`` bedeutet: es gab nichts zu tun -- Scan abgeschaltet, Kapitel
    nicht lesbar, oder kein einziges im Vault belegtes Zitat im Text.

    Der Datensatz haelt ``scanned`` (Zahl der BEWERTETEN Zitate) und
    ``findings`` (Zahl der GEMELDETEN) getrennt: im Detektor-Modus ist
    ``scanned`` immer die volle Zitatzahl des Kapitels, auch wenn nichts
    gemeldet wird (AC2).
    """
    chapter = Path(chapter_path)

    if not resolve_nli_prefilter_enabled(enabled, config_path):
        return None

    try:
        content = chapter.read_text(encoding="utf-8")
    except OSError:
        return None

    record: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "chapter": str(chapter),
        "created_at": int(time.time()),
        "scanned": 0,
        "findings": [],
    }

    try:
        items = scan_chapter_quotes(content, db_path)
    except Exception as err:  # Vault nicht lesbar/kaputt -> sichtbar melden
        record["error"] = f"Vault-Zugriff fehlgeschlagen: {err}"
        return record

    if not items:
        return None

    try:
        active_scorer = scorer if scorer is not None else build_default_scorer()
        result = run_batch_prefilter(items, scorer=active_scorer, enabled=True)
    except Exception as err:
        # AC5: fehlendes/kaputtes Modell -> Fehler-Datensatz, kein Traceback.
        record["error"] = f"NLI-Modell nicht verfuegbar: {err}"
        return record

    by_id = {item["quote_id"]: item for item in items}
    record["scanned"] = len(items)
    record["findings"] = [
        {
            "quote_id": hit["quote_id"],
            "paper_id": hit["paper_id"],
            "paper_ref": paper_reference(db_path, hit["paper_id"]),
            "verbatim": _shorten(by_id.get(hit["quote_id"], {}).get("verbatim")),
            "chapter_claim": _shorten(hit["chapter_claim"]),
            "raw_score": float(hit["raw_score"]),
        }
        for hit in result["suspicious"]
    ]
    return record


def scan_to_spool(
    chapter_path: str | Path,
    db_path: str,
    spool_dir: str | Path,
    scorer: NliScorer | None = None,
    enabled: bool | None = None,
    config_path: str | Path | None = None,
) -> Path | None:
    """Scannt ein Kapitel und legt das Ergebnis im Spool ab.

    Geschrieben wird NUR, wenn es etwas zu melden gibt: Fundstellen oder ein
    Fehler. Ein Kapitel, dessen Zitate alle als treu bewertet wurden, ist
    gescannt (siehe :func:`scan_chapter`) und hinterlaesst dennoch keinen
    Eintrag -- der Nutzer soll nur Auffaelliges zu sehen bekommen.

    Rueckgabe: der geschriebene Pfad, sonst ``None``.
    """
    record = scan_chapter(chapter_path, db_path, scorer, enabled, config_path)
    if record is None:
        return None
    if not record["findings"] and "error" not in record:
        return None
    return _write_record(Path(spool_dir), Path(chapter_path), record)


def main(argv: list[str] | None = None) -> int:
    """CLI-Einstieg. Gibt IMMER 0 zurueck (AC5)."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        sys.stderr.write(
            "[NLI-Zitatscan] Aufruf: python -m academic_vault.nli_scan_worker "
            "<vault.db> <kapitel-datei> [spool-dir]\n"
        )
        return 0

    db_path, chapter_path = args[0], args[1]
    spool = Path(args[2]) if len(args) > 2 else default_spool_dir()
    try:
        scan_to_spool(chapter_path, db_path, spool)
    except Exception as err:  # letzte Sicherung: nie ein Traceback nach aussen
        sys.stderr.write(f"[NLI-Zitatscan] Lauf abgebrochen: {err}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI-Einstieg
    raise SystemExit(main())
