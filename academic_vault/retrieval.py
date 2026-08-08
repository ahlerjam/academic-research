"""Hybrid Retrieval: Reciprocal-Rank-Fusion + optionaler Reranker (#109, #376).

Implementiert:
- reciprocal_rank_fusion(vec_results, fts_results, k=60, top_n=N)
- apply_reranker(query, candidates, voyage_api_key, cohere_api_key)
- rerank_with_voyage(query, candidates, api_key)
- rerank_with_cohere(query, candidates, api_key)
- rerank_with_local_bge(query, candidates)
- compute_recall_at_k(retrieved_ids, relevant_ids, k)
- compute_ndcg_at_k(retrieved_ids, relevant_ids, k)          (#708)
- compute_reciprocal_rank_at_k(retrieved_ids, relevant_ids, k) (#708)
- mean_reciprocal_rank(rankings, k)                          (#708)

RRF-Formel: score(d) = 1/(k + rank_vec(d)) + 1/(k + rank_fts(d))
Standard-Konstante k=60 nach Cormack et al. 2009.

Reranker-Prioritaetskette (#376): Voyage > Cohere > lokaler
``BAAI/bge-reranker-v2-m3``-Fallback (per Default aktiv, seit #714 ueber
``sentence_transformers.CrossEncoder`` statt FlagEmbedding geladen -- ueber
``VAULT_RERANK_LOCAL_DISABLE`` abschaltbar) > unveraendert. ``voyageai``/
``cohere`` sind optionale Extras (``rerank-cloud`` in pyproject.toml) -- kein
stiller ``except Exception: pass`` mehr: jede Fehlstufe loggt eine WARNING und
das zurueckgegebene Kandidaten-Dict traegt ``reranked`` (bool) + ``reranker``
(str) als sichtbaren Beleg statt eines verschleierten Fallbacks.
"""

import logging
import math
import os
import re
from collections.abc import Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

# Haertungs-Fallback (#702): FTS5-Snippets tragen '<b>'/'</b>'-Highlighting.
# Landet ein solches Snippet doch als Reranker-Text (kein Abstract/Chunk
# verfuegbar), darf ein Cross-Encoder trotzdem nie HTML-Markup statt
# Fliesstext bewerten.
_HTML_MARK_RE = re.compile(r"</?b>")

# Lokaler Reranker-Fallback (Apache-2.0, kostenfrei) -- greift nur, wenn weder
# VOYAGE_API_KEY noch COHERE_API_KEY gesetzt sind (siehe apply_reranker).
LOCAL_RERANKER_MODEL_ID = "BAAI/bge-reranker-v2-m3"
ENV_LOCAL_RERANKER_MODEL = "VAULT_RERANK_LOCAL_MODEL"

# Opt-out fuer den per-Default-aktiven lokalen Reranker (#714): jeder
# Wahrheitswert ausser "" schaltet ihn ab, analog dem Muster anderer
# Boolean-Env-Schalter im Repo (Praesenz-Check, kein "1"-Spezialfall).
# Bleibt seit #719 als Alias-Sonderfall neben dem kanonischen Schalter
# erhalten -- siehe resolve_reranker_enabled().
ENV_LOCAL_RERANKER_DISABLE = "VAULT_RERANK_LOCAL_DISABLE"

# ---------------------------------------------------------------------------
# Toggle (Issue #719, Muster: nli_prefilter.resolve_nli_prefilter_enabled)
# ---------------------------------------------------------------------------

#: Kanonischer Schalter seit #719 -- betrifft NUR den lokalen bge-Fallback.
#: Voyage/Cohere sind Cloud-Reranking, kein lokales Modell, und bleiben ueber
#: Cloud-Keys unabhaengig von diesem Schalter nutzbar.
ENV_RERANKER_ENABLED = "ACADEMIC_RESEARCH_RERANKER_ENABLED"
CONFIG_KEY_RERANKER = "reranker_enabled"
DEFAULT_RERANKER_ENABLED = True


