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
    assert "uni_profile_setup.py" in content, (
        "setup.sh muss den Uni-Profil-Setup-Helper aufrufen (Issue #388)"
    )


def test_setup_sh_parst_uni_flag():
    content = SETUP_SH.read_text(encoding="utf-8")
    assert "--uni" in content, "setup.sh muss --uni aus $@ parsen (Issue #388)"


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
