#!/usr/bin/env python3
"""Buchführung für den parallelen Screening-/RoB-Fan-out (Issue #460).

Die eigentliche Nebenläufigkeit erzeugt der Harness (mehrere Subagents pro
Nachricht). Dieses Modul liefert die deterministische Buchführung darum herum:

- ``plan_waves``   — teilt die Fälle in Wellen der konfigurierten Obergrenze auf
- ``record_decision`` — schreibt eine Ledger-Zeile und die Vault-Seiteneffekte
- ``pending`` / ``pending_rob`` — Resume: was ist nach einem Abbruch offen?
- ``merge``        — Einzelergebnisse zu ``include`` / ``exclude`` / ``unclear``
- ``to_prisma_counters`` — PRISMA-Zähler direkt aus dem Ledger

Das Limit ist eine organisatorische Grenze (wie viele Fälle in einer Welle
losgeschickt werden dürfen), kein technischer Semaphor.

Ledger: ``$SESSION_DIR/screening_ledger.jsonl``, append-only, eine Zeile je
entschiedenem Fall. Sie ist zugleich das Protokoll „welche Quelle wurde von
welchem Agent bewertet" und die Resume-Basis.

Zielstrukturen bleiben unverändert: Ausschlüsse gehen nach ``excluded_sources``,
Einschlüsse bleiben in ``papers``, RoB-Bewertungen in
``risk_of_bias_assessments``. ``unclear`` schreibt nie in den Vault.

CLI:
  python screening_ledger.py pending --session-dir DIR --ids a,b,c
  python screening_ledger.py waves --ids a,b,c [--max-parallel N]
  python screening_ledger.py merge --session-dir DIR
  python screening_ledger.py counters --session-dir DIR [--n-identified N]
  python screening_ledger.py open-cases --session-dir DIR
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Verträge
# ---------------------------------------------------------------------------

LEDGER_FILENAME = "screening_ledger.jsonl"

#: Stufen, die im Ledger geführt werden.
STAGE_SCREENING = "screening"
STAGE_ELIGIBILITY = "eligibility"
STAGE_ROB = "rob"

#: Erlaubte Entscheidungen je Stufe.
SCREENING_DECISIONS = ("include", "exclude", "unclear")
ROB_DECISIONS = ("assessed", "unclear")
VALID_DECISIONS: dict[str, tuple[str, ...]] = {
    STAGE_SCREENING: SCREENING_DECISIONS,
    STAGE_ELIGIBILITY: SCREENING_DECISIONS,
    STAGE_ROB: ROB_DECISIONS,
}

#: Felder, die eine Einzelfall-Rückgabe des Subagents mitbringen darf.
OPTIONAL_DECISION_FIELDS = ("criterion", "confidence", "evidence")

# ---------------------------------------------------------------------------
# Parallelitäts-Limit
# ---------------------------------------------------------------------------

MAX_PARALLEL_ENV = "ACADEMIC_RESEARCH_MAX_PARALLEL"
DEFAULT_MAX_PARALLEL = 4
MAX_PARALLEL_HARD_CAP = 8
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "parallel_agents.json"


def resolve_max_parallel(
    explicit: int | None = None,
    config_path: str | Path | None = None,
) -> int:
    """Ermittelt die Obergrenze gleichzeitiger Agents.

    Vorrang: Argument > Env ``ACADEMIC_RESEARCH_MAX_PARALLEL`` > Config-Datei >
    Default. Das Ergebnis wird hart auf ``MAX_PARALLEL_HARD_CAP`` gedeckelt.

    Raises:
        ValueError: bei einem explizit übergebenen Wert < 1.
    """
    if explicit is not None:
        value = int(explicit)
        if value < 1:
            raise ValueError(f"max_parallel muss >= 1 sein, war {explicit}")
        return min(value, MAX_PARALLEL_HARD_CAP)

    raw_env = os.environ.get(MAX_PARALLEL_ENV)
    if raw_env is not None:
        try:
            value = int(str(raw_env).strip())
        except ValueError:
            value = 0
        if value >= 1:
            return min(value, MAX_PARALLEL_HARD_CAP)

    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = int(data["max_parallel_agents"])
    except (OSError, ValueError, KeyError, TypeError):
        value = 0
    if value >= 1:
        return min(value, MAX_PARALLEL_HARD_CAP)

    return DEFAULT_MAX_PARALLEL


def plan_waves(paper_ids: list[str], max_parallel: int | None = None) -> list[list[str]]:
    """Teilt ``paper_ids`` reihenfolgetreu in Wellen von höchstens ``max_parallel``.

    Ohne ``max_parallel`` greift ``resolve_max_parallel()``. Jede ID landet in
    genau einer Welle; die Reihenfolge bleibt erhalten.
    """
    limit = (
        resolve_max_parallel(max_parallel) if max_parallel is not None else (resolve_max_parallel())
    )
    ids = list(paper_ids)
    return [ids[i : i + limit] for i in range(0, len(ids), limit)]


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def ledger_path(session_dir: str | Path) -> Path:
    """Pfad des Ledgers innerhalb einer ``/search``-Session."""
    return Path(session_dir) / LEDGER_FILENAME


def read_ledger(session_dir: str | Path) -> list[dict[str, Any]]:
    """Liest alle vollständigen Ledger-Zeilen.

    Eine abgebrochene Schreiboperation (halbe letzte Zeile) wird übersprungen,
    damit ein Resume nach hartem Abbruch nicht am eigenen Protokoll scheitert.
    """
    path = ledger_path(session_dir)
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and entry.get("paper_id"):
            entries.append(entry)
    return entries


def validate_decision(decision: dict[str, Any], stage: str = STAGE_SCREENING) -> dict[str, Any]:
    """Prüft die Einzelfall-Rückgabe eines Subagents gegen den Vertrag.

    Raises:
        ValueError: bei unbekannter Stufe/Entscheidung, fehlender ``paper_id``
            oder leerer Begründung.
    """
    if stage not in VALID_DECISIONS:
        raise ValueError(f"Unbekannte Stufe '{stage}'. Erlaubt: {sorted(VALID_DECISIONS)}")
    if not isinstance(decision, dict):
        raise ValueError(f"Entscheidung muss ein dict sein, war {type(decision)}")

    paper_id = str(decision.get("paper_id") or "").strip()
    if not paper_id:
        raise ValueError("Entscheidung ohne paper_id")

    value = str(decision.get("decision") or "").strip()
    if value not in VALID_DECISIONS[stage]:
        raise ValueError(
            f"{paper_id}: Entscheidung '{value}' ist in Stufe '{stage}' nicht erlaubt "
            f"(erlaubt: {list(VALID_DECISIONS[stage])})"
        )

    reason = str(decision.get("reason") or "").strip()
    if not reason:
        raise ValueError(f"{paper_id}: Begründung fehlt — jede Entscheidung braucht einen Grund")

    validated: dict[str, Any] = {"paper_id": paper_id, "decision": value, "reason": reason}
    for field in OPTIONAL_DECISION_FIELDS:
        if decision.get(field) is not None:
            validated[field] = decision[field]
    return validated


def record_decision(
    session_dir: str | Path,
    decision: dict[str, Any],
    *,
    stage: str = STAGE_SCREENING,
    agent: str = "unknown",
    wave: int = 1,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Protokolliert eine Einzelfall-Entscheidung und schreibt die Zielstruktur.

    ``exclude`` landet mit Stufen-Präfix in ``excluded_sources`` (nur wenn
    ``db_path`` gesetzt ist), ``include`` bleibt unangetastet in ``papers``,
    ``unclear`` erreicht den Vault nie.

    Idempotent: ist der Fall für diese Stufe bereits im Ledger, bleibt die
    Erstentscheidung stehen und es wird keine zweite Zeile angehängt.
    """
    validated = validate_decision(decision, stage=stage)
    paper_id = validated["paper_id"]

    for existing in read_ledger(session_dir):
        if existing["paper_id"] == paper_id and existing.get("stage") == stage:
            return existing

    if validated["decision"] == "exclude" and db_path:
        _add_excluded_source(db_path, paper_id, f"{stage}: {validated['reason']}")

    entry = {
        **validated,
        "stage": stage,
        "agent": agent,
        "wave": int(wave),
        "ts": int(time.time()),
    }
    path = ledger_path(session_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _add_excluded_source(db_path: str, paper_id: str, reason: str) -> None:
    """Schreibt nach ``excluded_sources`` (Import lokal, damit CLI ohne Vault läuft)."""
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from academic_vault.db import VaultDB

    VaultDB(db_path).add_excluded_source(paper_id=paper_id, reason=reason)


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


def decided_ids(session_dir: str | Path, stage: str = STAGE_SCREENING) -> set[str]:
    """IDs, die für diese Stufe bereits eine Ledger-Zeile haben."""
    return {e["paper_id"] for e in read_ledger(session_dir) if e.get("stage") == stage}


def pending(
    paper_ids: list[str],
    session_dir: str | Path,
    stage: str = STAGE_SCREENING,
) -> list[str]:
    """Offene Fälle: alles aus ``paper_ids`` ohne Ledger-Zeile für diese Stufe."""
    done = decided_ids(session_dir, stage=stage)
    return [pid for pid in paper_ids if pid not in done]


def pending_rob(
    paper_ids: list[str],
    session_dir: str | Path,
    db_path: str,
) -> list[str]:
    """Offene RoB-Fälle — Ledger UND Vault werden geprüft.

    ``add_risk_of_bias`` ist ein reines INSERT ohne Idempotenz: ein zweiter Lauf
    würde ein zweites Assessment anlegen. Darum zählt ein bereits im Vault
    liegendes Assessment auch dann als erledigt, wenn das Ledger fehlt (z.B.
    weil die Bewertung aus einer früheren Session stammt).
    """
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from academic_vault.db import VaultDB

    db = VaultDB(db_path)
    done = decided_ids(session_dir, stage=STAGE_ROB)
    return [pid for pid in paper_ids if pid not in done and not db.list_risk_of_bias(pid)]


# ---------------------------------------------------------------------------
# Zusammenführung
# ---------------------------------------------------------------------------


def merge(session_dir: str | Path, stage: str = STAGE_SCREENING) -> dict[str, list[str]]:
    """Führt die Einzelergebnisse einer Stufe zu drei Buckets zusammen."""
    buckets: dict[str, list[str]] = {"include": [], "exclude": [], "unclear": []}
    for entry in read_ledger(session_dir):
        if entry.get("stage") != stage:
            continue
        bucket = buckets.get(entry.get("decision", ""))
        if bucket is not None:
            bucket.append(entry["paper_id"])
    return buckets


def open_cases(session_dir: str | Path) -> list[dict[str, Any]]:
    """Alle uneindeutigen Fälle über alle Stufen — nichts davon ist entschieden."""
    return [e for e in read_ledger(session_dir) if e.get("decision") == "unclear"]


def open_cases_report(session_dir: str | Path) -> str:
    """Markdown-Vorlage, die die uneindeutigen Fälle gesammelt vorlegt."""
    cases = open_cases(session_dir)
    if not cases:
        return "## Offene Fälle\n\nKeine uneindeutigen Fälle — nichts zu entscheiden.\n"

    lines = [
        "## Offene Fälle — menschliche Entscheidung nötig",
        "",
        f"{len(cases)} Quelle(n) konnten am vorliegenden Material nicht entschieden werden.",
        "Sie sind weder ein- noch ausgeschlossen und stehen in keiner Vault-Zielstruktur.",
        "",
        "| Quelle | Stufe | Warum unklar | Kriterium | Beleglage | Agent |",
        "|--------|-------|--------------|-----------|-----------|-------|",
    ]
    for case in cases:
        lines.append(
            "| {paper_id} | {stage} | {reason} | {criterion} | {evidence} | {agent} |".format(
                paper_id=case["paper_id"],
                stage=case.get("stage", "—"),
                reason=case.get("reason", "—"),
                criterion=case.get("criterion", "—"),
                evidence=case.get("evidence", "—"),
                agent=case.get("agent", "—"),
            )
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PRISMA
# ---------------------------------------------------------------------------


def to_prisma_counters(
    session_dir: str | Path,
    n_identified: int | None = None,
    n_after_dedup: int | None = None,
) -> dict[str, int]:
    """Erzeugt die PRISMA-Zähler direkt aus dem Ledger.

    Summenregel: ``n_after_dedup == n_excluded_screening + n_included +
    n_unclear_screening`` (solange keine Volltextprüfung protokolliert ist).
    Läuft zusätzlich eine Eligibility-Stufe, verschiebt sie ``n_included``.

    ``n_unclear_screening`` ist ein Zusatzfeld: uneindeutige Fälle sind weder
    ein- noch ausgeschlossen und dürfen darum nicht als Volltextkandidaten
    gezählt werden.
    """
    screening = merge(session_dir, stage=STAGE_SCREENING)
    eligibility = merge(session_dir, stage=STAGE_ELIGIBILITY)

    n_excluded_screening = len(screening["exclude"])
    n_unclear = len(screening["unclear"])
    n_screen_include = len(screening["include"])

    if n_after_dedup is None:
        n_after_dedup = n_excluded_screening + n_unclear + n_screen_include
    if n_identified is None:
        n_identified = n_after_dedup

    has_eligibility = any(eligibility[bucket] for bucket in eligibility)
    n_excluded_eligibility = len(eligibility["exclude"])
    n_included = (
        n_screen_include - n_excluded_eligibility - len(eligibility["unclear"])
        if has_eligibility
        else n_screen_include
    )

    return {
        "n_identified": int(n_identified),
        "n_after_dedup": int(n_after_dedup),
        "n_excluded_screening": n_excluded_screening,
        "n_excluded_eligibility": n_excluded_eligibility,
        "n_included": n_included,
        "n_unclear_screening": n_unclear,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _split_ids(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Screening-Ledger (Issue #460)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pending = sub.add_parser("pending", help="Offene Fälle nach Abbruch")
    p_pending.add_argument("--session-dir", required=True)
    p_pending.add_argument("--ids", required=True, help="Komma-separierte paper_ids")
    p_pending.add_argument("--stage", default=STAGE_SCREENING, choices=sorted(VALID_DECISIONS))

    p_waves = sub.add_parser("waves", help="Fälle in Wellen aufteilen")
    p_waves.add_argument("--ids", required=True)
    p_waves.add_argument("--max-parallel", type=int, default=None)

    p_merge = sub.add_parser("merge", help="Buckets include/exclude/unclear")
    p_merge.add_argument("--session-dir", required=True)
    p_merge.add_argument("--stage", default=STAGE_SCREENING, choices=sorted(VALID_DECISIONS))

    p_counters = sub.add_parser("counters", help="PRISMA-Zähler aus dem Ledger")
    p_counters.add_argument("--session-dir", required=True)
    p_counters.add_argument("--n-identified", type=int, default=None)
    p_counters.add_argument("--n-after-dedup", type=int, default=None)

    p_open = sub.add_parser("open-cases", help="Uneindeutige Fälle als Markdown-Vorlage")
    p_open.add_argument("--session-dir", required=True)

    args = parser.parse_args(argv)

    if args.command == "pending":
        print(json.dumps(pending(_split_ids(args.ids), args.session_dir, stage=args.stage)))
    elif args.command == "waves":
        print(json.dumps(plan_waves(_split_ids(args.ids), args.max_parallel)))
    elif args.command == "merge":
        print(json.dumps(merge(args.session_dir, stage=args.stage), ensure_ascii=False, indent=2))
    elif args.command == "counters":
        counters = to_prisma_counters(
            args.session_dir,
            n_identified=args.n_identified,
            n_after_dedup=args.n_after_dedup,
        )
        print(json.dumps(counters, ensure_ascii=False, indent=2))
    elif args.command == "open-cases":
        print(open_cases_report(args.session_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
