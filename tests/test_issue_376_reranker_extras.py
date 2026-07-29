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


def _all_declared_dependency_names(data: dict) -> set[str]:
    """Alle Paketnamen aus [project.dependencies] + jeder optional-dependencies-Gruppe."""
    names = set()
    for dep in data["project"]["dependencies"]:
        names.add(__import__("re").split(r"[<>=!~\[ ;]", dep, maxsplit=1)[0].strip().lower())
    for group in data["project"]["optional-dependencies"].values():
        for dep in group:
            names.add(__import__("re").split(r"[<>=!~\[ ;]", dep, maxsplit=1)[0].strip().lower())
    return names


def test_flagembedding_is_not_a_uv_managed_dependency():
    """FlagEmbedding darf NICHT in pyproject.toml auftauchen (P1-Regression, Fixrunde PR #422).

    Ursprünglich stand FlagEmbedding in einem eigenen Extra `rerank-local` --
    das genügt aber NICHT, um die Default-Installation zu schützen: uv löst
    [project.dependencies], optional-dependencies und dev-Gruppen ohne
    `tool.uv.conflicts` GEMEINSAM zu einer einzigen Version je Paket auf. Eine
    Ceiling wie `transformers<5.0`, egal ob global oder nur in einem Extra
    deklariert, zwingt daher JEDE Installation -- auch `uv sync --extra dev`
    ohne rerank-local -- auf die ältere Version herunter (verifiziert: PR #422
    downgradete dadurch `transformers` 5.14.1->4.57.6 und `huggingface-hub`
    1.24.0->0.36.2 im Default-Lock). `tool.uv.conflicts` löst das nicht, weil
    es die gleichzeitige Installation der als konfliktär markierten Extras
    verbietet -- genau das braucht aber der AC2-Live-Test
    (`uv sync --extra dev --extra rerank-local`).

    Deshalb bleibt FlagEmbedding bewusst außerhalb der uv-verwalteten
    Dependency-Graphen: Opt-in nur per manuellem
    `uv pip install 'FlagEmbedding>=1.3,<2.0' 'transformers<5.0'` (siehe
    Kommentar in pyproject.toml), niemals als deklarierte
    [project.optional-dependencies]-Gruppe.
    """
    data = _load_pyproject()
    assert "flagembedding" not in _all_declared_dependency_names(data), (
        "FlagEmbedding ist wieder in pyproject.toml deklariert -- das zwingt "
        "jede uv-Installation (auch ohne den lokalen Reranker) auf die "
        "transformers-Ceiling herunter, die FlagEmbedding braucht. Siehe "
        "Docstring dieses Tests und PR #422."
    )


def test_transformers_hard_dependency_has_no_version_ceiling():
    """transformers darf in [project.dependencies] keine Obergrenze tragen (P1-Regression).

    Die einzig bekannte Notwendigkeit fuer `transformers<5.0` war FlagEmbedding
    (Tokenizer.prepare_for_model() wurde in transformers>=5.x entfernt). Da
    FlagEmbedding jetzt bewusst kein uv-verwalteter Dependency mehr ist (siehe
    `test_flagembedding_is_not_a_uv_managed_dependency`), darf auch keine
    Ceiling mehr auf `transformers` lasten -- sonst bekommt jede
    `uv sync --extra dev`-Installation weiterhin die aeltere Version
    aufgezwungen, obwohl der Grund dafuer (FlagEmbedding) gar nicht installiert
    wird.
    """
    data = _load_pyproject()
    transformers_specs = [
        dep for dep in data["project"]["dependencies"] if dep.lower().startswith("transformers")
    ]
    assert not any("<" in spec for spec in transformers_specs), (
        f"transformers traegt eine Obergrenze in [project.dependencies], obwohl "
        f"FlagEmbedding (der einzige Grund dafuer) kein uv-Extra mehr ist: {transformers_specs}"
    )
