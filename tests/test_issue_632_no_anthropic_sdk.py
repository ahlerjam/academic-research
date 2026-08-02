"""Regressionstest fuer Issue #632 — keine Plugin-Funktion braucht einen ANTHROPIC_API_KEY.

Belegt die Akzeptanzkriterien aus Issue #632:
  - Kein Produktivmodul importiert das Anthropic-SDK (AC1) und ein Rueckfall
    laesst genau diesen Test scheitern (AC3).
  - ``anthropic`` steht in keiner Datei, die ein Endnutzer installiert (AC2).
  - ``/search`` und ``/history`` bewerben keine ``--batch``-Option mehr, der
    CHANGELOG nennt den Wegfall samt Grund (AC6).
  - Keine Endnutzer-Doku nennt ``ANTHROPIC_API_KEY`` als Voraussetzung fuer
    eine Plugin-Funktion (AC7).
  - ``vault.ensure_file`` ist deregistriert und wird nirgends mehr aufgerufen (AC8).
  - Keine Test-Datei referenziert die entfernten Module (AC9).

Muster: ``tests/test_issue_377_dead_code_removed.py`` (Scan ueber getrackte
Dateien via ``git ls-files``/``git grep``, damit ``.venv`` und vendored Code
keine False-Positives liefern).
"""

import re
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
THIS_FILE_REL = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()

# Der SDK-Import ist ausserhalb von tests/ komplett verboten. Innerhalb von
# tests/ bleibt genau ein Pfad zulaessig: tests/evals/eval_runner.py ist
# Repo-Infrastruktur fuer die Entwicklung (Out-of-Scope laut Issue-Body,
# Umstellung auf die OAuth-Session behandelt #631).
_SDK_IMPORT_RE = re.compile(r"^\s*(?:import\s+anthropic|from\s+anthropic[\s.])", re.MULTILINE)


def _tracked_files(*patterns: str) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--", *patterns],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [REPO_ROOT / line for line in result.stdout.splitlines() if line]


