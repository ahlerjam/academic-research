"""Tests fuer die gemeinsame Pfadpruefung der drei Kapitel-Guards (Issue #615).

Vorher definierten verbatim-guard.mjs, claim-drift-guard.mjs und
context-fidelity-guard.mjs je eine eigene Kopie von isProtectedPath() mit
derselben case-sensitiven Regex. "Kapitel/03.md" (korrekte deutsche
Grossschreibung) lief dadurch an allen drei Guards ungeprueft vorbei.

Akzeptanzkriterien (Issue #615):
  AC1  Kapitel/03.md, KAPITEL/03.md und kapitel/03.MD werden geprueft.
  AC2  Das Kapitelverzeichnis ist konfigurierbar (ACADEMIC_CHAPTER_DIR),
       der Vorgabewert verhaelt sich wie heute.
  AC3  Ein Schreibvorgang in eine .md/.tex-Datei ausserhalb der geschuetzten
       Menge hinterlaesst eine sichtbare Meldung (stderr).
  AC4  Bash-Writes: Doku-Aussage statt Erkennung (bewusste Wahl, siehe
       docs/reference/hooks.md).
  AC5  Die Pfadpruefung existiert genau einmal im Repo und wird von allen
       drei Guards genutzt.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
LIB_PATH = REPO_ROOT / "hooks" / "lib" / "protected-path.mjs"
VERBATIM_GUARD = REPO_ROOT / "hooks" / "verbatim-guard.mjs"
CLAIM_DRIFT_GUARD = REPO_ROOT / "hooks" / "claim-drift-guard.mjs"
CONTEXT_FIDELITY_GUARD = REPO_ROOT / "hooks" / "context-fidelity-guard.mjs"
HOOKS_DOC = REPO_ROOT / "docs" / "reference" / "hooks.md"


def run_node(source: str, env_overrides: dict = None) -> subprocess.CompletedProcess:
    """Fuehrt ein ESM-Snippet gegen hooks/lib/protected-path.mjs aus."""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["node", "--input-type=module", "-e", source],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=60,
    )


def run_guard(guard_path: Path, tool_input: dict, env_overrides: dict = None):
    """Startet einen der drei Guards als Subprocess mit einem Write-Payload."""
    payload = json.dumps({"tool_name": "Write", "tool_input": tool_input})
    env = os.environ.copy()
    env["VAULT_DB_PATH"] = str(REPO_ROOT / "nonexistent_vault_for_tests.db")
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["node", str(guard_path)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


# ---------------------------------------------------------------------------
# AC1 + AC2 — Unit-Tests gegen das neue Modul
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "file_path",
    [
        "kapitel/03.md",
        "Kapitel/03.md",
        "KAPITEL/03.md",
        "kapitel/03.MD",
        "Kapitel/03.MD",
    ],
)
def test_isProtectedPath_case_insensitive(file_path):
    """AC1: alle Gross-/Kleinschreibvarianten von Ordner und Endung sind geschuetzt."""
    source = f"""
    import {{ isProtectedPath }} from './hooks/lib/protected-path.mjs';
    console.log(JSON.stringify({{ protected: isProtectedPath('{file_path}', {{}}) }}));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    data = json.loads(result.stdout)
    assert data["protected"] is True, f"{file_path} sollte geschuetzt sein"


