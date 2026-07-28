"""Regressionstest fuer Issue #377 — TF-IDF-Parallelsystem entfernt.

Belegt die Akzeptanzkriterien aus Issue #377:
  - scripts/pdf.py enthaelt keine TF-IDF-Fulltext-Index-Funktionen mehr.
  - scripts/files_api_helper.py, scripts/auth_helper_lib.py, scripts/smoke.py
    existieren nicht mehr.
  - Kein verbleibender Skill/Command/Test referenziert die entfernten
    Dateien/Funktionen.
"""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_pdf_py_has_no_tfidf_functions():
    """scripts/pdf.py referenziert die TF-IDF-Funktionen nicht mehr (AC1)."""
    src = (REPO_ROOT / "scripts" / "pdf.py").read_text(encoding="utf-8")
    for pattern in ("action_index", "action_search", "_tokenize_for_index"):
        assert pattern not in src, f"{pattern} noch in scripts/pdf.py gefunden"


def test_orphaned_scripts_deleted():
    """Die drei verwaisten Skripte existieren nicht mehr im Repo (AC2)."""
    for name in ("files_api_helper.py", "auth_helper_lib.py", "smoke.py"):
        assert not (REPO_ROOT / "scripts" / name).exists(), f"scripts/{name} existiert noch"


def test_no_remaining_references_to_removed_code():
    """Repo-weiter Grep (nur git-getrackte Dateien, damit .venv/vendored
    Code keine False-Positives liefert) ueber *.py/*.md/*.mjs/*.sh/*.json
    findet keine Treffer mehr fuer die entfernten Funktionen/Dateien (AC3),
    exkl. dieser Testdatei selbst (die die Suchmuster als String-Literale
    enthaelt)."""
    this_file_rel = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()
    pattern = (
        r"action_index|action_search|_tokenize_for_index|"
        r"files_api_helper|auth_helper_lib|scripts/smoke|scripts\.smoke"
    )
    result = subprocess.run(
        [
            "git",
            "grep",
            "-lE",
            pattern,
            "--",
            "*.py",
            "*.md",
            "*.mjs",
            "*.sh",
            "*.json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    hits = [line for line in result.stdout.splitlines() if line != this_file_rel]
    assert hits == [], f"Verbleibende Referenzen gefunden: {hits}"
