#!/usr/bin/env python3
"""Live-Nachweis: erreicht der Reinforcement-Hook wirklich den Modell-Kontext? (#382, AC1)

Warum dieses Skript existiert
-----------------------------
AC1 von Issue #382 verlangt zweierlei: (a) der Reinforcement-Hinweis haengt an
einem Event, dessen stdout laut Doku als Modell-Kontext wirkt, und (b) er ist
"im tatsaechlichen Modell-Kontext nachweisbar". (a) laesst sich aus der Doku und
aus Unit-Tests belegen, (b) nicht — Unit-Tests beweisen nur, dass der Hook Text
auf stdout schreibt, nicht dass Claude Code diesen Text an das Modell weiterreicht.
Genau diese Luecke schliesst dieses Skript.

Verfahren (Nonce-Round-Trip)
----------------------------
1. Temporaerer Vault mit genau EINER aktiven Decision, deren Text einen frisch
   gewuerfelten Nonce-Marker enthaelt (existiert sonst nirgends — nicht im Prompt,
   nicht im Repo, nicht in den Trainingsdaten).
2. Ein settings.json wird NICHT von Hand geschrieben, sondern aus der deployten
   `hooks/hooks.json` abgeleitet: alle Bloecke, die `mid-session-reinforcement.mjs`
   aufrufen, mit aufgeloestem `${CLAUDE_PLUGIN_ROOT}`. Damit prueft der Lauf die
   echte Verdrahtung, nicht eine Test-Attrappe.
3. `claude -p` wird headless mit diesem settings.json gestartet und gefragt, welchen
   Nonce-Marker es im Kontext sieht.
4. Steht der Marker in der Modell-Antwort, kann er nur ueber die Hook-Injection
   dorthin gelangt sein: Vault -> Hook-stdout -> Modell-Kontext -> Antwort.

Zusaetzlich wird das Session-Transcript (~/.claude/projects/<slug>/<sid>.jsonl)
auf den `hook_success`-Attachment-Eintrag geprueft — eine zweite, vom Modell-
verhalten unabhaengige Evidenzschicht.

Aufruf
------
    uv run python scripts/dev/verify_reinforcement_context.py

Voraussetzungen: `claude` im PATH, gueltige Anmeldung, Netzzugang. Der Lauf kostet
einen kurzen Haiku-Aufruf. Deshalb ist er NICHT Teil der normalen Testsuite; der
zugehoerige pytest-Test (tests/test_hook_midsession_live_context.py) ist per
`ACADEMIC_LIVE_CONTEXT_TEST=1` gegated — analog zum bestehenden
`VAULT_E5_LIVE_TEST`-Muster.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
REINFORCEMENT_HOOK = "mid-session-reinforcement.mjs"
PLUGIN_ROOT_PLACEHOLDER = "${CLAUDE_PLUGIN_ROOT}"

NONCE_PREFIX = "REINFORCE"

PROMPT = (
    "Im Kontext wurde dir eine Liste aktiver Decisions injiziert. "
    f"Gib ausschliesslich den darin enthaltenen Marker aus (Format {NONCE_PREFIX}-XXXXXXXXXX). "
    "Steht dort kein solcher Marker, antworte exakt: KEIN-MARKER"
)


class LiveCheckError(RuntimeError):
    """Der Live-Check konnte nicht durchgefuehrt werden (Setup-/Toolfehler)."""


def build_settings(plugin_root: Path, hooks_json: Path = HOOKS_JSON) -> dict:
    """Leitet ein settings.json aus der deployten hooks.json ab.

    Uebernommen werden nur die Hook-Eintraege, die `mid-session-reinforcement.mjs`
    aufrufen; `${CLAUDE_PLUGIN_ROOT}` wird auf `plugin_root` aufgeloest. Dadurch
    testet der Live-Lauf exakt die Event-Verdrahtung, die auch ausgeliefert wird.
    """
    raw = json.loads(hooks_json.read_text(encoding="utf-8"))
    selected: dict[str, list] = {}

    for event, blocks in raw.get("hooks", {}).items():
        kept_blocks = []
        for block in blocks:
            kept_hooks = [
                {
                    **hook,
                    "command": hook["command"].replace(PLUGIN_ROOT_PLACEHOLDER, str(plugin_root)),
                }
                for hook in block.get("hooks", [])
                if REINFORCEMENT_HOOK in hook.get("command", "")
            ]
            if kept_hooks:
                kept_blocks.append({**block, "hooks": kept_hooks})
        if kept_blocks:
            selected[event] = kept_blocks

    if not selected:
        raise LiveCheckError(
            f"Kein Hook-Eintrag fuer {REINFORCEMENT_HOOK} in {hooks_json} gefunden."
        )
    return {"hooks": selected}


def _seed_vault(db_path: str, nonce: str) -> None:
    """Legt eine Vault-DB mit genau einer aktiven, nonce-tragenden Decision an."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from academic_vault.db import VaultDB
    from academic_vault.server import add_decision

    VaultDB(db_path).init_schema()
    add_decision(
        db_path,
        category="LiveCheck",
        text=f"Nonce-Marker fuer die Kontext-Verifikation: {nonce}",
        rationale="Temporaer, nur fuer scripts/dev/verify_reinforcement_context.py",
    )


