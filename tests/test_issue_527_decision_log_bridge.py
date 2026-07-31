"""Tests fuer Issue #527 — Decision-Log wieder verbunden.

Befund: `hooks/post-tool-use-decisions.mjs` schrieb in die Textdatei
`~/.academic-research/decisions.log`, waehrend `hooks/mid-session-reinforcement.mjs`
die SQLite-Tabelle `decisions` liest — die nie befuellt wurde. Das
Decision-Log-Feature (v6.4, #90/#91) war damit faktisch tot.

Diese Datei prueft die vier Akzeptanzkriterien:
  AC1  Eine vom Hook protokollierte Aenderung landet ohne Zwischenschritt in
       `list_decisions()` (SQLite).
  AC2  `mid-session-reinforcement.mjs` zeigt sie in der naechsten Session an —
       ohne echte (manuelle) Decisions zu verdraengen.
  AC3  Kein zweiter divergenter Speicherort: `decisions.log` ist Opt-in-Debug-Log.
  AC4  Der Schreibpfad bleibt billig (kein `academic_vault.server`-Import) und
       fail-open.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers import docs as _docs

REPO_ROOT = Path(__file__).resolve().parent.parent
DECISIONS_HOOK = REPO_ROOT / "hooks" / "post-tool-use-decisions.mjs"
REINFORCEMENT_HOOK = REPO_ROOT / "hooks" / "mid-session-reinforcement.mjs"
BRIDGE = REPO_ROOT / "hooks" / "lib" / "vault-bridge.mjs"


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_vault(tmp_path: Path) -> str:
    """Legt eine leere, initialisierte Vault-DB an und gibt den Pfad zurueck."""
    from academic_vault.db import VaultDB

    db_path = str(tmp_path / "vault.db")
    VaultDB(db_path).init_schema()
    return db_path


def run_node_hook(
    hook: Path, payload: dict, env_overrides: dict, timeout: int = 30
) -> subprocess.CompletedProcess:
    """Startet einen Hook als Node-Subprozess mit JSON-Payload auf stdin."""
    env = os.environ.copy()
    env.update(env_overrides)
    return subprocess.run(
        ["node", str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


def write_payload(md_file: Path, content: str) -> dict:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": str(md_file), "content": content},
    }


def hook_env(project_dir: Path, db_path: str | None = None, **extra: str) -> dict:
    """Environment fuer die Hooks: eigener Interpreter, eigenes HOME."""
    env = {
        "CLAUDE_PROJECT_DIR": str(project_dir),
        "ACADEMIC_PYTHON": sys.executable,
    }
    if db_path is not None:
        env["VAULT_DB_PATH"] = db_path
    env.update(extra)
    return env


# ---------------------------------------------------------------------------
# AC1 — Vault-Schreibpfad (academic_vault.decision_log)
# ---------------------------------------------------------------------------


def test_record_file_change_creates_active_decision(tmp_path):
    """Eine protokollierte Datei-Aenderung erscheint in list_decisions()."""
    from academic_vault.db import VaultDB
    from academic_vault.decision_log import AUTO_CATEGORY, record_file_change

    db_path = make_vault(tmp_path)
    record_file_change(db_path, "Write", "kapitel/kap1.md", _sha256("a"))

    decisions = VaultDB(db_path).list_decisions(active_only=True)
    assert len(decisions) == 1, f"Erwartet genau eine Decision, got {decisions}"
    assert decisions[0]["category"] == AUTO_CATEGORY
    assert "kap1.md" in decisions[0]["text"]


def test_same_hash_creates_no_duplicate(tmp_path):
    """Identischer Inhalt derselben Datei erzeugt keinen zweiten Eintrag."""
    from academic_vault.db import VaultDB
    from academic_vault.decision_log import record_file_change

    db_path = make_vault(tmp_path)
    digest = _sha256("unveraendert")
    first = record_file_change(db_path, "Write", "kapitel/kap1.md", digest)
    second = record_file_change(db_path, "Edit", "kapitel/kap1.md", digest)

    assert first == second, "Gleicher Hash muss dieselbe decision_id liefern"
    assert len(VaultDB(db_path).list_decisions(active_only=False)) == 1


def test_changed_hash_supersedes_previous(tmp_path):
    """Neuer Inhalt loest den Vorgaenger derselben Datei ab (max. 1 aktiv)."""
    from academic_vault.db import VaultDB
    from academic_vault.decision_log import record_file_change

    db_path = make_vault(tmp_path)
    old_id = record_file_change(db_path, "Write", "kapitel/kap1.md", _sha256("v1"))
    new_id = record_file_change(db_path, "Edit", "kapitel/kap1.md", _sha256("v2"))

    assert old_id != new_id
    db = VaultDB(db_path)
    active = db.list_decisions(active_only=True)
    assert len(active) == 1, f"Genau ein aktiver Eintrag pro Datei erwartet: {active}"
    assert active[0]["decision_id"] == new_id
    superseded = [d for d in db.list_decisions(active_only=False) if d["decision_id"] == old_id]
    assert superseded[0]["superseded_by"] == new_id


# ---------------------------------------------------------------------------
# Abgrenzung zum Material-Passport (#380) — die Auto-Eintraege sind kein
# Bestandteil des Reproduzierbarkeits-Artefakts.
# ---------------------------------------------------------------------------


class _FrozenTime:
    """Ersetzt das ``time``-Modul im Passport-Builder, damit ``created_at`` fix ist."""

    @staticmethod
    def time() -> int:
        return 1_700_000_000


def _export_passport(db_path: str, out_dir: Path) -> dict:
    from academic_vault import server as vault_server

    out_dir.mkdir(parents=True, exist_ok=True)
    path = vault_server.export_material_passport(
        db_path=db_path, slug="projekt", output_dir=str(out_dir)
    )
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_material_passport_excludes_auto_file_changes(tmp_path, monkeypatch):
    """`decisions_snapshot` enthaelt methodische Decisions, keine Auto-Eintraege.

    Der Passport ist das Reproduzierbarkeits-Artefakt (#380). Datei-Aenderungen
    sind keine methodischen Entscheidungen — sie gehoeren dort so wenig hinein
    wie in den Decisions-Block des Reinforcements.
    """
    from academic_vault import material_passport
    from academic_vault.decision_log import AUTO_CATEGORY, record_file_change

    monkeypatch.setattr(material_passport, "time", _FrozenTime)

    db_path = make_vault(tmp_path)
    from academic_vault import server as vault_server

    manual_id = vault_server.add_decision(db_path, "scope", "Nur Peer-Review", "Qualitaet")
    record_file_change(db_path, "Write", "kapitel/kap1.md", _sha256("a"))

    snapshot = _export_passport(db_path, tmp_path / "out")["decisions_snapshot"]

    assert [d["decision_id"] for d in snapshot] == [manual_id], (
        f"Auto-Eintraege im Passport-Snapshot: {snapshot}"
    )
    assert all(d.get("category") != AUTO_CATEGORY for d in snapshot)


def test_passport_hash_is_stable_across_markdown_writes(tmp_path, monkeypatch):
    """Ein `.md`-Write darf den `passport_hash` nicht bewegen.

    Sonst signalisiert der Passport bei jeder Kapitel-Aenderung ein neues
    Material, obwohl sich am Material nichts geaendert hat.
    """
    from academic_vault import material_passport
    from academic_vault.decision_log import record_file_change

    monkeypatch.setattr(material_passport, "time", _FrozenTime)

    db_path = make_vault(tmp_path)
    before = _export_passport(db_path, tmp_path / "vorher")["passport_hash"]

    for i in range(12):
        record_file_change(db_path, "Write", f"kapitel/kap{i}.md", _sha256(str(i)))

    after = _export_passport(db_path, tmp_path / "nachher")["passport_hash"]

    assert before == after, "12 Markdown-Writes haben den passport_hash veraendert"


def test_distinct_files_get_distinct_decisions(tmp_path):
    """Verschiedene Dateien verdraengen sich nicht gegenseitig."""
    from academic_vault.db import VaultDB
    from academic_vault.decision_log import record_file_change

    db_path = make_vault(tmp_path)
    record_file_change(db_path, "Write", "kapitel/kap1.md", _sha256("a"))
    record_file_change(db_path, "Write", "kapitel/kap2.md", _sha256("b"))

    active = VaultDB(db_path).list_decisions(active_only=True)
    assert len(active) == 2


def test_record_file_change_stores_no_plaintext_content(tmp_path):
    """Privacy (#191): in der DB stehen nur Pfad, Tool und Hash."""
    from academic_vault.db import VaultDB
    from academic_vault.decision_log import record_file_change

    db_path = make_vault(tmp_path)
    record_file_change(db_path, "Write", "kapitel/kap1.md", _sha256("GEHEIM-PII"))

    row = VaultDB(db_path).list_decisions(active_only=True)[0]
    blob = json.dumps(row, ensure_ascii=False)
    assert "GEHEIM-PII" not in blob
    assert _sha256("GEHEIM-PII") in blob


def test_record_file_change_is_failopen_on_missing_table(tmp_path):
    """Eine DB ohne decisions-Tabelle fuehrt zu None statt zu einer Exception."""
    import sqlite3

    from academic_vault.decision_log import record_file_change

    db_path = str(tmp_path / "leer.db")
    sqlite3.connect(db_path).close()

    assert record_file_change(db_path, "Write", "kap1.md", _sha256("x")) is None


def test_record_file_change_is_failopen_on_locked_vault(tmp_path):
    """Gesperrter Material-Passport blockiert den Hook nicht (VaultLockedError)."""
    from academic_vault.db import VaultDB
    from academic_vault.decision_log import record_file_change

    db_path = make_vault(tmp_path)
    VaultDB(db_path).lock_vault("testprojekt")

    assert record_file_change(db_path, "Write", "kap1.md", _sha256("x")) is None


# ---------------------------------------------------------------------------
# AC1 — der Hook selbst schreibt in den Vault
# ---------------------------------------------------------------------------


def test_hook_write_lands_in_vault_decisions(tmp_path):
    """Ein Write-Event des Hooks erscheint ohne Zwischenschritt in list_decisions()."""
    from academic_vault.db import VaultDB
    from academic_vault.decision_log import AUTO_CATEGORY

    project = tmp_path / "projekt"
    (project / "kapitel").mkdir(parents=True)
    db_path = make_vault(tmp_path)

    result = run_node_hook(
        DECISIONS_HOOK,
        write_payload(project / "kapitel" / "kap1.md", "# Kapitel 1\nText"),
        hook_env(project, db_path),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    active = VaultDB(db_path).list_decisions(active_only=True)
    assert len(active) == 1, f"Keine Decision im Vault: {active}, stderr={result.stderr}"
    assert active[0]["category"] == AUTO_CATEGORY
    assert "kap1.md" in active[0]["text"]


@pytest.mark.parametrize(
    ("tool_name", "tool_input_extra"),
    [
        ("Edit", {"old_string": "alt", "new_string": "neu"}),
        ("MultiEdit", {"edits": [{"old_string": "a", "new_string": "neu"}]}),
    ],
)
def test_edit_and_multiedit_land_in_vault(tmp_path, tool_name, tool_input_extra):
    """Regression #220 auf dem neuen Pfad: Edit/MultiEdit umgehen den Vault nicht."""
    from academic_vault.db import VaultDB

    project = tmp_path / "projekt"
    project.mkdir()
    db_path = make_vault(tmp_path)

    payload = {
        "tool_name": tool_name,
        "tool_input": {"file_path": str(project / "kap2.md"), **tool_input_extra},
    }
    result = run_node_hook(DECISIONS_HOOK, payload, hook_env(project, db_path))
    assert result.returncode == 0, f"stderr: {result.stderr}"

    active = VaultDB(db_path).list_decisions(active_only=True)
    assert len(active) == 1, f"{tool_name} landete nicht im Vault: {result.stderr}"
    assert "kap2.md" in active[0]["text"]


def test_hook_writes_no_duplicate_for_unchanged_content(tmp_path):
    """Zwei identische Writes derselben Datei ergeben genau einen aktiven Eintrag."""
    from academic_vault.db import VaultDB

    project = tmp_path / "projekt"
    project.mkdir()
    db_path = make_vault(tmp_path)
    payload = write_payload(project / "kap1.md", "# Unveraendert")

    for _ in range(2):
        result = run_node_hook(DECISIONS_HOOK, payload, hook_env(project, db_path))
        assert result.returncode == 0, f"stderr: {result.stderr}"

    assert len(VaultDB(db_path).list_decisions(active_only=False)) == 1


def test_both_hooks_resolve_same_db_path(tmp_path):
    """Ohne VAULT_DB_PATH schreiben und lesen beide Hooks dieselbe DB.

    Genau diese Divergenz war der Bug: der eine Hook adressierte eine
    Textdatei, der andere eine DB. Der Test faehrt beide Hooks nur ueber
    CLAUDE_PROJECT_DIR + HOME und verlangt, dass die Schreib-Seite in der
    DB landet, die die Lese-Seite oeffnet.
    """
    home = tmp_path / "home"
    project = tmp_path / "projekt-527"
    project.mkdir()
    db_dir = home / ".academic-research" / "projects" / "projekt-527"
    db_dir.mkdir(parents=True)
    make_vault(db_dir)  # legt vault.db im kanonischen Verzeichnis an

    env = hook_env(project, None, HOME=str(home), VIRTUAL_ENV="")
    write_result = run_node_hook(
        DECISIONS_HOOK, write_payload(project / "kap1.md", "# Inhalt"), env
    )
    assert write_result.returncode == 0, f"stderr: {write_result.stderr}"

    read_result = run_node_hook(
        REINFORCEMENT_HOOK,
        {"hook_event_name": "SessionStart", "source": "compact"},
        dict(env, ACADEMIC_REINFORCEMENT_STATE=str(tmp_path / "state.json")),
    )
    assert read_result.returncode == 0, f"stderr: {read_result.stderr}"
    assert "kap1.md" in read_result.stdout, (
        "Schreib- und Lesepfad zeigen auf unterschiedliche DBs: "
        f"stdout={read_result.stdout!r}, stderr={read_result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# AC2 — das Reinforcement zeigt die Entscheidung an
# ---------------------------------------------------------------------------


def test_hook_written_decision_reaches_reinforcement(tmp_path):
    """Ohne Zwischenschritt: Hook schreibt, Reinforcement zeigt an."""
    project = tmp_path / "projekt"
    (project / "kapitel").mkdir(parents=True)
    db_path = make_vault(tmp_path)
    env = hook_env(project, db_path)

    write_result = run_node_hook(
        DECISIONS_HOOK,
        write_payload(project / "kapitel" / "kap1.md", "# Kapitel 1"),
        env,
    )
    assert write_result.returncode == 0, f"stderr: {write_result.stderr}"

    read_result = run_node_hook(
        REINFORCEMENT_HOOK,
        {"hook_event_name": "SessionStart", "source": "compact"},
        dict(env, ACADEMIC_REINFORCEMENT_STATE=str(tmp_path / "state.json")),
    )
    assert read_result.returncode == 0, f"stderr: {read_result.stderr}"
    assert "kap1.md" in read_result.stdout, (
        f"stdout={read_result.stdout!r}, stderr={read_result.stderr!r}"
    )


def test_manual_decisions_not_crowded_out(tmp_path):
    """Viele Datei-Aenderungen verdraengen die manuelle Decision nicht."""
    from academic_vault.db import VaultDB
    from academic_vault.decision_log import record_file_change

    project = tmp_path / "projekt"
    project.mkdir()
    db_path = make_vault(tmp_path)

    VaultDB(db_path).add_decision(
        category="Zitierstil", text="APA 7th Edition verwenden", rationale=None
    )
    for index in range(6):
        record_file_change(db_path, "Write", f"kapitel/kap{index}.md", _sha256(str(index)))

    result = run_node_hook(
        REINFORCEMENT_HOOK,
        {"hook_event_name": "SessionStart", "source": "compact"},
        hook_env(project, db_path, ACADEMIC_REINFORCEMENT_STATE=str(tmp_path / "state.json")),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "APA 7th Edition verwenden" in result.stdout, (
        f"Die manuelle Decision wurde von den Auto-Eintraegen verdraengt: {result.stdout!r}"
    )


def test_reinforcement_limits_file_change_bucket(tmp_path):
    """Der Datei-Aenderungs-Block bleibt auf wenige Eintraege begrenzt."""
    from academic_vault.decision_log import record_file_change

    project = tmp_path / "projekt"
    project.mkdir()
    db_path = make_vault(tmp_path)
    for index in range(8):
        record_file_change(db_path, "Write", f"kapitel/kap{index}.md", _sha256(str(index)))

    result = run_node_hook(
        REINFORCEMENT_HOOK,
        {"hook_event_name": "SessionStart", "source": "compact"},
        hook_env(project, db_path, ACADEMIC_REINFORCEMENT_STATE=str(tmp_path / "state.json")),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    listed = [name for name in (f"kap{i}.md" for i in range(8)) if name in result.stdout]
    assert 0 < len(listed) <= 3, f"Unerwartet viele/keine Datei-Eintraege: {listed}"


# ---------------------------------------------------------------------------
# AC3 — kein zweiter divergenter Speicherort
# ---------------------------------------------------------------------------


def test_no_default_decisions_log_without_env(tmp_path):
    """Ohne ACADEMIC_DECISIONS_LOG entsteht keine Log-Datei unter HOME."""
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "projekt"
    project.mkdir()
    db_path = make_vault(tmp_path)

    result = run_node_hook(
        DECISIONS_HOOK,
        write_payload(project / "kap1.md", "# Inhalt"),
        hook_env(project, db_path, HOME=str(home)),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    strays = list(home.rglob("decisions.log*"))
    assert not strays, f"decisions.log wird weiterhin per Default geschrieben: {strays}"


def test_debug_log_is_opt_in_and_0600(tmp_path):
    """Mit gesetztem ACADEMIC_DECISIONS_LOG schreibt der Hook weiter (0600, Hash)."""
    import stat

    project = tmp_path / "projekt"
    project.mkdir()
    log_file = tmp_path / "decisions.log"
    db_path = make_vault(tmp_path)

    result = run_node_hook(
        DECISIONS_HOOK,
        write_payload(project / "kap1.md", "# GEHEIM-PII"),
        hook_env(project, db_path, ACADEMIC_DECISIONS_LOG=str(log_file)),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert log_file.exists(), "Opt-in-Debug-Log wurde nicht geschrieben"
    assert stat.S_IMODE(log_file.stat().st_mode) == 0o600
    text = log_file.read_text(encoding="utf-8")
    assert "GEHEIM-PII" not in text
    assert _sha256("# GEHEIM-PII") in text


def test_hooks_doc_marks_decisions_log_as_debug():
    """Die Hooks-Referenz kennzeichnet decisions.log als Opt-in-Debug-Log."""
    text = _docs.HOOKS_DOC.read_text(encoding="utf-8")
    assert "ACADEMIC_DECISIONS_LOG" in text
    assert "Debug-Log" in text, (
        "docs/reference/hooks.md kennzeichnet decisions.log nicht als Debug-Log"
    )
    assert "file-change" in text, (
        "Die Doku nennt die neue Senke (Vault-Tabelle decisions, Kategorie file-change) nicht"
    )


# ---------------------------------------------------------------------------
# AC4 — billiger, fail-open Schreibpfad
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hook_name", ["post-tool-use-decisions.mjs", "mid-session-reinforcement.mjs"]
)
def test_hooks_do_not_import_server(hook_name):
    """Kein Hook darf academic_vault.server importieren (Latenz-Regression).

    Der PostToolUse-Hook feuert bei JEDEM `.md`-Write; `academic_vault.server`
    zieht die fastmcp/pydantic-Kette nach (~1,2 s CPU statt ~0,06 s fuer
    `academic_vault.db`).
    """
    source = (REPO_ROOT / "hooks" / hook_name).read_text(encoding="utf-8")
    for statement in ("from academic_vault.server", "import academic_vault.server"):
        assert statement not in source, f"{hook_name} enthaelt '{statement}'"


def test_decision_log_module_does_not_pull_server():
    """`academic_vault.decision_log` laedt den MCP-Server nicht mit."""
    probe = (
        "import sys, json; import academic_vault.decision_log; "
        "print(json.dumps('academic_vault.server' in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=True,
    )
    assert json.loads(result.stdout.strip()) is False, (
        "decision_log zieht academic_vault.server nach"
    )


def test_hook_is_failopen_without_vault_db(tmp_path):
    """Fehlt die Vault-DB, bleibt der Hook still und exit 0 — und legt keine DB an."""
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "projekt-ohne-vault"
    project.mkdir()

    result = run_node_hook(
        DECISIONS_HOOK,
        write_payload(project / "kap1.md", "# Inhalt"),
        hook_env(project, None, HOME=str(home), VIRTUAL_ENV=""),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert not list(home.rglob("vault.db")), "Der Hook hat eine Vault-DB angelegt"


def test_hook_is_failopen_with_broken_interpreter(tmp_path):
    """Ein kaputter ACADEMIC_PYTHON blockiert den Write nicht."""
    project = tmp_path / "projekt"
    project.mkdir()
    db_path = make_vault(tmp_path)

    result = run_node_hook(
        DECISIONS_HOOK,
        write_payload(project / "kap1.md", "# Inhalt"),
        hook_env(project, db_path, ACADEMIC_PYTHON=str(tmp_path / "gibt-es-nicht" / "python")),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_both_hooks_share_the_vault_bridge():
    """Beide Hooks beziehen DB-Pfad und Interpreter aus derselben Bruecke."""
    assert BRIDGE.exists(), "hooks/lib/vault-bridge.mjs fehlt"
    for hook in (DECISIONS_HOOK, REINFORCEMENT_HOOK):
        assert "vault-bridge.mjs" in hook.read_text(encoding="utf-8"), (
            f"{hook.name} nutzt die gemeinsame Bruecke nicht — die Pfad-Divergenz "
            "koennte erneut auseinanderlaufen"
        )
