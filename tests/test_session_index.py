"""Tests for scripts/session_index.py (#466):

`/academic-research:history` reads `~/.academic-research/sessions/index.json`,
but nothing ever wrote to it — the index that history relies on was always
empty. `session_index.py` supplies the missing write/read/search/restore
path; `commands/search.md` and `commands/history.md` are wired to it.

Covers the four acceptance criteria of #466:
  1. After a search run, the session appears in the listing with query,
     date and hit count.
  2. A past session can be selected and restored as the working state.
  3. Searching the history finds sessions by their query.
  4. A deleted session folder yields a plain-language message instead of
     a crash.
"""

import json
import time
from pathlib import Path

import session_index

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCH_MD = REPO_ROOT / "commands" / "search.md"
HISTORY_MD = REPO_ROOT / "commands" / "history.md"

# ---------------------------------------------------------------------------
# Import / API surface
# ---------------------------------------------------------------------------


def test_module_importable():
    """scripts/session_index.py must be importable."""
    import session_index as mod  # noqa: F401

    for name in (
        "load_session_index",
        "save_session_index",
        "count_fulltexts",
        "build_session_entry",
        "update_session_index",
        "search_session_index",
        "annotate_missing_sessions",
        "restore_session",
    ):
        assert hasattr(mod, name), f"session_index missing {name}"
        assert callable(getattr(mod, name))


# ---------------------------------------------------------------------------
# load_session_index: tolerant of missing / corrupt index.json
# ---------------------------------------------------------------------------


def test_load_session_index_missing_file_returns_empty_list(tmp_path):
    index_path = tmp_path / "index.json"
    assert session_index.load_session_index(index_path) == []


def test_load_session_index_corrupt_json_returns_empty_list(tmp_path):
    index_path = tmp_path / "index.json"
    index_path.write_text("{not valid json", encoding="utf-8")
    assert session_index.load_session_index(index_path) == []


def test_load_session_index_non_list_json_returns_empty_list(tmp_path):
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps({"unexpected": "shape"}), encoding="utf-8")
    assert session_index.load_session_index(index_path) == []


# ---------------------------------------------------------------------------
# count_fulltexts
# ---------------------------------------------------------------------------


