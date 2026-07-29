#!/usr/bin/env python3
"""Eval-Runner fuer sparring-partner (Issue #454 / PR #494 Fix-Runde).

Der AC-Verifier markierte AC2/AC3/AC4/AC5 als "verfehlt": Die einzige inhaltliche
Evidenz war die API-gated Suite tests/evals/test_sparring_partner_evals.py, die
ohne ANTHROPIC_API_KEY (kein Workflow unter .github/workflows/ setzt ihn) niemals
laeuft -- "Es existiert im PR keinerlei tatsaechlicher Modell-Output."

Dieser Runner prueft stattdessen fuenf real aufgenommene Transkripte
(evals/sparring-partner/recordings.json) gegen die expected-Vorgaben aus
evals/sparring-partner/evals.json. Die Transkripte wurden waehrend der PR-#494-
Fix-Runde von einer echten Claude-Session erzeugt: Body von
agents/sparring-partner.md als System-Prompt, Eval-Input als User-Message, echte
Modell-Antwort. Kein Live-Aufruf des in der Frontmatter spezifizierten
``model: opus`` per Anthropic-API (Provenienz siehe recordings.json::provenance).

Was dieser Runner NICHT prueft: ob das Modell auf abweichende Formulierungen der
gleichen fuenf Prompts genauso reagieren wuerde, oder ob kuenftige Prompts das tun.
Das ist eine eingefrorene Stichprobe, kein Live-Judge -- deshalb der Hash-Pin unten:
Aendert sich agents/sparring-partner.md, meldet run_eval_cases() den Drift, statt
die veraltete Aufnahme stillschweigend weiter bestehen zu lassen.

Aufruf: python3 evals/sparring-partner/runner.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent.parent
AGENT_PATH = REPO_ROOT / "agents" / "sparring-partner.md"
EVALS_PATH = EVAL_DIR / "evals.json"
RECORDINGS_PATH = EVAL_DIR / "recordings.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_expected(output: str, expected: dict[str, Any]) -> bool:
    """Eigenstaendiger Nachbau von tests/evals/eval_runner.check_expected fuer die
    beiden in evals/sparring-partner/evals.json genutzten Typen. Bewusst nicht aus
    tests/evals importiert, damit dieser Runner ohne das tests/-Paket lauffaehig
    bleibt (Muster: evals/auto-download/runner.py, das ebenfalls autark ist)."""
    t = expected.get("type")
    if t == "substring":
        return expected["value"] in output
    if t == "regex":
        return bool(re.search(expected["value"], output))
    raise ValueError(f"sparring-partner-Runner unterstuetzt expected.type={t!r} nicht")


def load_evals() -> dict[str, Any]:
    return json.loads(EVALS_PATH.read_text(encoding="utf-8"))


def load_recordings() -> dict[str, Any]:
    return json.loads(RECORDINGS_PATH.read_text(encoding="utf-8"))


def hash_pin_matches() -> tuple[bool, str, str]:
    """Vergleicht den in recordings.json gepinnten sha256 gegen den aktuellen
    Stand von agents/sparring-partner.md. Weicht der Agent-Text vom
    Aufnahmezeitpunkt ab, ist die Aufnahme veraltet."""
    recordings = load_recordings()
    pinned = recordings.get("agent_file_sha256", "")
    current = _sha256(AGENT_PATH)
    return pinned == current, pinned, current


def run_eval_cases() -> dict[str, Any]:
    """Prueft die aufgenommenen Transkripte gegen evals.json::expected.

    Rueckgabe: dict mit passed/failed/total/details (je Prompt: id/expected/
    has_transcript/ok) plus hash_pin_ok/hash_pin_expected/hash_pin_actual.
    """
    evals = load_evals()
    recordings = load_recordings()
    transcripts: dict[str, str] = recordings.get("transcripts", {})
    pin_ok, pinned, current = hash_pin_matches()

    details: list[dict[str, Any]] = []
    for prompt in evals["prompts"]:
        pid = prompt["id"]
        transcript = transcripts.get(pid, "")
        ok = bool(transcript) and _check_expected(transcript, prompt["expected"])
        details.append(
            {
                "id": pid,
                "expected": prompt["expected"],
                "has_transcript": bool(transcript),
                "ok": ok,
            }
        )

    passed = sum(1 for d in details if d["ok"])
    return {
        "passed": passed,
        "failed": len(details) - passed,
        "total": len(details),
        "details": details,
        "hash_pin_ok": pin_ok,
        "hash_pin_expected": pinned,
        "hash_pin_actual": current,
    }


def run_eval() -> None:
    """CLI-Einstiegspunkt: Report auf stdout, Exit 1 bei Fehlschlag oder Hash-Drift."""
    summary = run_eval_cases()
    for detail in summary["details"]:
        status = "OK" if detail["ok"] else "FAIL"
        print(f"[{status}] {detail['id']}")
    print(f"\n{summary['passed']}/{summary['total']} bestanden.")
    if not summary["hash_pin_ok"]:
        print(
            f"HASH-DRIFT: agents/sparring-partner.md hat sich seit der Aufnahme "
            f"geaendert (erwartet {summary['hash_pin_expected'][:12]}..., aktuell "
            f"{summary['hash_pin_actual'][:12]}...) -- recordings.json braucht eine "
            f"neue Aufnahme."
        )
    if summary["failed"] or not summary["hash_pin_ok"]:
        sys.exit(1)


if __name__ == "__main__":
    run_eval()
