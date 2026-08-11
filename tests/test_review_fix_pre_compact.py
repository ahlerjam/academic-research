"""Regressionstest fuer Finding 9 (Code-Review, kritisch, Datenverlust).

hooks/pre-compact.mjs definierte exportVaultSnapshot() (Vault-DB-Export via
academic_vault.server.export_snapshot()), rief die Funktion aber nirgends aus
main() auf. main() erstellte ausschliesslich einen Tarball aus den drei
Markdown-State-Dateien (STATE_FILES) — die Vault-DB (Papers, Zitate,
Chunk-Embeddings, Entscheidungen) landete NIE im PreCompact-Snapshot, obwohl
das Modul-Docstring (Zeilen 5-8) genau das verspricht.

Dieser Test prueft direkt das beobachtbare Symptom: nach einem Lauf des
PreCompact-Hooks gegen ein Projekt mit vault.db muss der erzeugte Tarball ein
vault.db-Member enthalten (analog zu
tests/test_hook_session_snapshot.py::test_session_snapshot_creates_tarball_when_vault_changed,
das denselben Vertrag fuer den Stop-Hook bereits absichert).

Zweite Testrunde (Regressionen aus dem Review von Runde 1, #834-Nachfolger):

  Regression A — die vollen Vault-Tarballs, die Finding 9 jetzt zuverlaessig
  erzeugt, wurden von NIEMANDEM geprunt (session-snapshot.mjs prunt nur seine
  eigenen `*.session.tgz`, siehe dort isOwnSnapshotFilename()). Der Fix
  spiegelt dieselbe Konvention (eigenes Suffix `.precompact.tgz` + eigenes
  Pruning) innerhalb von pre-compact.mjs.

  Regression B — createTarball() schrieb auf einen fest aus dem
  Minuten-Zeitstempel gebildeten Pfad; ein zweiter Lauf in derselben Minute
  (z. B. Vault-Export scheitert nach einem vorherigen Erfolg) kuerzte per
  `tar czf` den vorhandenen, potenziell vault-haltigen Tarball auf einen
  reinen Markdown-Snapshot. Der Fix uebernimmt dasselbe Kollisionsschema wie
  academic_vault/server.py::export_snapshot() (`<ts>.tgz`, `<ts>-1.tgz`, ...).
"""

import json
import os
import subprocess
import tarfile
from pathlib import Path

HOOK_PATH = Path(__file__).parent.parent / "hooks" / "pre-compact.mjs"


