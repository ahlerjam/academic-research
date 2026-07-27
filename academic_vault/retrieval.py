"""Hybrid Retrieval: Reciprocal-Rank-Fusion + optionaler Reranker (#109, #376).

Implementiert:
- reciprocal_rank_fusion(vec_results, fts_results, k=60, top_n=N)
- apply_reranker(query, candidates, voyage_api_key, cohere_api_key)
- rerank_with_voyage(query, candidates, api_key)
- rerank_with_cohere(query, candidates, api_key)
- rerank_with_local_bge(query, candidates)
- compute_recall_at_k(retrieved_ids, relevant_ids, k)

RRF-Formel: score(d) = 1/(k + rank_vec(d)) + 1/(k + rank_fts(d))
Standard-Konstante k=60 nach Cormack et al. 2009.

Reranker-Prioritaetskette (#376): Voyage > Cohere > lokaler
``BAAI/bge-reranker-v2-m3``-Fallback (NUR wenn *beide* Cloud-Keys fehlen) >
unveraendert. ``voyageai``/``cohere`` sind optionale Extras (``rerank-cloud``
in pyproject.toml) -- kein stiller ``except Exception: pass`` mehr: jede
Fehlstufe loggt eine WARNING und das zurueckgegebene Kandidaten-Dict traegt
``reranked`` (bool) + ``reranker`` (str) als sichtbaren Beleg statt eines
verschleierten Fallbacks.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Lokaler Reranker-Fallback (Apache-2.0, kostenfrei) -- greift nur, wenn weder
# VOYAGE_API_KEY noch COHERE_API_KEY gesetzt sind (siehe apply_reranker).
LOCAL_RERANKER_MODEL_ID = "BAAI/bge-reranker-v2-m3"
ENV_LOCAL_RERANKER_MODEL = "VAULT_RERANK_LOCAL_MODEL"

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
    except ImportError:
        raise ImportError("voyageai SDK nicht installiert. Bitte 'pip install voyageai'.")


def _get_cohere_client(api_key: str | None = None):
    """Erstellt Cohere-Client.

    Kein Singleton — api_key kann pro Aufruf uebergeben werden.
    """
    try:
        import cohere

        key = api_key or os.environ.get("COHERE_API_KEY", "")
        return cohere.Client(api_key=key)
    except ImportError:
        raise ImportError("cohere SDK nicht installiert. Bitte 'pip install cohere'.")


def _load_local_reranker_backend(model_id: str):
    """Laedt das FlagEmbedding-Backend fuer den lokalen Reranker.

    Separate Funktion, damit Tests das Fehlen bzw. Scheitern des Backends
    deterministisch simulieren koennen, ohne echte Modellgewichte zu laden —
    analog ``embedding_model._load_backend_model``. Die autouse-Fixture in
    tests/conftest.py haengt sich genau hier ein.
    """
    from FlagEmbedding import FlagReranker

    return FlagReranker(model_id, use_fp16=True)


# Cache pro Modell-ID: ``None`` bedeutet "Backend fehlt" und wird bewusst
# mitgecacht, analog embedding_model._EMBEDDER_CACHE.
_LOCAL_RERANKER_CACHE: dict[str, object | None] = {}


def reset_local_reranker_cache() -> None:
    """Leert den Cache des lokalen Rerankers (Tests, Modellwechsel zur Laufzeit)."""
    _LOCAL_RERANKER_CACHE.clear()


def _get_local_reranker(model_id: str | None = None):
    """Gibt den lokalen bge-reranker-v2-m3 zurueck oder ``None`` (Degradationspfad).

    Analog ``embedding_model.get_embedder()``: ``None`` ist ein Degradations-,
    kein Absturzpfad -- fehlt das FlagEmbedding-Backend (Extra ``rerank-local``
    nicht installiert) oder schlaegt der Modell-Download fehl, wird das
    geloggt und ``apply_reranker`` faellt auf die unrerankte Reihenfolge
    zurueck statt abzustuerzen.
    """
    key = model_id or os.environ.get(ENV_LOCAL_RERANKER_MODEL) or LOCAL_RERANKER_MODEL_ID
    if key in _LOCAL_RERANKER_CACHE:
        return _LOCAL_RERANKER_CACHE[key]

    reranker: object | None
    try:
        reranker = _load_local_reranker_backend(key)
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

    Kostenfreier Fallback ohne Cloud-API-Key: laedt/nutzt das FlagEmbedding-
    Backend (Extra ``rerank-local``) ueber den lazy Singleton
    :func:`_get_local_reranker`.

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
            "(FlagEmbedding fehlt oder Modell-Download fehlgeschlagen)."
        )

    pairs = [[query, c["text"]] for c in candidates]
    scores = reranker.compute_score(pairs, normalize=True)
    # Backend gibt bei genau einem Paar einen Skalar statt einer Liste zurueck.
    if isinstance(scores, int | float):
        scores = [scores]

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
    if not voyage_api_key and not cohere_api_key:
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
