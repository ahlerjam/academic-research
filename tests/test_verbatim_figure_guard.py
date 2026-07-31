"""Tests fuer den additiven Figure-Check im verbatim-guard-Hook.

Der Hook wird als Node.js-Subprocess gestartet. JSON auf stdin, Ausgabe auf stdout/stderr.
Exit-Code 0 = allow, Exit-Code 2 = block.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

HOOK_PATH = Path(__file__).parent.parent / "hooks" / "verbatim-guard.mjs"
WORKTREE_ROOT = Path(__file__).parent.parent


def run_hook(
    tool_name: str, file_path: str, content: str, env_overrides: dict = None
) -> subprocess.CompletedProcess:
    """Startet den Hook als Subprocess mit JSON-Eingabe auf stdin."""
    payload = json.dumps(
        {
            "tool_name": tool_name,
            "tool_input": {
                "file_path": file_path,
                "content": content,
            },
        }
    )
    env = os.environ.copy()
    # Vault-DB-Pfad auf nicht-existierende DB setzen (fail-open Tests)
    env["VAULT_DB_PATH"] = str(WORKTREE_ROOT / "nonexistent_vault_for_tests.db")
    if env_overrides:
        env.update(env_overrides)

    return subprocess.run(
        ["node", str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


@pytest.fixture
def vault_with_figure(tmp_path):
    """Erstellt temporaere Vault-DB mit einem Figure-Eintrag."""
    from academic_vault.db import VaultDB
    from academic_vault.server import add_figure, add_paper

    db_path = str(tmp_path / "test_vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    add_paper(
        db_path=db_path,
        paper_id="test-paper",
        csl_json=json.dumps({"title": "Test", "type": "article-journal"}),
    )
    add_figure(
        db_path=db_path,
        paper_id="test-paper",
        page=3,
        caption="Abb. 3.4: Ergebnisse der Messung",
        vlm_description="Balkendiagramm mit fuenf Experimenten.",
        data_extracted=None,
    )
    return db_path


def test_hook_failopen_when_vault_missing():
    """Hook erlaubt (fail-open) wenn Vault-DB nicht existiert."""
    content = "In Abb. 3.4 sieht man deutlich, dass der Wert steigt."
    result = run_hook("Write", "kapitel/kap1.md", content)
    # fail-open → exit 0
    assert result.returncode == 0, (
        f"Erwartet 0 (fail-open), got {result.returncode}. stderr: {result.stderr}"
    )
    # Issue #381 (AC1): Wortlaut-Pin, damit der "DB fehlt"-Fall nicht mit dem
    # "Exception bei vorhandener DB"-Fall verschmilzt.
    assert "Vault-DB nicht gefunden" in result.stderr, (
        f"Erwartet 'DB fehlt'-Wortlaut in stderr, got: {result.stderr}"
    )


def test_hook_ignores_non_protected_path():
    """Hook ignoriert Pfade die nicht geschuetzt sind."""
    content = "In Abb. 3.4 ist ein Diagramm dargestellt."
    result = run_hook("Write", "README.md", content)
    assert result.returncode == 0


def test_hook_non_write_tool_ignored():
    """Hook reagiert nicht auf Nicht-Write-Tools."""
    result = run_hook("Read", "kapitel/kap1.md", "Abb. 3.4 zeigt etwas.")
    assert result.returncode == 0


def test_hook_blocks_unknown_figure_reference(tmp_path):
    """Hook blockiert bei Abb.-Referenz die nicht im Vault ist (Vault existiert, kein Eintrag)."""
    from academic_vault.db import VaultDB
    from academic_vault.server import add_paper

    db_path = str(tmp_path / "empty_vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    add_paper(
        db_path=db_path,
        paper_id="test-paper",
        csl_json=json.dumps({"title": "Test", "type": "article-journal"}),
    )

    content = "Wie in Abb. 3.4 gezeigt, ist der Effekt signifikant."
    result = run_hook(
        "Write",
        "kapitel/kap1.md",
        content,
        env_overrides={"VAULT_DB_PATH": db_path},
    )
    assert result.returncode == 2, (
        f"Erwartet exit 2 (block), got {result.returncode}. stderr: {result.stderr}"
    )


def test_hook_allows_when_figure_in_vault(vault_with_figure):
    """Hook erlaubt wenn Figure-Caption im Vault gefunden wird (kein Quote-Span, nur Figure-Ref)."""
    # Inhalt ohne Quote-Span, nur Figure-Referenz mit passendem Caption-Fragment
    content = "Wie in Abb. 3.4 sichtbar, ist der Wert hoch."
    result = run_hook(
        "Write",
        "kapitel/kap1.md",
        content,
        env_overrides={"VAULT_DB_PATH": vault_with_figure},
    )
    # Figure ist im Vault -> kein Figure-Block
    assert "[Figure-Guard] BLOCKIERT" not in result.stderr
    assert result.returncode == 0


@pytest.fixture
def vault_with_divergent_caption(tmp_path):
    """Vault-DB mit einer Caption in ausgeschriebenem Format (Kern-Bug #379:
    Referenz-Label 'Abb. 3.4' ist KEIN Teilstring von 'Abbildung 3.4: ...')."""
    from academic_vault.db import VaultDB
    from academic_vault.server import add_figure, add_paper

    db_path = str(tmp_path / "divergent_vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    add_paper(
        db_path=db_path,
        paper_id="test-paper",
        csl_json=json.dumps({"title": "Test", "type": "article-journal"}),
    )
    add_figure(
        db_path=db_path,
        paper_id="test-paper",
        page=3,
        caption="Abbildung 3.4: Übersicht der Systemarchitektur der Cloud-Plattform",
        vlm_description="Blockdiagramm der Architektur.",
        data_extracted=None,
    )
    return db_path


def test_hook_allows_divergent_label_with_matching_vault_entry(vault_with_divergent_caption):
    """Regression #379 (AC1+AC3): In-Text-Label 'Abb. 3.4' referenziert einen Vault-Eintrag
    mit Caption 'Abbildung 3.4: ...' — muss trotz Formatabweichung NICHT blockiert werden.
    Mit dem alten LIKE-Freitext-Matching haette dies faelschlich geblockt."""
    content = "Wie in Abb. 3.4 gezeigt, ist der Effekt signifikant."
    result = run_hook(
        "Write",
        "kapitel/kap1.md",
        content,
        env_overrides={"VAULT_DB_PATH": vault_with_divergent_caption},
    )
    assert "[Figure-Guard] BLOCKIERT" not in result.stderr
    assert result.returncode == 0, (
        f"Erwartet 0 (Figure-Match trotz Formatabweichung), got {result.returncode}. "
        f"stderr: {result.stderr}"
    )


def test_hook_blocks_unrelated_reference_despite_vault_entry(vault_with_divergent_caption):
    """AC2: Referenz ohne passenden Eintrag bleibt blockiert (kein Fail-open durch den Fix)."""
    content = "Wie in Abb. 9.9 gezeigt, ist der Effekt signifikant."
    result = run_hook(
        "Write",
        "kapitel/kap1.md",
        content,
        env_overrides={"VAULT_DB_PATH": vault_with_divergent_caption},
    )
    assert result.returncode == 2, (
        f"Erwartet 2 (Block, kein passender Eintrag), got {result.returncode}. "
        f"stderr: {result.stderr}"
    )
    assert "[Figure-Guard] BLOCKIERT" in result.stderr
    # Issue #381 (AC3): auch die Figure-Guard-Block-Message ohne Bypass-Marker-Wortlaut.
    assert "vault-guard: skip" not in result.stderr, (
        f"Bypass-Marker-Wortlaut sollte aus der Figure-Block-Message entfernt sein: {result.stderr}"
    )


def test_existing_quote_check_still_works(tmp_path):
    """Regression: bestehende Quote-Pruefung blockiert weiterhin bei unverifizierten Zitaten."""
    from academic_vault.db import VaultDB
    from academic_vault.server import add_paper

    db_path = str(tmp_path / "quote_vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    add_paper(
        db_path=db_path,
        paper_id="paper-001",
        csl_json=json.dumps({"title": "Test", "type": "article-journal"}),
    )

    # Langer Quote-Span (>10 Zeichen) ohne Vault-Eintrag -> Block
    content = 'Laut dem Autor "Dies ist ein sehr wichtiger Satz aus dem Buch" stimmt das.'
    result = run_hook(
        "Write",
        "kapitel/kap1.md",
        content,
        env_overrides={"VAULT_DB_PATH": db_path},
    )
    assert result.returncode == 2, f"Erwartet exit 2 (Quote-Block), got {result.returncode}"
    # Issue #381 (AC3): Block-Message darf den Bypass-Marker-Wortlaut nicht mehr nennen.
    assert "vault-guard: skip" not in result.stderr, (
        f"Bypass-Marker-Wortlaut sollte aus der Block-Message entfernt sein: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Regression #220: Edit/MultiEdit duerfen verbatim-guard nicht umgehen.
# Edit-Tool-Input traegt den neuen Text in new_string; MultiEdit in
# edits[].new_string. Der Guard muss diese Pfade ebenso pruefen wie Write.
# ---------------------------------------------------------------------------


def run_hook_raw(payload: dict, env_overrides: dict = None) -> subprocess.CompletedProcess:
    """Startet den Hook mit beliebiger Payload (fuer Edit/MultiEdit-Shape)."""
    env = os.environ.copy()
    env["VAULT_DB_PATH"] = str(WORKTREE_ROOT / "nonexistent_vault_for_tests.db")
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["node", str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


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


def test_hook_blocks_unverified_quote_on_edit(tmp_path):
    """Regression #220: Edit auf kapitel/*.md mit unverifiziertem Zitat -> Block (exit 2)."""
    db_path = _empty_vault(tmp_path)
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "kapitel/kap1.md",
            "old_string": "Platzhalter",
            "new_string": 'Laut dem Autor "Dies ist ein sehr wichtiger Satz aus dem Buch" stimmt das.',
        },
    }
    result = run_hook_raw(payload, env_overrides={"VAULT_DB_PATH": db_path})
    assert result.returncode == 2, (
        f"Edit umgeht verbatim-guard: erwartet exit 2 (block), got {result.returncode}. "
        f"stderr: {result.stderr}"
    )