def run_hook(payload: dict, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    """Startet den PreCompact-Hook als Subprocess mit JSON-Eingabe auf stdin."""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    return subprocess.run(
        ["node", str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _make_vault_db(path: Path, content: bytes = b"vault-content-v1") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_precompact_tarball_contains_vault_db(tmp_path):
    """Finding 9: Der PreCompact-Snapshot muss die Vault-DB enthalten.

    Vorher (main() ruft exportVaultSnapshot() nie auf): der einzige Tarball
    enthielt nur academic_context.md/literature_state.md/writing_state.md,
    kein vault.db-Member -> dieser Test schlug fehl.
    """
    slug = "test-project"
    snapshots_dir = tmp_path / "snapshots"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "academic_context.md").write_text("# Kontext\nTestinhalt")

    vault_db = tmp_path / "vault.db"
    _make_vault_db(vault_db)

    env_overrides = {
        "ACADEMIC_SNAPSHOTS_DIR": str(snapshots_dir),
        "ACADEMIC_PROJECT_SLUG": slug,
        "CLAUDE_PROJECT_DIR": str(project_dir),
        "VAULT_DB_PATH": str(vault_db),
    }

    result = run_hook(
        {"hook_event_name": "PreCompact", "trigger_reason": "auto"}, env_overrides=env_overrides
    )
    assert result.returncode == 0, f"Erwartet 0, got {result.returncode}. stderr: {result.stderr}"

    slug_dir = snapshots_dir / slug
    tarballs = list(slug_dir.glob("*.tgz"))
    assert len(tarballs) >= 1, f"Kein Tarball in {slug_dir} erzeugt. stderr: {result.stderr}"

    found_vault_member = False
    for tarball in tarballs:
        with tarfile.open(tarball, "r:gz") as tar:
            names = tar.getnames()
        if any("vault.db" in n for n in names):
            found_vault_member = True
            break

    assert found_vault_member, (
        f"Keine der erzeugten .tgz-Dateien enthaelt ein vault.db-Member: "
        f"{[tuple(tarfile.open(t, 'r:gz').getnames()) for t in tarballs]}. stderr: {result.stderr}"
    )


def test_precompact_falls_back_to_markdown_when_vault_export_fails(tmp_path):
    """Degradations-Anforderung aus Finding 9: schlaegt der Vault-Export fehl
    (hier: VAULT_DB_PATH zeigt ins Leere), bleibt der Markdown-Snapshot
    trotzdem erhalten -- der Hook darf nicht ganz leer ausgehen.
    """
    slug = "test-project"
    snapshots_dir = tmp_path / "snapshots"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "academic_context.md").write_text("# Kontext\nTestinhalt")
    (project_dir / "literature_state.md").write_text("# Literatur\nTestpaper")
    (project_dir / "writing_state.md").write_text("# Schreibstatus\nKapitel 1")

    env_overrides = {
        "ACADEMIC_SNAPSHOTS_DIR": str(snapshots_dir),
        "ACADEMIC_PROJECT_SLUG": slug,
        "CLAUDE_PROJECT_DIR": str(project_dir),
        "VAULT_DB_PATH": str(tmp_path / "nonexistent.db"),
    }

    result = run_hook({"hook_event_name": "PreCompact"}, env_overrides=env_overrides)
    assert result.returncode == 0, (
        f"Erwartet 0 (fail-open), got {result.returncode}. stderr: {result.stderr}"
    )

    slug_dir = snapshots_dir / slug
    tarballs = list(slug_dir.glob("*.tgz"))
    assert len(tarballs) >= 1, f"Kein Markdown-Fallback-Tarball in {slug_dir}"

    with tarfile.open(tarballs[0], "r:gz") as tar:
        names = tar.getnames()
    assert any("academic_context.md" in n for n in names), (
        f"Markdown-Fallback fehlt academic_context.md: {names}"
    )


def test_precompact_zweiter_lauf_ueberschreibt_ersten_vault_snapshot_nicht(tmp_path):
    """Regression B (Review Runde 2): ein zweiter PreCompact-Lauf in derselben
    Minute darf den vorhandenen, vault-haltigen Tarball des ersten Laufs nicht
    per `tar czf` auf einen reinen Markdown-Snapshot kuerzen.

    Szenario: Lauf 1 hat eine gueltige Vault-DB -> Tarball enthaelt vault.db.
    Lauf 2 (unmittelbar danach, praktisch garantiert dieselbe Minute) hat
    eine kaputte VAULT_DB_PATH -> faellt auf den Markdown-Fallback zurueck.
    Vorher: createTarball() schrieb auf denselben, aus der Minute
    berechneten Pfad wie Lauf 1 und ueberschrieb dessen vault.db-Inhalt.
    Nachher: beide Tarballs muessen nebeneinander existieren, und der aus
    Lauf 1 muss weiterhin sein vault.db-Member haben.
    """
    slug = "test-project"
    snapshots_dir = tmp_path / "snapshots"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "academic_context.md").write_text("# Kontext\nTestinhalt")

    vault_db = tmp_path / "vault.db"
    _make_vault_db(vault_db)

    base_env = {
        "HOME": str(tmp_path / "home"),
        "ACADEMIC_SNAPSHOTS_DIR": str(snapshots_dir),
        "ACADEMIC_PROJECT_SLUG": slug,
        "CLAUDE_PROJECT_DIR": str(project_dir),
    }
    slug_dir = snapshots_dir / slug

    # Lauf 1: gueltige Vault-DB -> Tarball MIT vault.db.
    result1 = run_hook(
        {"hook_event_name": "PreCompact", "trigger_reason": "auto"},
        env_overrides={**base_env, "VAULT_DB_PATH": str(vault_db)},
    )
    assert result1.returncode == 0, (
        f"Lauf 1: erwartet 0, got {result1.returncode}. stderr: {result1.stderr}"
    )
    tarballs_after_1 = set((slug_dir).glob("*.tgz"))
    assert len(tarballs_after_1) == 1, (
        f"Lauf 1 haette genau einen Tarball erzeugen sollen: {tarballs_after_1}"
    )
    erster = next(iter(tarballs_after_1))
    with tarfile.open(erster, "r:gz") as tar:
        assert any("vault.db" in n for n in tar.getnames()), (
            f"Tarball aus Lauf 1 enthaelt kein vault.db-Member direkt nach der Erstellung: {erster}"
        )

    # Lauf 2: kaputte VAULT_DB_PATH -> Markdown-Fallback, faellt in dieselbe
    # Minute wie Lauf 1 (beide Aufrufe folgen unmittelbar aufeinander).
    result2 = run_hook(
        {"hook_event_name": "PreCompact", "trigger_reason": "auto"},
        env_overrides={**base_env, "VAULT_DB_PATH": str(tmp_path / "nonexistent.db")},
    )
    assert result2.returncode == 0, (
        f"Lauf 2: erwartet 0, got {result2.returncode}. stderr: {result2.stderr}"
    )

    tarballs_after_2 = set(slug_dir.glob("*.tgz"))
    assert len(tarballs_after_2) == 2, (
        f"Nach zwei Laeufen werden zwei getrennte Tarballs erwartet, nicht einer ueberschrieben: "
        f"{tarballs_after_2}. stderr Lauf 2: {result2.stderr}"
    )
    assert erster in tarballs_after_2, (
        f"Der Tarball aus Lauf 1 ({erster}) wurde ersetzt/umbenannt: {tarballs_after_2}"
    )
    assert erster.exists(), f"Tarball aus Lauf 1 existiert nach Lauf 2 nicht mehr: {erster}"

    # Kernpruefung: der ERSTE Tarball muss weiterhin sein vault.db-Member
    # haben -- vorher wurde er von Lauf 2 auf den Markdown-Inhalt gekuerzt.
    with tarfile.open(erster, "r:gz") as tar:
        names_nach_lauf2 = tar.getnames()
    assert any("vault.db" in n for n in names_nach_lauf2), (
        f"Tarball aus Lauf 1 hat sein vault.db-Member nach Lauf 2 verloren "
        f"(Regression B, Datenverlust): {names_nach_lauf2}"
    )


