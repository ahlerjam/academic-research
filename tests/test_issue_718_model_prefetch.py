"""Tests fuer Issue #718 — Modelle beim Setup vorab laden + Hardware-Doku.

Akzeptanzkriterium -> Testklasse:

AC1  Genau einmal fragen, Gesamtgroesse genannt        -> TestPromptOnce
AC2  Zustimmung -> alle drei im Cache, kein Re-Download -> TestDownloadAndCache
AC3  Ablehnung -> Lazy-Load mit vorheriger Groessen-Meldung -> TestLazyLoadNotice
     (Kanaltreue am echten MCP-Serverprozess: tests/test_issue_718_mcp_stdio_stream.py)
AC4  Abgebrochener Download wird fortgesetzt            -> TestResume
AC5  Doku nennt 8 GB RAM / 4 GB Platte / keine GPU-Pflicht / CPU-Hinweis -> TestHardwareDocs
AC6  Tabelle mit Platte/RAM/Laufzeit je Modell in der Doku -> TestHardwareTable

Live-Netzwerktests sind hinter ``MODEL_PREFETCH_LIVE_TEST=1`` gegated (Muster:
``VAULT_E5_LIVE_TEST``/``VAULT_RERANK_LOCAL_LIVE_TEST`` in tests/conftest.py) --
im normalen Gate-Lauf (``pytest tests/ --ignore=tests/evals``) uebersprungen,
damit die Suite netzunabhaengig und schnell bleibt.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from academic_vault import embedding_model, nli_prefilter, retrieval
from academic_vault._model_prefetchable import (
    APPROX_BYTES,
    format_gb,
    is_cached,
    notify_lazy_download,
)
from scripts import model_prefetch

from tests.helpers.fake_hf_hub import FakeHfHub

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SETUP_SH = SCRIPTS_DIR / "setup.sh"
PREFETCH_SCRIPT = SCRIPTS_DIR / "model_prefetch.py"

# Erfasst VOR jedem Testlauf (Modul-Kollektionszeit, bevor die autouse-Guards
# in tests/conftest.py ``_load_backend_model``/``_load_local_reranker_backend``
# durch Blocker ersetzen) -- so lassen sich die echten Funktionen mit
# gemocktem Backend-Import testen, ohne die Netzwerk-Guards zu umgehen oder
# von der Fixture-Ausfuehrungsreihenfolge abzuhaengen.
_ORIGINAL_EMBEDDING_LOAD_BACKEND = embedding_model._load_backend_model
_ORIGINAL_RERANKER_LOAD_BACKEND = retrieval._load_local_reranker_backend


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Setup-Wiring
# ---------------------------------------------------------------------------


class TestSetupWiring:
    def test_prefetch_script_exists(self):
        assert PREFETCH_SCRIPT.is_file(), f"{PREFETCH_SCRIPT} fehlt"

    def test_setup_sh_calls_model_prefetch(self):
        text = _read(SETUP_SH)
        assert "model_prefetch.py" in text, "setup.sh ruft model_prefetch.py nicht auf."

    def test_all_three_modules_share_the_same_default_cache_dir(self, monkeypatch):
        """AC2-Voraussetzung: ohne Env-Override landen alle drei im selben Verzeichnis."""
        for var in (
            embedding_model.ENV_CACHE_DIR,
            nli_prefilter.ENV_CACHE_DIR,
            retrieval.ENV_LOCAL_RERANKER_CACHE,
        ):
            monkeypatch.delenv(var, raising=False)
        dirs = {
            embedding_model.default_cache_dir(),
            nli_prefilter.default_cache_dir(),
            retrieval.default_cache_dir(),
        }
        assert len(dirs) == 1, f"Cache-Verzeichnisse laufen auseinander: {dirs}"


# ---------------------------------------------------------------------------
# AC1 — genau einmal fragen, Gesamtgroesse genannt
# ---------------------------------------------------------------------------


class TestPromptOnce:
    def test_non_tty_defaults_to_no_download(self, monkeypatch):
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        specs = model_prefetch.build_model_specs()
        assert model_prefetch._prompt_prefetch(specs) is False

    def test_tty_prompt_mentions_total_size_once(self, monkeypatch):
        specs = model_prefetch.build_model_specs()
        expected_total = format_gb(model_prefetch.total_download_bytes(specs))

        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        calls: list[str] = []

        def fake_input(prompt: str = "") -> str:
            calls.append(prompt)
            return "n"

        monkeypatch.setattr("builtins.input", fake_input)
        model_prefetch._prompt_prefetch(specs)

        assert len(calls) == 1, f"Prompt wurde {len(calls)}x gestellt, erwartet genau 1x."
        assert expected_total in calls[0], (
            f"Prompt nennt die Gesamtgroesse '{expected_total}' nicht: {calls[0]!r}"
        )

    def test_already_fully_cached_skips_the_prompt(self, monkeypatch, capsys):
        """Wiederholter Setup-Lauf: alles gecacht -> keine erneute Frage (Idempotenz)."""
        monkeypatch.setattr(model_prefetch, "all_cached", lambda specs: True)

        def _fail_prompt(specs):
            raise AssertionError("Prompt haette bei vollstaendigem Cache nicht laufen duerfen")

        monkeypatch.setattr(model_prefetch, "_prompt_prefetch", _fail_prompt)
        rc = model_prefetch.main([])
        assert rc == 0
        assert "bereits vollstaendig" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# AC2 — Zustimmung: alle drei im Cache, kein Re-Download
# ---------------------------------------------------------------------------


class TestDownloadAndCache:
    def test_yes_flag_downloads_every_spec_exactly_once(self, monkeypatch):
        monkeypatch.setattr(model_prefetch, "all_cached", lambda specs: False)
        monkeypatch.setattr(model_prefetch, "is_cached", lambda repo_id, cache_dir: False)

        downloaded: list[str] = []
        monkeypatch.setattr(
            model_prefetch, "download_model", lambda spec: downloaded.append(spec.repo_id)
        )

        rc = model_prefetch.main(["--yes"])
        assert rc == 0
        specs = model_prefetch.build_model_specs()
        assert downloaded == [s.repo_id for s in specs]

    def test_already_cached_spec_is_not_downloaded_again(self, monkeypatch):
        """Selbst mit --yes: ein bereits gecachtes Modell wird nicht erneut geladen."""
        monkeypatch.setattr(model_prefetch, "all_cached", lambda specs: False)
        monkeypatch.setattr(model_prefetch, "is_cached", lambda repo_id, cache_dir: True)

        downloaded: list[str] = []
        monkeypatch.setattr(
            model_prefetch, "download_model", lambda spec: downloaded.append(spec.repo_id)
        )

        model_prefetch.main(["--yes"])
        assert downloaded == [], "Bereits gecachte Modelle duerfen nicht erneut geladen werden."

    def test_no_flag_skips_download_without_error(self, monkeypatch):
        monkeypatch.setattr(model_prefetch, "all_cached", lambda specs: False)

        def _fail(spec):
            raise AssertionError("download_model haette bei --no nicht laufen duerfen")

        monkeypatch.setattr(model_prefetch, "download_model", _fail)
        rc = model_prefetch.main(["--no"])
        assert rc == 0


# ---------------------------------------------------------------------------
# AC3 — Ablehnung: Lazy-Load mit vorheriger Groessen-Meldung
# ---------------------------------------------------------------------------


class TestLazyLoadNotice:
    def test_notify_prints_size_before_download_when_not_cached(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "academic_vault._model_prefetchable.is_cached", lambda repo_id, cache_dir: False
        )
        notify_lazy_download(
            label="Embedding-Modell",
            repo_id="intfloat/multilingual-e5-small",
            cache_dir="/tmp/does-not-matter",
        )
        captured = capsys.readouterr()
        assert "Embedding-Modell" in captured.err
        assert format_gb(APPROX_BYTES["intfloat/multilingual-e5-small"]) in captured.err
        # stdout ist im MCP-Server der JSON-RPC-Kanal (``mcp.run()`` -> stdio),
        # dort darf keine Klartextzeile landen. Protokollnachweis am echten
        # Serverprozess: tests/test_issue_718_mcp_stdio_stream.py
        assert captured.out == ""

    def test_notify_stays_silent_when_already_cached(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "academic_vault._model_prefetchable.is_cached", lambda repo_id, cache_dir: True
        )
        notify_lazy_download(
            label="Embedding-Modell",
            repo_id="intfloat/multilingual-e5-small",
            cache_dir="/tmp/does-not-matter",
        )
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_embedding_backend_load_notifies_before_download(self, monkeypatch):
        """embedding_model._load_backend_model ruft notify_lazy_download auf, bevor das
        Backend (hier gemockt) das eigentliche Modell laedt."""
        calls: list[str] = []
        monkeypatch.setattr(
            "academic_vault._model_prefetchable.is_cached", lambda repo_id, cache_dir: False
        )

        fake_st_module = ModuleType("sentence_transformers")

        def fake_sentence_transformer(model_id, cache_folder=None):
            calls.append("model-loaded")
            return SimpleNamespace(model_id=model_id)

        fake_st_module.SentenceTransformer = fake_sentence_transformer
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st_module)

        on_stderr = io.StringIO()
        on_stdout = io.StringIO()
        monkeypatch.setattr(sys, "stderr", on_stderr)
        monkeypatch.setattr(sys, "stdout", on_stdout)
        _ORIGINAL_EMBEDDING_LOAD_BACKEND("intfloat/multilingual-e5-small", "/tmp/cache")
        monkeypatch.undo()

        assert "Embedding-Modell" in on_stderr.getvalue()
        assert "model-loaded" not in on_stderr.getvalue()  # Meldung, nicht das Mock-Ergebnis
        # stdout bleibt unberuehrt: im MCP-Server laeuft dieser Ladepfad
        # in-process, und stdout traegt dort JSON-RPC.
        assert on_stdout.getvalue() == ""

    def test_local_reranker_backend_passes_cache_dir_to_crossencoder(self, monkeypatch):
        """Reranker-Cache-Mismatch-Fix (#718): cache_dir wird durchgereicht (#714: CrossEncoder)."""
        monkeypatch.setattr(
            "academic_vault._model_prefetchable.is_cached", lambda repo_id, cache_dir: True
        )
        captured = {}

        class FakeCrossEncoder:
            def __init__(self, model_id, cache_folder=None, max_length=None):
                captured["model_id"] = model_id
                captured["cache_folder"] = cache_folder
                captured["max_length"] = max_length

        monkeypatch.setattr("sentence_transformers.CrossEncoder", FakeCrossEncoder)

        _ORIGINAL_RERANKER_LOAD_BACKEND("BAAI/bge-reranker-v2-m3", cache_dir="/tmp/rr")
        assert captured == {
            "model_id": "BAAI/bge-reranker-v2-m3",
            "cache_folder": "/tmp/rr",
            "max_length": 512,
        }


# ---------------------------------------------------------------------------
# AC4 — Abbruch/Resume
# ---------------------------------------------------------------------------

#: Drei Miniatur-Repos in der Rolle der drei Produktionsmodelle. Die
#: Dateinamen sind die echten (``config.json``/``model.safetensors``), die
#: Inhalte beliebig -- ``huggingface_hub`` interessiert nur Groesse und ETag.
_FAKE_REPOS = {
    "prefetch-test/modell-eins": {
        "config.json": b'{"model_type":"eins"}',
        "model.safetensors": bytes(range(256)) * 4,
    },
    "prefetch-test/modell-zwei": {
        "config.json": b'{"model_type":"zwei"}',
        "model.safetensors": bytes(range(256)) * 32,
    },
    "prefetch-test/modell-drei": {
        "config.json": b'{"model_type":"drei"}',
        "model.safetensors": bytes(range(256)) * 4,
    },
}
_MODELL_EINS, _MODELL_ZWEI, _MODELL_DREI = _FAKE_REPOS

#: Ein vollstaendiger Setup-Schritt-9-Lauf in einem EIGENEN Prozess. Der Lauf
#: geht ueber ``model_prefetch.main(["--yes"])``, also durch denselben Code,
#: den ``scripts/setup.sh`` startet -- nur die drei Modell-Specs zeigen auf den
#: lokalen Test-Ursprung statt auf huggingface.co.
_PREFETCH_CHILD = """
import sys

sys.path.insert(0, {repo_root!r})
from scripts import model_prefetch

specs = [
    model_prefetch.ModelSpec(label=repo, repo_id=repo, cache_dir={cache_dir!r})
    for repo in {repos!r}
]
model_prefetch.build_model_specs = lambda: specs
raise SystemExit(model_prefetch.main(["--yes"]))
"""


def _spawn_prefetch(hub: FakeHfHub, cache_dir: str, log_dir: Path) -> subprocess.Popen[bytes]:
    """Startet Schritt 9 gegen den lokalen Ursprung in einem frischen Prozess.

    Eigener Prozess, weil AC4 genau das behauptet: was ein ABGEBROCHENER Lauf
    auf der Platte hinterlaesst, muss der NAECHSTE Lauf wiederverwenden. Der
    Endpunkt kommt ueber ``HF_ENDPOINT`` und nicht per monkeypatch, weil
    ``huggingface_hub`` ihn beim Import in ``constants`` einfriert.
    """
    script = _PREFETCH_CHILD.format(
        repo_root=str(REPO_ROOT), cache_dir=cache_dir, repos=list(_FAKE_REPOS)
    )
    env = {
        **os.environ,
        "HF_ENDPOINT": hub.endpoint,
        "HF_HOME": str(log_dir / "hf-home"),
        "HF_HUB_DISABLE_XET": "1",
        "HF_HUB_DISABLE_PROGRESS_BARS": "1",
        "HF_HUB_OFFLINE": "0",
    }
    with (log_dir / "child-stderr.log").open("wb") as stderr:
        return subprocess.Popen(
            [sys.executable, "-c", script],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
        )


class TestResume:
    def test_interrupted_prefetch_continues_at_the_next_setup_run(self, tmp_path):
        """AC4 an echtem Abbruch statt an einer Behauptung.

        Ablauf, ohne einen einzigen Mock im Download-Pfad:

        1. Setup-Schritt 9 laeuft in einem eigenen Prozess gegen einen lokalen
           HF-Ursprung (``FakeHfHub``) und laedt Modell 1 vollstaendig; bei
           Modell 2 ist ``config.json`` durch, ``model.safetensors`` haengt
           mitten in der Uebertragung.
        2. Der Prozess wird hart beendet (``SIGKILL``) -- das ist der Abbruch
           aus dem Akzeptanzkriterium, kein simulierter Fehlerpfad.
        3. Ein ZWEITER, frischer Prozess laeuft denselben Schritt erneut.

        Belegt wird, was AC4 verlangt: der zweite Lauf beginnt nicht von vorn.
        Modell 1 wird nicht einmal mehr angefragt, von Modell 2 wird nur die
        abgebrochene Datei erneut uebertragen. Mitgeprueft wird die Grenze des
        Verfahrens, damit die Doku daran haengen kann: die abgebrochene Datei
        selbst startet bei Byte 0 (kein ``Range``-Header), denn
        ``huggingface_hub`` haelt ihren Zwischenstand in einer
        prozess-eigenen ``.incomplete``-Datei.
        """
        cache_dir = str(tmp_path / "models")
        stall_file = (_MODELL_ZWEI, "model.safetensors")

        with FakeHfHub(_FAKE_REPOS, stall_file=stall_file) as hub:
            first = _spawn_prefetch(hub, cache_dir, tmp_path)
            try:
                started = hub.stall_started.wait(timeout=60)
                stderr = (tmp_path / "child-stderr.log").read_text(
                    encoding="utf-8", errors="replace"
                )
                assert started, f"Der erste Lauf kam nie bis zum stockenden Download.\n{stderr}"
                time.sleep(0.2)  # ein paar Chunks unterwegs lassen
                first.kill()
                first.wait(timeout=30)
            finally:
                if first.poll() is None:  # pragma: no cover — nur bei haengendem Kind
                    first.kill()

            # Zustand nach dem Abbruch: Modell 1 fertig, Modell 2 angefangen,
            # Modell 3 nie begonnen.
            assert is_cached(_MODELL_EINS, cache_dir) is True, (
                "Modell 1 war vor dem Abbruch fertig und muesste im Cache liegen."
            )
            assert is_cached(_MODELL_ZWEI, cache_dir) is False, (
                "Modell 2 war beim Abbruch unvollstaendig — is_cached darf es nicht "
                "als fertig melden, sonst wuerde der naechste Lauf es ueberspringen."
            )
            assert is_cached(_MODELL_DREI, cache_dir) is False

            hub.reset_log()
            second = _spawn_prefetch(hub, cache_dir, tmp_path)
            rc = second.wait(timeout=120)
            stderr = (tmp_path / "child-stderr.log").read_text(encoding="utf-8", errors="replace")
            assert rc == 0, f"Zweiter Lauf fehlgeschlagen (rc={rc}):\n{stderr}"

            # Fortgesetzt, nicht neu begonnen:
            assert _MODELL_EINS not in hub.touched_repos(), (
                "Das bereits vollstaendige Modell 1 wurde erneut angefasst — der "
                "zweite Lauf beginnt damit von vorn statt fortzusetzen."
            )
            assert hub.downloaded_files(_MODELL_ZWEI) == {"model.safetensors"}, (
                "Von Modell 2 haette nur die abgebrochene Datei erneut uebertragen "
                f"werden duerfen, tatsaechlich: {hub.downloaded_files(_MODELL_ZWEI)}"
            )
            assert hub.downloaded_files(_MODELL_DREI) == {"config.json", "model.safetensors"}

            # Grenze des Verfahrens (traegt die Formulierung in installation.md):
            # die abgebrochene Datei beginnt von vorn, nicht an der Abbruchstelle.
            retry_gets = [r for r in hub.file_requests(*stall_file) if r.method == "GET"]
            assert len(retry_gets) == 1
            assert retry_gets[0].range_header is None, (
                "huggingface_hub setzt die abgebrochene Datei doch an der Abbruchstelle "
                f"fort (Range={retry_gets[0].range_header!r}) — dann ist die Einschraenkung "
                "in docs/guide/installation.md falsch und muss zurueckgenommen werden."
            )

            # Und am Ende liegen alle drei vollstaendig da.
            for repo_id in _FAKE_REPOS:
                assert is_cached(repo_id, cache_dir) is True, f"{repo_id} fehlt nach Lauf 2."

    def test_download_model_delegates_resume_to_huggingface_hub(self, monkeypatch):
        """Kein eigener Fortsetzungscode: ``snapshot_download`` wird ohne
        resume-spezifische Extra-Logik aufgerufen -- welcher Zwischenstand
        einen Abbruch ueberlebt, entscheidet allein die Library (belegt in
        ``test_interrupted_prefetch_continues_at_the_next_setup_run``)."""
        captured = {}

        def fake_snapshot_download(*, repo_id, cache_dir):
            captured["repo_id"] = repo_id
            captured["cache_dir"] = cache_dir
            return "/fake/path"

        fake_hub_module = ModuleType("huggingface_hub")
        fake_hub_module.snapshot_download = fake_snapshot_download
        monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub_module)

        spec = model_prefetch.build_model_specs()[0]
        result = model_prefetch.download_model(spec)
        assert result == "/fake/path"
        assert captured == {"repo_id": spec.repo_id, "cache_dir": spec.cache_dir}

    @pytest.mark.skipif(
        os.environ.get("MODEL_PREFETCH_LIVE_TEST") != "1",
        reason="Live-Download-Test nur mit MODEL_PREFETCH_LIVE_TEST=1 (braucht Netz).",
    )
    def test_is_cached_reflects_a_real_download_live(self, tmp_path):
        """Live-Beleg fuer den Cache-Check-Mechanismus (AC2/AC4-Grundlage):

        Nutzt bewusst ein winziges oeffentliches HF-Repo statt eines der drei
        Produktionsmodelle (zusammen ~3,9 GB) -- das waere fuer einen
        Testlauf unverhaeltnismaessig. Ergaenzt
        ``test_interrupted_prefetch_continues_at_the_next_setup_run`` (dort
        laeuft alles gegen einen lokalen Ursprung) um den Beleg, dass
        ``is_cached`` auch gegen den ECHTEN Hub so urteilt: False vor dem
        Download, True danach, und ein zweiter ``snapshot_download``-Aufruf
        macht keinen Netzzugriff mehr (kein zusaetzlicher Assert noetig --
        ``local_files_only=True`` in ``is_cached`` erzwingt das bereits).
        """
        from huggingface_hub import snapshot_download

        repo_id = "hf-internal-testing/tiny-random-bert"
        cache_dir = str(tmp_path)

        assert is_cached(repo_id, cache_dir) is False
        snapshot_download(repo_id=repo_id, cache_dir=cache_dir)
        assert is_cached(repo_id, cache_dir) is True