def resolve_reranker_enabled(
    explicit: bool | None = None,
    config_path: str | None = None,
) -> bool:
    """Schalter fuer den lokalen ``bge-reranker-v2-m3``-Fallback (Issue #719).

    Vorrang: Argument > Env > ``config/parallel_agents.json`` (Schluessel
    ``reranker_enabled``) > Default ``True``. Betrifft NUR den lokalen
    Fallback -- Voyage/Cohere sind Cloud-Dienste, kein lokales Modell, und
    Reranking als Feature bleibt darueber unabhaengig von diesem Schalter
    nutzbar (sonst wuerde "abschaltbar, ohne dass eine andere Komponente
    ausfaellt" verletzt).

    ``VAULT_RERANK_LOCAL_DISABLE`` (#714) bleibt als Alias erhalten, hat aber
    ABWEICHENDE Semantik: ein reines Praesenz-Flag (jeder gesetzte Wert
    schaltet ab, kein truthy/falsy-Parsing) statt eines echten
    Boolean-Schalters. Deshalb kein Eintrag in der ``env_vars``-Liste des
    generischen Resolvers, sondern ein Sonderfall davor: gesetzt, gewinnt er
    ueber den kanonischen Schalter (bestehende Setups mit
    ``VAULT_RERANK_LOCAL_DISABLE=1`` brechen dadurch nicht still).
    """
    if explicit is not None:
        return bool(explicit)

    if os.environ.get(ENV_LOCAL_RERANKER_DISABLE):
        return False

    from .config_switches import resolve_bool_switch

    return resolve_bool_switch(
        None, ENV_RERANKER_ENABLED, CONFIG_KEY_RERANKER, DEFAULT_RERANKER_ENABLED, config_path
    )


# Cache-Ziel fuer die Reranker-Gewichte (#718). Zuvor bekam ``FlagReranker``
# keinen ``cache_dir`` uebergeben und landete im HF-Standard-Cache
# (``HF_HOME``/``~/.cache/huggingface/hub``) -- ein anderes Verzeichnis als
# ``embedding_model.default_cache_dir()``/``nli_prefilter.default_cache_dir()``
# (``~/.academic-research/models``). Ein Vorab-Download nach
# ``~/.academic-research/models`` haette der Reranker beim naechsten Ladeversuch
# NICHT gefunden. Eigener Env-Override analog den beiden anderen Modulen.
ENV_LOCAL_RERANKER_CACHE = "VAULT_RERANK_LOCAL_CACHE"


def default_cache_dir() -> str:
    """Ablageort fuer die Gewichte des lokalen Rerankers (Env-Override moeglich).

    Identisches Muster wie ``embedding_model.default_cache_dir`` (#372) und
    ``nli_prefilter.default_cache_dir`` (#592) -- eigener Env-Override, gleicher
    Default-Pfad, damit alle drei Modelle ohne weitere Konfiguration im selben
    Verzeichnis landen.
    """
    env = os.environ.get(ENV_LOCAL_RERANKER_CACHE)
    if env:
        return env
    return str(Path.home() / ".academic-research" / "models")


# Spezifische SDK-Fehlerbasisklassen fuer benanntes Exception-Handling statt
# eines stillen `except Exception: pass` (#376). Beide SDKs sind optionale
# Extras (rerank-cloud) -- ist eines nicht installiert, faellt die jeweilige
# Basisklasse auf einen nie ausgeloesten Platzhalter zurueck; der eigentliche
# ImportError wird in apply_reranker ohnehin separat gefangen.
try:
    from voyageai.error import VoyageError
except ImportError:  # voyageai ist optionales Extra, evtl. nicht installiert

    class VoyageError(Exception):  # type: ignore[no-redef]
        """Platzhalter, wenn das voyageai-SDK nicht installiert ist."""


try:
    from cohere.core.api_error import ApiError as CohereApiError
except ImportError:  # cohere ist optionales Extra, evtl. nicht installiert

    class CohereApiError(Exception):  # type: ignore[no-redef]
        """Platzhalter, wenn das cohere-SDK nicht installiert ist."""


def _get_voyage_client(api_key: str | None = None):
    """Erstellt Voyage-Client.

    Kein Singleton — api_key kann pro Aufruf uebergeben werden.
    """
    try:
        import voyageai

        key = api_key or os.environ.get("VOYAGE_API_KEY", "")
        return voyageai.Client(api_key=key)
    except ImportError as err:
        raise ImportError("voyageai SDK nicht installiert. Bitte 'pip install voyageai'.") from err


def _get_cohere_client(api_key: str | None = None):
    """Erstellt Cohere-Client.

    Kein Singleton — api_key kann pro Aufruf uebergeben werden.
    """
    try:
        import cohere

        key = api_key or os.environ.get("COHERE_API_KEY", "")
        return cohere.Client(api_key=key)
    except ImportError as err:
        raise ImportError("cohere SDK nicht installiert. Bitte 'pip install cohere'.") from err


