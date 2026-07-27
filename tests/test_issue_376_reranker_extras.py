"""Regressionstest fuer Issue #376 (AC1): voyageai/cohere sind optionale Extras.

Vorher waren `rerank_with_voyage`/`rerank_with_cohere` faktisch tot, weil weder
`voyageai` noch `cohere` in irgendeiner Dependency-Datei standen (Live-Aufruf
schlug sofort mit ImportError fehl) UND der stille `except Exception: pass` in
`apply_reranker` das verschleierte. AC1 verlangt, dass beide SDKs als
*optionale* Extras deklariert sind -- nicht als versteckte Hard-Dependency in
`[project.dependencies]`.
"""

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _load_pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_voyageai_and_cohere_not_hard_dependencies():
    """voyageai/cohere duerfen NICHT in [project.dependencies] stehen (AC1)."""
    data = _load_pyproject()
    hard_deps = {
        __import__("re").split(r"[<>=!~\[ ;]", dep, maxsplit=1)[0].strip().lower()
        for dep in data["project"]["dependencies"]
    }
    assert "voyageai" not in hard_deps, "voyageai ist als Hard-Dependency deklariert (AC1 verletzt)"
    assert "cohere" not in hard_deps, "cohere ist als Hard-Dependency deklariert (AC1 verletzt)"


def test_voyageai_and_cohere_declared_as_optional_extras():
    """voyageai/cohere muessen unter [project.optional-dependencies] auffindbar sein (AC1)."""
    data = _load_pyproject()
    optional = data["project"]["optional-dependencies"]

    all_optional_names = set()
    for group in optional.values():
        for dep in group:
            name = __import__("re").split(r"[<>=!~\[ ;]", dep, maxsplit=1)[0].strip().lower()
            all_optional_names.add(name)

    assert "voyageai" in all_optional_names, "voyageai fehlt in [project.optional-dependencies]"
    assert "cohere" in all_optional_names, "cohere fehlt in [project.optional-dependencies]"


def test_local_reranker_backend_is_separate_extra_from_dev():
    """FlagEmbedding (schwerer ML-Stack) darf NICHT im dev-Extra stecken (Risiko #1 im Plan).

    Sonst blaeht es jede Default-CI-Installation (`uv sync --extra dev`) auf.
    """
    data = _load_pyproject()
    optional = data["project"]["optional-dependencies"]
    dev_names = {
        __import__("re").split(r"[<>=!~\[ ;]", dep, maxsplit=1)[0].strip().lower()
        for dep in optional.get("dev", [])
    }
    assert "flagembedding" not in dev_names, (
        "FlagEmbedding steckt im dev-Extra -- muss eigener rerank-local-Extra bleiben"
    )

    # Muss aber IRGENDWO deklariert sein (nicht komplett vergessen).
    all_names = set()
    for group in optional.values():
        for dep in group:
            name = __import__("re").split(r"[<>=!~\[ ;]", dep, maxsplit=1)[0].strip().lower()
            all_names.add(name)
    assert "flagembedding" in all_names, (
        "FlagEmbedding (lokaler Reranker) fehlt komplett in pyproject.toml"
    )
