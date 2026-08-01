"""Regressionstests fuer Issue #528 — quality-reviewer eskaliert ab Iteration 2
an den User, statt automatisch PASS-with-warnings zu liefern (Audit R6).

Befund: `agents/quality-reviewer.md` gab bei `iteration >= 2` unabhaengig von
offenen Findings ein PASS-with-warnings zurueck (Z. 41 „Loop-Begrenzung" und
Z. 91 Strategie-Punkt 5), die Spiegelstelle
`skills/chapter-writer/references/quality-review-config.md:32` schrieb dasselbe
vor. Das Qualitaets-Gate war damit genau dann wirkungslos, wenn es zaehlt.

Fix (dieser Test deckt ihn ab):
- Der Agent kennt ein drittes Verdict `ESCALATE`, das an `iteration >= 2`
  **und** mindestens ein FAIL gekoppelt ist. Ohne offenes Finding bleibt PASS.
- Das Entscheidungs-Gate liegt beim Aufrufer (der Agent laeuft mit
  `tools: [Read]` und erreicht `AskUserQuestion` nicht): Die Referenz
  beschreibt `AskUserQuestion` mit genau drei Optionen (akzeptieren /
  weitere Revision / abbrechen), `chapter-writer` deklariert das Tool.
- Die Loop-Begrenzung bleibt: „weitere Revision" gewaehrt genau eine
  zusaetzliche Runde, danach wird erneut eskaliert.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT = REPO_ROOT / "agents" / "quality-reviewer.md"
REFERENCE = REPO_ROOT / "skills" / "chapter-writer" / "references" / "quality-review-config.md"
CHAPTER_WRITER = REPO_ROOT / "skills" / "chapter-writer" / "SKILL.md"
ADVISOR = REPO_ROOT / "skills" / "advisor" / "SKILL.md"
ABSTRACT_GENERATOR = REPO_ROOT / "skills" / "abstract-generator" / "SKILL.md"
EVALS = REPO_ROOT / "evals" / "quality-reviewer" / "evals.json"
AGENTS_DOC = REPO_ROOT / "docs" / "reference" / "agents.md"

OPTION_TERMS = ("akzeptieren", "weitere revision", "abbrechen")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _frontmatter(path: Path) -> dict[str, Any]:
    """Nur den YAML-Frontmatter-Block parsen (nicht den Fliesstext)."""
    content = _read(path)
    assert content.startswith("---\n"), f"{path.name} hat keinen Frontmatter-Block"
    _, block, _ = content.split("---\n", 2)
    parsed = yaml.safe_load(block)
    assert isinstance(parsed, dict), f"{path.name}: Frontmatter ist kein Mapping"
    return parsed


def _body(path: Path) -> str:
    """Fliesstext ohne YAML-Frontmatter — verhindert tautologische Treffer."""
    content = _read(path)
    if content.startswith("---\n"):
        return content.split("---\n", 2)[2]
    return content


def _section(content: str, heading: str) -> str:
    """Abschnitt ab `heading` bis zur naechsten Ueberschrift gleicher Ebene."""
    start = content.find(heading)
    assert start != -1, f"Abschnitt {heading!r} fehlt"
    level = heading.split(" ", 1)[0]
    rest = content[start + len(heading) :]
    end = rest.find(f"\n{level} ")
    return rest if end == -1 else rest[:end]


# ---------------------------------------------------------------------------
# AC1: iteration >= 2 mit offenen Findings endet in einer User-Entscheidung
# ---------------------------------------------------------------------------


def test_agent_has_no_auto_pass_with_warnings():
    assert "PASS-with-warnings" not in _read(AGENT), (
        "agents/quality-reviewer.md darf kein automatisches PASS-with-warnings "
        "mehr vorschreiben (Audit R6)"
    )


def test_agent_output_format_declares_escalate_verdict():
    body = _body(AGENT)
    verdict_lines = [line for line in body.splitlines() if line.startswith("VERDICT:")]
    assert verdict_lines, "Output-Format-Block ohne VERDICT:-Zeile"
    assert all("ESCALATE" in line for line in verdict_lines), (
        f"VERDICT-Zeile(n) muessen ESCALATE listen, gefunden: {verdict_lines}"
    )


def test_config_escalate_handling_uses_ask_user_question():
    section = _section(_body(REFERENCE), "## Ergebnis-Handling")
    assert "ESCALATE" in section, "Ergebnis-Handling kennt kein ESCALATE"
    assert "AskUserQuestion" in section, (
        "Ergebnis-Handling muss das User-Gate ueber AskUserQuestion beschreiben"
    )
    lowered = section.lower()
    for term in OPTION_TERMS:
        assert term in lowered, f"Option {term!r} fehlt im Ergebnis-Handling"


def test_chapter_writer_declares_ask_user_question():
    tools = _frontmatter(CHAPTER_WRITER).get("allowed-tools")
    assert isinstance(tools, list), "chapter-writer: allowed-tools fehlt oder ist keine Liste"
    assert "AskUserQuestion" in tools, (
        "chapter-writer muss AskUserQuestion deklarieren — das Review-Gate ruft es auf"
    )


def test_other_callers_still_document_the_revise_loop():
    """`advisor` und `abstract-generator` bleiben in diesem Issue unveraendert.

    Beide rufen den quality-reviewer ebenfalls auf, ihr SKILL.md ist aber vom
    Groessenbudget (`tests/test_skills_manifest.py::test_token_reduction`)
    ausgereizt — advisor hat 2 Zeichen Luft. Das ESCALATE-Handling dort
    nachzuziehen erfordert eine Textkompression und ist damit ein eigener
    Vorgang. Dieser Test haelt den Ist-Zustand fest, damit die Luecke sichtbar
    bleibt und nicht unbemerkt weiter driftet.
    """
    for skill in (ADVISOR, ABSTRACT_GENERATOR):
        assert "Bei REVISE Empfehlungen anwenden, max 2 Iterationen." in _read(skill), (
            f"{skill.parent.name}: Der REVISE-Hinweis ist der dokumentierte Ist-Zustand"
        )


def test_loop_bound_is_preserved():
    section = _section(_body(REFERENCE), "## Ergebnis-Handling")
    assert "genau eine zusätzliche Runde" in section, (
        "'weitere Revision' muss explizit auf genau eine Zusatzrunde begrenzt sein"
    )
    assert "erneut ESCALATE" in section, (
        "Nach der Zusatzrunde muss erneut eskaliert werden — kein unbegrenzter Zyklus"
    )


# ---------------------------------------------------------------------------
# AC2: ohne offene Findings bleibt PASS unveraendert
# ---------------------------------------------------------------------------


def test_escalate_is_conditioned_on_open_findings():
    body = _body(AGENT)
    paragraphs = [p for p in body.split("\n\n") if "ESCALATE" in p]
    assert paragraphs, "Agent beschreibt ESCALATE nirgends"
    conditioned = [p for p in paragraphs if "iteration >= 2" in p and "FAIL" in p]
    assert conditioned, (
        "ESCALATE muss an beide Bedingungen gekoppelt sein: iteration >= 2 UND mindestens ein FAIL"
    )


def test_agent_keeps_pass_when_no_criterion_fails_at_iteration_limit():
    body = _body(AGENT)
    paragraphs = [p for p in body.split("\n\n") if "ESCALATE" in p and "iteration >= 2" in p]
    assert any("bleibt es bei PASS" in p for p in paragraphs), (
        "Der Agent muss festhalten, dass bei iteration >= 2 ohne FAIL weiterhin PASS gilt (AC2)"
    )


def test_pass_path_unchanged():
    assert "REVISE nur wenn mindestens 1 Kriterium FAIL" in _read(AGENT), (
        "Die REVISE-Bedingung darf sich nicht aendern"
    )
    assert "**Bei PASS:** Output an User liefern" in _read(REFERENCE), (
        "Der PASS-Pfad im Ergebnis-Handling darf sich nicht aendern"
    )


# ---------------------------------------------------------------------------
# AC3: kein Drift zwischen Agent-Definition und chapter-writer-Referenz
# ---------------------------------------------------------------------------


def test_no_drift_between_agent_and_reference():
    agent = _read(AGENT)
    reference = _read(REFERENCE)
    for token in ("ESCALATE", "iteration >= 2", "iteration-limit"):
        assert token in agent, f"{token!r} fehlt in agents/quality-reviewer.md"
        assert token in reference, f"{token!r} fehlt in quality-review-config.md"
    for term in OPTION_TERMS:
        assert term in reference.lower(), f"Option {term!r} fehlt in der Referenz"
    assert "PASS-with-warnings" not in reference, (
        "quality-review-config.md darf kein Auto-PASS mehr vorschreiben"
    )


def test_evals_encode_escalation_instead_of_auto_pass():
    raw = _read(EVALS)
    assert "PASS-with-warnings" not in raw, "evals.json kodiert noch das alte Auto-PASS-Verhalten"
    prompts = {p["id"]: p for p in json.loads(raw)["prompts"]}
    qr03 = prompts["qr-03"]
    assert "ESCALATE" in qr03["expected"]["value"], "qr-03 muss ESCALATE erwarten, nicht PASS"
    assert "iteration-limit" in qr03["expected"]["value"], (
        "qr-03 muss BLOCKIERT_VON: iteration-limit weiterhin pruefen"
    )
    assert "PASS" not in qr03["expected"]["value"], (
        "qr-03 darf PASS nicht mehr als gueltigen Ausgang zulassen"
    )


def test_evals_cover_pass_at_iteration_limit_without_findings():
    prompts = {p["id"]: p for p in json.loads(_read(EVALS))["prompts"]}
    assert "qr-04" in prompts, "Es fehlt ein Eval fuer AC2: iteration >= 2 ohne FAIL bleibt PASS"
    qr04 = prompts["qr-04"]
    assert "Iteration: 2" in qr04["input"], "qr-04 muss am Iterations-Limit ansetzen"
    assert "PASS" in qr04["expected"]["value"], "qr-04 muss PASS erwarten"
    assert "ESCALATE" not in qr04["expected"]["value"]


def test_agents_reference_doc_lists_escalate():
    row = [
        line for line in _read(AGENTS_DOC).splitlines() if line.startswith("| `quality-reviewer`")
    ]
    assert row, "docs/reference/agents.md fuehrt quality-reviewer nicht mehr"
    assert "PASS/REVISE/ESCALATE" in row[0], (
        "docs/reference/agents.md muss das dritte Verdict nennen (doc-sync)"
    )