@pytest.mark.parametrize(
    "file_path",
    ["chapters/03.md", "meinkapitel/03.md", "kapitel/03.txt"],
)
def test_isProtectedPath_default_unchanged(file_path):
    """AC2: ohne Env-Override verhaelt sich das Modul wie vorher (nur kapitel/*.md, *.tex)."""
    source = f"""
    import {{ isProtectedPath }} from './hooks/lib/protected-path.mjs';
    console.log(JSON.stringify({{ protected: isProtectedPath('{file_path}', {{}}) }}));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    data = json.loads(result.stdout)
    assert data["protected"] is False, f"{file_path} sollte NICHT geschuetzt sein"


def test_isProtectedPath_respects_ACADEMIC_CHAPTER_DIR():
    """AC2: Override auf 'chapters' schuetzt chapters/*.md statt kapitel/*.md."""
    source = """
    import { isProtectedPath } from './hooks/lib/protected-path.mjs';
    const env = { ACADEMIC_CHAPTER_DIR: 'chapters' };
    console.log(JSON.stringify({
      chaptersProtected: isProtectedPath('chapters/03.md', env),
      kapitelStillProtected: isProtectedPath('kapitel/03.md', env),
    }));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    data = json.loads(result.stdout)
    assert data["chaptersProtected"] is True, "chapters/03.md sollte mit Override geschuetzt sein"
    assert data["kapitelStillProtected"] is False, (
        "kapitel/03.md sollte bei aktivem Override NICHT mehr geschuetzt sein"
    )


def test_isProtectedPath_chapter_dir_override_is_case_insensitive():
    """AC1+AC2 kombiniert: auch der konfigurierte Ordnername ist case-insensitiv."""
    source = """
    import { isProtectedPath } from './hooks/lib/protected-path.mjs';
    const env = { ACADEMIC_CHAPTER_DIR: 'chapters' };
    console.log(JSON.stringify({ protected: isProtectedPath('CHAPTERS/03.MD', env) }));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    assert json.loads(result.stdout)["protected"] is True


def test_isProtectedPath_escapes_regex_special_chars_in_chapter_dir():
    """Ein Ordnername mit Regex-Sonderzeichen darf die Pruefung nicht brechen (Injection-Schutz)."""
    source = """
    import { isProtectedPath } from './hooks/lib/protected-path.mjs';
    const env = { ACADEMIC_CHAPTER_DIR: 'kapitel.neu' };
    console.log(JSON.stringify({
      matchesLiteral: isProtectedPath('kapitel.neu/03.md', env),
      doesNotMatchAnyChar: isProtectedPath('kapitelXneu/03.md', env),
    }));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    data = json.loads(result.stdout)
    assert data["matchesLiteral"] is True
    assert data["doesNotMatchAnyChar"] is False, (
        "'.' im konfigurierten Ordnernamen darf nicht als Regex-Wildcard wirken"
    )


def test_isProtectedPath_tex_remains_folder_independent():
    """Bestehendes Verhalten: *.tex ist ueberall geschuetzt, nicht nur unter kapitel/ (#615-Risiko)."""
    source = """
    import { isProtectedPath } from './hooks/lib/protected-path.mjs';
    console.log(JSON.stringify({
      anywhere: isProtectedPath('irgendwo/tief/verschachtelt/kap1.tex', {}),
      upperExt: isProtectedPath('kap1.TEX', {}),
    }));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    data = json.loads(result.stdout)
    assert data["anywhere"] is True
    assert data["upperExt"] is True


# ---------------------------------------------------------------------------
# AC1 — End-to-End gegen verbatim-guard.mjs (echter Block-Pfad, nicht nur Unit)
# ---------------------------------------------------------------------------

UNVERIFIED_QUOTE = 'Laut dem Autor "Dies ist ein sehr wichtiger Satz aus dem Buch" stimmt das.'


def _empty_vault(tmp_path, name="empty_vault.db"):
    from academic_vault.db import VaultDB
    from academic_vault.server import add_paper

    db_path = str(tmp_path / name)
    db = VaultDB(db_path)
    db.init_schema()
    add_paper(
        db_path=db_path,
        paper_id="paper-001",
        csl_json=json.dumps({"title": "Test", "type": "article-journal"}),
    )
    return db_path


@pytest.mark.parametrize(
    "file_path",
    ["Kapitel/kap1.md", "KAPITEL/kap1.md", "kapitel/kap1.MD"],
)
def test_verbatim_guard_blocks_unverified_quote_case_variants(tmp_path, file_path):
    """AC1 End-to-End: Case-Varianten des Kapitelordners/der Endung werden vom
    echten Guard geprueft und blockieren ein unverifiziertes Zitat.

    Gegenprobe gegen origin/main (AC6): mit der alten case-sensitiven Regex
    ist dieser Test rot (exit 0 statt 2), da nur 'kapitel/*.md' erkannt wurde.
    """
    db_path = _empty_vault(tmp_path, "nested_vault.db")
    result = run_guard(
        VERBATIM_GUARD,
        {"file_path": file_path, "content": UNVERIFIED_QUOTE},
        env_overrides={"VAULT_DB_PATH": db_path},
    )
    assert result.returncode == 2, (
        f"{file_path} sollte case-insensitiv geprueft werden: erwartet exit 2, "
        f"got {result.returncode}. stderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# AC3 — sichtbare Meldung bei Kapiteltext-Write ausserhalb der Schutzzone
# ---------------------------------------------------------------------------


def test_verbatim_guard_warns_on_unprotected_markdown_write(tmp_path):
    """AC3: Write auf eine .md-Datei ausserhalb von kapitel/ hinterlaesst eine
    stderr-Meldung, obwohl der Write selbst erlaubt bleibt (exit 0)."""
    result = run_guard(
        VERBATIM_GUARD,
        {"file_path": "notizen/entwurf.md", "content": "Ein harmloser Entwurf."},
    )
    assert result.returncode == 0, (
        f"Write ausserhalb der Schutzzone soll erlaubt bleiben: {result.stderr}"
    )
    assert "außerhalb des geschützten Kapitelverzeichnisses" in result.stderr, (
        f"Erwartete sichtbare Meldung fehlt in stderr: {result.stderr!r}"
    )


def test_verbatim_guard_silent_on_unrelated_file_type(tmp_path):
    """Kontrolltest zu AC3: kein Rauschen bei Dateitypen, die nie Kapiteltexte sind."""
    result = run_guard(
        VERBATIM_GUARD,
        {"file_path": "scripts/tool.py", "content": "print('hallo')"},
    )
    assert result.returncode == 0
    assert result.stderr == "", (
        f"Write auf eine .py-Datei ausserhalb kapitel/ sollte keine Meldung erzeugen: {result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# AC4 — Bash-Writes: Doku-Aussage statt Erkennung
# ---------------------------------------------------------------------------


def test_docs_state_bash_writes_unprotected():
    """AC4: docs/reference/hooks.md sagt ausdruecklich, dass Bash-Writes (cat >,
    tee, sed -i, ...) nicht von den drei Guards erfasst werden."""
    text = HOOKS_DOC.read_text(encoding="utf-8")
    assert "Bash" in text and (
        "nicht erfasst" in text or "ungeschützt" in text or "werden nicht geprüft" in text
    ), (
        "docs/reference/hooks.md sollte ausdruecklich dokumentieren, dass "
        "Bash-Schreibvorgaenge (cat >, tee, sed -i, ...) an den Guards vorbeilaufen."
    )


def test_hooks_json_matcher_still_excludes_bash():
    """Begleitbeleg zu AC4: hooks.json matcht PreToolUse weiterhin nur auf
    Write|Edit|MultiEdit — Bash-Aufrufe erreichen die Guards nicht."""
    hooks_data = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    matchers = [entry.get("matcher", "") for entry in hooks_data["hooks"].get("PreToolUse", [])]
    guard_matchers = [m for m in matchers if "Write" in m or "Edit" in m]
    assert guard_matchers, "Keine PreToolUse-Matcher mit Write/Edit gefunden"
    for matcher in guard_matchers:
        assert "Bash" not in matcher, (
            f"Matcher '{matcher}' schliesst Bash ein — AC4-Doku-Aussage waere falsch"
        )


# ---------------------------------------------------------------------------
# AC5 — Pfadpruefung existiert genau einmal, alle drei Guards nutzen sie
# ---------------------------------------------------------------------------


def test_no_duplicate_isProtectedPath_definition():
    """AC5: keine lokale Funktionsdefinition mehr in den drei Guards."""
    for guard_path in (VERBATIM_GUARD, CLAIM_DRIFT_GUARD, CONTEXT_FIDELITY_GUARD):
        text = guard_path.read_text(encoding="utf-8")
        assert "function isProtectedPath" not in text, (
            f"{guard_path.name} definiert isProtectedPath noch lokal statt zu importieren"
        )


def test_all_three_guards_import_shared_module():
    """AC5: alle drei Guards importieren isProtectedPath aus hooks/lib/protected-path.mjs."""
    for guard_path in (VERBATIM_GUARD, CLAIM_DRIFT_GUARD, CONTEXT_FIDELITY_GUARD):
        text = guard_path.read_text(encoding="utf-8")
        assert "protected-path.mjs" in text, (
            f"{guard_path.name} importiert nicht aus hooks/lib/protected-path.mjs"
        )


def test_protected_path_module_exists():
    """Die neue gemeinsame Modul-Datei muss existieren."""
    assert LIB_PATH.exists(), f"{LIB_PATH} fehlt"