def test_precompact_prunt_eigene_snapshots_auf_academic_snapshots_keep(tmp_path):
    """Regression A (Review Runde 2): PreCompact-Tarballs (inkl. voller
    vault.db-Kopie bei jeder Auto-Compaction) wurden von KEINEM Pruning
    erfasst -- session-snapshot.mjs prunt nachweislich nur seine eigenen
    `*.session.tgz` (isOwnSnapshotFilename() dort). Ohne eigenes Pruning
    waechst das Slug-Verzeichnis unbegrenzt.

    Dieser Test erzwingt mit ACADEMIC_SNAPSHOTS_KEEP=2 vier PreCompact-Laeufe
    und erwartet, dass danach maximal 2 eigene Tarballs im Slug-Verzeichnis
    liegen -- nicht 4.
    """
    slug = "test-project"
    snapshots_dir = tmp_path / "snapshots"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "academic_context.md").write_text("# Kontext\nTestinhalt")

    vault_db = tmp_path / "vault.db"
    _make_vault_db(vault_db)

    env_overrides = {
        "HOME": str(tmp_path / "home"),
        "ACADEMIC_SNAPSHOTS_DIR": str(snapshots_dir),
        "ACADEMIC_PROJECT_SLUG": slug,
        "CLAUDE_PROJECT_DIR": str(project_dir),
        "VAULT_DB_PATH": str(vault_db),
        "ACADEMIC_SNAPSHOTS_KEEP": "2",
    }

    for lauf in range(4):
        result = run_hook(
            {"hook_event_name": "PreCompact", "trigger_reason": "auto"},
            env_overrides=env_overrides,
        )
        assert result.returncode == 0, (
            f"Lauf {lauf}: erwartet 0, got {result.returncode}. stderr: {result.stderr}"
        )

    slug_dir = snapshots_dir / slug
    tarballs = list(slug_dir.glob("*.tgz"))
    assert len(tarballs) <= 2, (
        f"ACADEMIC_SNAPSHOTS_KEEP=2 wurde nicht durchgesetzt -- "
        f"{len(tarballs)} Tarballs statt maximal 2 im Slug-Verzeichnis: {tarballs}"
    )


