"""Regressionstests fuer Issue #458 — Zustimmung vor Browser-Zugriff mit
Hochschul-Zugangsdaten (Tiefensuche-Modus).

Akzeptanzkriterien (Issue #458):
- AC4: Der erste Lauf des Tiefensuche-Modus holt eine erklaerte Zustimmung
  ein, bevor Hochschul-Zugangsdaten verwendet werden.
- AC5: Die Zustimmung wird gespeichert und nicht bei jedem Lauf erneut
  abgefragt.

Zusaetzlich: commands/search.md muss den Consent-Schritt textuell VOR dem
Auth-Modul-Abschnitt platzieren (Reihenfolge-Pruefung wie in
test_issue_238_search_allowed_tools_consistency.py), und allowed-tools muss
AskUserQuestion konsistent deklarieren.
"""

from __future__ import annotations

import json
from pathlib import Path

import deep_search_consent

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCH_COMMAND = REPO_ROOT / "commands" / "search.md"
SEARCH_REFERENCE_DOC = REPO_ROOT / "docs" / "reference" / "search.md"

# ---------------------------------------------------------------------------
# AC4: has_consent() False ohne vorhandene consent.json
# ---------------------------------------------------------------------------


def test_has_consent_false_when_file_missing(tmp_path):
    consent_path = tmp_path / "consent.json"
    assert deep_search_consent.has_consent(consent_path) is False


def test_has_consent_false_on_malformed_json(tmp_path):
    consent_path = tmp_path / "consent.json"
    consent_path.write_text("{not valid json", encoding="utf-8")
    assert deep_search_consent.has_consent(consent_path) is False


def test_has_consent_false_when_key_missing(tmp_path):
    consent_path = tmp_path / "consent.json"
    consent_path.write_text(json.dumps({"other_flag": True}), encoding="utf-8")
    assert deep_search_consent.has_consent(consent_path) is False


# ---------------------------------------------------------------------------
# AC5: record_consent() -> has_consent() True, kein erneutes Fragen, idempotent
# ---------------------------------------------------------------------------


def test_record_consent_then_has_consent_true(tmp_path):
    consent_path = tmp_path / "consent.json"
    assert deep_search_consent.has_consent(consent_path) is False

    deep_search_consent.record_consent(consent_path)

    # Unabhaengiger, zweiter has_consent()-Aufruf -> True, ohne erneuten Prompt.
    assert deep_search_consent.has_consent(consent_path) is True


def test_record_consent_idempotent(tmp_path):
    consent_path = tmp_path / "consent.json"
    deep_search_consent.record_consent(consent_path)
    first = consent_path.read_text(encoding="utf-8")

    deep_search_consent.record_consent(consent_path)
    second = consent_path.read_text(encoding="utf-8")

    data = json.loads(second)
    assert data[deep_search_consent.DEEP_SEARCH_CONSENT_KEY] is True
    assert first == second


def test_record_consent_preserves_other_keys(tmp_path):
    consent_path = tmp_path / "consent.json"
    consent_path.write_text(json.dumps({"other_flag": "kept"}), encoding="utf-8")

    deep_search_consent.record_consent(consent_path)

    data = json.loads(consent_path.read_text(encoding="utf-8"))
    assert data["other_flag"] == "kept"
    assert data[deep_search_consent.DEEP_SEARCH_CONSENT_KEY] is True


def test_record_consent_creates_parent_dir(tmp_path):
    consent_path = tmp_path / "nested" / "consent.json"
    deep_search_consent.record_consent(consent_path)
    assert consent_path.exists()
    assert deep_search_consent.has_consent(consent_path) is True


# ---------------------------------------------------------------------------
# CLI-Fassade (main(), fuer den Aufruf aus commands/search.md)
# ---------------------------------------------------------------------------


def test_main_check_prints_no_without_consent(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        deep_search_consent, "_default_consent_path", lambda: tmp_path / "consent.json"
    )
    rc = deep_search_consent.main()
    assert rc == 0
    assert capsys.readouterr().out.strip() == "no"


def test_main_record_then_check_prints_yes(tmp_path, monkeypatch, capsys):
    import sys

    monkeypatch.setattr(
        deep_search_consent, "_default_consent_path", lambda: tmp_path / "consent.json"
    )
    monkeypatch.setattr(sys, "argv", ["deep_search_consent.py", "--record"])
    rc = deep_search_consent.main()
    assert rc == 0
    capsys.readouterr()  # clear buffer from --record output

    monkeypatch.setattr(sys, "argv", ["deep_search_consent.py"])
    rc = deep_search_consent.main()
    assert rc == 0
    assert capsys.readouterr().out.strip() == "yes"


# ---------------------------------------------------------------------------
# commands/search.md: Reihenfolge + allowed-tools
# ---------------------------------------------------------------------------


def test_search_command_has_consent_gate_before_auth_modules():
    content = SEARCH_COMMAND.read_text(encoding="utf-8")

    consent_idx = content.find("deep_search_consent")
    # "Pro Modul:" markiert den Beginn der tatsaechlichen Ausfuehrungsschleife
    # (browser-use open/state/input/click), in der HAN-Login mit Hochschul-
    # Zugangsdaten passiert — der Consent-Schritt muss textuell davor stehen.
    per_module_loop_idx = content.find("Pro Modul:")

    assert consent_idx != -1, "search.md muss den Consent-Schritt referenzieren"
    assert per_module_loop_idx != -1, "search.md muss die Pro-Modul-Ausfuehrungsschleife enthalten"
    assert consent_idx < per_module_loop_idx, (
        "Der Consent-Schritt muss textuell VOR der Pro-Modul-Ausfuehrungsschleife "
        "stehen (Issue #458 AC4)"
    )


def test_search_command_allowed_tools_includes_ask_user_question():
    content = SEARCH_COMMAND.read_text(encoding="utf-8")
    frontmatter = content.split("---")[1]
    for line in frontmatter.splitlines():
        if line.strip().startswith("allowed-tools:"):
            assert "AskUserQuestion" in line, (
                "search.md nutzt AskUserQuestion fuer das Consent-Gate, "
                "muss es aber auch in allowed-tools deklarieren"
            )
            return
    raise AssertionError("Kein 'allowed-tools:' in search.md-Frontmatter gefunden")


def test_search_command_mentions_record_and_check():
    content = SEARCH_COMMAND.read_text(encoding="utf-8")
    assert "--check" in content
    assert "--record" in content


# ---------------------------------------------------------------------------
# Doku: ToS-Hinweise + Consent-Speicherort
# ---------------------------------------------------------------------------


def test_reference_doc_names_platforms_and_consent_storage():
    content = SEARCH_REFERENCE_DOC.read_text(encoding="utf-8")
    for platform in ("EBSCOhost", "ProQuest", "HAN"):
        assert platform in content, f"docs/reference/search.md muss {platform} nennen"
    assert "consent.json" in content, (
        "docs/reference/search.md muss den Speicherort der Zustimmung nennen"
    )
