#!/usr/bin/env python3
"""Mechanischer Vorfilter vor dem Modelldurchlauf (Issue #892).

Vor #892 kostete jeder Treffer einen Modellaufruf: 1000 Treffer waren 100
Batches à zehn Arbeiten, auch dort, wo ein Blick auf das Publikationsjahr
gereicht hätte. Dieses Modul entscheidet vorab, was die Ein-/Ausschluss-
kriterien **eindeutig** entscheiden — Zeitraum, Sprache, Publikationstyp —
und legt dem Modell nur die Grenzfälle vor.

Drei Grundsätze:

1. **Fail-open.** Fehlt der Filterblock, ist der Lauf ein No-Op und verhält
   sich exakt wie vor #892. Fehlt einem Treffer das geprüfte Metadatum, wird
   er **nicht** ausgeschlossen, sondern dem Modell vorgelegt. Unwissen ist
   kein Ausschlussgrund.
2. **Allowlist statt Heuristik.** Es gibt nur Bereichs- und Allowlist-Regeln
   auf tatsächlich vorhandenen Metadaten. Kein Titel-Matching, keine
   Relevanzabschätzung — die Relevanz bleibt beim Modell.
3. **Protokollpflicht.** Jeder mechanische Ausschluss geht als Ledger-Zeile
   (``decided_by="rule"``) und mit Kriteriumsnamen im Grund nach
   ``excluded_sources``. Der PRISMA-Fluss ergibt sich danach vollständig aus
   dem Protokoll; weil ``pending()`` protokollierte IDs überspringt, sieht das
   Modell diese Treffer nie.

Der Filterblock steht als eingezäunter ``screening_filters``-Abschnitt in der
Section ``### Ein-/Ausschlusskriterien`` von ``./academic_context.md``
(geschrieben vom ``preregistration``-Skill):

```screening_filters
year_min: 2015
year_max: 2026
languages: [de, en]
publication_types: [journal-article, proceedings-article]
```

CLI:
  python screening_prefilter.py prefilter --session-dir DIR --papers ranked.json \
      --context ./academic_context.md [--db-path vault.db] [--no-prefilter]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any

from screening_ledger import (
    DECIDED_BY_RULE,
    STAGE_SCREENING,
    record_decision,
)

# ---------------------------------------------------------------------------
# Verträge
# ---------------------------------------------------------------------------

CRITERIA_HEADING = "### Ein-/Ausschlusskriterien"
FILTER_BLOCK_LANG = "screening_filters"

#: Kriteriumsnamen, wie sie im Ausschlussgrund und im Report auftauchen.
CRITERION_PERIOD = "Zeitraum"
CRITERION_LANGUAGE = "Sprache"
CRITERION_PUBLICATION_TYPE = "Publikationstyp"

#: Bekannte Filterschlüssel. Unbekannte werden ignoriert (fail-open) statt
#: einen Lauf an einem Tippfehler scheitern zu lassen.
KNOWN_FILTER_KEYS = ("year_min", "year_max", "languages", "publication_types")

#: Batchgröße des ``relevance-scorer``-Durchlaufs (``commands/search.md``).
BATCH_SIZE = 10

PREFILTER_ENV = "ACADEMIC_RESEARCH_SCREENING_PREFILTER"
DEFAULT_PREFILTER = True
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "parallel_agents.json"

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}

TO_SCREEN_FILENAME = "to_screen.json"
REPORT_FILENAME = "prefilter_report.json"


def resolve_prefilter(
    explicit: bool | None = None,
    config_path: str | Path | None = None,
) -> bool:
    """Schalter für den mechanischen Vorfilter (#892).

    Vorrang: Argument > Env ``ACADEMIC_RESEARCH_SCREENING_PREFILTER`` >
    Config-Datei > Default ``True``. Der Default ist wirkungslos, solange kein
    Filterblock existiert — er schaltet also nichts ein, was nicht ausdrücklich
    in den Kriterien steht.
    """
    if explicit is not None:
        return bool(explicit)

    raw_env = os.environ.get(PREFILTER_ENV)
    if raw_env is not None:
        stripped = raw_env.strip().lower()
        if stripped in _TRUTHY:
            return True
        if stripped in _FALSY:
            return False

    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data["screening_prefilter"]
    except (OSError, ValueError, KeyError, TypeError):
        value = None
    if isinstance(value, bool):
        return value

    return DEFAULT_PREFILTER


# ---------------------------------------------------------------------------
# Filterblock
# ---------------------------------------------------------------------------

_FENCE = re.compile(
    r"^```" + FILTER_BLOCK_LANG + r"[ \t]*\n(?P<body>.*?)^```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)


def _criteria_section(text: str) -> str:
    """Der Abschnitt ``### Ein-/Ausschlusskriterien`` bis zur nächsten Überschrift."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == CRITERIA_HEADING)
    except StopIteration:
        return ""
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(r"^#{1,3} ", lines[i])),
        len(lines),
    )
    return "\n".join(lines[start:end]) + "\n"