def test_hook_blocks_unverified_quote_on_multiedit(tmp_path):
    """Regression #220: MultiEdit auf *.tex mit unverifiziertem Zitat -> Block (exit 2)."""
    db_path = _empty_vault(tmp_path, "empty_vault2.db")
    payload = {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": "kapitel/kap1.tex",
            "edits": [
                {"old_string": "x", "new_string": "Harmloser Text ohne Zitat."},
                {
                    "old_string": "y",
                    "new_string": 'Er schrieb "Dies ist ein sehr wichtiger Satz aus dem Buch" woertlich.',
                },
            ],
        },
    }
    result = run_hook_raw(payload, env_overrides={"VAULT_DB_PATH": db_path})
    assert result.returncode == 2, (
        f"MultiEdit umgeht verbatim-guard: erwartet exit 2 (block), got {result.returncode}. "
        f"stderr: {result.stderr}"
    )


def test_hook_allows_clean_edit(tmp_path):
    """Edit ohne Zitat/Figure-Referenz wird durchgelassen (exit 0)."""
    db_path = _empty_vault(tmp_path, "empty_vault3.db")
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "kapitel/kap1.md",
            "old_string": "alt",
            "new_string": "Ein voellig unauffaelliger Absatz ohne Zitate.",
        },
    }
    result = run_hook_raw(payload, env_overrides={"VAULT_DB_PATH": db_path})
    assert result.returncode == 0, f"Erwartet 0, got {result.returncode}. stderr: {result.stderr}"