def _load_local_reranker_backend(model_id: str, cache_dir: str | None = None):
    """Laedt das CrossEncoder-Backend fuer den lokalen Reranker (#714).

    Separate Funktion, damit Tests das Fehlen bzw. Scheitern des Backends
    deterministisch simulieren koennen, ohne echte Modellgewichte zu laden —
    analog ``embedding_model._load_backend_model``. Die autouse-Fixture in
    tests/conftest.py haengt sich genau hier ein.

    ``cache_dir`` wird seit #718 explizit gesetzt (Default
    ``default_cache_dir()``) -- vorher landete der Download unbenannt im
    HF-Standard-Cache, siehe Kommentar bei ``ENV_LOCAL_RERANKER_CACHE`` oben.

    Seit #714 ueber ``sentence_transformers.CrossEncoder`` statt
    ``FlagEmbedding.FlagReranker`` geladen -- ``sentence-transformers`` ist
    bereits Hard-Dependency (Embeddings, #372), das gepinnte ``transformers``
    (kein Downgrade auf <5.0 mehr noetig) reicht aus.
    """
    from sentence_transformers import CrossEncoder

    from academic_vault._model_prefetchable import notify_lazy_download

    resolved_cache_dir = cache_dir if cache_dir is not None else default_cache_dir()
    notify_lazy_download(label="Reranker-Modell", repo_id=model_id, cache_dir=resolved_cache_dir)
    return CrossEncoder(model_id, cache_folder=resolved_cache_dir, max_length=512)


# Cache pro Modell-ID: ``None`` bedeutet "Backend fehlt" und wird bewusst
# mitgecacht, analog embedding_model._EMBEDDER_CACHE.
_LOCAL_RERANKER_CACHE: dict[str, object | None] = {}


def reset_local_reranker_cache() -> None:
    """Leert den Cache des lokalen Rerankers (Tests, Modellwechsel zur Laufzeit)."""
    _LOCAL_RERANKER_CACHE.clear()


def _get_local_reranker(model_id: str | None = None, cache_dir: str | None = None):
    """Gibt den lokalen bge-reranker-v2-m3 zurueck oder ``None`` (Degradationspfad).

    Analog ``embedding_model.get_embedder()``: ``None`` ist ein Degradations-,
    kein Absturzpfad -- schlaegt das Laden des CrossEncoder-Backends (#714)
    bzw. der Modell-Download fehl, wird das geloggt und ``apply_reranker``
    faellt auf die unrerankte Reihenfolge zurueck statt abzustuerzen.
    """
    key = model_id or os.environ.get(ENV_LOCAL_RERANKER_MODEL) or LOCAL_RERANKER_MODEL_ID
    if key in _LOCAL_RERANKER_CACHE:
        return _LOCAL_RERANKER_CACHE[key]

    resolved_cache_dir = cache_dir if cache_dir is not None else default_cache_dir()
    reranker: object | None
    try:
        reranker = _load_local_reranker_backend(key, cache_dir=resolved_cache_dir)
    except Exception as exc:
        logger.warning(
            "Lokaler Reranker '%s' nicht nutzbar (%s: %s) — kein kostenfreies "
            "Reranking, RRF-Reihenfolge bleibt unveraendert.",
            key,
            type(exc).__name__,
            exc,
        )
        reranker = None

    _LOCAL_RERANKER_CACHE[key] = reranker
    return reranker


def rrf_score(
    rank_vec: int | None,
    rank_fts: int | None,
    k: int = 60,
) -> float:
    """Berechnet RRF-Score fuer ein Dokument.

    RRF-Score = 1/(k+rank_vec) + 1/(k+rank_fts)

    Args:
        rank_vec: 1-basierter Rang in vec0-Ergebnissen oder None wenn nicht enthalten.
        rank_fts: 1-basierter Rang in FTS5-Ergebnissen oder None wenn nicht enthalten.
        k: Konstante (Standard: 60 nach Cormack et al. 2009).

    Returns:
        RRF-Score als float.
    """
    score = 0.0
    if rank_vec is not None:
        score += 1.0 / (k + rank_vec)
    if rank_fts is not None:
        score += 1.0 / (k + rank_fts)
    return score


