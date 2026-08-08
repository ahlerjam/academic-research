"""Regressionstests fuer Issue #714: lokaler Reranker ueber CrossEncoder, Default-aktiv.

Vorher lud `_load_local_reranker_backend` `FlagEmbedding.FlagReranker` -- ein
Paket, das bewusst kein uv-Extra war (erzwingt `transformers<5.0`), weshalb der
lokale Reranker aus #376 in der Praxis nie lief. Seit #714 laedt dieselbe
Funktion `sentence_transformers.CrossEncoder` -- bereits Hard-Dependency
(#372) -- und der Reranker ist per Default aktiv statt manuelles Opt-in zu
verlangen.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RETRIEVAL_SRC = (REPO_ROOT / "academic_vault" / "retrieval.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC1: kein FlagEmbedding mehr, CrossEncoder statt dessen
# ---------------------------------------------------------------------------


def test_retrieval_module_does_not_import_flagembedding():
    """retrieval.py darf `FlagEmbedding` nicht mehr importieren (AC1).

    Historische Kommentare, die den Umstieg von FlagEmbedding auf CrossEncoder
    erklaeren, sind zulaessig -- geprueft wird der tatsaechliche Import, nicht
    jede Textstelle.
    """
    assert "import FlagEmbedding" not in RETRIEVAL_SRC, (
        "retrieval.py importiert noch FlagEmbedding -- AC1 verlangt den vollstaendigen "
        "Umstieg auf sentence_transformers.CrossEncoder."
    )
    assert "from FlagEmbedding" not in RETRIEVAL_SRC


def test_load_local_reranker_backend_uses_crossencoder():
    """`_load_local_reranker_backend` instanziiert `sentence_transformers.CrossEncoder` (AC1).

    Quelltext-Inspektion (auf dem direkt aus der Datei gelesenen Text, NICHT
    via ``inspect.getsource`` auf dem Live-Objekt) statt Live-Aufruf: die
    autouse-Fixture `block_real_local_reranker_backend` (tests/conftest.py)
    patcht `_load_local_reranker_backend` im Modul, `inspect.getsource` saehe
    also nur den Blocker-Stub. Isoliert wird der Funktionskoerper zwischen
    ``def _load_local_reranker_backend`` und der naechsten Top-Level-``def``.
    """
    start = RETRIEVAL_SRC.index("def _load_local_reranker_backend")
    end = RETRIEVAL_SRC.index("\ndef ", start + 1)
    func_source = RETRIEVAL_SRC[start:end]

    assert "from sentence_transformers import CrossEncoder" in func_source
    assert "CrossEncoder(" in func_source
    assert "cache_folder=" in func_source
    assert "max_length=512" in func_source
    # Erlaubt: der Docstring erwaehnt FlagReranker historisch (Umstiegsgrund).
    # Verboten: ein tatsaechlicher Import/Aufruf.
    assert "import FlagEmbedding" not in func_source
    assert "from FlagEmbedding" not in func_source
    assert "FlagReranker(" not in func_source


# ---------------------------------------------------------------------------
# AC3: Reranking per Default aktiv, ueber VAULT_RERANK_LOCAL_DISABLE abschaltbar
# ---------------------------------------------------------------------------


class TestLocalRerankerDefaultActive:
    def test_apply_reranker_uses_local_backend_by_default(self, monkeypatch):
        """Ohne Cloud-Keys und ohne Disable-Schalter greift der lokale Reranker (AC3)."""
        from academic_vault.retrieval import apply_reranker

        monkeypatch.delenv("VAULT_RERANK_LOCAL_DISABLE", raising=False)

        candidates = [
            {"paper_id": "p001", "text": "Unrelated snippet.", "rrf_score": 0.02},
            {"paper_id": "p002", "text": "Highly relevant snippet.", "rrf_score": 0.015},
        ]

        mock_reranker = MagicMock()
        mock_reranker.predict.return_value = [0.1, 0.9]

        with patch("academic_vault.retrieval._get_local_reranker", return_value=mock_reranker):
            result = apply_reranker(
                query="test query",
                candidates=candidates,
                voyage_api_key=None,
                cohere_api_key=None,
            )

        assert all(entry["reranked"] is True for entry in result)
        assert all(entry["reranker"] == "local-bge" for entry in result)

    def test_apply_reranker_disabled_via_env_switch(self, monkeypatch, caplog):
        """`VAULT_RERANK_LOCAL_DISABLE` schaltet den lokalen Reranker ab, ohne das Backend zu laden (AC3)."""
        import logging

        from academic_vault.retrieval import apply_reranker

        monkeypatch.setenv("VAULT_RERANK_LOCAL_DISABLE", "1")

        candidates = [{"paper_id": "p001", "text": "Some text.", "rrf_score": 0.02}]

        with patch("academic_vault.retrieval._get_local_reranker") as mock_get_local:
            with caplog.at_level(logging.INFO, logger="academic_vault.retrieval"):
                result = apply_reranker(
                    query="test",
                    candidates=candidates,
                    voyage_api_key=None,
                    cohere_api_key=None,
                )

        mock_get_local.assert_not_called()
        assert all(entry["reranked"] is False for entry in result)
        assert all(entry["reranker"] == "none" for entry in result)
        # Seit #719 ein gemeinsamer Log-Text fuer kanonischen Schalter UND
        # Alias (resolve_reranker_enabled()) statt einer env-var-spezifischen
        # Meldung -- die Kernaussage ("deaktiviert, keine Umsortierung")
        # bleibt erhalten.
        assert any(
            "deaktiviert" in r.message and "unveraendert" in r.message for r in caplog.records
        )


# ---------------------------------------------------------------------------
# AC5: pyproject.toml ohne FlagEmbedding-Sonderbehandlung
# ---------------------------------------------------------------------------


def test_pyproject_has_no_flagembedding_opt_in_instructions():
    """Die manuelle FlagEmbedding-Opt-in-Anleitung ist aus pyproject.toml entfernt (AC5).

    Historische Erwaehnungen (z.B. im Guard-Test-Verweis, warum die Ceiling
    frueher noetig war) sind zulaessig -- geprueft wird die konkrete
    Installationsanleitung, die AC1 (kein manueller Schritt) obsolet macht.
    """
    pyproject_text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "pip install 'FlagEmbedding" not in pyproject_text, (
        "pyproject.toml enthaelt noch die manuelle FlagEmbedding-Installationsanleitung -- "
        "AC1/AC5 verlangen den ersatzlosen Wegfall des manuellen Opt-in-Schritts."
    )
    optional_deps = _load_pyproject_optional_dependencies()
    assert "rerank-local" not in optional_deps, (
        "pyproject.toml deklariert wieder ein 'rerank-local'-Extra -- FlagEmbedding bleibt "
        "bewusst kein uv-verwaltetes Extra (AC5)."
    )


def _load_pyproject_optional_dependencies() -> dict:
    import tomllib

    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["optional-dependencies"]


# ---------------------------------------------------------------------------
# AC6: Latenz gemessen und in der Doku genannt
# ---------------------------------------------------------------------------


def test_docs_mention_measured_local_reranker_latency():
    """docs/reference/vault.md nennt die gemessenen Latenzzahlen (AC6, Regressionsnetz)."""
    docs_text = (REPO_ROOT / "docs" / "reference" / "vault.md").read_text(encoding="utf-8")
    assert "48" in docs_text and "ms" in docs_text, (
        "Latenzzahl (48 ms/Paar, CPU) fehlt in docs/reference/vault.md -- AC6 verlangt eine "
        "dokumentierte Messung, kein spaeteres stilles Verschwinden."
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
