#!/usr/bin/env python3
"""Aufnahme-Werkzeug fuer evals/sparring-partner/recordings.json (Issue #454).

Zweck
-----
Erzeugt die Transkripte in ``recordings.json`` durch **echte Modellaufrufe**
statt durch handverfassten Text. Ruft dazu die Claude-Code-CLI headless auf
(``claude --print``, OAuth-Session -- kein ANTHROPIC_API_KEY noetig, gleiche
Auth-Art wie das Repo-Secret ``CLAUDE_CODE_OAUTH_TOKEN`` in CI).

Warum ueberhaupt ein eigener Recorder
-------------------------------------
Der AC-Verifier zu PR #494 beanstandete zu Recht, dass die erste Fassung von
``recordings.json`` selbstverfasster Text einer Claude-Session war: Transkript
und Regex-Erwartung stammten aus derselben Sitzung, also konnte der Abgleich
nicht scheitern. Dieser Recorder trennt beides sauber:

1. ``evals.json`` (Erwartungen) und ``counter_examples.json`` (Negativkontrollen)
   sind **vor** der Aufnahme committed und im Repo nachlesbar.
2. Der Aufnahme-Subprozess bekommt ausschliesslich ``agents/sparring-partner.md``
   als System-Prompt und den jeweiligen ``evals.json::input`` als User-Message.
   Er sieht die Erwartungen **nicht** -- weder ``expected`` noch die
   Gegenproben werden an die CLI uebergeben.
3. Erst danach prueft ``runner.py`` das Ergebnis gegen die vorher festgelegten
   Kriterien. Ein Fehlschlag ist damit moeglich und aussagekraeftig.

Prompt-Aufbau bewusst identisch zum API-gated Pfad
--------------------------------------------------
Uebergeben wird die **komplette** Agent-Datei inklusive YAML-Frontmatter,
genau wie ``tests/evals/eval_runner.load_agent_content()`` es fuer
``tests/evals/test_sparring_partner_evals.py`` tut. Die erste Fassung nutzte
nur den Body nach dem Frontmatter -- der Coordinator-Gate-Befund zu PR #494
hielt fest, dass beide Pfade dadurch unterschiedlich prompten und keine
austauschbare Evidenzkette bilden. Diese Divergenz ist damit beseitigt.

Aufruf (Operator/Entwickler, nicht CI -- verbraucht Modell-Budget):

    python3 evals/sparring-partner/record.py

Der Lauf schreibt ``recordings.json`` neu, inklusive frischem ``agent_file_sha256``.
Danach ``uv run pytest tests/evals/test_sparring_partner_recording.py`` und
``tests/evals/test_sparring_partner_criteria.py`` ausfuehren.

CI ruft dieses Skript nie auf: ``tests/evals/test_sparring_partner_recording.py``
prueft ausdruecklich, dass ``runner.py`` ohne Netz und ohne API-Key laeuft
(Issue #390 AC4). Der Recorder ist ein separater, manuell gestarteter Pfad.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent.parent
AGENT_PATH = REPO_ROOT / "agents" / "sparring-partner.md"
EVALS_PATH = EVAL_DIR / "evals.json"
RECORDINGS_PATH = EVAL_DIR / "recordings.json"

# agents/sparring-partner.md deklariert "model: opus"; die CLI nimmt denselben
# Kurznamen entgegen, sodass die Aufnahme dasselbe Modell trifft wie ein realer
# Agent-Aufruf.
CLI_MODEL = "opus"
TIMEOUT_SECONDS = 300


def agent_prompt() -> str:
    """Komplette Agent-Datei -- identisch zu load_agent_content() im API-Pfad."""
    return AGENT_PATH.read_text(encoding="utf-8")


def record_one(system_prompt: str, user_input: str) -> str:
    """Ein headless Modellaufruf. Sieht keine Erwartungen, nur Prompt + Eingabe."""
    result = subprocess.run(
        [
            "claude",
            "--print",
            "--model",
            CLI_MODEL,
            "--system-prompt",
            system_prompt,
            # Keine Tools: die Eval-Eingaben liefern academic_context.md- und
            # Vault-Inhalte bereits inline, und ein Datei-/Vault-Zugriff waere
            # vom Aufnahmerechner abhaengig statt reproduzierbar.
            "--allowedTools",
            "",
            # Keine Projekt-/User-Settings, kein CLAUDE.md: sonst faerbt die
            # Umgebung des Aufnahmerechners in die Antwort ein.
            "--setting-sources",
            "",
            user_input,
        ],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        cwd=str(EVAL_DIR),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude --print schlug fehl ({result.returncode}): {result.stderr[:500]}"
        )
    return result.stdout.strip()


def main() -> int:
    if shutil.which("claude") is None:
        print("claude-CLI nicht gefunden -- Aufnahme nicht moeglich.", file=sys.stderr)
        return 2

    system_prompt = agent_prompt()
    prompts = json.loads(EVALS_PATH.read_text(encoding="utf-8"))["prompts"]

    transcripts: dict[str, str] = {}
    for prompt in prompts:
        print(f"[record] {prompt['id']} …", file=sys.stderr)
        transcripts[prompt["id"]] = record_one(system_prompt, prompt["input"])

    previous = (
        json.loads(RECORDINGS_PATH.read_text(encoding="utf-8")) if RECORDINGS_PATH.exists() else {}
    )
    payload = {
        "component": "sparring-partner",
        "agent_file": "agents/sparring-partner.md",
        "agent_file_sha256": hashlib.sha256(AGENT_PATH.read_bytes()).hexdigest(),
        "generated": datetime.date.today().isoformat(),
        "recorded_with": f"claude --print --model {CLI_MODEL} (Claude-Code-CLI, OAuth)",
        "recorder": "evals/sparring-partner/record.py",
        "provenance": previous.get("provenance", ""),
        "transcripts": transcripts,
    }
    RECORDINGS_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"[record] {len(transcripts)} Transkripte -> {RECORDINGS_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