def reciprocal_rank_fusion(
    vec_results: list[dict],
    fts_results: list[dict],
    k: int = 60,
    top_n: int | None = None,
) -> list[dict]:
    """Kombiniert vec0- und FTS5-Ergebnisse via Reciprocal-Rank-Fusion.

    Jedes Ergebnis-Dict muss 'paper_id' enthalten.
    Das Ergebnis-Dict wird um 'rrf_score' ergaenzt.

    Metadaten werden pro Paper aus beiden Quellen zusammengefuehrt: ein Paper,
    das in beiden Listen auftaucht, behaelt sowohl die vec0-Felder
    (chunk_id, distance) als auch die FTS5-Felder (score, Snippet mit
    '<b>'-Highlighting). Bei gleichem Schluessel gewinnt FTS5.

    Args:
        vec_results: Liste von Dicts aus vec0-Suche (geordnet nach Relevanz).
        fts_results: Liste von Dicts aus FTS5-Suche (geordnet nach Relevanz).
        k: RRF-Konstante (Standard: 60).
        top_n: Maximale Anzahl zurueckgegebener Ergebnisse. None = alle.

    Returns:
        Kombinierte Liste, absteigend nach rrf_score sortiert.
    """
    vec_ranks: dict[str, int] = {r["paper_id"]: idx + 1 for idx, r in enumerate(vec_results)}
    fts_ranks: dict[str, int] = {r["paper_id"]: idx + 1 for idx, r in enumerate(fts_results)}
    all_paper_ids = set(vec_ranks.keys()) | set(fts_ranks.keys())

    # Metadaten BEIDER Quellen zusammenfuehren statt einander verdraengen zu
    # lassen: vec0 liefert chunk_id/distance, FTS5 den dokumentierten 'score'
    # und das '<b>'-Highlighting im Snippet. Bei Schluesselkollision gewinnt
    # FTS5, weil dessen Felder den Rueckgabevertrag von search_papers bilden.
    paper_data: dict[str, dict] = {}
    for r in vec_results:
        paper_data.setdefault(r["paper_id"], {}).update(r)
    for r in fts_results:
        paper_data.setdefault(r["paper_id"], {}).update(r)

    fused: list[dict] = []
    for pid in all_paper_ids:
        entry = dict(paper_data.get(pid, {"paper_id": pid}))
        entry["rrf_score"] = rrf_score(
            rank_vec=vec_ranks.get(pid),
            rank_fts=fts_ranks.get(pid),
            k=k,
        )
        fused.append(entry)

    fused.sort(key=lambda x: x["rrf_score"], reverse=True)

    if top_n is not None:
        fused = fused[:top_n]

    return fused


def rerank_with_voyage(
    query: str,
    candidates: list[dict],
    api_key: str | None = None,
    model: str = "rerank-2",
) -> list[dict]:
    """Rerankt Kandidaten via Voyage-API.

    Args:
        query: Suchquery.
        candidates: Liste von Dicts mit 'paper_id' und 'text'.
        api_key: Voyage API-Key. Fallback: VOYAGE_API_KEY env.
        model: Voyage-Reranker-Modell (Standard: rerank-2).

    Returns:
        Kandidaten-Liste, absteigend nach Voyage-Score sortiert.
    """
    client = _get_voyage_client(api_key)
    documents = [c["text"] for c in candidates]

    result = client.rerank(
        query=query,
        documents=documents,
        model=model,
    )

    # Ergebnisse nach Voyage-Score sortieren
    reranked: list[dict] = []
    for item in result.results:
        entry = dict(candidates[item.index])
        entry["rerank_score"] = item.relevance_score
        reranked.append(entry)

    reranked.sort(key=lambda x: x["rerank_score"], reverse=True)
    return reranked


def rerank_with_cohere(
    query: str,
    candidates: list[dict],
    api_key: str | None = None,
    model: str = "rerank-english-v3.0",
) -> list[dict]:
    """Rerankt Kandidaten via Cohere-API.

    Args:
        query: Suchquery.
        candidates: Liste von Dicts mit 'paper_id' und 'text'.
        api_key: Cohere API-Key. Fallback: COHERE_API_KEY env.
        model: Cohere-Reranker-Modell (Standard: rerank-english-v3.0).

    Returns:
        Kandidaten-Liste, absteigend nach Cohere-Score sortiert.
    """
    client = _get_cohere_client(api_key)
    documents = [c["text"] for c in candidates]

    response = client.rerank(
        query=query,
        documents=documents,
        model=model,
    )

    reranked: list[dict] = []
    for item in response.results:
        entry = dict(candidates[item.index])
        entry["rerank_score"] = item.relevance_score
        reranked.append(entry)

    reranked.sort(key=lambda x: x["rerank_score"], reverse=True)
    return reranked


