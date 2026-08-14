"""Regressionstests fuer Issue #841 — ``academic_vault/db.py`` in Repository-Module.

Die frueher monolithische Klasse ``VaultDB`` (3.279 Zeilen) ist in
Aggregat-Mixins unter ``academic_vault/repositories/`` aufgeteilt; ``db.py``
bleibt schlanke Fassade fuer Connection-/Transaktions-Handling.

Die Tests decken die vier Akzeptanzkriterien maschinell ab:

* AC1 — kein Modul der frueheren ``db.py``-Funktionalitaet > 1.200 Zeilen.
* AC2 — Transaktions-Disziplin bleibt in der Fassade zentralisiert.
* AC3 — die oeffentliche API bleibt kompatibel (bestehende Suite unveraendert).
* AC4 — neue Module sind vollstaendig typannotiert (mypy-Override erzwingt es).
"""

import re
import sqlite3
import sys
import tomllib
import uuid
from pathlib import Path

import pytest
from academic_vault.db import VaultDB, VaultLockedError

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_DIR = _REPO_ROOT / "academic_vault"
_REPOSITORIES_DIR = _PACKAGE_DIR / "repositories"

# Zeilenbudget aus dem Issue-Akzeptanzkriterium.
_MAX_MODULE_LINES = 1200
# Die Fassade traegt nur noch Connection-Kern, Schema-Init und Komposition.
_MAX_FACADE_LINES = 900

# Aggregat-Module, in die die frueheren ``VaultDB``-CRUD-Methoden gewandert
# sind. Die Liste steht hier, damit ein spaeteres stilles Zurueckdrehen der
# Aufteilung auffaellt (und nicht nur die Zeilenzahl geprueft wird).
_EXPECTED_AGGREGATE_MODULES = frozenset(
    {
        "appraisal",
        "chunks",
        "decisions",
        "empirics",
        "figures",
        "fulltext",
        "notes",
        "papers",
        "quotes",
        "tables",
        "vectors",
    }
)


def _repository_sources() -> list[Path]:
    return sorted(p for p in _REPOSITORIES_DIR.glob("*.py") if p.name != "__init__.py")


# ---------------------------------------------------------------------------
# AC1 — Modulgroessen
# ---------------------------------------------------------------------------


def test_expected_aggregate_modules_exist() -> None:
    """Jedes Aggregat hat ein eigenes Modul unter ``academic_vault/repositories``."""
    assert _REPOSITORIES_DIR.is_dir(), (
        "academic_vault/repositories/ fehlt — die Aufteilung aus #841 wurde zurueckgedreht."
    )
    present = {p.stem for p in _repository_sources()}
    assert _EXPECTED_AGGREGATE_MODULES <= present, (
        f"Fehlende Aggregat-Module: {sorted(_EXPECTED_AGGREGATE_MODULES - present)}"
    )


def test_split_modules_stay_within_line_budget() -> None:
    """AC1: kein Modul der frueheren db.py-Funktionalitaet ueberschreitet 1.200 Zeilen.

    Geprueft werden ``db.py`` selbst und alle Repository-Module.
    ``server.py``/``migrate.py`` sind laut Issue-Scope ausdruecklich
    ausgenommen (eigenes Issue bzw. "Out").
    """
    oversized: list[str] = []
    for source in [_PACKAGE_DIR / "db.py", *_repository_sources()]:
        lines = len(source.read_text(encoding="utf-8").splitlines())
        if lines > _MAX_MODULE_LINES:
            oversized.append(f"{source.relative_to(_REPO_ROOT)}: {lines} Zeilen")
    assert oversized == [], f"Module ueber dem Budget von {_MAX_MODULE_LINES} Zeilen: {oversized}"


def test_facade_stays_lean() -> None:
    """db.py traegt nur noch Connection-Kern, Schema-Init und Komposition."""
    lines = len((_PACKAGE_DIR / "db.py").read_text(encoding="utf-8").splitlines())
    assert lines <= _MAX_FACADE_LINES, (
        f"academic_vault/db.py hat {lines} Zeilen — die Fassade soll <= "
        f"{_MAX_FACADE_LINES} bleiben."
    )


# ---------------------------------------------------------------------------
# AC2 — zentralisierte Transaktions-Disziplin
# ---------------------------------------------------------------------------


def test_no_repository_opens_own_connection() -> None:
    """Kein Repository-Modul oeffnet eine eigene ad-hoc-Connection."""
    offenders: list[str] = []
    for source in _repository_sources():
        text = source.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "sqlite3.connect(" in line or "._open(" in line:
                offenders.append(f"{source.name}:{lineno}: {line.strip()}")
    assert offenders == [], (
        "Repository-Module duerfen keine eigenen Connections oeffnen — "
        f"Schreibpfade laufen ueber die Fassade: {offenders}"
    )


