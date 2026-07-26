"""Tests fuer Issue #190 — vault.db-Pfad-Konsistenz.

Stellt sicher:
  (a) .gitignore (Repo-Wurzel) UND das Bootstrap-Fragment ignorieren *.db / vault.db,
      damit keine Forschungs-PII versehentlich committet wird (CWE-538).
  (b) Es gibt genau EINE kanonische Quelle der Wahrheit fuer den DB-Default:
      academic_vault.db.default_db_path(). Der MCP-Server (server.py) leitet
      seinen Default davon ab, und der Default zeigt NICHT mehr ins CWD oder
      ins Plugin-Verzeichnis, sondern nach ~/.academic-research/projects/<slug>/vault.db.

TDD: Diese Tests schlagen gegen den Zustand auf origin/main fehl, weil dort
weder .gitignore noch das Fragment *.db ignorieren und es keine zentrale
default_db_path()-Funktion gibt (server.py:19 nutzt hart "vault.db" im CWD).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# (a) .gitignore — vault.db / *.db duerfen nicht ins Repo gelangen
# ---------------------------------------------------------------------------


def _matches_db_pattern(lines: list[str]) -> bool:
    """True, wenn irgendeine .gitignore-Zeile vault.db bzw. *.db erfasst."""
    db_patterns = {"*.db", "vault.db", "**/*.db", "*.db*"}
    return any(ln.strip() in db_patterns for ln in lines)


def test_repo_gitignore_ignores_db_files():
    gitignore = REPO_ROOT / ".gitignore"
    assert gitignore.exists(), ".gitignore fehlt in der Repo-Wurzel"
    lines = gitignore.read_text(encoding="utf-8").splitlines()
    assert _matches_db_pattern(lines), (
        ".gitignore muss ein Pattern enthalten, das vault.db/*.db ignoriert "
        "(Forschungs-PII darf nicht committet werden — CWE-538)."
    )


def test_bootstrap_gitignore_fragment_ignores_db_files():
    fragment = REPO_ROOT / "scripts" / "bootstrap" / "gitignore.fragment"
    assert fragment.exists(), "bootstrap/gitignore.fragment fehlt"
    lines = fragment.read_text(encoding="utf-8").splitlines()
    assert _matches_db_pattern(lines), (
        "Das Bootstrap-Fragment muss vault.db/*.db ignorieren, damit "
        "bootstrappte Projekte ihre DB nicht versehentlich committen."
    )


# ---------------------------------------------------------------------------
# (b) Single Source of Truth fuer den DB-Default
# ---------------------------------------------------------------------------


def test_canonical_resolver_exists():
    from academic_vault import db

    assert hasattr(db, "default_db_path"), (
        "academic_vault.db muss eine kanonische Resolver-Funktion "
        "default_db_path() exportieren (Single Source of Truth)."
    )


def test_canonical_resolver_respects_env(monkeypatch):
    from academic_vault import db

    monkeypatch.setenv("VAULT_DB_PATH", "/tmp/explicit/vault.db")
    assert db.default_db_path() == "/tmp/explicit/vault.db"


def test_canonical_resolver_default_is_under_home_projects(monkeypatch, tmp_path):
    """Ohne VAULT_DB_PATH liegt der Default unter ~/.academic-research/projects/<slug>/vault.db
    und NICHT im CWD oder im Plugin-Verzeichnis."""
    from academic_vault import db

    monkeypatch.delenv("VAULT_DB_PATH", raising=False)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    workdir = tmp_path / "meine-facharbeit"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    resolved = Path(db.default_db_path())
    expected = fake_home / ".academic-research" / "projects" / "meine-facharbeit" / "vault.db"
    assert resolved == expected, f"erwartet {expected}, war {resolved}"
    # Darf nicht im CWD und nicht im Plugin-Repo liegen
    assert Path(resolved).parent != workdir
    assert REPO_ROOT not in Path(resolved).parents


def test_project_slug_prefers_claude_project_dir_over_cwd(monkeypatch, tmp_path):
    """project_slug() (parameterlos) bevorzugt CLAUDE_PROJECT_DIR vor Path.cwd(),
    genau wie hooks/verbatim-guard.mjs (Issue #365)."""
    from academic_vault import db

    project_dir = tmp_path / "mein-claude-projekt"
    project_dir.mkdir()
    other_cwd = tmp_path / "irgendein-anderes-verzeichnis"
    other_cwd.mkdir()

    monkeypatch.chdir(other_cwd)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))

    assert db.project_slug() == "mein-claude-projekt"