def rerank_with_local_bge(
    query: str,
    candidates: list[dict],
    model_id: str | None = None,
) -> list[dict]:
    """Rerankt Kandidaten via lokalem ``BAAI/bge-reranker-v2-m3`` (Apache-2.0, #376).

    Kostenfreier Fallback ohne Cloud-API-Key: laedt/nutzt das
    CrossEncoder-Backend (#714, ``sentence-transformers`` ist bereits
    Hard-Dependency, kein manuelles Opt-in mehr noetig) ueber den lazy
    Singleton :func:`_get_local_reranker`.

    Args:
        query: Suchquery.
        candidates: Liste von Dicts mit 'paper_id' und 'text'.
        model_id: Optionale Modell-Override (Standard: ``LOCAL_RERANKER_MODEL_ID``).

    Returns:
        Kandidaten-Liste, absteigend nach lokalem Rerank-Score sortiert.

    Raises:
        RuntimeError: Wenn das lokale Backend nicht ladbar ist (analog dem
            ``ImportError`` von :func:`rerank_with_voyage`/:func:`rerank_with_cohere`
            — wird von :func:`apply_reranker` gefangen und auf die naechste
            Stufe (bzw. das unveraenderte Ergebnis) zurueckgefallen).
    """
    reranker = _get_local_reranker(model_id)
    if reranker is None:
        raise RuntimeError(
            f"Lokaler Reranker '{model_id or LOCAL_RERANKER_MODEL_ID}' nicht verfuegbar "
            "(Modell-Download fehlgeschlagen oder Backend nicht ladbar)."
        )

    pairs = [[query, c["text"]] for c in candidates]
    # CrossEncoder.predict() gibt bei num_labels=1 (Default-Sigmoid-Aktivierung)
    # immer ein Array zurueck, auch bei genau einem Paar -- anders als
    # FlagReranker.compute_score(), das dort einen Skalar lieferte (#714).
    scores = reranker.predict(pairs)

    reranked: list[dict] = []
    for c, score in zip(candidates, scores, strict=True):
        entry = dict(c)
        entry["rerank_score"] = float(score)
        reranked.append(entry)

    reranked.sort(key=lambda x: x["rerank_score"], reverse=True)
    return reranked


