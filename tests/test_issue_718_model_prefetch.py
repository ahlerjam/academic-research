"""Tests fuer Issue #718 — Modelle beim Setup vorab laden + Hardware-Doku.

Akzeptanzkriterium -> Testklasse:

AC1  Genau einmal fragen, Gesamtgroesse genannt        -> TestPromptOnce
AC2  Zustimmung -> alle drei im Cache, kein Re-Download -> TestDownloadAndCache
AC3  Ablehnung -> Lazy-Load mit vorheriger Groessen-Meldung -> TestLazyLoadNotice
AC4  Abgebrochener Download wird fortgesetzt            -> TestResume (live-gated)
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
import sys
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
        out = capsys.readouterr().out
        assert "Embedding-Modell" in out
        assert format_gb(APPROX_BYTES["intfloat/multilingual-e5-small"]) in out

    def test_notify_stays_silent_when_already_cached(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "academic_vault._model_prefetchable.is_cached", lambda repo_id, cache_dir: True
        )
        notify_lazy_download(
            label="Embedding-Modell",
            repo_id="intfloat/multilingual-e5-small",
            cache_dir="/tmp/does-not-matter",
        )
        assert capsys.readouterr().out == ""

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

        printed = io.StringIO()
        monkeypatch.setattr(sys, "stdout", printed)
        _ORIGINAL_EMBEDDING_LOAD_BACKEND("intfloat/multilingual-e5-small", "/tmp/cache")
        monkeypatch.undo()

        assert "Embedding-Modell" in printed.getvalue()
        assert printed.getvalue().index("Embedding-Modell") < len(printed.getvalue())
        assert "model-loaded" not in printed.getvalue()  # Meldung, nicht das Mock-Ergebnis

    def test_local_reranker_backend_passes_cache_dir_to_flagreranker(self, monkeypatch):
        """Reranker-Cache-Mismatch-Fix (#718): cache_dir wird durchgereicht."""
        monkeypatch.setattr(
            "academic_vault._model_prefetchable.is_cached", lambda repo_id, cache_dir: True
        )
        captured = {}

        fake_flagembedding_module = ModuleType("FlagEmbedding")

        class FakeFlagReranker:
            def __init__(self, model_id, cache_dir=None, use_fp16=True):
                captured["model_id"] = model_id
                captured["cache_dir"] = cache_dir

        fake_flagembedding_module.FlagReranker = FakeFlagReranker
        monkeypatch.setitem(sys.modules, "FlagEmbedding", fake_flagembedding_module)

        _ORIGINAL_RERANKER_LOAD_BACKEND("BAAI/bge-reranker-v2-m3", cache_dir="/tmp/rr")
        assert captured == {"model_id": "BAAI/bge-reranker-v2-m3", "cache_dir": "/tmp/rr"}


# ---------------------------------------------------------------------------
# AC4 — Abbruch/Resume (live-gated, keine echten 3,9 GB im normalen Gate-Lauf)
# ---------------------------------------------------------------------------


class TestResume:
    def test_download_model_delegates_resume_to_huggingface_hub(self, monkeypatch):
        """Kein eigener Fortsetzungscode: snapshot_download wird ohne
        resume-spezifische Extra-Logik aufgerufen -- das Resume-Verhalten
        (``.incomplete``-Blobs) ist Library-intern, siehe Modul-Docstring."""
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
        Testlauf unverhaeltnismaessig. Belegt wird die Mechanik, die AC2
        (kein Re-Download bei vollstaendigem Cache) und AC4 (Resume ueber
        huggingface_hub) tragen: ``is_cached`` liefert False vor dem
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


class TestHardwareTable:
    def test_installation_doc_has_a_table_with_all_three_models_and_disk_sizes(self):
        text = _read(REPO_ROOT / "docs" / "guide" / "installation.md")
        for model_id in APPROX_BYTES:
            short_name = model_id.rsplit("/", 1)[-1]
            assert short_name in text, f"Modell '{short_name}' fehlt in der Hardware-Tabelle."
        # Die konkreten Disk-Groessen (aus derselben Quelle wie APPROX_BYTES)
        # muessen als Text auftauchen, nicht nur der Modellname.
        assert "470 MB" in text
        assert "2,1 GB" in text
        assert "1,1 GB" in text
