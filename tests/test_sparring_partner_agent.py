"""Strukturtests fuer den sparring-partner-Agent (Issue #454).

Deckt die statisch (ohne API-Key) pruefbaren Teile der Akzeptanzkriterien ab:

- AC1: Agent-Datei existiert, Frontmatter parst fehlerfrei, Pflichtfelder
  nicht leer, `model` ist einer der laut Doku gueltigen Kurznamen
  (per WebFetch gegen code.claude.com/docs/en/sub-agents verifiziert:
  sonnet/opus/haiku/fable/volle Modell-ID/inherit).
- AC3 (struktureller Teil): `tools`-Frontmatter deklariert `Read` sowie die
  beiden Vault-MCP-Tools mit korrektem Bindestrich-Praefix
  `mcp__academic-vault__` (Muster aus Issue #366 /
  tests/test_issue_366_agent_tool_prefix.py).
- AC4 (struktureller Teil): ein "## Abgrenzung"-Abschnitt benennt die vier
  Nachbar-Skills/-Agenten namentlich.

Der inhaltliche Teil (AC2/AC3b/AC4b/AC5 -- echtes Modellverhalten) liegt in
evals/sparring-partner/evals.json, geprueft durch:

- tests/evals/test_sparring_partner_recording.py (CI-fest, offline): prueft
  fuenf an agents/sparring-partner.md sha256-gepinnte Transkripte
  (evals/sparring-partner/recordings.json) gegen expected -- ein Snapshot-/
  Konsistenz-Check, kein unabhaengiger Verhaltensbeleg (Transkript und
  Erwartung stammen aus derselben Sitzung, siehe recordings.json::provenance).
- tests/evals/test_sparring_partner_evals.py (API-gated, Live-Aufruf gegen
  `model="claude-opus-4-6"`, skippt ohne ANTHROPIC_API_KEY) -- das ist der
  eigentliche inhaltliche AC-Beleg.

Siehe docs/evals/STRATEGY.md (Status `structural`).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
AGENT_PATH = REPO_ROOT / "agents" / "sparring-partner.md"

# Laut code.claude.com/docs/en/sub-agents (Abschnitt "Supported frontmatter
# fields", per WebFetch am 2026-07-29 geprueft): model akzeptiert sonnet,
# opus, haiku, fable, eine volle Modell-ID oder inherit.
VALID_MODEL_SHORT_NAMES = {"sonnet", "opus", "haiku", "fable", "inherit"}

REQUIRED_VAULT_TOOLS = [
    "mcp__academic-vault__vault_search",
    "mcp__academic-vault__vault_get_paper",
]

NEIGHBOR_SKILLS = [
    "advisor",
    "research-question-refiner",
    "methodology-advisor",
    "quality-reviewer",
]


def _parse_frontmatter(path: Path) -> tuple[dict, str]:
    content = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
    assert match, f"Kein gueltiges Frontmatter in {path}"
    fm = yaml.safe_load(match.group(1))
    return fm, match.group(2)


def test_agent_file_exists():
    assert AGENT_PATH.exists(), f"Agent-Datei fehlt: {AGENT_PATH} (Issue #454, AC1)"


def test_agent_frontmatter_parses_without_error():
    fm, _ = _parse_frontmatter(AGENT_PATH)
    assert isinstance(fm, dict)


@pytest.mark.parametrize("field", ["name", "description", "model", "tools"])
def test_agent_frontmatter_required_fields_non_empty(field):
    fm, _ = _parse_frontmatter(AGENT_PATH)
    assert fm.get(field), f"Frontmatter-Feld '{field}' fehlt oder ist leer (AC1)"


def test_agent_name_matches_filename():
    fm, _ = _parse_frontmatter(AGENT_PATH)
    assert fm["name"] == "sparring-partner"


def test_agent_model_is_a_valid_short_name():
    fm, _ = _parse_frontmatter(AGENT_PATH)
    model = fm["model"]
    is_valid = model in VALID_MODEL_SHORT_NAMES or bool(re.match(r"^claude-", model))
    assert is_valid, (
        f"model='{model}' ist kein laut Doku gueltiger Kurzname "
        f"({VALID_MODEL_SHORT_NAMES}) oder volle Modell-ID (AC1)"
    )


def test_agent_declares_read_and_vault_tools():
    """AC3 (struktureller Teil): Read + beide Vault-MCP-Tools korrekt praefixiert."""
    fm, _ = _parse_frontmatter(AGENT_PATH)
    tools = fm.get("tools", [])
    assert isinstance(tools, list), f"tools muss eine Liste sein, ist: {type(tools)}"
    assert "Read" in tools, "Agent muss 'Read' deklarieren (fuer academic_context.md)"
    missing = [t for t in REQUIRED_VAULT_TOOLS if t not in tools]
    assert not missing, f"Fehlende Vault-Tools im Frontmatter: {missing}. Deklariert: {tools}"


def test_agent_declares_no_write_tool():
    """Scope-Out laut Issue: kein automatisches Umschreiben von Nutzertext."""
    fm, _ = _parse_frontmatter(AGENT_PATH)
    tools = fm.get("tools", [])
    assert "Write" not in tools, "Agent soll laut Scope keinen Write-Zugriff haben"


def test_agent_has_abgrenzung_section_naming_neighbor_skills():
    """AC4 (struktureller Teil): '## Abgrenzung' benennt alle vier Nachbarn."""
    _, body = _parse_frontmatter(AGENT_PATH)
    section_match = re.search(r"##\s*Abgrenzung(.*?)(?:\n##\s|\Z)", body, re.DOTALL)
    assert section_match, "Kein '## Abgrenzung'-Abschnitt im Agent-Body gefunden (AC4)"
    section_text = section_match.group(1)
    missing = [name for name in NEIGHBOR_SKILLS if f"`{name}`" not in section_text]
    assert not missing, f"Abgrenzung-Abschnitt nennt nicht alle Nachbarn: fehlt {missing}"


def test_agent_body_defines_fixed_output_section_markers():
    """Festes Abschnitts-Format statt Fliesstext (Risiko 3 aus Plan)."""
    _, body = _parse_frontmatter(AGENT_PATH)
    for marker in ["SCHWÄCHE:", "ALTERNATIVE:", "GEGENPOSITION:", "ANSCHLUSSFRAGEN:"]:
        assert marker in body, f"Output-Format-Marker '{marker}' fehlt im Agent-Body"


# ---------------------------------------------------------------------------
# evals/sparring-partner/evals.json -- struktureller Teil von AC2/AC3/AC5
# (der inhaltliche Teil ist API-gated, siehe tests/evals/test_sparring_partner_evals.py)
# ---------------------------------------------------------------------------

EVALS_PATH = REPO_ROOT / "evals" / "sparring-partner" / "evals.json"


def _load_evals() -> dict:
    assert EVALS_PATH.exists(), f"evals.json fehlt: {EVALS_PATH} (Issue #454, AC2/AC5)"
    return json.loads(EVALS_PATH.read_text(encoding="utf-8"))


def test_evals_file_has_expected_component_metadata():
    data = _load_evals()
    assert data.get("component") == "sparring-partner"
    assert data.get("component_type") == "agent"
    assert len(data.get("prompts", [])) >= 3


def test_evals_file_prompts_have_required_fields():
    data = _load_evals()
    for prompt in data["prompts"]:
        assert prompt.get("id"), f"Prompt ohne id: {prompt}"
        assert prompt.get("input"), f"{prompt.get('id')}: input fehlt/leer"
        expected = prompt.get("expected", {})
        assert expected.get("type") in {"substring", "regex", "json_field"}, (
            f"{prompt.get('id')}: unbekannter expected.type"
        )


def test_evals_file_covers_weak_research_question_case():
    """AC5: mind. ein Prompt mit bewusst schwacher/tautologischer Forschungsfrage."""
    data = _load_evals()
    combined = json.dumps(data["prompts"], ensure_ascii=False)
    assert "wichtig für Unternehmen" in combined or "wichtig fuer Unternehmen" in combined, (
        "Kein Eval-Fall mit der aus dem Plan vorgesehenen tautologischen "
        "Forschungsfrage ('...wichtig für Unternehmen?') gefunden (AC5)"
    )


def test_evals_file_covers_material_grounded_case():
    """AC3b: mind. ein Prompt bettet academic_context.md-Kontext + Vault-Quelle ein."""
    data = _load_evals()
    combined = json.dumps(data["prompts"], ensure_ascii=False)
    assert "academic_context" in combined.lower() or "academic-context" in combined.lower()


def test_evals_file_covers_chapter_prose_refusal_case():
    """AC4b: mind. ein Prompt fordert Kapitel-Prosa an und erwartet Verweis statt Text."""
    data = _load_evals()
    combined = " ".join(p["input"] for p in data["prompts"])
    assert "Grundlagenkapitel" in combined or "Kapitel" in combined
