"""Regression guard für Issue #189: lokales Cleanup .DS_Store + optionaler pre-commit hook.

Akzeptanzkriterien (siehe Issue #189):
- Kein `.DS_Store` ist im git-Index getrackt.
- `.gitignore` schließt `.DS_Store` aus.
- `.pre-commit-config.yaml` existiert mit den Hooks `check-added-large-files`,
  `forbid-new-submodules`, `detect-private-key`.
- README enthält einen Hinweis, dass pre-commit empfohlen wird.
"""

import subprocess
from pathlib import Path

import yaml

from tests.helpers import docs as _docs

REPO_ROOT = Path(__file__).parent.parent


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.splitlines()


def test_no_dsstore_is_tracked():
    tracked = _tracked_files()
    offenders = [p for p in tracked if Path(p).name == ".DS_Store"]
    assert not offenders, f".DS_Store darf nicht getrackt sein: {offenders}"


def test_gitignore_excludes_dsstore():
    gitignore = REPO_ROOT / ".gitignore"
    assert gitignore.exists(), ".gitignore fehlt"
    entries = {
        line.strip()
        for line in gitignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert ".DS_Store" in entries, ".gitignore muss '.DS_Store' ausschließen"


def test_pre_commit_config_exists_with_required_hooks():
    cfg = REPO_ROOT / ".pre-commit-config.yaml"
    assert cfg.exists(), ".pre-commit-config.yaml fehlt"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data.get("repos"), (
        ".pre-commit-config.yaml muss einen 'repos'-Block haben"
    )
    hook_ids = {hook.get("id") for repo in data["repos"] for hook in repo.get("hooks", [])}
    for required in ("check-added-large-files", "forbid-new-submodules", "detect-private-key"):
        assert required in hook_ids, f"pre-commit hook '{required}' fehlt"


def test_readme_mentions_pre_commit():
    """Die Entwickler-Doku empfiehlt pre-commit.

    Stand bis #402 in der README; mit dem Relaunch in docs/development.md
    ausgelagert, weil die README ein Nutzer- und kein Beitragenden-Dokument ist.
    """
    dev_doc = _docs.DEVELOPMENT_DOC
    assert dev_doc.exists(), "docs/development.md fehlt"
    assert "pre-commit" in dev_doc.read_text(encoding="utf-8").lower(), (
        "Entwickler-Doku sollte einen Hinweis auf pre-commit enthalten"
    )