class _ConnTracker:
    """Zaehlt geoeffnete vs. geschlossene sqlite3-Connections (Muster aus #237)."""

    def __init__(self) -> None:
        self.opened: list[sqlite3.Connection] = []
        self.closed: list[sqlite3.Connection] = []
        self._orig_connect = sqlite3.connect

    def connect(self, *args: object, **kwargs: object):
        tracker = self

        class _TrackedConnection(sqlite3.Connection):
            def close(self_inner) -> None:  # noqa: N805
                tracker.closed.append(self_inner)
                super().close()

        kwargs.setdefault("factory", _TrackedConnection)
        conn = self._orig_connect(*args, **kwargs)  # type: ignore[arg-type]
        self.opened.append(conn)
        return conn

    @property
    def open_count(self) -> int:
        return len(self.opened) - len(self.closed)


# Eine Tabelle im Format von :func:`academic_vault.tables.extract_tables`.
_TABLE = {
    "page": 1,
    "table_index": 0,
    "n_rows": 1,
    "n_cols": 2,
    "bbox": [0, 0, 10, 10],
    "rows": [["a", "b"]],
    "cells": [],
}


def _seed_paper(db: VaultDB) -> str:
    paper_id = "p_" + uuid.uuid4().hex[:8]
    db.add_paper(paper_id=paper_id, csl_json='{"type": "article-journal"}')
    return paper_id


def _write_once_per_aggregate(db: VaultDB, paper_id: str) -> None:
    """Genau ein Schreibaufruf je Aggregat-Modul."""
    db.add_quote(
        quote_id="q_" + uuid.uuid4().hex[:8],
        paper_id=paper_id,
        verbatim="Ein hinreichend langer Wortlaut fuer den Schreibpfad.",
        extraction_method="manual",
    )
    db.add_note(paper_id=paper_id, text="Notiz")
    db.set_fulltext(paper_id, "Volltext des Papers.")
    db.set_paper_tables(paper_id, [_TABLE], backend="pdfplumber")
    db.add_figure(
        paper_id=paper_id,
        page=1,
        caption="Abbildung 1: Beispiel",
        vlm_description=None,
        data_extracted_json=None,
    )
    db.add_transcript_segment(paper_id=paper_id, seq=1, text="Segment")
    db.add_decision(category="test", text="Entscheidung")
    db.add_excluded_source(paper_id, reason="Test")
    db.add_score_snapshot(paper_id=paper_id, session_id="s1", scores_json="{}")
    db.add_chunk_embedding(
        paper_id=paper_id,
        chunk_text="Chunk-Text",
        context_sentence="Kontext",
        embedding_text="Kontext Chunk-Text",
        embedding_vector=None,
    )


def test_writes_share_the_facade_connection(tmp_path, monkeypatch) -> None:
    """AC2: alle Aggregat-Schreibpfade teilen sich die Connection der Fassade."""
    db_path = str(tmp_path / "vault.db")
    with VaultDB(db_path) as setup_db:
        setup_db.init_schema()
        paper_id = _seed_paper(setup_db)

    tracker = _ConnTracker()
    monkeypatch.setattr("academic_vault.db.sqlite3.connect", tracker.connect)

    with VaultDB(db_path) as db:
        _write_once_per_aggregate(db, paper_id)
        assert len(tracker.opened) == 1, (
            "Innerhalb des Fassaden-Context-Managers darf genau EINE Connection "
            f"geoeffnet werden, es waren {len(tracker.opened)}."
        )

    assert tracker.open_count == 0, (
        f"Nach __exit__ sind noch {tracker.open_count} Connection(s) offen."
    )


def test_every_aggregate_write_path_honours_vault_lock(tmp_path) -> None:
    """AC2: der Lock-Guard der Fassade greift auf jedem verschobenen Schreibpfad."""
    db_path = str(tmp_path / "vault.db")
    with VaultDB(db_path) as setup_db:
        setup_db.init_schema()
        paper_id = _seed_paper(setup_db)
        setup_db.lock_vault("testprojekt")

    with VaultDB(db_path) as db:
        writes = {
            "papers": lambda: db.set_ocr_done(paper_id),
            "quotes": lambda: db.add_quote(
                quote_id="q_locked",
                paper_id=paper_id,
                verbatim="Wortlaut, der nicht geschrieben werden darf.",
                extraction_method="manual",
            ),
            "notes": lambda: db.add_note(paper_id=paper_id, text="Notiz"),
            "fulltext": lambda: db.set_fulltext(paper_id, "Volltext"),
            "tables": lambda: db.set_paper_tables(paper_id, [_TABLE], backend="pdfplumber"),
            "figures": lambda: db.add_figure(
                paper_id=paper_id,
                page=1,
                caption="Abbildung 1: X",
                vlm_description=None,
                data_extracted_json=None,
            ),
            "empirics": lambda: db.add_transcript_segment(paper_id=paper_id, seq=1, text="Seg"),
            "decisions": lambda: db.add_decision(category="test", text="Entscheidung"),
            "appraisal": lambda: db.add_excluded_source(paper_id, reason="Test"),
            "chunks": lambda: db.add_chunk_embedding(
                paper_id=paper_id,
                chunk_text="Chunk",
                context_sentence="Kontext",
                embedding_text="Kontext Chunk",
                embedding_vector=None,
            ),
            "vectors": lambda: db.replace_chunk_vectors([], model_id=None, dim=384),
        }
        for aggregate, write in writes.items():
            with pytest.raises(VaultLockedError):
                write()
                pytest.fail(f"Schreibpfad des Aggregats '{aggregate}' ignoriert den Vault-Lock")


