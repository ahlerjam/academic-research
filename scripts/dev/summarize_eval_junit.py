"""Rendert eine JUnit-XML (von ``pytest --junitxml``) als kompakte Markdown-Tabelle.

Genutzt vom Workflow ``.github/workflows/eval-behavior.yml`` (Issue #470), um das
Ergebnis der Verhaltens-Evals sichtbar nach ``$GITHUB_STEP_SUMMARY`` zu schreiben,
statt es nur im Job-Log zu verstecken.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def summarize(junit_path: Path) -> str:
    """Liest eine JUnit-XML-Datei und liefert eine Markdown-Tabelle mit den Zaehlern.

    Unterstuetzt sowohl ein einzelnes ``<testsuite>``-Wurzelelement als auch den
    ``<testsuites>``-Wrapper mit mehreren Suiten (Zaehler werden aufsummiert).
    """
    root = ET.parse(junit_path).getroot()
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]

    tests = sum(int(s.get("tests", 0)) for s in suites)
    failures = sum(int(s.get("failures", 0)) for s in suites)
    errors = sum(int(s.get("errors", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    passed = tests - failures - errors - skipped

    lines = [
        "| Tests gesamt | " + str(tests) + " |",
        "| --- | --- |",
        "| bestanden | " + str(passed) + " |",
        "| fehlgeschlagen | " + str(failures) + " |",
        "| Fehler | " + str(errors) + " |",
        "| uebersprungen | " + str(skipped) + " |",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: summarize_eval_junit.py <junit.xml>", file=sys.stderr)
        return 2
    print(summarize(Path(argv[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
