"""Tests fuer den einheitlichen Config-Block der drei lokalen Modelle (Issue #719).

AC -> Testfall (siehe Issue #719 / Plan-Kommentar):
  AC1 (alle drei einzeln abschaltbar, ohne dass eine andere ausfaellt) ->
      :func:`test_disabling_embedding_leaves_reranker_and_nli_unaffected`,
      :func:`test_disabling_reranker_leaves_embedding_and_nli_unaffected`,
      :func:`test_disabling_nli_leaves_embedding_and_reranker_unaffected`
  AC2 (Vorrang Argument > Env > Config > Default, je Ebene getestet, fuer
      alle drei identisch) -> :func:`test_resolve_bool_switch_argument_wins`,
      :func:`test_resolve_bool_switch_env_wins_over_config`,
      :func:`test_resolve_bool_switch_config_wins_over_default`,
      :func:`test_resolve_bool_switch_default_when_nothing_set`,
      parametrisiert ueber die drei konkreten Resolver in
      :func:`test_all_three_resolvers_share_the_same_precedence`
  AC3 (alte Schalter funktionieren weiter/migriert, Alias-Test) ->
      :func:`test_embedding_alias_env_var_still_works`,
      :func:`test_reranker_alias_env_var_still_works`
  AC4 (alle drei aus -> reine FTS5-Suche, kein Modell geladen) ->
      :func:`test_all_three_disabled_no_model_ever_loaded`
  AC5 (Doku) -> keine Testabdeckung hier, Doku-Review in vault.md.

Rot->Gruen-Beweis: Diese Datei importiert ``academic_vault.config_switches``,
das vor #719 nicht existiert -- der Import schlaegt mit
``ModuleNotFoundError`` fehl; auf diesem Branch gruen.
"""

from __future__ import annotations

import json

import pytest
from academic_vault.config_switches import resolve_bool_switch
from academic_vault.embedding_model import get_embedder, resolve_embedding_enabled
from academic_vault.nli_prefilter import resolve_nli_prefilter_enabled
from academic_vault.retrieval import apply_reranker, resolve_reranker_enabled

# ---------------------------------------------------------------------------
# AC2 -- generischer Resolver: Vorrang Argument > Env > Config > Default
# ---------------------------------------------------------------------------

ENV_VAR = "ACADEMIC_RESEARCH_TEST_SWITCH_719"
CONFIG_KEY = "test_switch_719"


def test_resolve_bool_switch_argument_wins(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, "0")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({CONFIG_KEY: False}), encoding="utf-8")
    assert resolve_bool_switch(True, ENV_VAR, CONFIG_KEY, False, config) is True


def test_resolve_bool_switch_env_wins_over_config(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, "1")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({CONFIG_KEY: False}), encoding="utf-8")
    assert resolve_bool_switch(None, ENV_VAR, CONFIG_KEY, False, config) is True


def test_resolve_bool_switch_config_wins_over_default(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({CONFIG_KEY: True}), encoding="utf-8")
    assert resolve_bool_switch(None, ENV_VAR, CONFIG_KEY, False, config) is True


