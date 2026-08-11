"""Beweis, dass der Schutzwall aus tests/conftest.py haelt.

Anlass ist der Datenverlust vom 11.08.2026: ein Testlauf ueberschrieb den
ECHTEN Vault unter ``~/.academic-research/projects/<slug>/vault.db`` mit
tmp-Testdaten, ein zweiter schrieb echte Tarballs nach
``~/.academic-research/snapshots/``. Beide Male, weil die Tests sich nicht
isoliert hatten.

Diese Datei prueft die drei Schichten des Walls einzeln:

  1. **Umleitung** — ``HOME`` (und damit ``Path.home()`` / ``os.homedir()``)
     zeigt waehrend jedes Tests in ein tmp-Verzeichnis.
  2. **Sperre** — ein Audit-Hook laesst Schreibzugriffe auf den echten
     ``~/.academic-research``-Baum gar nicht erst zu, unabhaengig davon, ueber
     welche Env-Variable der Pfad zustande kam.
  3. **Nachkontrolle** — ein Fingerabdruck des echten Baums vor/nach jedem Test
     schlaegt an, wenn doch etwas durchkam (z.B. aus einem Subprozess, den der
     Audit-Hook prinzipbedingt nicht sieht).

Wichtig fuer die Testfuehrung: KEIN Test hier schreibt tatsaechlich in den
echten Baum -- auch nicht versehentlich, wenn der Wall fehlt. Die Sonden zielen
auf Pfade unterhalb eines nicht existierenden Elternverzeichnisses. Ohne Wall
scheitert der Schreibversuch am fehlenden Verzeichnis (FileNotFoundError bzw.
sqlite3.OperationalError), mit Wall an der Sperre -- geschrieben wird in beiden
Faellen nichts.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tests import conftest as guard

# Elternverzeichnis existiert bewusst NICHT (siehe Modul-Docstring).
PROBE_DIR = "__pytest_guard_probe_darf_nie_entstehen__"


# ---------------------------------------------------------------------------
# Schicht 1: Umleitung
# ---------------------------------------------------------------------------


def test_home_zeigt_waehrend_des_tests_ins_tmp(tmp_path):
    """``HOME``/``Path.home()`` ist umgebogen, der echte HOME ist es nicht."""
    assert Path.home() != guard.REAL_HOME, (
        f"HOME wurde nicht umgeleitet: Path.home() == {Path.home()}"
    )
    # tmp_path und das Sandbox-HOME liegen im selben pytest-tmp-Baum.
    assert guard.PYTEST_TMP_MARKER in str(Path.home()), (
        f"Sandbox-HOME liegt nicht im pytest-tmp-Baum: {Path.home()}"
    )


def test_default_db_path_landet_nicht_im_echten_vault():
    """Der kanonische DB-Default zeigt waehrend der Suite nie auf den Live-Vault."""
    from academic_vault.db import default_db_path

    resolved = Path(default_db_path())
    assert not guard.is_protected_path(resolved), (
        f"default_db_path() zeigt in den geschuetzten Baum: {resolved}"
    )


def test_env_pfade_im_echten_baum_werden_in_die_sandbox_gespiegelt(tmp_path):
    """Eine Env-Variable, die in den echten Baum zeigt, wird umgebogen statt uebernommen."""
    sandbox = tmp_path / "sandbox-home"
    echt = guard.REAL_ACADEMIC_ROOT / "projects" / "academic-research" / "vault.db"

    gespiegelt = guard.mirror_into_sandbox(sandbox, echt)

    assert not guard.is_protected_path(gespiegelt), (
        f"Spiegelung blieb im geschuetzten Baum: {gespiegelt}"
    )
    assert sandbox in Path(gespiegelt).parents, (
        f"Spiegelung liegt nicht in der Sandbox: {gespiegelt}"
    )
    # Die relative Lage bleibt erhalten, damit Tests weiter sinnvolle Pfade sehen.
    assert Path(gespiegelt).name == "vault.db"


# ---------------------------------------------------------------------------
# Schicht 2: Sperre (Audit-Hook)
# ---------------------------------------------------------------------------


def test_echter_academic_baum_ist_als_geschuetzt_registriert():
    """Der echte ``~/.academic-research`` steht auf der Sperrliste."""
    assert guard.REAL_ACADEMIC_ROOT in guard.protected_roots(), (
        f"{guard.REAL_ACADEMIC_ROOT} fehlt in {guard.protected_roots()}"
    )


def test_schreibendes_open_im_echten_baum_wird_blockiert():
    """``open(..., 'w')`` unterhalb des echten Baums fliegt auf die Sperre."""
    ziel = guard.REAL_ACADEMIC_ROOT / PROBE_DIR / "probe.txt"
    with pytest.raises(guard.RealPathWriteBlocked):
        with open(ziel, "w") as fh:  # noqa: F841 -- erreicht den Body nie
            fh.write("darf nie passieren")


def test_os_open_im_echten_baum_wird_blockiert():
    """Auch der Low-Level-Weg ``os.open(..., O_CREAT)`` ist gesperrt."""
    ziel = guard.REAL_ACADEMIC_ROOT / PROBE_DIR / "probe-low-level.txt"
    with pytest.raises(guard.RealPathWriteBlocked):
        os.open(str(ziel), os.O_WRONLY | os.O_CREAT)


def test_sqlite_connect_im_echten_baum_wird_blockiert():
    """``sqlite3.connect`` oeffnet immer schreibend -- also gesperrt.

    Genau dieser Aufruf hat den Vault ueberschrieben (VaultDB.__init__).
    """
    ziel = guard.REAL_ACADEMIC_ROOT / PROBE_DIR / "vault.db"
    with pytest.raises(guard.RealPathWriteBlocked):
        sqlite3.connect(str(ziel))


def test_mkdir_im_echten_baum_wird_blockiert():
    """Verzeichnisse anlegen ist ebenfalls gesperrt (Snapshot-Ordner-Vorfall)."""
    ziel = guard.REAL_ACADEMIC_ROOT / "snapshots" / PROBE_DIR
    with pytest.raises(guard.RealPathWriteBlocked):
        os.mkdir(str(ziel))


def test_lesen_im_echten_baum_bleibt_erlaubt():
    """Der Wall sperrt Schreibzugriffe, nicht Lesezugriffe.

    Beleg: ein lesendes ``open`` auf eine nicht existierende Datei scheitert am
    fehlenden Pfad (FileNotFoundError) -- und NICHT an der Sperre.
    """
    ziel = guard.REAL_ACADEMIC_ROOT / PROBE_DIR / "gibt-es-nicht.txt"
    with pytest.raises(FileNotFoundError):
        open(ziel)


def test_sperre_greift_fuer_jede_registrierte_wurzel(tmp_path):
    """Der Mechanismus haengt nicht am konkreten Pfad -- Beweis an einer tmp-Wurzel.

    Hier darf wirklich geschrieben werden (tmp), deshalb laesst sich hier auch
    das vollstaendige Verhalten zeigen: erst erlaubt, nach Registrierung
    gesperrt, danach wieder erlaubt.
    """
    wurzel = tmp_path / "geschuetzt"
    wurzel.mkdir()
    datei = wurzel / "datei.txt"
    datei.write_text("vorher")

    with guard.protected_root(wurzel):
        with pytest.raises(guard.RealPathWriteBlocked):
            datei.write_text("nachher")
        with pytest.raises(guard.RealPathWriteBlocked):
            os.remove(str(datei))
        with pytest.raises(guard.RealPathWriteBlocked):
            os.rename(str(datei), str(wurzel / "neu.txt"))
        with pytest.raises(guard.RealPathWriteBlocked):
            shutil.rmtree(str(wurzel))
        # Lesen bleibt auch hier erlaubt.
        assert datei.read_text() == "vorher"

    # Nach dem Block ist der Pfad wieder frei.
    datei.write_text("nachher")
    assert datei.read_text() == "nachher"


def test_symlink_auf_den_geschuetzten_baum_ist_erlaubt_hinein_nicht(tmp_path):
    """Ein Symlink LIEST sein Ziel -- geschrieben wird nur der Linkpfad.

    Sonst koennte das Sandbox-HOME das Setup-venv nicht durchreichen. Umgekehrt
    darf innerhalb des geschuetzten Baums kein Link entstehen.
    """
    link = tmp_path / "zeigt-in-den-echten-baum"
    link.symlink_to(guard.REAL_ACADEMIC_ROOT)
    assert link.is_symlink()

    with pytest.raises(guard.RealPathWriteBlocked):
        os.symlink(str(tmp_path), str(guard.REAL_ACADEMIC_ROOT / PROBE_DIR))


def test_sperre_laesst_sich_nur_ausdruecklich_aussetzen(tmp_path):
    """``allow_writes_to_protected_roots()`` ist die einzige Hintertuer."""
    wurzel = tmp_path / "geschuetzt2"
    wurzel.mkdir()
    datei = wurzel / "datei.txt"

    with guard.protected_root(wurzel):
        with pytest.raises(guard.RealPathWriteBlocked):
            datei.write_text("nein")
        with guard.allow_writes_to_protected_roots():
            datei.write_text("ja")
        assert datei.read_text() == "ja"
        # Hintertuer wieder zu.
        with pytest.raises(guard.RealPathWriteBlocked):
            datei.write_text("nein")


# ---------------------------------------------------------------------------
# Schicht 3: Nachkontrolle (Fingerabdruck)
# ---------------------------------------------------------------------------


def test_fingerabdruck_erkennt_neue_datei(tmp_path):
    """Eine neu angelegte Datei aendert den Fingerabdruck."""
    wurzel = tmp_path / "baum"
    (wurzel / "projects" / "proj").mkdir(parents=True)
    (wurzel / "snapshots" / "slug").mkdir(parents=True)

    vorher = guard.academic_tree_fingerprint(wurzel)
    (wurzel / "snapshots" / "slug" / "20990101-0000.tgz").write_bytes(b"x")
    nachher = guard.academic_tree_fingerprint(wurzel)

    assert vorher != nachher, "Neuer Tarball im Slug-Ordner blieb unbemerkt"
    assert guard.fingerprint_diff(vorher, nachher), "fingerprint_diff meldet keine Abweichung"


def test_fingerabdruck_erkennt_ueberschriebene_vault_db(tmp_path):
    """Der Vorfall vom 11.08.2026: vault.db wird an Ort und Stelle ueberschrieben.

    Der Ordner-mtime aendert sich dabei nicht -- der Fingerabdruck muss also
    bis auf Dateiebene in ``projects/`` hinunterreichen.
    """
    wurzel = tmp_path / "baum2"
    projekt = wurzel / "projects" / "academic-research"
    projekt.mkdir(parents=True)
    db = projekt / "vault.db"
    db.write_bytes(b"echte-forschungsdaten")

    vorher = guard.academic_tree_fingerprint(wurzel)
    db.write_bytes(b"tmp-testdaten-die-alles-plattmachen")
    nachher = guard.academic_tree_fingerprint(wurzel)

    assert vorher != nachher, "Ueberschriebene vault.db blieb unbemerkt"
    assert any("vault.db" in eintrag for eintrag in guard.fingerprint_diff(vorher, nachher))


def test_nachkontrolle_meldet_subprozess_schreibzugriff(tmp_path):
    """Schicht 3 im Ganzen: ein Subprozess schreibt, der Test faellt durch.

    Genau die Luecke aus Vorfall B (node hooks/pre-compact.mjs schrieb echte
    Tarballs) -- die Schreibsperre sieht Subprozesse prinzipbedingt nicht.

    Der Beweis laeuft in einem GESCHACHTELTEN pytest-Lauf mit gefaelschtem
    ``HOME``: dadurch ist ``REAL_ACADEMIC_ROOT`` dort ein tmp-Verzeichnis, und
    der absichtlich schaedliche Test richtet nachweislich Schaden an, ohne dass
    der echte Nutzer-Baum je in Reichweite kommt.
    """
    fake_home = tmp_path / "fakehome"
    opfer = fake_home / ".academic-research" / "projects" / "proj" / "vault.db"
    opfer.parent.mkdir(parents=True)
    opfer.write_text("echte-forschungsdaten")

    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "conftest.py").write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(guard.REPO_ROOT)!r})\n"
        "from tests.conftest import *  # noqa: F403\n"
    )
    (suite / "test_boeser_subprozess.py").write_text(
        "import subprocess, sys\n"
        "from tests.conftest import REAL_ACADEMIC_ROOT\n"
        "\n"
        "def test_subprozess_schreibt_in_den_echten_baum():\n"
        "    ziel = REAL_ACADEMIC_ROOT / 'projects' / 'proj' / 'vault.db'\n"
        "    subprocess.run([sys.executable, '-c',\n"
        '                    \'import sys; open(sys.argv[1], "w").write("tmp-testdaten")\',\n'
        "                    str(ziel)], check=True)\n"
    )

    umgebung = dict(os.environ)
    umgebung["HOME"] = str(fake_home)
    umgebung["PYTHONPATH"] = str(guard.REPO_ROOT)

    lauf = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "test_boeser_subprozess.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=str(suite),
        env=umgebung,
        capture_output=True,
        text=True,
        timeout=180,
    )
    ausgabe = lauf.stdout + lauf.stderr

    assert lauf.returncode != 0, f"Der schaedliche Test lief gruen durch:\n{ausgabe}"
    assert "Schutzwall" in ausgabe, f"Keine Schutzwall-Meldung:\n{ausgabe}"
    assert "1 failed" in ausgabe, (
        f"Der Schaden wurde nicht als FEHLSCHLAG des Tests gemeldet:\n{ausgabe}"
    )
    # Und der Schaden im gefaelschten Baum ist wirklich eingetreten -- der
    # Beweis prueft also die Erkennung, nicht bloss eine Schutzbehauptung.
    assert opfer.read_text() == "tmp-testdaten"


def test_fingerabdruck_ist_stabil_ohne_aenderung(tmp_path):
    """Ohne Aenderung darf der Fingerabdruck nicht flattern (sonst wird er ignoriert)."""
    wurzel = tmp_path / "baum3"
    (wurzel / "projects" / "proj").mkdir(parents=True)
    (wurzel / "projects" / "proj" / "vault.db").write_bytes(b"x")
    (wurzel / "snapshots" / "slug").mkdir(parents=True)

    assert guard.academic_tree_fingerprint(wurzel) == guard.academic_tree_fingerprint(wurzel)
    assert (
        guard.fingerprint_diff(
            guard.academic_tree_fingerprint(wurzel), guard.academic_tree_fingerprint(wurzel)
        )
        == []
    )