# ---------------------------------------------------------------------------
# AC3 — oeffentliche API bleibt kompatibel
# ---------------------------------------------------------------------------

# Namen, die vor #841 aus ``academic_vault.db`` importierbar waren und es
# bleiben muessen (server.py, hooks-Bridge, evals, ~40 Testdateien).
_PUBLIC_DB_NAMES = (
    "CURRENT_SCHEMA_VERSION",
    "SCIHUB_PROVENANCE_SIDECAR_SUFFIX",
    "VALID_AUDIT_SEVERITIES",
    "VALID_AUDIT_VERDICTS",
    "VALID_CATEGORY_ORIGINS",
    "VALID_CHUNK_CONTEXT_SOURCES",
    "VALID_EXTRACTION_METHODS",
    "VALID_PAPER_TYPES",
    "VALID_SOURCE_KINDS",
    "VALID_STANCES",
    "VaultDB",
    "VaultLockedError",
    "_LEGACY_MIGRATION_COLUMNS",
    "_UNSET",
    "_Unset",
    "_parse_figure_reference",
    "_sanitize_fts5_query",
    "csl_families",
    "csl_title",
    "csl_year",
    "default_db_path",
    "escape_like",
    "family_names_match",
    "format_table_evidence",
    "normalize_family_name",
    "paper_cited_in_chapters",
    "project_slug",
)


@pytest.mark.parametrize("name", _PUBLIC_DB_NAMES)
def test_db_module_still_exports_public_name(name: str) -> None:
    """Kein Aufrufer muss seinen Import anpassen."""
    from academic_vault import db as db_module

    assert hasattr(db_module, name), (
        f"academic_vault.db exportiert '{name}' nicht mehr — die Fassade muss "
        "alle bisher importierbaren Namen re-exportieren."
    )


def test_vault_db_keeps_every_method_on_the_class() -> None:
    """Die Mixin-Komposition haelt jede Methode an ``VaultDB`` selbst.

    Wichtig fuer ``monkeypatch.setattr(db_module.VaultDB, "_papers_snapshot", ...)``
    (tests/test_issue_378_citation_guard.py): bei Delegation an separate
    Repository-Objekte griffe dieser Patch ins Leere.
    """
    for method in (
        "_papers_snapshot",
        "add_paper",
        "add_quote",
        "knn_chunks",
        "add_chunk_embedding",
    ):
        assert callable(getattr(VaultDB, method, None)), (
            f"VaultDB.{method} ist nicht mehr an der Klasse erreichbar."
        )


def test_repository_modules_do_not_import_the_facade() -> None:
    """Kein Repository-Modul importiert ``db.py`` (Zirkularimport-Schutz)."""
    offenders: list[str] = []
    for source in _repository_sources():
        text = source.read_text(encoding="utf-8")
        if re.search(r"^\s*from\s+\.\.db\s+import|^\s*from\s+\.\.\s+import\s+db\b", text, re.M):
            offenders.append(source.name)
    assert offenders == [], f"Repository-Module importieren die Fassade: {offenders}"


# ---------------------------------------------------------------------------
# AC4 — neue Module sind vollstaendig typannotiert
# ---------------------------------------------------------------------------


def test_repositories_enforce_typed_defs() -> None:
    """Ein mypy-Override macht "vollstaendig typannotiert" maschinell pruefbar."""
    config = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    overrides = config["tool"]["mypy"]["overrides"]
    matching = [
        override
        for override in overrides
        if "academic_vault.repositories.*" in override.get("module", [])
    ]
    assert matching, (
        "pyproject.toml braucht einen [[tool.mypy.overrides]]-Block fuer "
        "academic_vault.repositories.* — sonst ist AC4 nicht ueberpruefbar."
    )
    assert any(override.get("disallow_untyped_defs") is True for override in matching), (
        "Der Override fuer academic_vault.repositories.* muss disallow_untyped_defs = true setzen."
    )


def test_repositories_package_is_importable() -> None:
    """Das Unterpaket laesst sich eigenstaendig importieren (kein Zirkularimport)."""
    __import__("academic_vault.repositories.papers")
    assert "academic_vault.repositories.papers" in sys.modules