def _find_transcript(session_id: str) -> Path | None:
    """Sucht das Session-Transcript zu einer Session-ID unter ~/.claude/projects/."""
    base = Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return None
    return next(iter(base.glob(f"*/{session_id}.jsonl")), None)


def _transcript_shows_injection(transcript: Path, nonce: str) -> bool:
    """Prueft, ob Claude Code die Hook-Ausgabe als Kontext-Attachment verbucht hat."""
    for line in transcript.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        attachment = entry.get("attachment")
        if not isinstance(attachment, dict):
            continue
        if attachment.get("type") != "hook_success":
            continue
        if nonce in json.dumps(attachment, ensure_ascii=False):
            return True
    return False


def run_live_check(
    model: str = "haiku",
    timeout: int = 300,
    plugin_root: Path = REPO_ROOT,
) -> dict:
    """Fuehrt den Nonce-Round-Trip aus und liefert das Ergebnis als dict.

    Rueckgabe-Schluessel: nonce, answer, model_saw_nonce, transcript_confirms,
    session_id, transcript, settings.
    """
    if shutil.which("claude") is None:
        raise LiveCheckError("`claude` ist nicht im PATH — Live-Check nicht moeglich.")

    nonce = f"{NONCE_PREFIX}-{secrets.token_hex(5).upper()}"
    workdir = Path(tempfile.mkdtemp(prefix="reinforcement-live-"))
    try:
        db_path = str(workdir / "vault.db")
        _seed_vault(db_path, nonce)

        settings = build_settings(plugin_root)
        settings_file = workdir / "settings.json"
        settings_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")

        env = os.environ.copy()
        env.update(
            {
                "VAULT_DB_PATH": db_path,
                "ACADEMIC_REINFORCEMENT_STATE": str(workdir / "state.json"),
                # Jeder UserPromptSubmit triggert — sonst braeuchte der Check 20 Prompts.
                "ACADEMIC_REINFORCEMENT_N": "1",
            }
        )

        session_id = str(uuid.uuid4())
        proc = subprocess.run(
            [
                "claude",
                "-p",
                PROMPT,
                "--settings",
                str(settings_file),
                "--session-id",
                session_id,
                "--model",
                model,
                "--output-format",
                "json",
                "--allowed-tools",
                "",
            ],
            cwd=str(workdir),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            raise LiveCheckError(
                f"`claude -p` endete mit Exit {proc.returncode}: {proc.stderr.strip()[:500]}"
            )
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise LiveCheckError(
                f"Antwort von `claude -p` ist kein JSON: {proc.stdout[:500]!r}"
            ) from exc

        answer = payload.get("result") or ""
        transcript = _find_transcript(payload.get("session_id") or session_id)

        return {
            "nonce": nonce,
            "answer": answer,
            "model_saw_nonce": nonce in answer,
            "transcript": str(transcript) if transcript else None,
            "transcript_confirms": bool(
                transcript and _transcript_shows_injection(transcript, nonce)
            ),
            "session_id": payload.get("session_id") or session_id,
            "settings": settings,
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--model", default="haiku", help="Modell fuer den Live-Lauf (default: haiku)"
    )
    parser.add_argument(
        "--timeout", type=int, default=300, help="Timeout in Sekunden (default: 300)"
    )
    parser.add_argument("--json", action="store_true", help="Ergebnis als JSON ausgeben")
    args = parser.parse_args(argv)

    try:
        result = run_live_check(model=args.model, timeout=args.timeout)
    except LiveCheckError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Nonce (nur im temporaeren Vault):  {result['nonce']}")
        print(f"Antwort des Modells:               {result['answer']!r}")
        print(f"Transcript:                        {result['transcript']}")
        print(f"Modell hat den Marker gesehen:     {result['model_saw_nonce']}")
        print(f"Transcript bestaetigt Injection:   {result['transcript_confirms']}")

    if result["model_saw_nonce"]:
        print("\nOK: Der Reinforcement-Hinweis ist im tatsaechlichen Modell-Kontext nachweisbar.")
        return 0
    print(
        "\nFEHLGESCHLAGEN: Der Marker ist nicht in der Modellantwort aufgetaucht.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