# ---------------------------------------------------------------------------
# AC5 — Doku: 8 GB RAM / 4 GB Platte / keine GPU-Pflicht / CPU-Laufzeit-Hinweis
# ---------------------------------------------------------------------------


class TestHardwareDocs:
    @pytest.mark.parametrize(
        "doc", [REPO_ROOT / "README.md", REPO_ROOT / "docs" / "guide" / "installation.md"]
    )
    def test_mentions_minimum_ram_and_disk(self, doc):
        text = _read(doc)
        assert "8 GB" in text, f"{doc}: '8 GB' RAM-Untergrenze fehlt."
        assert "4 GB" in text, f"{doc}: '4 GB' Platten-Untergrenze fehlt."

    def test_installation_doc_states_no_gpu_required_and_cpu_runtime_hint(self):
        text = _read(REPO_ROOT / "docs" / "guide" / "installation.md")
        assert re.search(r"[Kk]eine GPU", text), "Kein Hinweis, dass keine GPU noetig ist."
        assert re.search(r"CPU.{0,40}langsamer|langsamer.{0,40}CPU", text), (
            "Kein CPU-Laufzeit-Hinweis (spuerbar langsamer auf reiner CPU)."
        )


# ---------------------------------------------------------------------------
# AC6 — Tabelle mit Platte/RAM/Laufzeit je Modell
# ---------------------------------------------------------------------------


