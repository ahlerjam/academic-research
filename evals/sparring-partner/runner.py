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
Transkript (recordings.json) und Erwartung (evals.json::expected) stammen aus
derselben Sitzung -- kein unabhaengiger Verhaltensbeleg, sondern ein Snapshot-/
Konsistenz-Check (Status ``structural`` in docs/evals/STRATEGY.md, nicht ``metric``).
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
COUNTER_EXAMPLES_PATH = EVAL_DIR / "counter_examples.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _as_patterns(value: Any) -> list[str]:
    """Normalisiert ``value``/``reject`` auf eine Liste von Mustern."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    raise ValueError(f"expected.value/reject muss str oder list[str] sein, ist: {type(value)}")


def _check_expected(output: str, expected: dict[str, Any]) -> bool:
    """Eigenstaendiger Nachbau von tests/evals/eval_runner.check_expected fuer die
    beiden in evals/sparring-partner/evals.json genutzten Typen. Bewusst nicht aus
    tests/evals importiert, damit dieser Runner ohne das tests/-Paket lauffaehig
    bleibt (Muster: evals/auto-download/runner.py, das ebenfalls autark ist).

    Semantik identisch zu check_expected: ``value`` ist eine UND-Liste, ``reject``
    eine NOR-Liste. Die Deckungsgleichheit beider Implementierungen ist durch
    tests/evals/test_sparring_partner_criteria.py abgesichert."""
    t = expected.get("type")
    if t not in {"substring", "regex"}:
        raise ValueError(f"sparring-partner-Runner unterstuetzt expected.type={t!r} nicht")
    if any(re.search(r, output) for r in _as_patterns(expected.get("reject"))):
        return False
    if t == "substring":
        return all(v in output for v in _as_patterns(expected["value"]))
    return all(bool(re.search(v, output)) for v in _as_patterns(expected["value"]))


def load_evals() -> dict[str, Any]:
    return json.loads(EVALS_PATH.read_text(encoding="utf-8"))


def load_recordings() -> dict[str, Any]:
    return json.loads(RECORDINGS_PATH.read_text(encoding="utf-8"))


def load_counter_examples() -> dict[str, Any]:
    return json.loads(COUNTER_EXAMPLES_PATH.read_text(encoding="utf-8"))


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

    counter_details = run_counter_examples()
    counter_failed = sum(1 for c in counter_details if not c["rejected"])

    passed = sum(1 for d in details if d["ok"])
    return {
        "passed": passed,
        "failed": len(details) - passed + counter_failed,
        "total": len(details),
        "details": details,
        "counter_examples": counter_details,
        "counter_examples_failed": counter_failed,
        "hash_pin_ok": pin_ok,
        "hash_pin_expected": pinned,
        "hash_pin_actual": current,
    }


def run_counter_examples() -> list[dict[str, Any]]:
    """Prueft, ob jede Negativkontrolle vom zugehoerigen expected ABGELEHNT wird.

    Das ist der Fehlerpfad, der dem Runner vor Issue #454 fehlte: ohne
    Gegenproben konnte er nur bestaetigen, dass ein eingefrorenes Transkript zu
    einer Regex passt, die in Kenntnis dieses Transkripts geschrieben wurde.
    Die Gegenproben sind format-konform und scheitern ausschliesslich an dem,
    was die Akzeptanzkriterien inhaltlich verlangen -- sie belegen damit, dass
    die Kriterien ueberhaupt zwischen konformem und nicht-konformem Verhalten
    unterscheiden koennen.
    """
    if not COUNTER_EXAMPLES_PATH.exists():
        return []
    expected_by_id = {p["id"]: p["expected"] for p in load_evals()["prompts"]}
    results: list[dict[str, Any]] = []
    for prompt_id, cases in load_counter_examples()["counter_examples"].items():
        expected = expected_by_id.get(prompt_id)
        for case in cases:
            rejected = expected is not None and not _check_expected(case["text"], expected)
            results.append(
                {
                    "id": prompt_id,
                    "label": case["label"],
                    "violates": case.get("violates", ""),
                    "rejected": rejected,
                }
            )
    return results


def run_eval() -> None:
    """CLI-Einstiegspunkt: Report auf stdout, Exit 1 bei Fehlschlag oder Hash-Drift."""
    summary = run_eval_cases()
    for detail in summary["details"]:
        status = "OK" if detail["ok"] else "FAIL"
        print(f"[{status}] {detail['id']}")
    print(f"\n{summary['passed']}/{summary['total']} Transkripte bestanden.")
    for case in summary["counter_examples"]:
        status = "OK" if case["rejected"] else "FAIL"
        print(f"[{status}] negativ {case['id']}/{case['label']}")
    rejected = sum(1 for c in summary["counter_examples"] if c["rejected"])
    print(f"{rejected}/{len(summary['counter_examples'])} Negativkontrollen abgelehnt.")
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