def test_project_slug_falls_back_to_cwd_without_claude_project_dir(monkeypatch, tmp_path):
    """Ohne CLAUDE_PROJECT_DIR bleibt project_slug() beim bisherigen
    Path.cwd()-Verhalten (Rueckwaertskompatibilitaet)."""
    from academic_vault import db

    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    workdir = tmp_path / "nur-cwd-projekt"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    assert db.project_slug() == "nur-cwd-projekt"


def test_project_slug_explicit_cwd_param_beats_env(monkeypatch, tmp_path):
    """Ein explizit uebergebener cwd-Parameter gewinnt weiterhin gegen
    CLAUDE_PROJECT_DIR (Escape-Hatch fuer bestehende Aufrufer/Tests, #365)."""
    from academic_vault import db

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "env-projekt"))
    explicit = tmp_path / "explizit-projekt"
    explicit.mkdir()

    assert db.project_slug(str(explicit)) == "explizit-projekt"


def test_server_default_derives_from_canonical_resolver(monkeypatch):
    """server.py darf den Default nicht mehr hart als 'vault.db' (CWD) setzen,
    sondern muss ihn aus dem kanonischen Resolver ableiten."""
    src = (REPO_ROOT / "academic_vault" / "server.py").read_text(encoding="utf-8")
    # Kein hart kodierter CWD-Fallback "vault.db" mehr als Default-Quelle.
    assert 'os.environ.get("VAULT_DB_PATH", "vault.db")' not in src, (
        "server.py darf den CWD-Fallback 'vault.db' nicht mehr verwenden; "
        "muss default_db_path() referenzieren."
    )
    assert "default_db_path" in src, (
        "server.py muss die kanonische default_db_path()-Funktion verwenden."
    )


# ---------------------------------------------------------------------------
# (c) .mcp.json -- keine kaputte Bash-Substring-Expansion mehr (Issue #365)
# ---------------------------------------------------------------------------


def test_mcp_json_has_no_broken_pwd_substring_expansion():
    """`.mcp.json` darf ${PWD##*/} nicht mehr enthalten.

    Claude Code loest Bash-Substring-Expansion in env-Werten nicht auf; der
    gespawnte Server-Prozess erhielt den Platzhalter woertlich im Pfad und
    scheiterte bei jedem Schreibzugriff mit sqlite3.OperationalError, weil
    das Verzeichnis nie existiert (Issue #365).
    """
    mcp_json = REPO_ROOT / ".mcp.json"
    assert mcp_json.exists(), ".mcp.json fehlt in der Repo-Wurzel"
    raw = mcp_json.read_text(encoding="utf-8")
    assert "${PWD##*/}" not in raw, (
        ".mcp.json enthaelt noch die kaputte Bash-Substring-Expansion "
        "${PWD##*/} -- Claude Code loest das nicht auf, der Server-Prozess "
        "bekommt den Platzhalter woertlich in VAULT_DB_PATH (#365)."
    )


def test_mcp_json_has_no_manual_vault_db_path_env():
    """.mcp.json setzt VAULT_DB_PATH nicht mehr manuell.

    Der Server soll ohne gesetzte Env-Variable ueber
    academic_vault.db.default_db_path() automatisch auf
    ~/.academic-research/projects/<slug>/vault.db zurueckfallen (#365).
    """
    import json as jsonlib

    mcp_json = REPO_ROOT / ".mcp.json"
    config = jsonlib.loads(mcp_json.read_text(encoding="utf-8"))
    env = config["mcpServers"]["academic-vault"]["env"]
    assert "VAULT_DB_PATH" not in env, (
        ".mcp.json darf VAULT_DB_PATH nicht mehr manuell setzen -- der Server "
        "soll ueber default_db_path() automatisch den kanonischen Pfad "
        "verwenden (#365)."
    )


def test_mcp_json_default_academic_vault_only_env_stays_valid_json():
    """.mcp.json bleibt nach dem Entfernen von VAULT_DB_PATH valides JSON
    mit den verbleibenden erwarteten Env-Keys."""
    import json as jsonlib

    mcp_json = REPO_ROOT / ".mcp.json"
    config = jsonlib.loads(mcp_json.read_text(encoding="utf-8"))
    env = config["mcpServers"]["academic-vault"]["env"]
    assert set(env.keys()) == {"PYTHONPATH", "SQLITE_VEC_PATH"}