UNVERIFIED_QUOTE = 'Laut dem Autor "Dies ist ein sehr wichtiger Satz aus dem Buch" stimmt das.'


@pytest.mark.parametrize(
    "file_path",
    [
        "kapitel/teil1/intro.md",
        "kapitel/teil1/abschnitt2/ergebnisse.md",
        "projekt/kapitel/teil1/intro.md",
    ],
)
def test_hook_blocks_unverified_quote_in_nested_chapter_path(tmp_path, file_path):
    """Issue #516: Unterordner unter kapitel/ sind ebenfalls geschuetzt."""
    db_path = _empty_vault(tmp_path, "nested_vault.db")
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": UNVERIFIED_QUOTE},
    }
    result = run_hook_raw(payload, env_overrides={"VAULT_DB_PATH": db_path})
    assert result.returncode == 2, (
        f"Verschachtelter Kapitelpfad {file_path} umgeht verbatim-guard: "
        f"erwartet exit 2 (block), got {result.returncode}. stderr: {result.stderr}"
    )


@pytest.mark.parametrize(
    "file_path",
    [
        "notizen/entwurf.md",
        "README.md",
        "meinkapitel/intro.md",
        "kapitel/teil1/notiz.txt",
    ],
)
def test_hook_ignores_markdown_outside_kapitel(tmp_path, file_path):
    """Issue #516: Die Unterordner-Erweiterung darf nicht uebergeneralisieren."""
    db_path = _empty_vault(tmp_path, "outside_vault.db")
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": UNVERIFIED_QUOTE},
    }
    result = run_hook_raw(payload, env_overrides={"VAULT_DB_PATH": db_path})
    assert result.returncode == 0, (
        f"{file_path} liegt ausserhalb der Schutzzone, wurde aber geprueft: "
        f"got exit {result.returncode}. stderr: {result.stderr}"
    )
