"""Regressionstest fuer Issue #715: voyageai/cohere kommen in pyproject.toml
nicht mehr vor.

Vormals (Issue #376) waren `voyageai`/`cohere` als optionales Extra
`rerank-cloud` deklariert. #715 entfernt den Cloud-Reranker ersatzlos -- der
lokale `bge-reranker-v2-m3`-Fallback ist der einzige verbleibende Weg. Dieser
Test ersetzt die vorherigen #376-AC1-Tests (die verlangten, dass beide SDKs
als optionale Extras existieren) durch die Umkehrung: beide Namen duerfen
weder als Hard-Dependency noch als Extra auftauchen.
"""

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _load_pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_voyageai_and_cohere_absent_from_pyproject():
    """voyageai/cohere duerfen NIRGENDS in pyproject.toml stehen (Issue #715).

    Weder als Hard-Dependency ([project.dependencies]) noch als optionales
    Extra ([project.optional-dependencies]) -- der Cloud-Reranker ist
    ersatzlos entfernt.
    """
    data = _load_pyproject()
    hard_deps = {
        __import__("re").split(r"[<>=!~\[ ;]", dep, maxsplit=1)[0].strip().lower()
        for dep in data["project"]["dependencies"]
    }
    assert "voyageai" not in hard_deps, (
        "voyageai ist als Hard-Dependency deklariert (#715 verletzt)"
    )
    assert "cohere" not in hard_deps, "cohere ist als Hard-Dependency deklariert (#715 verletzt)"

    all_optional_names = set()
    for group in data["project"]["optional-dependencies"].values():
        for dep in group:
            name = __import__("re").split(r"[<>=!~\[ ;]", dep, maxsplit=1)[0].strip().lower()
            all_optional_names.add(name)

    assert "voyageai" not in all_optional_names, (
        "voyageai noch als Extra deklariert (#715 verletzt)"
    )
    assert "cohere" not in all_optional_names, "cohere noch als Extra deklariert (#715 verletzt)"


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