def test_count_fulltexts_no_pdfs_dir_returns_zero(tmp_path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    assert session_index.count_fulltexts(session_dir) == 0


def test_count_fulltexts_counts_pdf_files(tmp_path):
    session_dir = tmp_path / "session"
    pdfs = session_dir / "pdfs"
    pdfs.mkdir(parents=True)
    (pdfs / "a.pdf").write_bytes(b"%PDF-1.4")
    (pdfs / "b.pdf").write_bytes(b"%PDF-1.4")
    (pdfs / "notes.txt").write_text("not a pdf")
    assert session_index.count_fulltexts(session_dir) == 2


# ---------------------------------------------------------------------------
# Akzeptanzkriterium 1: Session erscheint nach Suchlauf mit Query/Datum/Trefferzahl
# ---------------------------------------------------------------------------


def test_update_session_index_appends_entry_with_query_mode_hits(tmp_path):
    index_path = tmp_path / "index.json"
    session_dir = tmp_path / "session-1"
    (session_dir / "pdfs").mkdir(parents=True)

    entry = session_index.build_session_entry(
        session_dir, query="DevOps Governance", mode="standard", n_hits=47
    )
    session_index.update_session_index(index_path, entry)

    entries = session_index.load_session_index(index_path)
    assert len(entries) == 1
    saved = entries[0]
    assert saved["query"] == "DevOps Governance"
    assert saved["mode"] == "standard"
    assert saved["n_hits"] == 47
    assert saved["session_path"] == str(session_dir)
    assert "timestamp" in saved and saved["timestamp"]


def test_update_session_index_upserts_by_session_path(tmp_path):
    index_path = tmp_path / "index.json"
    session_dir = tmp_path / "session-1"
    session_dir.mkdir()

    first = session_index.build_session_entry(
        session_dir, query="AI Ethics", mode="quick", n_hits=10
    )
    session_index.update_session_index(index_path, first)
    second = session_index.build_session_entry(
        session_dir, query="AI Ethics v2", mode="deep", n_hits=32
    )
    session_index.update_session_index(index_path, second)

    entries = session_index.load_session_index(index_path)
    assert len(entries) == 1, "same session_path must replace, not duplicate"
    assert entries[0]["query"] == "AI Ethics v2"
    assert entries[0]["n_hits"] == 32


def test_build_session_entry_counts_fulltexts_by_default(tmp_path):
    session_dir = tmp_path / "session-1"
    pdfs = session_dir / "pdfs"
    pdfs.mkdir(parents=True)
    (pdfs / "p1.pdf").write_bytes(b"%PDF-1.4")

    entry = session_index.build_session_entry(session_dir, query="X", mode="standard", n_hits=5)
    assert entry["n_fulltexts"] == 1


# ---------------------------------------------------------------------------
# Akzeptanzkriterium 2: frühere Session auswählbar & wiederherstellbar
# ---------------------------------------------------------------------------


def test_restore_session_makes_entry_latest_by_mtime(tmp_path):
    older = tmp_path / "older-session"
    newer = tmp_path / "newer-session"
    older.mkdir()
    time.sleep(0.01)
    newer.mkdir()

    # Sanity check: newer is currently the latest by the ls -t convention
    # (score.md/excel.md pick the session dir with the highest mtime).
    latest_before = max((older, newer), key=lambda p: p.stat().st_mtime)
    assert latest_before == newer

    result = session_index.restore_session(older)
    assert result["ok"] is True

    latest_after = max((older, newer), key=lambda p: p.stat().st_mtime)
    assert latest_after == older, "restore_session must bump mtime so it sorts as latest"


# ---------------------------------------------------------------------------
# Akzeptanzkriterium 3: Suche über die Historie findet Sessions per Suchbegriff
# ---------------------------------------------------------------------------


def test_search_session_index_matches_case_insensitive_substring():
    entries = [
        {"session_path": "/a", "query": "DevOps Governance"},
        {"session_path": "/b", "query": "AI Ethics"},
        {"session_path": "/c", "query": "ml in healthcare"},
    ]
    results = session_index.search_session_index(entries, "devops")
    assert [e["session_path"] for e in results] == ["/a"]

    results_ml = session_index.search_session_index(entries, "ML")
    assert [e["session_path"] for e in results_ml] == ["/c"]

    results_none = session_index.search_session_index(entries, "quantum computing")
    assert results_none == []


# ---------------------------------------------------------------------------
# Akzeptanzkriterium 4: gelöschter Sitzungsordner → Meldung statt Fehler
# ---------------------------------------------------------------------------


def test_annotate_missing_sessions_flags_deleted_folder_without_raising(tmp_path):
    existing = tmp_path / "still-here"
    existing.mkdir()
    entries = [
        {"session_path": str(existing), "query": "kept"},
        {"session_path": str(tmp_path / "long-gone"), "query": "deleted"},
    ]

    annotated = session_index.annotate_missing_sessions(entries)

    kept = next(e for e in annotated if e["query"] == "kept")
    deleted = next(e for e in annotated if e["query"] == "deleted")
    assert kept["missing"] is False
    assert "status" not in kept
    assert deleted["missing"] is True
    assert "status" in deleted and deleted["status"]


def test_restore_session_missing_folder_returns_status_without_raising(tmp_path):
    missing = tmp_path / "does-not-exist"
    result = session_index.restore_session(missing)
    assert result["ok"] is False
    assert "nicht gefunden" in result["message"]


# ---------------------------------------------------------------------------
# save_session_index: atomic write (no leftover .tmp file, valid JSON)
# ---------------------------------------------------------------------------


def test_save_session_index_writes_valid_json_without_leftover_tmp(tmp_path):
    index_path = tmp_path / "nested" / "index.json"
    entries = [{"session_path": "/x", "query": "q"}]

    session_index.save_session_index(entries, index_path)

    assert index_path.exists()
    assert json.loads(index_path.read_text(encoding="utf-8")) == entries
    assert not (index_path.parent / (index_path.name + ".tmp")).exists()


# ---------------------------------------------------------------------------
# Wiring: search.md schreibt den Index tatsächlich fort
# ---------------------------------------------------------------------------


def test_search_md_calls_update_session_index():
    """search.md muss update_session_index nach dem Scoring aufrufen (#466)."""
    content = SEARCH_MD.read_text(encoding="utf-8")
    assert "session_index" in content, "search.md importiert das session_index-Modul nicht"
    assert "update_session_index" in content, "search.md ruft update_session_index nicht auf"
    assert "build_session_entry" in content, "search.md baut keinen Session-Eintrag auf"


# ---------------------------------------------------------------------------
# Wiring: history.md liest/sucht/restauriert über session_index.py
# ---------------------------------------------------------------------------


def _parse_frontmatter(path: Path) -> dict:
    """Parse YAML frontmatter delimited by '---' lines (ohne yaml-Dep)."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return {}
    fm: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" in line:
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip()
    return fm


def test_history_md_argument_hint_documents_restore_session():
    """`--restore-session <id>` muss im argument-hint von history.md stehen."""
    fm = _parse_frontmatter(HISTORY_MD)
    hint = fm.get("argument-hint", "")
    assert "--restore-session" in hint, (
        f"argument-hint von history.md dokumentiert --restore-session nicht: {hint!r}"
    )
    # --restore (Snapshot) muss weiterhin dokumentiert bleiben, um die
    # bestehende Semantik nicht zu verlieren.
    assert "--restore <ts>" in hint


def test_history_md_reads_session_index_module_not_raw_cat():
    """history.md muss session_index.py statt rohem `cat index.json` nutzen (#466)."""
    content = HISTORY_MD.read_text(encoding="utf-8")
    assert "session_index" in content, "history.md importiert das session_index-Modul nicht"
    assert "load_session_index" in content
    assert "cat ~/.academic-research/sessions/index.json" not in content, (
        "history.md sollte den Index nicht mehr per rohem cat einlesen"
    )


def test_history_md_search_uses_search_session_index():
    """Die Query-Text-Suche muss search_session_index nutzen (Akzeptanzkriterium 3)."""
    content = HISTORY_MD.read_text(encoding="utf-8")
    assert "search_session_index" in content


def test_history_md_handles_missing_session_folders():
    """Gelöschte Sitzungsordner müssen über annotate_missing_sessions abgefangen werden (Akzeptanzkriterium 4)."""
    content = HISTORY_MD.read_text(encoding="utf-8")
    assert "annotate_missing_sessions" in content
    assert "missing" in content


def test_history_md_restore_session_workflow_documented():
    """Ein --restore-session-Workflow muss restore_session nutzen (Akzeptanzkriterium 2)."""
    content = HISTORY_MD.read_text(encoding="utf-8")
    assert "restore_session" in content
    assert "--restore-session" in content