# ---------------------------------------------------------------------------
# Runde 3 — Rundlauf und Restpunkte
# ---------------------------------------------------------------------------


def _echte_vault_db(path: Path) -> None:
    """Legt eine echte, lesbare SQLite-Vault-DB mit einem Paper an."""
    from academic_vault.server import add_paper

    path.parent.mkdir(parents=True, exist_ok=True)
    add_paper(
        str(path),
        paper_id="p-rundlauf",
        csl_json=json.dumps(
            {
                "id": "p-rundlauf",
                "type": "article-journal",
                "title": "Rundlauf-Testpaper",
                "author": [{"family": "Muster", "given": "Erika"}],
                "issued": {"date-parts": [[2026]]},
            }
        ),
    )


def test_precompact_snapshot_ist_ueber_den_restore_pfad_wiederherstellbar(tmp_path):
    """Regression D (Runde 3): echter Rundlauf Hook -> Restore -> Inhalt.

    Die Kennzeichnung ``.precompact.tgz`` aus Runde 2 machte PreCompact-
    Snapshots ueber ``restore_snapshot_report()`` unauffindbar, weil dort der
    Pfad hart als ``<ts>.tgz`` gebaut wurde. Genau die Snapshots, die als
    einzige die vault.db mitfuehren, meldete der einzige dokumentierte
    Wiederherstellungsweg (``/academic-research:history --restore <ts>``) als
    "Snapshot nicht gefunden".
    """
    from academic_vault.server import get_paper, restore_snapshot_report

    slug = "rundlauf-projekt"
    snapshots_dir = tmp_path / "snapshots"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "academic_context.md").write_text("# Kontext\nStand vor der Compaction")

    vault_db = tmp_path / "vault" / "vault.db"
    _echte_vault_db(vault_db)

    result = run_hook(
        {"hook_event_name": "PreCompact", "trigger_reason": "auto"},
        env_overrides={
            "HOME": str(tmp_path / "home"),
            "ACADEMIC_SNAPSHOTS_DIR": str(snapshots_dir),
            "ACADEMIC_PROJECT_SLUG": slug,
            "CLAUDE_PROJECT_DIR": str(project_dir),
            "VAULT_DB_PATH": str(vault_db),
        },
    )
    assert result.returncode == 0, f"Hook-Exit {result.returncode}. stderr: {result.stderr}"

    tarballs = list((snapshots_dir / slug).glob("*.tgz"))
    assert len(tarballs) == 1, f"Genau ein Snapshot erwartet: {tarballs}. stderr: {result.stderr}"
    snapshot = tarballs[0]
    assert snapshot.name.endswith(".precompact.tgz"), (
        f"Herkunftskennzeichnung fehlt (Retention aus Runde 2): {snapshot.name}"
    )

    # ts wie ihn der Nutzer aus der Auflistung abliest: der Teil vor der
    # Herkunftskennzeichnung.
    ts = snapshot.name[: -len(".precompact.tgz")]

    # Live-Stand veraendern, damit der Restore nachweisbar etwas bewirkt.
    (project_dir / "academic_context.md").write_text("# Kontext\nSTAND NACH DER COMPACTION")
    live_db = tmp_path / "live" / "vault.db"
    _echte_vault_db(live_db)
    assert get_paper(str(live_db), "p-rundlauf") is not None

    report = restore_snapshot_report(
        slug=slug,
        ts=ts,
        snapshots_dir=str(snapshots_dir),
        target_dir=str(project_dir),
        db_path=str(live_db),
    )

    assert report["ok"] is True, f"Restore des PreCompact-Snapshots scheiterte: {report}"
    assert report["tarball"] == str(snapshot)
    assert "academic_context.md" in report["restored_files"]
    assert (
        project_dir / "academic_context.md"
    ).read_text() == "# Kontext\nStand vor der Compaction"
    assert report["vault_db_restored"] == str(live_db)
    assert get_paper(str(live_db), "p-rundlauf") is not None, (
        "Die zurueckgespielte vault.db ist nicht lesbar."
    )


