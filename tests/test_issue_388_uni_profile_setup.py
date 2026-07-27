"""Regressionstest fuer Issue #388.

Das Uni-Profil-Setup war bisher unverdrahtet: ``scripts/setup.sh`` rief nirgends
``hooks/onboard-project-uni-prompt.sh`` auf, kein Code parste ein ``--uni``-Flag,
und ``library-profiles/active.yaml.template`` wurde nie real kopiert.

Diese Tests pruefen das *reale* Verhalten von ``scripts/uni_profile_setup.py``
(dem neuen, ungeschuetzten Wrapper um den unveraenderten, protected-area-Hook
``hooks/onboard-project-uni-prompt.sh``) sowie die Verdrahtung in
``scripts/setup.sh`` und ``commands/setup.md``.

Akzeptanzkriterien (#388):
1. ``/academic-research:setup --uni tum`` kopiert ``config/library-profiles/tum.yaml``
   real nach ``~/.academic-research/library-profiles/active.yaml``.
2. Setup ohne ``--uni``-Flag fragt interaktiv (Opt-in) nach einem Hochschul-Profil.
3. Bei Opt-out bleibt das aktive Profil leer/Default, ohne Fehler.
4. Ein Test verifiziert, dass nach einem Lauf mit ``--profile <bekanntes Profil>``
   eine ``active.yaml`` mit den Pflichtfeldern existiert.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from jsonschema import validate

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SETUP_SH = SCRIPTS_DIR / "setup.sh"
SETUP_MD = REPO_ROOT / "commands" / "setup.md"
UNI_SCRIPT = SCRIPTS_DIR / "uni_profile_setup.py"
PROFILES_DIR = REPO_ROOT / "config" / "library-profiles"
SCHEMA_PATH = PROFILES_DIR / "_schema.json"


def _load_schema():
    import json

    with open(SCHEMA_PATH) as f:
        return json.load(f)


def _code_only(content: str) -> str:
    """Entfernt reine Kommentarzeilen (Zeilen, die mit ``#`` beginnen).

    Ohne diesen Filter sind Wiring-Checks nicht mutationssensitiv: setup.sh
    erwaehnt sowohl ``uni_profile_setup.py`` als auch ``--uni`` zusaetzlich in
    Kommentaren (Z. 11, 17, 156, 158) — ein naiver ``in content``-Test bleibt
    daher gruen, selbst wenn die echte Verdrahtung geloescht wird (PR #417
    critic, test-gaming-Fund)."""
    return "\n".join(line for line in content.splitlines() if not line.strip().startswith("#"))


def _invokes_uni_profile_setup(content: str) -> bool:
    """True nur, wenn eine echte Code-Zeile den Helper ueber den venv-Python
    aufruft (nicht nur ein Kommentar ihn erwaehnt)."""
    return any(
        "venv/bin/python" in line and "uni_profile_setup.py" in line
        for line in _code_only(content).splitlines()
    )


def _parses_uni_flag(content: str) -> bool:
    """True nur, wenn ein echter ``--uni)``-case-Arm existiert (nicht nur ein
    Kommentar ``--uni`` erwaehnt)."""
    return any(line.strip() == "--uni)" for line in _code_only(content).splitlines())


# ---------------------------------------------------------------------------
# 0. Skript existiert und ist importierbar
# ---------------------------------------------------------------------------


def test_uni_profile_setup_script_exists():
    assert UNI_SCRIPT.exists(), (
        f"scripts/uni_profile_setup.py fehlt — setup.sh kann das Uni-Profil-Setup "
        f"nicht verdrahten ({UNI_SCRIPT})"
    )


def test_uni_profile_setup_importable():
    import uni_profile_setup  # noqa: F401

    assert hasattr(uni_profile_setup, "run_profile_copy")
    assert hasattr(uni_profile_setup, "_prompt_optin")
    assert hasattr(uni_profile_setup, "main")


# ---------------------------------------------------------------------------
# AC1 + AC4 — run_profile_copy kopiert ein bekanntes Profil real nach active.yaml
# ---------------------------------------------------------------------------


def test_run_profile_copy_kopiert_tum_profil(tmp_path):
    import uni_profile_setup

    result = uni_profile_setup.run_profile_copy("tum", output_dir=tmp_path)
    assert result.returncode == 0, f"Hook-Aufruf schlug fehl: {result.stderr}"

    active_yaml = tmp_path / "active.yaml"
    assert active_yaml.exists(), "active.yaml wurde nicht angelegt"

    written = yaml.safe_load(active_yaml.read_text(encoding="utf-8"))
    original = yaml.safe_load((PROFILES_DIR / "tum.yaml").read_text(encoding="utf-8"))
    assert written["uni"] == original["uni"] == "tum"
    assert written["auth_type"] == original["auth_type"] == "Shibboleth"
    assert written["auth_url"] == original["auth_url"]
    assert written["licensed_sites"] == original["licensed_sites"]
    assert written["bib_pickup_url"] == original["bib_pickup_url"]


def test_run_profile_copy_active_yaml_ist_schema_valide(tmp_path):
    import uni_profile_setup

    uni_profile_setup.run_profile_copy("tum", output_dir=tmp_path)
    active_yaml = tmp_path / "active.yaml"
    data = yaml.safe_load(active_yaml.read_text(encoding="utf-8"))
    validate(instance=data, schema=_load_schema())


def test_main_mit_uni_flag_ruft_hook_mit_profile_auf(tmp_path):
    """``main(["--uni", "tum", "--output-dir", ...])`` ruft den Hook mit --profile auf."""
    import uni_profile_setup

    fake_result = MagicMock(returncode=0, stderr="")
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        rc = uni_profile_setup.main(["--uni", "tum", "--output-dir", str(tmp_path)])
    assert rc == 0
    mock_run.assert_called_once()
    called_args = mock_run.call_args[0][0]
    assert "--profile" in called_args
    assert "tum" in called_args


# ---------------------------------------------------------------------------
# AC2 — ohne --uni fragt main() interaktiv (Opt-in) nach einem Profil
# ---------------------------------------------------------------------------


class _FakeStdin:
    def __init__(self, isatty: bool):
        self._isatty = isatty

    def isatty(self):
        return self._isatty


def test_prompt_optin_true_bei_interaktivem_ja(monkeypatch):
    import uni_profile_setup

    monkeypatch.setattr(sys, "stdin", _FakeStdin(isatty=True))
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "j")
    assert uni_profile_setup._prompt_optin() is True


def test_prompt_optin_defaults_false_non_interactive(monkeypatch):
    import uni_profile_setup

    monkeypatch.setattr(sys, "stdin", _FakeStdin(isatty=False))
    assert uni_profile_setup._prompt_optin() is False


def test_main_ohne_uni_flag_fragt_interaktiv_und_ruft_hook_ohne_profile(tmp_path, monkeypatch):
    """Opt-in (isatty=True, Antwort 'j') ruft den Hook OHNE --profile auf (interaktive Auswahl im Hook selbst)."""
    import uni_profile_setup

    monkeypatch.setattr(sys, "stdin", _FakeStdin(isatty=True))
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "j")

    fake_result = MagicMock(returncode=0, stderr="")
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        rc = uni_profile_setup.main(["--output-dir", str(tmp_path)])
    assert rc == 0
    mock_run.assert_called_once()
    called_args = mock_run.call_args[0][0]
    assert "--profile" not in called_args


def test_main_interaktiver_hook_fehler_wird_wie_opt_out_behandelt(tmp_path, monkeypatch, capsys):
    """PR #417 critic (P1): Ein fehlschlagender interaktiver Hook (z.B. Enter
    oder eine ungueltige Nummer bei "Nummer eingeben [1-5]:") darf NICHT als
    Setup-Abbruch durchschlagen. scripts/setup.sh ruft dieses Skript unter
    ``set -euo pipefail`` auf (setup.sh:14); ein ungefiltert durchgereichter
    Hook-Exitcode (uni_profile_setup.py:115) wuerde setup.sh vor Schritt 8
    (SciHub-Opt-in) abbrechen lassen -- Schritt 8 und "Setup complete" liefen
    nie. AC3 deckt sinngemaess auch diesen Fall ab: ein Abbruch am
    Nummern-Prompt ist ebenfalls "keine Uni-Auswahl" und darf keinen Fehler
    verursachen."""
    import uni_profile_setup

    monkeypatch.setattr(sys, "stdin", _FakeStdin(isatty=True))
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "j")

    fake_result = MagicMock(returncode=1, stderr="Ungueltige Auswahl: 6\n")
    with patch("subprocess.run", return_value=fake_result):
        rc = uni_profile_setup.main(["--output-dir", str(tmp_path)])

    assert rc == 0, (
        "main() darf einen fehlgeschlagenen interaktiven Hook nicht als "
        "Setup-Abbruch weiterreichen (verletzt AC3 -- setup.sh wuerde vor "
        "Schritt 8/SciHub abbrechen, vgl. PR #417 critic)"
    )
    assert not (tmp_path / "active.yaml").exists()
    captured = capsys.readouterr()
    assert captured.err.strip(), (
        "Bei Hook-Fehlschlag muss eine Hinweismeldung auf stderr erscheinen, "
        "damit der stumm uebersprungene Schritt nicht unbemerkt bleibt"
    )


# ---------------------------------------------------------------------------
# AC3 — Opt-out: aktives Profil bleibt leer/Default, kein Fehler
# ---------------------------------------------------------------------------


def test_main_non_interactive_ohne_uni_flag_ist_opt_out_ohne_fehler(tmp_path, monkeypatch):
    import uni_profile_setup

    monkeypatch.setattr(sys, "stdin", _FakeStdin(isatty=False))
    with patch("subprocess.run") as mock_run:
        rc = uni_profile_setup.main(["--output-dir", str(tmp_path)])
    assert rc == 0
    mock_run.assert_not_called()
    assert not (tmp_path / "active.yaml").exists()


def test_main_interaktives_opt_out_ruft_hook_nicht_auf(tmp_path, monkeypatch):
    import uni_profile_setup

    monkeypatch.setattr(sys, "stdin", _FakeStdin(isatty=True))
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "N")
    with patch("subprocess.run") as mock_run:
        rc = uni_profile_setup.main(["--output-dir", str(tmp_path)])
    assert rc == 0
    mock_run.assert_not_called()
    assert not (tmp_path / "active.yaml").exists()


# ---------------------------------------------------------------------------
# Verdrahtung — setup.sh ruft uni_profile_setup.py auf, setup.md reicht $ARGUMENTS durch
# ---------------------------------------------------------------------------


def test_setup_sh_invokes_uni_profile_setup():
    content = SETUP_SH.read_text(encoding="utf-8")
    assert _invokes_uni_profile_setup(content), (
        "setup.sh muss den Uni-Profil-Setup-Helper aus echtem Code (nicht nur "
        "einem Kommentar) aufrufen (Issue #388)"
    )


def test_setup_sh_parst_uni_flag():
    content = SETUP_SH.read_text(encoding="utf-8")
    assert _parses_uni_flag(content), (
        "setup.sh muss --uni als echten case-Arm (nicht nur in einem "
        "Kommentar) aus $@ parsen (Issue #388)"
    )


def test_wiring_checks_sind_mutationssensitiv():
    """PR #417 critic (P1): die urspruenglichen Wiring-Asserts pruefen nur
    ``"uni_profile_setup.py" in content`` bzw. ``"--uni" in content`` — beide
    Substrings stehen aber zusaetzlich im Kommentarblock von setup.sh (Z. 11
    ``via uni_profile_setup.py``, Z. 17 ``(--uni <profil>; ...)``). Loescht man
    den echten ``--uni)``-Case-Arm UND den Aufrufblock, aber laesst die
    Kommentare stehen, blieben die alten Asserts gruen (verifiziert im
    Review). Dieser Test reproduziert exakt diese Mutation und verlangt, dass
    die (jetzt strengeren) Wiring-Checks sie erkennen."""
    content = SETUP_SH.read_text(encoding="utf-8")

    case_arm = '    --uni)\n      UNI_PROFILE="$2"\n      shift 2\n      ;;\n'
    invocation_block = (
        'if [ -n "$UNI_PROFILE" ]; then\n'
        '  "$BASE/venv/bin/python" "$SCRIPT_DIR/uni_profile_setup.py" --uni "$UNI_PROFILE"\n'
        "else\n"
        '  "$BASE/venv/bin/python" "$SCRIPT_DIR/uni_profile_setup.py"\n'
        "fi\n"
    )
    assert case_arm in content, "Testannahme veraltet: --uni-Case-Arm-Text hat sich geaendert"
    assert invocation_block in content, (
        "Testannahme veraltet: Invocation-Block-Text hat sich geaendert"
    )

    mutated = content.replace(case_arm, "").replace(invocation_block, "")

    # Die Kommentare (Z. 11, 17, 156, 158) ueberleben die Mutation unangetastet
    # -- ein naiver Substring-Test waere hier weiterhin gruen (das ist exakt
    # der Kritik-Fund).
    assert "uni_profile_setup.py" in mutated
    assert "--uni" in mutated

    # Die tatsaechlichen Wiring-Checks muessen die entfernte Verdrahtung aber
    # erkennen:
    assert not _invokes_uni_profile_setup(mutated), (
        "Wiring-Check erkennt geloeschten Aufrufblock nicht (test-gaming)"
    )
    assert not _parses_uni_flag(mutated), (
        "Wiring-Check erkennt geloeschten --uni-Case-Arm nicht (test-gaming)"
    )


def test_setup_sh_numbering_bleibt_luekenlos():
    """Neuer Schritt darf die bestehende 6->7-Nummerierung nicht kaputt machen —
    SciHub (bisher # 7.) muss auf # 8. verschoben werden, wenn Uni-Profil-Setup
    als neuer # 7.-Schritt eingefuegt wird."""
    content = SETUP_SH.read_text(encoding="utf-8")
    assert "# 6." in content
    assert "# 7." in content
    assert "# 8." in content
    six = content.index("# 6.")
    seven = content.index("# 7.")
    eight = content.index("# 8.")
    assert six < seven < eight


def test_setup_sh_bash_syntax_valide():
    result = subprocess.run(["bash", "-n", str(SETUP_SH)], capture_output=True, text=True)
    assert result.returncode == 0, f"bash -n schlug fehl: {result.stderr}"


def test_setup_md_reicht_arguments_durch():
    content = SETUP_MD.read_text(encoding="utf-8")
    assert "$ARGUMENTS" in content, (
        "commands/setup.md muss $ARGUMENTS an scripts/setup.sh durchreichen, "
        "sonst kommt --uni nie bei setup.sh an (Issue #388)"
    )
