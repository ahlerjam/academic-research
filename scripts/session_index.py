#!/usr/bin/env python3
"""Session index for /academic-research:history (#466).

Reads/writes ``~/.academic-research/session_index.json`` — the index that
`/history` lists, searches and restores from. Before this module existed,
nothing ever wrote to that file, so `/history` always found it empty
regardless of how many searches had run.

Deliberately NOT stored inside ``~/.academic-research/sessions/`` (PR #486
review, #466): `score.md`/`excel.md` pick the "latest" session via
``ls -t ~/.academic-research/sessions/ | head -1``, which sorts by mtime
without distinguishing files from directories. `search.md` step 9 writes
this index last in every search run — after the session directory itself —
so a sibling ``index.json`` inside ``sessions/`` would permanently outrank
every session directory in that listing, breaking the default
`/search` -> `/score`/`/excel` flow (``.../index.json/deduped.json`` does
not exist).

Usage:
  from session_index import (
      DEFAULT_INDEX_PATH,
      build_session_entry,
      update_session_index,
      load_session_index,
      search_session_index,
      annotate_missing_sessions,
      restore_session,
  )

  entry = build_session_entry(session_dir, query="DevOps", mode="standard", n_hits=47)
  update_session_index(DEFAULT_INDEX_PATH, entry)

  entries = annotate_missing_sessions(load_session_index(DEFAULT_INDEX_PATH))
  hits = search_session_index(entries, "devops")
  restore_session(hits[0]["session_path"])
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_INDEX_PATH = Path.home() / ".academic-research" / "session_index.json"


def load_session_index(index_path: str | Path = DEFAULT_INDEX_PATH) -> list[dict[str, Any]]:
    """Load session index entries.

    Tolerant of a missing or corrupt ``index.json`` — both return an empty
    list instead of raising, so `/history` never crashes on a fresh install
    or a partially-written file.
    """
    path = Path(index_path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return data


def save_session_index(
    entries: list[dict[str, Any]], index_path: str | Path = DEFAULT_INDEX_PATH
) -> None:
    """Write session index entries atomically (tmp file + rename).

    Parallel `/search` runs could otherwise race on a plain read-modify-write;
    a full lock isn't required for this issue's scope, but the write itself
    should not leave a half-written ``index.json`` behind.
    """
    path = Path(index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def count_fulltexts(session_dir: str | Path) -> int:
    """Count fetched full-text PDFs under ``<session_dir>/pdfs/``."""
    pdf_dir = Path(session_dir) / "pdfs"
    if not pdf_dir.is_dir():
        return 0
    return sum(1 for p in pdf_dir.glob("*.pdf") if p.is_file())


def build_session_entry(
    session_dir: str | Path,
    query: str,
    mode: str,
    n_hits: int,
    n_fulltexts: int | None = None,
) -> dict[str, Any]:
    """Build a session index entry describing one completed search run.

    ``n_fulltexts`` defaults to :func:`count_fulltexts` on ``session_dir``
    when not given explicitly.
    """
    session_dir = str(session_dir)
    if n_fulltexts is None:
        n_fulltexts = count_fulltexts(session_dir)
    return {
        "session_path": session_dir,
        "query": query,
        "mode": mode,
        "n_hits": n_hits,
        "n_fulltexts": n_fulltexts,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def update_session_index(
    index_path: str | Path,
    entry: dict[str, Any],
) -> list[dict[str, Any]]:
    """Upsert ``entry`` into the session index by ``session_path``.

    Re-running a search against the same session directory replaces its
    existing entry instead of appending a duplicate. Returns the full,
    updated list of entries after an atomic write.
    """
    entries = load_session_index(index_path)
    session_path = entry.get("session_path")
    for i, existing in enumerate(entries):
        if existing.get("session_path") == session_path:
            entries[i] = entry
            break
    else:
        entries.append(entry)
    save_session_index(entries, index_path)
    return entries


def search_session_index(
    entries: list[dict[str, Any]], query_substring: str
) -> list[dict[str, Any]]:
    """Filter entries whose ``query`` contains ``query_substring`` (case-insensitive)."""
    needle = query_substring.lower()
    return [entry for entry in entries if needle in str(entry.get("query", "")).lower()]


def annotate_missing_sessions(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag entries whose ``session_path`` no longer exists on disk.

    Never raises — a session folder deleted or moved after the fact should
    surface as a plain-language status in `/history`, not a stack trace.
    Returns new dicts with ``missing`` (bool) set, plus a human-readable
    ``status`` message for the missing ones.
    """
    annotated = []
    for entry in entries:
        annotated_entry = dict(entry)
        session_path = entry.get("session_path")
        exists = bool(session_path) and Path(str(session_path)).is_dir()
        annotated_entry["missing"] = not exists
        if not exists:
            annotated_entry["status"] = f"Sitzungsordner nicht mehr vorhanden: {session_path}"
        annotated.append(annotated_entry)
    return annotated


def restore_session(session_path: str | Path) -> dict[str, Any]:
    """Restore a past session as the current working state.

    Follows the existing ``ls -t`` convention that `score.md`/`excel.md`
    already use to pick the "latest" session by directory mtime: restoring
    simply bumps the session directory's mtime to now, so it sorts first
    again — the session storage layout itself is not rebuilt (explicitly
    out of scope for #466).

    Never raises on a missing folder — returns a status dict (``ok``,
    ``session_path``, ``message``) instead, so callers can surface a plain
    message rather than a traceback.
    """
    path = Path(session_path)
    if not path.is_dir():
        return {
            "ok": False,
            "session_path": str(session_path),
            "message": f"Sitzungsordner nicht gefunden: {session_path}",
        }
    now = datetime.now(UTC).timestamp()
    os.utime(path, (now, now))
    return {
        "ok": True,
        "session_path": str(session_path),
        "message": f"Sitzung wiederhergestellt als Arbeitsstand: {session_path}",
    }