def test_no_production_module_imports_anthropic_sdk() -> None:
    """AC1/AC3: keine getrackte *.py ausserhalb tests/ importiert das SDK.

    Faellt rot, sobald ein Produktivpfad ``import anthropic`` /
    ``from anthropic ...`` zurueckbringt — das ist der Rueckfall-Guard.
    """
    offenders = []
    for path in _tracked_files("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel.startswith("tests/"):
            continue
        if _SDK_IMPORT_RE.search(path.read_text(encoding="utf-8")):
            offenders.append(rel)
    assert offenders == [], (
        f"Produktivcode importiert das Anthropic-SDK wieder: {offenders}. "
        "Issue #632: keine Plugin-Funktion darf einen ANTHROPIC_API_KEY brauchen."
    )


def test_removed_sdk_modules_are_gone() -> None:
    """AC1: die vier SDK-Pfade aus dem Issue-Body existieren nicht mehr."""
    for rel in ("scripts/batch_api.py", "academic_vault/files_api.py"):
        assert not (REPO_ROOT / rel).exists(), f"{rel} existiert noch"
    embeddings = (REPO_ROOT / "academic_vault" / "embeddings.py").read_text(encoding="utf-8")
    for symbol in ("generate_context_sentence", "_get_anthropic_client"):
        assert symbol not in embeddings, f"{symbol} noch in academic_vault/embeddings.py"
    parse_list = (
        REPO_ROOT / "skills" / "reading-list-import" / "scripts" / "parse_list.py"
    ).read_text(encoding="utf-8")
    assert "def llm_parse" not in parse_list, "llm_parse() noch in parse_list.py"


def test_end_user_requirements_free_of_anthropic() -> None:
    """AC2: keine Datei, die ein Endnutzer installiert, nennt ``anthropic``."""
    for rel in ("scripts/requirements.txt", "academic_vault/requirements.txt"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "anthropic" not in text.lower(), f"{rel} nennt weiterhin anthropic"

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime_deps = pyproject["project"]["dependencies"]
    hits = [dep for dep in runtime_deps if dep.lower().startswith("anthropic")]
    assert hits == [], (
        f"[project.dependencies] enthaelt weiterhin {hits} — "
        "das SDK gehoert ins dev-Extra (nur tests/evals, entfaellt mit #631)."
    )


def test_commands_do_not_advertise_batch() -> None:
    """AC6: weder /search noch /history bewerben eine --batch-Option."""
    for rel in ("commands/search.md", "commands/history.md"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "--batch" not in text, f"{rel} bewirbt weiterhin --batch"
        assert "batch_api" not in text, f"{rel} verweist weiterhin auf batch_api"


def test_search_md_scores_large_result_sets_without_batch_api() -> None:
    """AC4: /search scort auch grosse Treffermengen ueber den Agenten."""
    text = (REPO_ROOT / "commands" / "search.md").read_text(encoding="utf-8")
    assert "relevance-scorer" in text, "commands/search.md nennt den Scoring-Agenten nicht"
    assert "Batch-API" not in text, "commands/search.md verweist weiterhin auf die Batch-API"


def test_changelog_documents_removed_batch_path() -> None:
    """AC6: der CHANGELOG nennt den weggefallenen Zugriffsweg samt Grund."""
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    entry_start = changelog.find("#632")
    assert entry_start != -1, "CHANGELOG nennt Issue #632 nicht"
    entry = changelog[entry_start : entry_start + 4000]
    assert "--batch" in entry, (
        "CHANGELOG-Eintrag zu #632 nennt die weggefallene --batch-Option nicht"
    )
    assert "ANTHROPIC_API_KEY" in entry, "CHANGELOG-Eintrag zu #632 nennt den Grund (Key) nicht"


# AC7 — Grenzziehung: der Key bleibt eine *Entwickler*-Voraussetzung fuer die
# Eval-Infrastruktur (Out-of-Scope laut Issue-Body, Umstellung auf OAuth in
# #631). Diese Pfade sind darum bewusst ausgenommen; alles andere ist
# Endnutzer-Doku und darf den Key nicht mehr als Voraussetzung nennen.
_KEY_DOC_ALLOWLIST = (
    "docs/development.md",  # Entwickler-Setup, kein Plugin-Funktionspfad
    "docs/SKIP_REASONS.md",  # dokumentiert genau die API-gateten Test-Skips
    "docs/evals/",  # Eval-Strategie und -Protokolle (#631)
    "evals/",  # Eval-Runner und -Fixtures (#631)
    "CHANGELOG.md",  # historische Eintraege bleiben unveraendert
)


def test_user_docs_free_of_anthropic_api_key() -> None:
    """AC7: keine Endnutzer-Doku nennt ANTHROPIC_API_KEY."""
    patterns = ("README.md", "docs/*.md", "docs/**/*.md", "commands/**", "skills/**", "agents/**")
    offenders = []
    for path in _tracked_files(*patterns):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel.startswith(_KEY_DOC_ALLOWLIST) or rel == THIS_FILE_REL:
            continue
        if path.suffix not in {".md", ".txt"}:
            continue
        if "ANTHROPIC_API_KEY" in path.read_text(encoding="utf-8"):
            offenders.append(rel)
    assert offenders == [], f"Endnutzer-Doku nennt weiterhin ANTHROPIC_API_KEY: {offenders}"


def test_ensure_file_tool_not_registered() -> None:
    """AC8: vault.ensure_file ist kein registriertes MCP-Tool mehr."""
    server = (REPO_ROOT / "academic_vault" / "server.py").read_text(encoding="utf-8")
    assert '@mcp.tool(name="vault.ensure_file")' not in server, (
        "vault.ensure_file ist weiterhin als MCP-Tool registriert"
    )
    assert "def ensure_file" not in server, "server.ensure_file existiert weiterhin"


def test_no_skill_or_agent_calls_ensure_file() -> None:
    """AC8: keine Skill-, Agent- oder Command-Datei ruft vault.ensure_file auf."""
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _tracked_files("skills/**", "agents/**", "commands/**")
        if path.is_file() and "ensure_file" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert offenders == [], f"ensure_file wird weiterhin referenziert: {offenders}"


def test_no_test_imports_removed_modules() -> None:
    """AC9: keine Test-Datei referenziert die entfernten Module/Funktionen."""
    pattern = r"batch_api|academic_vault\.files_api|generate_context_sentence|llm_parse"
    result = subprocess.run(
        ["git", "grep", "-lE", pattern, "--", "tests/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    hits = [line for line in result.stdout.splitlines() if line != THIS_FILE_REL]
    assert hits == [], f"Tests referenzieren entfernte Module: {hits}"