#: Spalten der Hardware-Tabelle in docs/guide/installation.md. AC6 verlangt
#: Platte, RAM und Laufzeit je Modell; "Apple GPU" traegt zusaetzlich den
#: CPU-Vergleich aus AC5 ("spuerbar langsamer auf reiner CPU").
_HARDWARE_COLUMNS = ("Platte", "Peak-RSS", "CPU", "Apple GPU")

#: Werte, die eine Zelle als NICHT gemessen ausweisen. Eine Tabelle, in der
#: solche Platzhalter stehen, erfuellt AC6 nicht -- sie kuendigt die Zahl nur an.
_PLACEHOLDERS = ("nicht gemessen", "n/a", "tbd", "?", "-", "—", "–", "")


def _hardware_table_rows() -> dict[str, list[str]]:
    """Parst die Hardware-Tabelle -> ``{modellname: [zellen…]}``.

    Bewusst geparst statt per Substring geprueft: ``"1,1 GB" in text`` ist auch
    dann noch gruen, wenn die Zahl in einer ganz anderen Zeile steht.
    """
    lines = _read(REPO_ROOT / "docs" / "guide" / "installation.md").splitlines()
    header = "| Modell | " + " | ".join(_HARDWARE_COLUMNS) + " |"
    try:
        start = lines.index(header)
    except ValueError as exc:  # pragma: no cover — nur bei geaenderter Tabelle
        raise AssertionError(
            f"Hardware-Tabelle mit der Kopfzeile {header!r} steht nicht in installation.md."
        ) from exc

    rows: dict[str, list[str]] = {}
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        rows[cells[0]] = cells[1:]
    return rows