def load_filters(text: str) -> dict[str, Any]:
    """Liest den ``screening_filters``-Block aus dem Kriterien-Abschnitt.

    Rückgabe ist ein Dict mit den bekannten Schlüsseln; alles andere fällt
    weg. Fehlt der Abschnitt, fehlt der Block oder ist er nicht parsebar, ist
    das Ergebnis ``{}`` — und ``apply_filters`` damit ein No-Op (fail-open).

    Ein Block **außerhalb** des Kriterien-Abschnitts zählt nicht: die
    Kriterien haben genau eine Fundstelle, sonst wäre nicht mehr erkennbar,
    woran ein Ausschluss hängt.
    """
    import yaml

    section = _criteria_section(text)
    match = _FENCE.search(section)
    if match is None:
        return {}
    try:
        data = yaml.safe_load(match.group("body"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: data[key] for key in KNOWN_FILTER_KEYS if data.get(key) is not None}


def load_filters_from_file(path: str | Path | None) -> dict[str, Any]:
    """Wie :func:`load_filters`, mit Datei-Lesen davor. Fehlt die Datei: ``{}``."""
    if path is None:
        return {}
    file_path = Path(path)
    if not file_path.is_file():
        return {}
    return load_filters(file_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# ID-Ableitung
# ---------------------------------------------------------------------------

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize(value: str) -> str:
    """Die ``paper_id``-Schreibweise aus ``commands/fetch.md``, Schritt 2."""
    return _UNSAFE.sub("_", value.strip().lower())[:80]


def derive_paper_id(paper: dict[str, Any]) -> str:
    """Die ``paper_id`` eines Treffers — eine Ableitung, überall dieselbe.

    Vorrang: ausdrückliche ``paper_id`` > DOI > URL > Titel, jeweils in der
    Schreibweise aus ``commands/fetch.md`` (Nicht-Alphanumerisches außer
    ``._-`` durch ``_``, klein, max. 80 Zeichen).

    Das ist keine Kosmetik: ``excluded_sources.paper_id`` ist ein
    Primärschlüssel ohne Fremdschlüssel. Weicht die hier vergebene ID von der
    späteren Vault-``paper_id`` ab, ist das Ausschlussprotokoll nicht mehr
    zuordenbar.

    Raises:
        ValueError: wenn keines der vier Felder etwas hergibt — ein Treffer
            ohne jede Kennung lässt sich nicht protokollieren und darf
            deswegen auch nicht still verschwinden.
    """
    explicit = str(paper.get("paper_id") or "").strip()
    if explicit:
        return explicit
    for field in ("doi", "url", "title"):
        raw = str(paper.get(field) or "").strip()
        if raw:
            candidate = _sanitize(raw)
            if candidate:
                return candidate
    raise ValueError(f"Treffer ohne paper_id/doi/url/title, nicht protokollierbar: {paper!r}")


# ---------------------------------------------------------------------------
# Regeln
# ---------------------------------------------------------------------------


def _check_period(paper: dict[str, Any], filters: dict[str, Any]) -> str | None:
    year = paper.get("year")
    if year is None:
        return None
    try:
        year = int(year)
    except (TypeError, ValueError):
        return None
    year_min = filters.get("year_min")
    if year_min is not None and year < int(year_min):
        return f"Publikationsjahr {year} liegt vor {int(year_min)}"
    year_max = filters.get("year_max")
    if year_max is not None and year > int(year_max):
        return f"Publikationsjahr {year} liegt nach {int(year_max)}"
    return None


def _check_allowlist(value: Any, allowed: Any, label: str) -> str | None:
    if value is None or allowed is None:
        return None
    if not isinstance(allowed, (list, tuple, set)):
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    permitted = {str(item).strip().lower() for item in allowed}
    if normalized in permitted:
        return None
    return f"{label} '{value}' steht nicht in {sorted(permitted)}"


def _rule_violation(paper: dict[str, Any], filters: dict[str, Any]) -> tuple[str, str] | None:
    """Erstes verletztes Kriterium als ``(criterion, detail)``, sonst ``None``."""
    detail = _check_period(paper, filters)
    if detail:
        return CRITERION_PERIOD, detail
    detail = _check_allowlist(paper.get("language"), filters.get("languages"), "Sprache")
    if detail:
        return CRITERION_LANGUAGE, detail
    detail = _check_allowlist(
        paper.get("publication_type"), filters.get("publication_types"), "Publikationstyp"
    )
    if detail:
        return CRITERION_PUBLICATION_TYPE, detail
    return None


def apply_filters(
    papers: list[dict[str, Any]],
    filters: dict[str, Any],
    current_year: int | None = None,
) -> dict[str, Any]:
    """Teilt die Treffer in Modellmenge und mechanische Ausschlüsse.

    Rückgabe:

    ``to_screen``
        die verbleibenden Treffer, absteigend nach dem 4D-Vorranking
        (``scoring.prescore``) sortiert, Tie-Break ``paper_id`` — bei knappem
        Budget wird das Aussichtsreichste zuerst bewertet.
    ``excluded``
        je Ausschluss ``{"paper_id", "criterion", "reason"}``. Der
        Kriteriumsname steht im Grund, damit im Vault nachlesbar bleibt,
        **woran** der Ausschluss hing.
    ``report``
        die Zahlen vor/nach inklusive Aufschlüsselung je Kriterium.

    Ohne Filter (``{}``) bleibt die Reihenfolge der Eingabe unangetastet: ein
    Lauf ohne Kriterienblock verhält sich exakt wie vor #892.
    """
    filters = filters or {}
    if not filters:
        return {
            "to_screen": list(papers),
            "excluded": [],
            "report": _report(len(papers), len(papers), {}, filters_applied=False),
        }

    kept: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    by_criterion: dict[str, int] = {}

    for paper in papers:
        violation = _rule_violation(paper, filters)
        if violation is None:
            kept.append(paper)
            continue
        criterion, detail = violation
        excluded.append(
            {
                "paper_id": derive_paper_id(paper),
                "criterion": criterion,
                "reason": f"{criterion}: {detail}",
            }
        )
        by_criterion[criterion] = by_criterion.get(criterion, 0) + 1

    kept.sort(key=lambda p: (-_prescore(p, current_year), derive_paper_id(p)))

    return {
        "to_screen": kept,
        "excluded": excluded,
        "report": _report(len(papers), len(kept), by_criterion, filters_applied=True),
    }


def _prescore(paper: dict[str, Any], current_year: int | None) -> float:
    """4D-Vorranking; ohne verfügbares ``scoring``-Modul neutral (0.0)."""
    repo_root = Path(__file__).resolve().parents[3]
    scripts_dir = repo_root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    try:
        from scoring import prescore
    except ImportError:  # pragma: no cover - nur ohne installiertes Plugin
        return 0.0
    return prescore(paper, current_year)


def _report(
    n_input: int,
    n_to_screen: int,
    by_criterion: dict[str, int],
    *,
    filters_applied: bool,
) -> dict[str, Any]:
    return {
        "n_input": n_input,
        "n_to_screen": n_to_screen,
        "n_excluded_by_rule": n_input - n_to_screen,
        "batch_size": BATCH_SIZE,
        "batches_before": math.ceil(n_input / BATCH_SIZE),
        "batches_after": math.ceil(n_to_screen / BATCH_SIZE),
        "by_criterion": dict(sorted(by_criterion.items())),
        "filters_applied": filters_applied,
    }


# ---------------------------------------------------------------------------
# Protokoll
# ---------------------------------------------------------------------------


def record_rule_decisions(
    session_dir: str | Path,
    excluded: list[dict[str, Any]],
    *,
    stage: str = STAGE_SCREENING,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """Schreibt je Ausschluss eine ``decided_by="rule"``-Zeile ins Ledger.

    ``db_path`` ist hier auch bei aktivem Doppel-Screening erlaubt und richtig:
    ein Kriterienabgleich hat keine zweite Runde, es gibt also keinen Dissens,
    der einen Vault-Eintrag zurücknehmen müsste. Die Sperre in
    ``record_decision`` gilt unverändert für Modellurteile.

    Idempotent über ``record_decision``: ein zweiter Lauf hängt nichts an.
    """
    return [
        record_decision(
            session_dir,
            {
                "paper_id": row["paper_id"],
                "decision": "exclude",
                "reason": row["reason"],
                "criterion": row["criterion"],
            },
            stage=stage,
            agent="screening-prefilter",
            wave=0,
            db_path=db_path,
            decided_by=DECIDED_BY_RULE,
        )
        for row in excluded
    ]


def prefilter(
    papers: list[dict[str, Any]],
    filters: dict[str, Any],
    session_dir: str | Path,
    *,
    db_path: str | None = None,
    stage: str = STAGE_SCREENING,
    current_year: int | None = None,
) -> dict[str, Any]:
    """Vorfilter anwenden, protokollieren und Modellmenge ablegen.

    Schreibt ``$SESSION_DIR/to_screen.json`` (die Treffer in Bewertungs-
    reihenfolge) und ``$SESSION_DIR/prefilter_report.json`` und gibt den Report
    zurück.
    """
    result = apply_filters(papers, filters, current_year=current_year)
    record_rule_decisions(session_dir, result["excluded"], stage=stage, db_path=db_path)

    target = Path(session_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / TO_SCREEN_FILENAME).write_text(
        json.dumps(result["to_screen"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = dict(result["report"])
    report["excluded"] = result["excluded"]
    (target / REPORT_FILENAME).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Screening-Vorfilter (Issue #892)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pre = sub.add_parser("prefilter", help="Mechanische Vorauswahl vor dem Modelldurchlauf")
    p_pre.add_argument("--session-dir", required=True)
    p_pre.add_argument("--papers", required=True, help="JSON-Liste, i.d.R. ranked.json")
    p_pre.add_argument("--context", default=None, help="Pfad auf ./academic_context.md")
    p_pre.add_argument("--db-path", default=None)
    p_pre.add_argument("--current-year", type=int, default=None)
    p_pre.add_argument(
        "--no-prefilter",
        action="store_true",
        help="Vorfilter für diesen Lauf abschalten (Verhalten wie vor #892)",
    )

    args = parser.parse_args(argv)

    if args.command == "prefilter":
        papers = json.loads(Path(args.papers).read_text(encoding="utf-8"))
        enabled = resolve_prefilter(False if args.no_prefilter else None)
        filters = load_filters_from_file(args.context) if enabled else {}
        report = prefilter(
            papers,
            filters,
            args.session_dir,
            db_path=args.db_path,
            current_year=args.current_year,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