def test_precompact_hinterlaesst_bei_gescheiterter_kennzeichnung_nichts_unprunebares(tmp_path):
    """Restpunkt Runde 3: scheitert ``renameSync``, blieb eine Datei OHNE
    Herkunftskennzeichnung liegen — von keinem Pruning-Filter je erfasst — und
    ``pruneOldSnapshots()`` lief fuer diesen Lauf gar nicht erst.

    Aufbau: ein untergeschobener Interpreter (ACADEMIC_PYTHON) meldet einen
    Tarball in einem schreibgeschuetzten Verzeichnis zurueck. Das Umbenennen
    von dort scheitert (EACCES), das Kopieren in das Slug-Verzeichnis nicht.
    """
    slug = "kennzeichnung"
    snapshots_dir = tmp_path / "snapshots"
    slug_dir = snapshots_dir / slug
    slug_dir.mkdir(parents=True)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "academic_context.md").write_text("# Kontext")

    vault_db = tmp_path / "vault.db"
    _make_vault_db(vault_db)

    # Zwei alte, gekennzeichnete Snapshots, die das Pruning wegraeumen muss.
    alt_a = slug_dir / "19700101-0000.precompact.tgz"
    alt_b = slug_dir / "19700101-0001.precompact.tgz"
    alt_a.write_bytes(b"alt-a")
    alt_b.write_bytes(b"alt-b")

    # Schreibgeschuetzte Quelle: das Umbenennen von dort scheitert.
    ro_dir = tmp_path / "ro"
    ro_dir.mkdir()
    export_tar = ro_dir / "99991231-2359.tgz"
    export_tar.write_bytes(b"vault-tarball-inhalt")

    fake_python = tmp_path / "fake-python.sh"
    fake_python.write_text(f'#!/bin/sh\nprintf "%s\\n" "{export_tar}"\n')
    fake_python.chmod(0o755)

    ro_dir.chmod(0o500)
    try:
        result = run_hook(
            {"hook_event_name": "PreCompact", "trigger_reason": "auto"},
            env_overrides={
                "HOME": str(tmp_path / "home"),
                "ACADEMIC_SNAPSHOTS_DIR": str(snapshots_dir),
                "ACADEMIC_PROJECT_SLUG": slug,
                "CLAUDE_PROJECT_DIR": str(project_dir),
                "VAULT_DB_PATH": str(vault_db),
                "ACADEMIC_SNAPSHOTS_KEEP": "1",
                "ACADEMIC_PYTHON": str(fake_python),
            },
        )
    finally:
        ro_dir.chmod(0o700)

    assert result.returncode == 0, f"Hook-Exit {result.returncode}. stderr: {result.stderr}"

    im_slug = sorted(p.name for p in slug_dir.glob("*.tgz"))
    assert all(name.endswith(".precompact.tgz") for name in im_slug), (
        f"Unkennzeichnete (und damit nie prunebare) Datei im Slug-Verzeichnis: {im_slug}. "
        f"stderr: {result.stderr}"
    )
    # Der Zielname stammt aus dem Zeitstempel des HOOK-Laufs, nicht aus dem
    # Namen des von export_snapshot() gelieferten Roh-Tarballs — genauso wie im
    # Erfolgspfad (beide gehen durch uniqueOwnTarPath(slugDir, ts)). Das ist
    # zwingend so: der Restore loest ueber diesen ts auf, ein aus der Quelle
    # uebernommener Name waere ueber /history --restore nicht auffindbar.
    assert len(im_slug) == 1, (
        f"pruneOldSnapshots() lief nicht oder der Snapshot fehlt: {im_slug}. "
        f"stderr: {result.stderr}"
    )
    assert (slug_dir / im_slug[0]).read_bytes() == b"vault-tarball-inhalt", (
        "Der Snapshot-Inhalt ging beim Ausweichen auf das Kopieren verloren."
    )
