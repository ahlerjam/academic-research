"""Tests fuer den optionalen hallucinator-cli-Wrapper (Issue #398).

hallucinator (gianlucasb, AGPL-3.0) ist ein separates externes CLI-Tool
(https://github.com/gianlucasb/hallucinator), das per Subprozess aufgerufen
wird -- nie als Python-Bibliothek importiert, nie im Repo vendored.
"""

from __future__ import annotations

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
