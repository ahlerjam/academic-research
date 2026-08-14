"""Issue #877: Skill fuer die Zuruf-Abfrage des Phasenstands.

AC4: "was ist der naechste Schritt" (und die drei weiteren Trigger-
Formulierungen aus dem Issue) wird ohne eigenen Command beantwortet.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SKILL_PATH = REPO_ROOT / "skills" / "workflow-status" / "SKILL.md"

TRIGGER_PHRASES = [
    "wo stehe ich",
    "was ist der naechste Schritt",
    "wie geht es weiter",
    "Stand der Arbeit",
]


def _frontmatter_description() -> str:
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md hat kein YAML-Frontmatter"
    end = text.index("\n---", 4)
    frontmatter = text[4:end]
    for line in frontmatter.splitlines():
        if line.startswith("description:"):
            return line[len("description:") :].strip()
    raise AssertionError("Frontmatter hat kein 'description'-Feld")


def test_skill_exists() -> None:
    assert SKILL_PATH.is_file(), "skills/workflow-status/SKILL.md fehlt"


def test_skill_frontmatter_has_name_and_description() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.index("\n---", 4)
    frontmatter = text[4:end]
    assert "name:" in frontmatter
    assert "description:" in frontmatter


def test_skill_description_contains_all_trigger_phrases_verbatim() -> None:
    """Die vier Trigger-Formulierungen aus dem Issue-Body muessen woertlich
    im Frontmatter-'description' stehen -- nur so aktiviert sich der Skill
    zuverlaessig auf Zuruf."""
    description = _frontmatter_description()
    for phrase in TRIGGER_PHRASES:
        assert phrase in description, (
            f"Trigger-Formulierung {phrase!r} fehlt woertlich in der description: {description!r}"
        )


def test_skill_references_full_flag_of_workflow_status_script() -> None:
    """Der Skill ruft scripts/workflow_status.py mit --full auf, damit die
    Antwort die Restkette bis 'export' enthaelt (AC4), nicht nur den
    naechsten Schritt."""
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "workflow_status.py" in text
    assert "--full" in text


def test_skill_invokes_script_via_python_interpreter() -> None:
    """Review-Fund (PR #930): scripts/workflow_status.py hat kein
    Executable-Bit und keinen wirksamen Shebang bei direktem Aufruf ueber das
    Bash-Tool. Der Skill muss das Skript deshalb explizit ueber einen
    Python-Interpreter aufrufen (Muster: hooks/hooks.json ruft dasselbe
    Skript mit vorangestelltem 'python3' auf), statt es wie ein eigenes
    Kommando zu starten."""
    text = SKILL_PATH.read_text(encoding="utf-8")
    match = re.search(r"`([^`]*workflow_status\.py[^`]*)`", text)
    assert match, "Kein Aufruf-Kommando fuer workflow_status.py im Skill-Text gefunden"
    command = match.group(1)
    prefix = command.split("workflow_status.py", 1)[0]
    assert re.search(r"\bpython3?\b", prefix), (
        f"workflow_status.py wird ohne vorangestellten Python-Interpreter aufgerufen: "
        f"{command!r} -- das Skript ist nicht ausfuehrbar (kein Executable-Bit)."
    )


def test_skill_mentions_trigger_attribution() -> None:
    """Skill-Text nennt explizit, dass Claude bzw. Operator je Schritt der
    Ausloeser ist (Issue-Scope: 'Die Ausgabe nennt bei jedem Schritt, wer ihn
    ausloest')."""
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "Claude" in text
    assert "Operator" in text