def apply_reranker(
    query: str,
    candidates: list[dict],
    voyage_api_key: str | None = None,
    cohere_api_key: str | None = None,
) -> list[dict]:
    """Wendet optionalen Reranker an.

    Prioritaet: Voyage > Cohere > lokaler ``bge-reranker-v2-m3``-Fallback (NUR
    wenn *beide* Cloud-Keys fehlen) > unveraendert.

    Jeder zurueckgegebene Kandidat traegt zusaetzlich:
    - ``reranked`` (bool): ob dieser Kandidat tatsaechlich reranked wurde.
    - ``reranker`` (str): ``"voyage"`` / ``"cohere"`` / ``"local-bge"`` / ``"none"``.

    Jede Fehlstufe wird geloggt (``logger.warning``, #376) statt still
    verschluckt zu werden — der Aufrufer erfaehrt ueber ``reranked: false``
    UND das Log, dass kein Reranking stattgefunden hat.

    Args:
        query: Suchquery.
        candidates: Kandidaten aus RRF-Fusion.
        voyage_api_key: Voyage API-Key oder None.
        cohere_api_key: Cohere API-Key oder None.

    Returns:
        Rerankte oder unveraenderte Kandidaten-Liste (immer mit 'text',
        'reranked', 'reranker').
    """
    # text-Feld sicherstellen: Reranker-APIs brauchen Dokumenttext
    enriched = []
    for c in candidates:
        entry = dict(c)
        if "text" not in entry:
            entry["text"] = entry.get("snippet", entry.get("paper_id", ""))
        # Haertungs-Fallback (#702): egal woher 'text' stammt, es geht nie
        # FTS5-Markup an einen Reranker -- der Normalfall ergaenzt echten
        # Abstract-/Chunk-Text (server._fill_missing_reranker_text), aber
        # dieser Fallback sichert auch direkte apply_reranker()-Aufrufe ab,
        # die 'snippet' unveraendert als 'text' durchreichen.
        text = entry.get("text") or ""
        if text:
            entry["text"] = _HTML_MARK_RE.sub("", text)
        enriched.append(entry)

    if voyage_api_key:
        try:
            reranked = rerank_with_voyage(query, enriched, api_key=voyage_api_key)
        except ImportError as exc:
            logger.warning("Voyage-Reranking uebersprungen: SDK nicht installiert (%s).", exc)
        except VoyageError as exc:
            logger.warning(
                "Voyage-Reranking fehlgeschlagen (%s: %s) — Fallback auf naechste Stufe.",
                type(exc).__name__,
                exc,
            )
        except Exception as exc:
            logger.warning(
                "Voyage-Reranking fehlgeschlagen (%s: %s) — Fallback auf naechste Stufe.",
                type(exc).__name__,
                exc,
            )
        else:
            for entry in reranked:
                entry["reranked"] = True
                entry["reranker"] = "voyage"
            return reranked

    if cohere_api_key:
        try:
            reranked = rerank_with_cohere(query, enriched, api_key=cohere_api_key)
        except ImportError as exc:
            logger.warning("Cohere-Reranking uebersprungen: SDK nicht installiert (%s).", exc)
        except CohereApiError as exc:
            logger.warning(
                "Cohere-Reranking fehlgeschlagen (%s: %s) — Fallback auf naechste Stufe.",
                type(exc).__name__,
                exc,
            )
        except Exception as exc:
            logger.warning(
                "Cohere-Reranking fehlgeschlagen (%s: %s) — Fallback auf naechste Stufe.",
                type(exc).__name__,
                exc,
            )
        else:
            for entry in reranked:
                entry["reranked"] = True
                entry["reranker"] = "cohere"
            return reranked

    # Lokaler Fallback greift NUR, wenn beide Cloud-Keys fehlen -- ein
    # fehlgeschlagener Voyage/Cohere-Aufruf darf NICHT still durch den
    # lokalen Reranker ersetzt werden (sonst waere AC3 -- 'reranked: false'
    # bei ungueltigem Cloud-Key -- durch einen stillen Erfolg verdeckt).
    #
    # Seit #714 ist der lokale Reranker per Default aktiv (kein FlagEmbedding
    # mehr noetig) -- resolve_reranker_enabled() (#719) schaltet ihn ab
    # (kanonischer Schalter oder Alias VAULT_RERANK_LOCAL_DISABLE), geprueft
    # VOR dem Laden des Backends, damit kein Modell geladen wird.
    local_enabled = resolve_reranker_enabled()
    if not local_enabled:
        logger.info(
            "Lokaler Reranker deaktiviert (Schalter/Env/Config) -- "
            "RRF-Reihenfolge bleibt unveraendert."
        )
    if not voyage_api_key and not cohere_api_key and local_enabled:
        try:
            reranked = rerank_with_local_bge(query, enriched)
        except Exception as exc:
            logger.warning(
                "Lokaler Reranker fehlgeschlagen (%s: %s) — kein Reranking, "
                "RRF-Reihenfolge bleibt unveraendert.",
                type(exc).__name__,
                exc,
            )
        else:
            for entry in reranked:
                entry["reranked"] = True
                entry["reranker"] = "local-bge"
            return reranked

    for entry in enriched:
        entry["reranked"] = False
        entry["reranker"] = "none"
    return enriched


def compute_recall_at_k(
    retrieved_ids: list[str],
    relevant_ids: list[str],
    k: int = 10,
) -> float:
    """Berechnet Recall@K.

    Recall@K = |{relevante Papers in Top-K}| / |{relevante Papers}|

    Args:
        retrieved_ids: Liste der abgerufenen Paper-IDs (in Rang-Reihenfolge).
        relevant_ids: Liste der Ground-Truth-relevanten Paper-IDs.
        k: Cutoff.

    Returns:
        Recall@K als float zwischen 0.0 und 1.0.
    """
    if not relevant_ids:
        return 1.0
    top_k = set(retrieved_ids[:k])
    relevant = set(relevant_ids)
    return len(top_k & relevant) / len(relevant)