def test_resolve_bool_switch_default_when_nothing_set(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    missing_config = tmp_path / "does-not-exist.json"
    assert resolve_bool_switch(None, ENV_VAR, CONFIG_KEY, True, missing_config) is True
    assert resolve_bool_switch(None, ENV_VAR, CONFIG_KEY, False, missing_config) is False


def test_resolve_bool_switch_multiple_env_vars_first_wins(tmp_path, monkeypatch):
    """Mehrere Env-Namen (kanonisch + Alias): der zuerst uebergebene gewinnt."""
    monkeypatch.setenv(ENV_VAR, "1")
    monkeypatch.setenv(ENV_VAR + "_ALIAS", "0")
    missing_config = tmp_path / "does-not-exist.json"
    assert (
        resolve_bool_switch(None, (ENV_VAR, ENV_VAR + "_ALIAS"), CONFIG_KEY, False, missing_config)
        is True
    )


def test_resolve_bool_switch_alias_used_when_canonical_unset(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setenv(ENV_VAR + "_ALIAS", "0")
    missing_config = tmp_path / "does-not-exist.json"
    assert (
        resolve_bool_switch(None, (ENV_VAR, ENV_VAR + "_ALIAS"), CONFIG_KEY, True, missing_config)
        is False
    )


def test_resolve_bool_switch_unrecognized_env_value_falls_through(tmp_path, monkeypatch):
    """Ein nicht erkannter Wert (weder truthy noch falsy) wird uebersprungen,
    nicht als Fehler behandelt -- die Config entscheidet dann."""
    monkeypatch.setenv(ENV_VAR, "maybe")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({CONFIG_KEY: True}), encoding="utf-8")
    assert resolve_bool_switch(None, ENV_VAR, CONFIG_KEY, False, config) is True


@pytest.mark.parametrize(
    "resolver, env_var, config_key",
    [
        (resolve_embedding_enabled, "ACADEMIC_RESEARCH_EMBEDDING_ENABLED", "embedding_enabled"),
        (resolve_reranker_enabled, "ACADEMIC_RESEARCH_RERANKER_ENABLED", "reranker_enabled"),
        (resolve_nli_prefilter_enabled, "ACADEMIC_RESEARCH_NLI_PREFILTER", "nli_prefilter_enabled"),
    ],
)
def test_all_three_resolvers_share_the_same_precedence(
    resolver, env_var, config_key, tmp_path, monkeypatch
):
    """AC2: derselbe Vorrang, je Ebene, identisch fuer alle drei Resolver."""
    for name in (
        env_var,
        "VAULT_AUTO_EMBED",
        "VAULT_RERANK_LOCAL_DISABLE",
    ):
        monkeypatch.delenv(name, raising=False)

    # Ebene 1: Argument gewinnt ueber alles.
    config_all_false = tmp_path / "all_false.json"
    config_all_false.write_text(json.dumps({config_key: False}), encoding="utf-8")
    monkeypatch.setenv(env_var, "0")
    assert resolver(True, config_path=config_all_false) is True

    # Ebene 2: Env gewinnt ueber Config.
    monkeypatch.setenv(env_var, "1")
    assert resolver(config_path=config_all_false) is True

    # Ebene 3: Config gewinnt ueber Default (kein Env gesetzt).
    monkeypatch.delenv(env_var, raising=False)
    config_true = tmp_path / "true.json"
    config_true.write_text(json.dumps({config_key: True}), encoding="utf-8")
    assert resolver(config_path=config_true) is True
    config_false = tmp_path / "false.json"
    config_false.write_text(json.dumps({config_key: False}), encoding="utf-8")
    assert resolver(config_path=config_false) is False

    # Ebene 4: Default, wenn nichts greift.
    missing_config = tmp_path / "missing.json"
    assert resolver(config_path=missing_config) is True


# ---------------------------------------------------------------------------
# AC3 -- Alte Schalter bleiben als Alias funktionsfaehig
# ---------------------------------------------------------------------------


def test_embedding_alias_env_var_still_works(tmp_path, monkeypatch):
    """VAULT_AUTO_EMBED=0 ohne neue Variable gesetzt -> resolve_embedding_enabled() False."""
    monkeypatch.delenv("ACADEMIC_RESEARCH_EMBEDDING_ENABLED", raising=False)
    monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
    missing_config = tmp_path / "missing.json"
    assert resolve_embedding_enabled(config_path=missing_config) is False


def test_embedding_alias_env_var_enabled_value(tmp_path, monkeypatch):
    monkeypatch.delenv("ACADEMIC_RESEARCH_EMBEDDING_ENABLED", raising=False)
    monkeypatch.setenv("VAULT_AUTO_EMBED", "1")
    missing_config = tmp_path / "missing.json"
    assert resolve_embedding_enabled(config_path=missing_config) is True


def test_reranker_alias_env_var_still_works(tmp_path, monkeypatch):
    """VAULT_RERANK_LOCAL_DISABLE (Praesenz-Flag) schaltet weiterhin ab."""
    monkeypatch.delenv("ACADEMIC_RESEARCH_RERANKER_ENABLED", raising=False)
    monkeypatch.setenv("VAULT_RERANK_LOCAL_DISABLE", "1")
    missing_config = tmp_path / "missing.json"
    assert resolve_reranker_enabled(config_path=missing_config) is False


def test_reranker_alias_env_var_absent_keeps_default_on(tmp_path, monkeypatch):
    monkeypatch.delenv("ACADEMIC_RESEARCH_RERANKER_ENABLED", raising=False)
    monkeypatch.delenv("VAULT_RERANK_LOCAL_DISABLE", raising=False)
    missing_config = tmp_path / "missing.json"
    assert resolve_reranker_enabled(config_path=missing_config) is True


def test_repo_default_config_has_new_switches_enabled():
    """Auslieferungsstand: beide neuen Schalter AN (kein Verhaltenswechsel)."""
    from academic_vault.nli_prefilter import DEFAULT_CONFIG_PATH

    data = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    assert data["embedding_enabled"] is True
    assert data["reranker_enabled"] is True


# ---------------------------------------------------------------------------
# AC1 -- Jede Komponente einzeln abschaltbar, ohne die anderen zu beeintraechtigen
# ---------------------------------------------------------------------------


def test_disabling_embedding_leaves_reranker_and_nli_unaffected(monkeypatch):
    assert get_embedder(enabled=False) is None
    assert resolve_reranker_enabled() is True
    assert resolve_nli_prefilter_enabled() is True


def test_disabling_reranker_leaves_embedding_and_nli_unaffected(monkeypatch, fake_embedder):
    import academic_vault.retrieval as retrieval

    candidates = [{"paper_id": "p1", "text": "Beispieltext ueber DevOps-Governance."}]

    mock_reranker = type(
        "MockReranker", (), {"predict": lambda self, pairs: [0.5 for _ in pairs]}
    )()
    monkeypatch.setattr(retrieval, "_get_local_reranker", lambda *a, **kw: mock_reranker)

    # Default (nichts gesetzt): lokaler Fallback greift.
    result = apply_reranker("devops governance", candidates)
    assert result[0]["reranker"] == "local-bge"

    monkeypatch.setenv("ACADEMIC_RESEARCH_RERANKER_ENABLED", "0")
    result_off = apply_reranker("devops governance", candidates)
    assert result_off[0]["reranked"] is False
    assert result_off[0]["reranker"] == "none"

    assert resolve_embedding_enabled() is True
    assert resolve_nli_prefilter_enabled() is True


def test_disabling_nli_leaves_embedding_and_reranker_unaffected(monkeypatch):
    from academic_vault.nli_prefilter import run_batch_prefilter

    result = run_batch_prefilter(
        [
            {
                "quote_id": "q1",
                "chapter_claim": "Ein Satz.",
                "paper_id": "p1",
                "context_before": None,
                "verbatim": "irrelevanter Text",
                "context_after": None,
            }
        ],
        enabled=False,
    )
    assert result["enabled"] is False
    assert result["suspicious"] == []

    assert resolve_embedding_enabled() is True
    assert resolve_reranker_enabled() is True


# ---------------------------------------------------------------------------
# AC4 -- Alle drei aus: reine FTS5-Suche, kein Modell geladen
# ---------------------------------------------------------------------------


def test_all_three_disabled_no_model_ever_loaded(tmp_path, monkeypatch, temp_vault_db):
    """AC4: mit allen drei Schaltern auf 'aus' laeuft add_paper/search(rerank=True)
    FTS5-only durch, ohne dass ein Modell-Loader je aufgerufen wird."""
    import academic_vault.embedding_model as em
    import academic_vault.retrieval as retrieval
    from academic_vault import server

    config = tmp_path / "all_off.json"
    config.write_text(
        json.dumps(
            {
                "embedding_enabled": False,
                "reranker_enabled": False,
                "nli_prefilter_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("academic_vault.config_switches.DEFAULT_CONFIG_PATH", config)
    for name in (
        "ACADEMIC_RESEARCH_EMBEDDING_ENABLED",
        "VAULT_AUTO_EMBED",
        "ACADEMIC_RESEARCH_RERANKER_ENABLED",
        "VAULT_RERANK_LOCAL_DISABLE",
        "ACADEMIC_RESEARCH_NLI_PREFILTER",
    ):
        monkeypatch.delenv(name, raising=False)
    em.reset_embedder_cache()
    retrieval.reset_local_reranker_cache()

    def _fail(*_args, **_kwargs):
        raise AssertionError(
            "Modell-Loader haette bei abgeschalteten Schaltern nie aufgerufen werden duerfen"
        )

    monkeypatch.setattr(em, "_load_backend_model", _fail)
    monkeypatch.setattr(retrieval, "_load_local_reranker_backend", _fail)

    csl_json = json.dumps(
        {
            "type": "article-journal",
            "title": "DevOps-Governance in der Praxis",
            "author": [{"family": "Test", "given": "A"}],
            "issued": {"date-parts": [[2024]]},
        }
    )
    server.add_paper(temp_vault_db, "paper-719", csl_json)

    results = server.search_papers(temp_vault_db, "DevOps-Governance", rerank=True)
    assert isinstance(results, list)

    em.reset_embedder_cache()
    retrieval.reset_local_reranker_cache()
