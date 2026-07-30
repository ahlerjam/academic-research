"""TDD-Tests fuer scripts/dev/summarize_eval_junit.py (Issue #470).

Der eval-behavior.yml-Workflow braucht ein Ergebnis, das sich lesbar nach
``$GITHUB_STEP_SUMMARY`` schreiben laesst -- dieses Skript parst die von
pytest erzeugte JUnit-XML und rendert eine kompakte Markdown-Tabelle.
"""

from __future__ import annotations

from pathlib import Path

from scripts.dev import summarize_eval_junit as S


def _write_junit(tmp_path: Path, xml: str) -> Path:
    p = tmp_path / "eval-results.xml"
    p.write_text(xml, encoding="utf-8")
    return p


def test_summarize_single_suite_counts(tmp_path):
    xml = """<?xml version="1.0"?>
    <testsuite name="pytest" tests="10" failures="2" errors="1" skipped="3">
    </testsuite>
    """
    path = _write_junit(tmp_path, xml)
    table = S.summarize(path)
    assert "| Tests gesamt | 10 |" in table
    assert "| bestanden | 4 |" in table
    assert "| fehlgeschlagen | 2 |" in table
    assert "| Fehler | 1 |" in table
    assert "| uebersprungen | 3 |" in table


def test_summarize_testsuites_wrapper_sums_across_suites(tmp_path):
    xml = """<?xml version="1.0"?>
    <testsuites>
      <testsuite name="a" tests="5" failures="0" errors="0" skipped="1"></testsuite>
      <testsuite name="b" tests="7" failures="1" errors="0" skipped="0"></testsuite>
    </testsuites>
    """
    path = _write_junit(tmp_path, xml)
    table = S.summarize(path)
    assert "| Tests gesamt | 12 |" in table
    assert "| bestanden | 10 |" in table
    assert "| fehlgeschlagen | 1 |" in table


def test_summarize_all_passed_zero_failures(tmp_path):
    xml = """<?xml version="1.0"?>
    <testsuite name="pytest" tests="4" failures="0" errors="0" skipped="0"></testsuite>
    """
    path = _write_junit(tmp_path, xml)
    table = S.summarize(path)
    assert "| bestanden | 4 |" in table
    assert "| fehlgeschlagen | 0 |" in table
