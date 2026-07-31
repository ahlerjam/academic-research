"""Uni-Profil-Setup (Issue #388) — wird von setup.sh aufgerufen.

Verdrahtet das bereits vollstaendig implementierte, aber bisher unaufgerufene
Uni-Profil-Onboarding: ``commands/setup.md`` deklariert ein ``--uni <profil>``
Flag und ``library-profiles/active.yaml.template`` behauptet einen
Kopiervorgang nach ``~/.academic-research/library-profiles/active.yaml`` — bis
hierher fuehrte kein Code-Pfad diesen Kopiervorgang tatsaechlich aus.

``hooks/lib/onboard-project-uni-prompt.sh`` (protected area laut
``.claude/workflow.config.json``) implementiert die eigentliche Profil-Auswahl
und den Kopiervorgang bereits vollstaendig und bleibt hier unveraendert. Dieses
Modul kapselt nur die ``--uni``/Opt-in-Logik (Bauplan: ``scihub_optin.py``) und
ruft den Hook als Subprozess auf.

Verhalten:
- ``--uni <profil>``: Hook wird direkt mit ``--profile <profil>`` aufgerufen
  (nicht-interaktiv).
- Kein ``--uni`` + interaktives stdin: fragt Opt-in ("Hochschul-Profil jetzt
  auswaehlen? [j/N]"). Bei Zustimmung wird der Hook OHNE ``--profile``
  aufgerufen, der Hook fragt dann selbst interaktiv nach der Uni-Nummer
  (echtes stdin/stdout wird durchgereicht, kein capture_output).
- Kein ``--uni`` + nicht-interaktives stdin ODER Opt-out: kein Hook-Aufruf,
  kein Fehler, aktives Profil bleibt leer/Default (Exit 0).
- Schlaegt der interaktive Hook fehl (z.B. ungueltige Nummern-Eingabe bei der
  Profil-Auswahl): wird wie ein Opt-out behandelt — Warnung auf stderr, aktives
  Profil bleibt leer/Default, Exit 0. ``setup.sh`` ruft dieses Skript unter
  ``set -euo pipefail`` auf; ein ungefiltert durchgereichter Hook-Exitcode
  wuerde das gesamte Setup vor Schritt 8 (SciHub-Opt-in) abbrechen lassen
  (vgl. PR #417 critic).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROMPT = "Hochschul-Profil jetzt auswaehlen (Opt-in)? [j/N] "

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "lib" / "onboard-project-uni-prompt.sh"


def _default_output_dir() -> Path:
    return Path.home() / ".academic-research" / "library-profiles"


def _prompt_optin() -> bool:
    """Interaktive Opt-in-Frage. Bei nicht-interaktivem stdin: sicherer Default ``False``."""
    if not sys.stdin.isatty():
        return False
    answer = input(PROMPT).strip().lower()
    return answer in ("j", "ja", "y", "yes")


def run_profile_copy(profile: str, output_dir: Path | None = None) -> subprocess.CompletedProcess:
    """Ruft den (unveraenderten) Hook mit ``--profile <profile>`` auf.

    Reicht echtes stdin/stdout/stderr durch (kein capture_output), da der Hook
    bei fehlendem Profil interaktiv nachfragen kann — hier wird das Profil
    aber bereits explizit uebergeben, daher rein informativ nicht-interaktiv.
    """
    args = ["bash", str(HOOK_PATH), "--profile", profile]
    out_dir = output_dir if output_dir is not None else _default_output_dir()
    args += ["--output-dir", str(out_dir)]
    return subprocess.run(args, capture_output=True, text=True)


def _run_interactive_hook(output_dir: Path | None = None) -> subprocess.CompletedProcess:
    """Ruft den Hook OHNE ``--profile`` auf — der Hook fragt dann selbst interaktiv.

    Reicht reales stdin/stdout durch (kein capture_output), sonst haengt die
    numerierte Profil-Auswahl im Hook oder bricht ab.
    """
    args = ["bash", str(HOOK_PATH)]
    out_dir = output_dir if output_dir is not None else _default_output_dir()
    args += ["--output-dir", str(out_dir)]
    return subprocess.run(args)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    profile: str | None = None
    output_dir: Path | None = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--uni":
            if i + 1 >= len(argv):
                print("Fehler: --uni erwartet einen Profil-Namen.", file=sys.stderr)
                return 1
            profile = argv[i + 1]
            i += 2
            continue
        if arg == "--output-dir":
            if i + 1 >= len(argv):
                print("Fehler: --output-dir erwartet einen Pfad.", file=sys.stderr)
                return 1
            output_dir = Path(argv[i + 1])
            i += 2
            continue
        print(f"Unbekanntes Argument: {arg}", file=sys.stderr)
        return 1

    if profile is not None:
        result = run_profile_copy(profile, output_dir=output_dir)
        if result.returncode != 0:
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="")
            return result.returncode
        print(f"✅ Uni-Profil '{profile}' aktiviert.")
        return 0

    if not _prompt_optin():
        print("ℹ️  Uni-Profil-Setup uebersprungen (Default) — aktives Profil bleibt leer/Default.")
        return 0

    result = _run_interactive_hook(output_dir=output_dir)
    if result.returncode != 0:
        # Ein fehlgeschlagener interaktiver Hook (z.B. ungueltige Nummern-
        # Eingabe, hooks/lib/onboard-project-uni-prompt.sh:68-69) wird wie ein
        # Opt-out behandelt: NICHT den Hook-Exitcode ungefiltert durchreichen,
        # sonst bricht setup.sh (set -euo pipefail) vor Schritt 8 (SciHub-
        # Opt-in) und der Abschlussmeldung ab (PR #417 critic, Issue #388 AC3).
        print(
            "⚠️  Uni-Profil-Setup uebersprungen (Hook-Fehler oder ungueltige "
            "Auswahl) — aktives Profil bleibt leer/Default, Setup wird fortgesetzt.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