def _dedup_preserving_order(ids: Sequence[str]) -> list[str]:
    """Entfernt Dubletten und behaelt die ERSTE Position jedes Eintrags.

    Rangbewusste Metriken muessen das tun: zaehlte eine zweite Nennung
    desselben Treffers erneut, koennte ein Retriever seinen DCG ueber den
    Idealwert heben (nDCG > 1), indem er einen Treffer wiederholt ausgibt.
    Recall@k braucht den Schritt nicht, weil es ohnehin ueber Mengen rechnet.
    """
    seen: set[str] = set()
    unique: list[str] = []
    for item in ids:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def compute_ndcg_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: Sequence[str],
    k: int = 10,
) -> float:
    """Berechnet nDCG@K mit binaerer Relevanz (Issue #708).

    Anders als Recall@K bewertet nDCG die POSITION eines Treffers: ein
    relevanter Chunk auf Rang 1 zaehlt voll, derselbe auf Rang 10 nur noch
    ``1/log2(11) ≈ 0.29``. Genau diese Empfindlichkeit fehlt Recall@K, das
    jede Umsortierung innerhalb der Top-K ignoriert.

        DCG@K  = sum_{i=1..K} rel_i / log2(i + 1)          (rel_i in {0, 1})
        IDCG@K = sum_{i=1..min(|R|, K)} 1 / log2(i + 1)
        nDCG@K = DCG@K / IDCG@K

    ``IDCG`` wird bei ``K`` gekappt -- ohne diese Kappung koennte ein
    perfektes Top-K bei ``|R| > K`` nie 1.0 erreichen.

    Konventionen (bewusst festgelegt, siehe Tests):
        * Leeres ``relevant_ids`` -> ``1.0`` (identisch zu
          :func:`compute_recall_at_k`: es gibt nichts zu verfehlen).
        * Dubletten in ``retrieved_ids`` zaehlen nur an ihrer ersten Position
          (:func:`_dedup_preserving_order`).
        * ``k <= 0`` -> ``0.0``.

    Args:
        retrieved_ids: Abgerufene IDs in Rang-Reihenfolge (bester zuerst).
        relevant_ids: Ground-Truth-relevante IDs (ungeordnet).
        k: Cutoff.

    Returns:
        nDCG@K als float zwischen 0.0 und 1.0.
    """
    if not relevant_ids:
        return 1.0
    if k <= 0:
        return 0.0

    relevant = set(relevant_ids)
    ranked = _dedup_preserving_order(retrieved_ids)[:k]
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, doc_id in enumerate(ranked, start=1)
        if doc_id in relevant
    )
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(relevant), k) + 1))
    if idcg == 0.0:
        return 0.0
    return dcg / idcg


def compute_reciprocal_rank_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: Sequence[str],
    k: int = 10,
) -> float:
    """Reciprocal Rank@K: ``1 / Rang`` des ERSTEN Treffers, sonst ``0.0`` (#708).

    Beantwortet die Frage, die eine Nutzerin tatsaechlich stellt: wie weit muss
    ich scrollen, bis etwas Brauchbares kommt? Recall@K und nDCG@K beantworten
    sie beide nicht.

    Konventionen wie bei :func:`compute_ndcg_at_k`: leeres ``relevant_ids``
    ergibt ``1.0``, Dubletten zaehlen nur an ihrer ersten Position, ``k <= 0``
    ergibt ``0.0``.
    """
    if not relevant_ids:
        return 1.0
    if k <= 0:
        return 0.0

    relevant = set(relevant_ids)
    for rank, doc_id in enumerate(_dedup_preserving_order(retrieved_ids)[:k], start=1):
        if doc_id in relevant:
            return 1.0 / rank
    return 0.0


def mean_reciprocal_rank(
    rankings: Sequence[tuple[Sequence[str], Sequence[str]]],
    k: int = 10,
) -> float:
    """Mittelt :func:`compute_reciprocal_rank_at_k` ueber mehrere Queries (#708).

    Args:
        rankings: Liste aus ``(retrieved_ids, relevant_ids)`` je Query.
        k: Cutoff, der fuer jede Query gilt.

    Returns:
        MRR als float zwischen 0.0 und 1.0. ``0.0`` bei leerer Eingabe -- ein
        Mittelwert ueber null Queries hat keinen sinnvollen Wert, und ``1.0``
        waere hier die gefaehrlichere Luege (ein leeres Goldset saehe perfekt
        aus).
    """
    if not rankings:
        return 0.0
    return sum(
        compute_reciprocal_rank_at_k(retrieved, relevant, k=k) for retrieved, relevant in rankings
    ) / len(rankings)
