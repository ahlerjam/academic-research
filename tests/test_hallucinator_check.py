"""Tests fuer den optionalen hallucinator-cli-Wrapper (Issue #398).

hallucinator (gianlucasb, AGPL-3.0) ist ein separates externes CLI-Tool
(https://github.com/gianlucasb/hallucinator), das per Subprozess aufgerufen
wird -- nie als Python-Bibliothek importiert, nie im Repo vendored.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# AC1: Binary fehlt -> klare Fehlermeldung, kein Traceback, kein Absturz
# ---------------------------------------------------------------------------


class TestMissingBinary:
    """Tests fuer den Fall, dass hallucinator-cli nicht im PATH ist."""

    def test_missing_binary_raises_clean_runtime_error(self):
        """shutil.which -> None fuehrt zu RuntimeError mit Installationshinweis."""
        from hallucinator_check import run_hallucinator_check

        with patch("hallucinator_check.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="hallucinator-cli nicht gefunden"):
                run_hallucinator_check("dummy.pdf")

    def test_main_missing_binary_exits_cleanly(self, capsys):
        """main() faengt RuntimeError ab und beendet mit sys.exit(1) statt Traceback."""
        from hallucinator_check import main

        with patch("hallucinator_check.shutil.which", return_value=None):
            with pytest.raises(SystemExit) as exc_info:
                main(["dummy.pdf"])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "hallucinator-cli nicht gefunden" in captured.err
        assert "Traceback" not in captured.err
        assert "Traceback" not in captured.out


# ---------------------------------------------------------------------------
# AC2: Binary installiert, gemockter Subprozess -> strukturiertes Ergebnis
# ---------------------------------------------------------------------------


class TestParseOutputSuccess:
    """Tests fuer erfolgreichen (gemockten) hallucinator-cli-Aufruf."""

    SAMPLE_STDOUT = (
        "[1/4] Smith et al., 2020 -- Verified\n"
        "[2/4] Doe, 2019 -- Author Mismatch\n"
        "[3/4] Fake Author, 2099 -- Not Found (Potential Hallucination)\n"
        "[4/4] Roe, 2021 -- Verified (Web Search)\n"
    )

    def test_parse_output_success(self):
        """Bekannte Statuskategorien werden korrekt gezaehlt, Rohtext bleibt erhalten."""
        from hallucinator_check import parse_hallucinator_output

        result = parse_hallucinator_output(self.SAMPLE_STDOUT)

        assert result["verified"] == 1
        assert result["author_mismatch"] == 1
        assert result["not_found"] == 1
        assert result["verified_web_search"] == 1
        assert result["raw_output"] == self.SAMPLE_STDOUT

    def test_run_hallucinator_check_success(self):
        """run_hallucinator_check ruft subprocess.run korrekt auf und liefert geparstes Ergebnis."""
        from hallucinator_check import run_hallucinator_check

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = self.SAMPLE_STDOUT.encode()
        mock_result.stderr = b""

        with patch(
            "hallucinator_check.shutil.which",
            return_value="/usr/local/bin/hallucinator-cli",
        ):
            with patch("hallucinator_check.subprocess.run", return_value=mock_result) as mock_run:
                result = run_hallucinator_check("paper.pdf")

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "hallucinator-cli"
        assert "paper.pdf" in call_args

        assert result["verified"] == 1
        assert result["not_found"] == 1
        assert result["returncode"] == 0


# ---------------------------------------------------------------------------
# Optionales Vault-Logging -- darf den Check-Exit-Code nie beeinflussen
# ---------------------------------------------------------------------------


class TestRecordVaultDecision:
    """Tests fuer das optionale Festhalten des Ergebnisses als Vault-Decision."""

    def test_record_vault_decision_writes_decision(self, temp_vault_db):
        """Bei gueltigem Vault wird eine Decision mit Kategorie hallucinator-check angelegt."""
        from academic_vault.server import list_decisions

        from hallucinator_check import record_vault_decision

        result = {
            "verified": 2,
            "author_mismatch": 0,
            "not_found": 1,
            "verified_web_search": 0,
            "raw_output": "irrelevant",
            "returncode": 0,
        }

        record_vault_decision(temp_vault_db, result, "paper.pdf")

        decisions = list_decisions(temp_vault_db, category="hallucinator-check")
        assert len(decisions) == 1
        assert "paper.pdf" in decisions[0]["text"]

    def test_record_vault_decision_never_raises_on_bad_db(self):
        """Ein defekter/nicht existenter DB-Pfad darf keine Exception nach oben werfen."""
        from hallucinator_check import record_vault_decision

        result = {
            "verified": 0,
            "author_mismatch": 0,
            "not_found": 0,
            "verified_web_search": 0,
            "raw_output": "",
            "returncode": 0,
        }

        # Kein Traceback erwartet, auch wenn der Pfad in ein nicht existentes
        # Verzeichnis zeigt.
        record_vault_decision("/nonexistent/dir/vault.db", result, "paper.pdf")


# ---------------------------------------------------------------------------
# Fix-Runde PR #436 (Issue #398): --db ueber den echten CLI-Aufruf wirkungslos
# ---------------------------------------------------------------------------
#
# Die bisherigen Tests oben rufen record_vault_decision() In-Process auf.
# Dabei liegt das Repo-Root laengst auf sys.path (ueber tests/conftest.py),
# weshalb `from academic_vault.server import add_decision` dort immer
# funktioniert -- der eigentliche Bug bleibt unsichtbar. Der Bug zeigt sich
# erst, wenn das Skript wie dokumentiert per echtem Subprozessaufruf
# (`python scripts/hallucinator_check.py ...`) gestartet wird: dann setzt
# Python sys.path[0] auf das Skriptverzeichnis (scripts/), nicht auf das
# Repo-Root, wodurch der academic_vault-Import mit ModuleNotFoundError
# scheitert -- und das wurde bislang von `except Exception: pass` komplett
# verschluckt (kein stderr, Exit 0, keine Vault-Decision).


class TestDbFlagViaRealCliInvocation:
    """Reproduziert den Bug ueber einen echten Subprozessaufruf des Skripts."""

    def test_db_flag_persists_decision_via_real_cli_invocation(self, tmp_path):
        fake_bin_dir = tmp_path / "fake-bin"
        fake_bin_dir.mkdir()
        fake_cli = fake_bin_dir / "hallucinator-cli"
        fake_cli.write_text("#!/bin/sh\necho 'Verified: 1'\n")
        fake_cli.chmod(0o755)

        pdf_path = tmp_path / "paper.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        db_path = tmp_path / "vault.db"

        script_path = REPO_ROOT / "scripts" / "hallucinator_check.py"

        env = dict(os.environ)
        env["PATH"] = f"{fake_bin_dir}{os.pathsep}{env.get('PATH', '')}"
        # PYTHONPATH bewusst NICHT gesetzt -- reproduziert einen sauberen,
        # dokumentierten Aufruf ohne Test-Infrastruktur-Krücken.
        env.pop("PYTHONPATH", None)

        proc = subprocess.run(
            [sys.executable, str(script_path), str(pdf_path), "--db", str(db_path)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
        )

        assert proc.returncode == 0, (
            f"unerwarteter Exit-Code {proc.returncode} (stderr={proc.stderr!r})"
        )
        assert db_path.exists(), (
            "Vault-DB wurde nie angelegt -- --db ist ueber den echten CLI-Aufruf "
            f"wirkungslos (stdout={proc.stdout!r}, stderr={proc.stderr!r})"
        )

        from academic_vault.server import list_decisions

        decisions = list_decisions(str(db_path), category="hallucinator-check")
        assert len(decisions) == 1
        assert "paper.pdf" in decisions[0]["text"]


# ---------------------------------------------------------------------------
# Fix-Runde PR #436 (Issue #398): Nicht-Null-Exit/stderr von hallucinator-cli
# wurden verworfen, main() endete immer mit Exit 0.
# ---------------------------------------------------------------------------


class TestNonZeroExitAndStderrPropagation:
    """main() muss einen fehlgeschlagenen hallucinator-cli-Lauf sichtbar machen."""

    def test_main_propagates_nonzero_returncode_and_stderr(self, capsys):
        from hallucinator_check import main

        mock_result = MagicMock()
        mock_result.returncode = 2
        mock_result.stdout = b"[1/2] Foo -- Not Found\n"
        mock_result.stderr = b"hallucinator-cli: fatal: corrupt PDF\n"

        with patch(
            "hallucinator_check.shutil.which",
            return_value="/usr/local/bin/hallucinator-cli",
        ):
            with patch("hallucinator_check.subprocess.run", return_value=mock_result):
                with pytest.raises(SystemExit) as exc_info:
                    main(["paper.pdf"])

        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "corrupt PDF" in captured.err

    def test_main_exits_zero_when_returncode_zero(self, capsys):
        """Regressionsguard: Erfolgsfall (Exit 0) darf durch den Fix nicht brechen."""
        from hallucinator_check import main

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b"[1/1] Foo -- Verified\n"
        mock_result.stderr = b""

        with patch(
            "hallucinator_check.shutil.which",
            return_value="/usr/local/bin/hallucinator-cli",
        ):
            with patch("hallucinator_check.subprocess.run", return_value=mock_result):
                main(["paper.pdf"])  # darf NICHT per SystemExit(!=0) abbrechen

        captured = capsys.readouterr()
        assert "Verified" in captured.out


# ---------------------------------------------------------------------------
# Fix-Runde PR #436 (Issue #398): 'cargo install hallucinator' existiert nicht
# (crates.io-API https://crates.io/api/v1/crates/hallucinator -> HTTP 404,
# verifiziert 2026-07-28). Docs/INSTALL_HINT duerfen diesen Weg nicht mehr
# nennen.
# ---------------------------------------------------------------------------


class TestInstallInstructionsAccuracy:
    """Regressionsguard gegen den falschen cargo-Installationsweg."""

    def test_install_hint_drops_nonexistent_cargo_crate(self):
        from hallucinator_check import INSTALL_HINT

        assert "cargo install hallucinator" not in INSTALL_HINT
        assert "pip install hallucinator" in INSTALL_HINT

    def test_module_docstring_drops_nonexistent_cargo_crate(self):
        import hallucinator_check

        assert "cargo install hallucinator" not in (hallucinator_check.__doc__ or "")

    def test_installation_doc_drops_nonexistent_cargo_crate(self):
        from tests.helpers import docs as _docs

        text = _docs.INSTALLATION_DOC.read_text(encoding="utf-8")
        assert "cargo install hallucinator" not in text
        assert "pip install hallucinator" in text


# ---------------------------------------------------------------------------
# AC3 + AC4: Kein Vendoring, kein Paketeintrag (Regressionsguards)
# ---------------------------------------------------------------------------


class TestNoVendoringNoDependency:
    """Regressionsguards gegen versehentliches Vendoring/Bundling von hallucinator."""

    def test_no_vendored_hallucinator_source(self):
        """Kein hallucinator-Quellcode (z.B. hallucinator-rs/, Cargo.toml) im Repo."""
        markers_found = []
        for path in REPO_ROOT.rglob("*"):
            if ".git" in path.parts:
                continue
            name = path.name.lower()
            if name == "hallucinator-rs" or (
                name == "cargo.toml"
                and path.is_file()
                and "hallucinator" in path.read_text(errors="replace").lower()
            ):
                markers_found.append(str(path))

        assert markers_found == []

    def test_no_hallucinator_dependency_entry(self):
        """pyproject.toml und scripts/requirements.txt referenzieren hallucinator nicht als Paket."""
        pyproject = (REPO_ROOT / "pyproject.toml").read_text().lower()
        requirements = (REPO_ROOT / "scripts" / "requirements.txt").read_text().lower()

        assert "hallucinator" not in pyproject
        assert "hallucinator" not in requirements
