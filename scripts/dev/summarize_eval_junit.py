"""Rendert eine JUnit-XML (von ``pytest --junitxml``) als kompakte Markdown-Tabelle.

Genutzt vom Workflow ``.github/workflows/eval-behavior.yml`` (Issue #470), um das
Ergebnis der Verhaltens-Evals sichtbar nach ``$GITHUB_STEP_SUMMARY`` zu schreiben,
statt es nur im Job-Log zu verstecken.

Seit Issue #824 bleibt es nicht bei der Zahl: uebersprungene Faelle werden
**namentlich mit Grund** aufgelistet. Ein Zaehler allein macht einen
Dauer-Skip unsichtbar -- genau das Muster, das Issue #470 schon einmal
behoben hat ("taeuschend gruen, 0 real geprueft, N geskippt"). Wer im
Step-Summary nur "uebersprungen: 12" liest, sieht nicht, dass die
Kernfunktion darunter liegt.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

#: Maximale Zahl namentlich gelisteter Skips, damit das Step-Summary bei
#: einem CLI-losen Lauf (dort skippt praktisch alles) nicht ausufert.
MAX_LISTED_SKIPS = 40


def collect_skipped(junit_path: Path) -> list[tuple[str, str]]:
    """Liest ``[(node_id, grund), ...]`` aller uebersprungenen Faelle, sortiert."""
    root = ET.parse(junit_path).getroot()
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
    skipped: list[tuple[str, str]] = []
    for suite in suites:
        for case in suite.findall("testcase"):
            element = case.find("skipped")
            if element is None:
                continue
            classname = case.get("classname", "")
            name = case.get("name", "")
            node_id = f"{classname}::{name}" if classname else name
            skipped.append((node_id, element.get("message", "")))
    return sorted(skipped)


def _skip_section(skipped: list[tuple[str, str]]) -> list[str]:
    """Markdown-Abschnitt mit den uebersprungenen Faellen (leer, wenn keine)."""
    if not skipped:
        return []
    lines = ["", "### Uebersprungene Faelle", "", "| Fall | Grund |", "| --- | --- |"]
    for node_id, message in skipped[:MAX_LISTED_SKIPS]:
        # Pipes im Grund wuerden die Tabelle zerreissen.
        safe = message.replace("|", "\\|").replace("\n", " ").strip()
        lines.append(f"| `{node_id}` | {safe or '(ohne Grund)'} |")
    if len(skipped) > MAX_LISTED_SKIPS:
        lines.append(f"| … | {len(skipped) - MAX_LISTED_SKIPS} weitere (siehe JUnit-XML) |")
    return lines


def summarize(junit_path: Path) -> str:
    """Liest eine JUnit-XML-Datei und liefert eine Markdown-Tabelle mit den Zaehlern.

    Unterstuetzt sowohl ein einzelnes ``<testsuite>``-Wurzelelement als auch den
    ``<testsuites>``-Wrapper mit mehreren Suiten (Zaehler werden aufsummiert).
    Uebersprungene Faelle werden zusaetzlich namentlich mit Grund gelistet
    (Issue #824).
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
    lines += _skip_section(collect_skipped(junit_path))
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: summarize_eval_junit.py <junit.xml>", file=sys.stderr)
        return 2
    print(summarize(Path(argv[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