class TestHardwareTable:
    def test_table_lists_every_prefetched_model(self):
        rows = _hardware_table_rows()
        for model_id in APPROX_BYTES:
            short_name = model_id.rsplit("/", 1)[-1]
            assert any(short_name in name for name in rows), (
                f"Modell '{short_name}' fehlt in der Hardware-Tabelle (Zeilen: {list(rows)})."
            )

    def test_every_model_row_carries_a_measured_value_in_every_column(self):
        """AC6 verlangt Platte, RAM UND Laufzeit je Modell — fuer jedes der drei.

        Bis zu diesem Fix stand in der NLI-Zeile dreimal 'nicht gemessen'; die
        Tabelle nannte damit fuer ein Drittel der Modelle keine Anforderung.
        """
        rows = _hardware_table_rows()
        assert len(rows) == len(APPROX_BYTES), (
            f"Erwartet je eine Zeile pro vorab geladenem Modell, gefunden: {list(rows)}"
        )
        for name, cells in rows.items():
            assert len(cells) == len(_HARDWARE_COLUMNS), f"{name}: unvollstaendige Zeile {cells}"
            for column, cell in zip(_HARDWARE_COLUMNS, cells, strict=True):
                value = cell.rstrip("†*").strip()
                assert value.lower() not in _PLACEHOLDERS, (
                    f"{name}: Spalte '{column}' ist mit '{cell}' kein gemessener Wert."
                )
                assert re.search(r"\d", value), (
                    f"{name}: Spalte '{column}' enthaelt keine Zahl ('{cell}')."
                )

    def test_disk_column_matches_the_sizes_used_for_the_prompt(self):
        """Plattenspalte und Download-Meldung muessen dieselbe Groesse nennen.

        Sonst steht in der Tabelle etwas anderes als im Setup-Prompt — und die
        Zeilen summieren sich nicht mehr auf die dort genannte Gesamtgroesse.
        Toleranz 5 %, weil die Doku rundet (und weil MB/GB im Fliesstext
        dezimal gemeint sind, nicht binaer).
        """
        rows = _hardware_table_rows()
        disk_column = _HARDWARE_COLUMNS.index("Platte")
        for model_id, size in APPROX_BYTES.items():
            short_name = model_id.rsplit("/", 1)[-1]
            row = next(name for name in rows if short_name in name)
            cell = rows[row][disk_column]
            match = re.fullmatch(r"([\d,]+)\s*(MB|GB)", cell)
            assert match, f"{short_name}: Plattenangabe '{cell}' ist keine MB/GB-Groesse."
            factor = 1_000_000 if match.group(2) == "MB" else 1_000_000_000
            documented = float(match.group(1).replace(",", ".")) * factor
            assert abs(documented - size) / size <= 0.05, (
                f"{short_name}: Tabelle nennt '{cell}', der Setup-Prompt rechnet mit "
                f"{format_gb(size)} ({size} Bytes) — mehr als 5 % Abweichung."
            )
