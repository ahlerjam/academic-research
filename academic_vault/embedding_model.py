"""Lokales Embedding-Modell fuer academic_vault (Issue #372, seit #732: ``BAAI/bge-m3``).

Kapselt das konfigurierte Embedding-Modell (Default seit #732: ``BAAI/bge-m3``,
MIT, 1024 Dimensionen; zuvor ``intfloat/multilingual-e5-small``, 384d) hinter
einem schmalen ``Embedder``-Protokoll:

* ``embed_documents(texts)`` — Chunks fuer den Ingest
* ``embed_query(text)``      — Suchanfragen

Das Praefix-Schema haengt vom Modell ab, nicht ist es ein Detail: die
e5-Familie (``E5SmallEmbedder``, weiterhin genutzt fuer ``VAULT_EMBEDDING_MODEL``-
Overrides auf e5-kompatible Modelle) verlangt ``passage: ``/``query: `` als Teil
ihres Trainings-Setups. ``BAAI/bge-m3`` verlangt laut Modellkarte ausdruecklich
KEINE Instruktion ("the BGE-M3 model no longer requires adding instructions to
the queries") — ``BgeM3Embedder`` haengt deshalb keine Praefixe an. Ein
aufgezwungenes ``passage: `` waere hier kein Betriebspfad, sondern eine falsch
bediente Schnittstelle (belegt in ``docs/evals/2026-08-08-embedding-candidates-731.md``).

Backend-Politik: ``sentence-transformers`` ist eine **harte** Dependency
(pyproject.toml und scripts/requirements.txt) — ohne sie bliebe
``chunk_embeddings`` in jeder realen Installation leer und die Vektor-Suche
waere Attrappe (#372). Der Import bleibt trotzdem lazy: er zieht Torch nach und
darf den Import von ``academic_vault`` nicht um Sekunden verzoegern.

``get_embedder()`` liefert ``None``, wenn das Backend trotz Deklaration nicht
nutzbar ist (deinstalliert, Modell-Download nicht moeglich, inkompatible
Torch-Version). Das ist ein Degradations-, kein Absturzpfad: der Vault laeuft
dann FTS5-only weiter. Der Grund wird geloggt, damit eine leere
``chunk_embeddings``-Tabelle nicht wieder unbemerkt bleibt.

Das Modell selbst (~2,27 GB) wird beim ersten Gebrauch nach
``default_cache_dir()`` heruntergeladen und danach von dort geladen.
"""

import logging
import math
import os
import struct
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Legacy-Breite: die Dimension, in der vec0-Tabellen angelegt werden, solange
# ``embedding_meta`` noch keine Zeile traegt (frischer Vault vor dem ersten
# Embed, oder Bestands-DB ohne je registriertes Inventar, Issue #629). Bewusst
# KEINE Aussage mehr ueber "die" Embedding-Dimension: die eines Bestands steht
# in ``embedding_meta`` (siehe schema.sql), die eines Modells liefert der
# Embedder selbst (``Embedder.dim``). Wer hier wieder eine globale Konstante
# hineinliest, baut den Fehler aus #629 nach.
#
# Bleibt bewusst bei 384, auch nachdem #732 ``DEFAULT_MODEL_ID`` auf ein 1024d-
# Modell umgestellt hat: JEDER Bestands-Vault, der vor #732 existierte, wurde
# mit einem 384d-Modell befuellt -- das ist die Annahme, die dieser Fallback
# absichert. Ein frischer Vault ohne Bestand ist davon nicht betroffen:
# ``register_embedding_inventory()`` erkennt den leeren Bestand und baut
# ``chunk_vectors``/``quote_embeddings`` beim ersten echten Embed selbstheilend
# in der tatsaechlichen Modell-Dimension neu auf (``_rebuild_vector_tables``) --
# der Wert hier ist nie mehr als eine Uebergangsbreite fuer ``init_schema()``.
DEFAULT_EMBEDDING_DIM = 384

# Seit #732: BAAI/bge-m3 (MIT, 1024d) statt intfloat/multilingual-e5-small
# (MIT, 384d). Entscheidung und Zahlen: docs/evals/2026-08-08-embedding-model-
# decision-732.md, Datenbasis docs/evals/2026-08-08-embedding-candidates-731.md.
# Kurzfassung: BGE-M3 liefert auf dem Chunk-Goldset aus #708 den besten Recall
# (0,9808) bei CPU-Indexierungszeiten, die auf einem Laptop ohne GPU praktikabel
# bleiben (168,6 ms/Chunk) -- anders als der qualitativ ebenbuertige Kandidat
# qwen3-384, der trotz Migrationsfreiheit ~80x so lange je Chunk braucht.
DEFAULT_MODEL_ID = "BAAI/bge-m3"

# Dokumentierter Ausweg bei Dimensions-Mismatch. Steht hier, weil die
# Fehlermeldung aus mehreren Modulen erzeugt wird und ueberall denselben
# Aufruf nennen muss.
REINDEX_HINT = (
    "python -m academic_vault.migrate --db <VAULT.DB> --reindex-embeddings "
    "rechnet den Bestand mit dem aktuell konfigurierten Modell neu (#629)."
)


class EmbeddingDimensionMismatchError(RuntimeError):
    """Modell-Dimension passt nicht zur Dimension des Vault-Bestands (#629).

    Bewusst ein harter Fehler statt eines Degradationspfads: Vektoren aus zwei
    Modellen liegen nicht im selben Raum. Wuerden sie nebeneinander im Vault
    stehen, lieferte jede Suche nur den zufaellig passenden Teilbestand -- ohne
    dass irgendwo sichtbar waere, dass die Haelfte der Treffer fehlt.
    """


def dimension_mismatch_error(
    *,
    model_id: str | None,
    model_dim: int,
    vault_dim: int,
    vault_model_id: str | None = None,
) -> EmbeddingDimensionMismatchError:
    """Baut die Mismatch-Meldung: Ursache, Bestand und Ausweg in einem Satz."""
    origin = f" (Bestand aufgebaut mit '{vault_model_id}')" if vault_model_id else ""
    return EmbeddingDimensionMismatchError(
        f"Embedding-Modell '{model_id or 'unbekannt'}' liefert {model_dim} Dimensionen, "
        f"der Vault-Bestand hat {vault_dim}{origin}. Beide Vektorraeume sind nicht "
        f"vergleichbar; ein Modellwechsel braucht einen Re-Index: {REINDEX_HINT}"
    )


# e5-Pflichtpraefixe (asymmetrisches Retrieval).
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "

# Env-Overrides
ENV_MODEL_ID = "VAULT_EMBEDDING_MODEL"
ENV_CACHE_DIR = "VAULT_EMBEDDING_CACHE"

# ---------------------------------------------------------------------------
# Toggle (Issue #719, Muster: nli_prefilter.resolve_nli_prefilter_enabled)
# ---------------------------------------------------------------------------

#: Kanonischer Schalter seit #719.
ENV_EMBEDDING_ENABLED = "ACADEMIC_RESEARCH_EMBEDDING_ENABLED"
#: Alt-Name seit #372, bleibt als Alias erhalten -- bestehende Setups mit
#: ``VAULT_AUTO_EMBED=0`` brechen dadurch nicht still.
ENV_AUTO_EMBED_ALIAS = "VAULT_AUTO_EMBED"
CONFIG_KEY_EMBEDDING = "embedding_enabled"
DEFAULT_EMBEDDING_ENABLED = True


def resolve_embedding_enabled(
    explicit: bool | None = None,
    config_path: str | Path | None = None,
    *,
    legacy_alias: bool = True,
) -> bool:
    """Schalter fuer das lokale Embedding-Modell (Issue #719).

    Vorrang: Argument > Env (``ACADEMIC_RESEARCH_EMBEDDING_ENABLED``, mit
    ``legacy_alias=True`` zusaetzlich Alt-Name ``VAULT_AUTO_EMBED``) >
    ``config/parallel_agents.json`` (Schluessel ``embedding_enabled``) >
    Default ``True``. :func:`get_embedder` selbst wertet diesen Schalter
    NICHT aus (siehe dessen Docstring): explizite Aufrufer
    (``vault.embed_quote``, ``quote_context_similarity``,
    ``migrate.reindex_embeddings``) laden das Backend immer, unabhaengig vom
    Schalter -- wer sie aufruft, will das Modell laden.

    ``legacy_alias`` steuert, ob der Alt-Name ``VAULT_AUTO_EMBED`` (#372)
    mitzaehlt. Er gatete vor #719 AUSSCHLIESSLICH den Auto-Ingest in
    ``server._auto_embed_enabled`` -- Default ``True`` erhaelt das:
    bestehende Setups mit ``VAULT_AUTO_EMBED=0`` bleiben unveraendert
    (auch von Tests genutzt, um den Auto-Ingest-Seiteneffekt beim manuellen
    Bestuecken von ``chunk_embeddings`` zu unterdruecken, ohne die Suche
    abzuschalten). ``server._vec0_search`` ruft deshalb explizit
    ``legacy_alias=False`` auf: die Vektor-Suche ist eine mit #719 NEUE
    Gate-Faehigkeit, die es unter dem Alt-Namen nie gab, und sie darf nur
    ueber den kanonischen Schalter (oder die Config-Datei) abschaltbar sein.
    Fuer AC4 aus #719 ("alle drei Schalter aus => reine FTS5-Suche") genuegt
    der kanonische Schalter -- er gatet beide Pfade gleichzeitig.
    """
    from .config_switches import resolve_bool_switch

    env_vars = (
        (ENV_EMBEDDING_ENABLED, ENV_AUTO_EMBED_ALIAS) if legacy_alias else (ENV_EMBEDDING_ENABLED,)
    )
    return resolve_bool_switch(
        explicit,
        env_vars,
        CONFIG_KEY_EMBEDDING,
        DEFAULT_EMBEDDING_ENABLED,
        config_path,
    )


def default_cache_dir() -> str:
    """Ablageort fuer heruntergeladene Modellgewichte."""
    env = os.environ.get(ENV_CACHE_DIR)
    if env:
        return env
    return str(Path.home() / ".academic-research" / "models")


def serialize_f32(vector: Sequence[float]) -> bytes:
    """Serialisiert einen Vektor als float32 little-endian (sqlite-vec-Format)."""
    return struct.pack(f"<{len(vector)}f", *(float(v) for v in vector))


def deserialize_f32(blob: bytes) -> list[float]:
    """Umkehrung von :func:`serialize_f32`.

    Wirft ``ValueError`` bei einem BLOB, dessen Laenge kein Vielfaches von 4 ist
    (z. B. abgeschnittene Altdaten) — stillschweigend halbe Floats zu lesen
    waere schlimmer als ein klarer Fehler.
    """
    if len(blob) % 4 != 0:
        raise ValueError(f"Embedding-BLOB hat Laenge {len(blob)} (kein Vielfaches von 4 Bytes)")
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def l2_normalize(vector: Sequence[float]) -> list[float]:
    """L2-Normalisierung. Der Nullvektor bleibt unveraendert (keine Division durch 0)."""
    norm = math.sqrt(sum(float(v) * float(v) for v in vector))
    if norm == 0.0:
        return [float(v) for v in vector]
    return [float(v) / norm for v in vector]


@runtime_checkable
class Embedder(Protocol):
    """Minimales Interface, das Ingest und Suche brauchen."""

    @property
    def dim(self) -> int:
        """Dimension der gelieferten Vektoren.

        Read-only deklariert (statt als Attribut), damit Implementierungen sie
        vom geladenen Backend erfragen duerfen -- ein festes Klassenattribut
        erfuellt diese Signatur weiterhin (Tests injizieren solche).
        """
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Vektorisiert Chunks (Passage-Seite des asymmetrischen Retrievals)."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Vektorisiert eine Suchanfrage (Query-Seite)."""
        ...


def _load_backend_model(model_id: str, cache_dir: str | None = None) -> Any:
    """Laedt das sentence-transformers-Backend (deklarierte Dependency).

    Separate Funktion, damit Tests das Fehlen bzw. Scheitern des Backends
    deterministisch simulieren koennen, ohne echte Modellgewichte zu laden —
    die autouse-Fixture in tests/conftest.py haengt sich genau hier ein.
    """
    from sentence_transformers import SentenceTransformer

    from academic_vault._model_prefetchable import notify_lazy_download

    notify_lazy_download(
        label="Embedding-Modell",
        repo_id=model_id,
        cache_dir=cache_dir if cache_dir is not None else default_cache_dir(),
    )
    return SentenceTransformer(model_id, cache_folder=cache_dir)


class E5SmallEmbedder:
    """Embedder mit e5-Praefixschema (``passage: ``/``query: ``).

    Urspruenglich fuer ``intfloat/multilingual-e5-small`` geschrieben (#372);
    das Praefixschema ist Teil des Trainings-Setups der GESAMTEN e5-Familie
    (auch ``multilingual-e5-large``), deshalb bleibt diese Klasse die
    Basisimplementierung fuer jedes ueber ``VAULT_EMBEDDING_MODEL`` gesetzte
    e5-kompatible Modell -- der Klassenname ist historisch, keine Aussage
    ueber die konfigurierte Modell-ID. Fuer Modelle mit ANDEREM Prompting
    (seit #732: ``BAAI/bge-m3``, kein Praefix) siehe :class:`BgeM3Embedder`.

    ``query_prefix``/``passage_prefix`` sind Klassenattribute, keine
    Instanzattribute -- eine Unterklasse veraendert sie durch simples
    Ueberschreiben, ohne ``__init__`` anzufassen (siehe ``BgeM3Embedder``).

    ``model`` kann injiziert werden (Tests/alternative Backends); ohne
    Injektion wird das Backend beim ersten Encode lazy geladen.
    """

    #: Praefixe dieser Embedder-Klasse (Issue #732: konfigurierbar je
    #: Unterklasse statt hart auf die Modul-Konstanten verdrahtet).
    query_prefix: str = QUERY_PREFIX
    passage_prefix: str = PASSAGE_PREFIX

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        cache_dir: str | None = None,
        model: Any | None = None,
    ) -> None:
        self.model_id = model_id
        self.cache_dir = cache_dir if cache_dir is not None else default_cache_dir()
        self._model = model
        self._dim: int | None = None

    def load(self) -> Any:
        """Laedt das Backend-Modell (idempotent) und gibt es zurueck."""
        if self._model is None:
            self._model = _load_backend_model(self.model_id, self.cache_dir)
        return self._model

    @property
    def dim(self) -> int:
        """Dimension des GELADENEN Backends -- keine Annahme (Issue #629).

        Zuvor war das ein Klassenattribut mit dem Wert 384. Ein per
        ``VAULT_EMBEDDING_MODEL`` gesetztes 1024d-Modell (etwa
        ``intfloat/multilingual-e5-large`` oder ``BAAI/bge-m3``) blieb damit
        unbemerkt: der Vault bekam Vektoren, deren Breite nirgends zur
        deklarierten passte.

        Primaerquelle ist ``get_sentence_embedding_dimension()`` von
        sentence-transformers; liefert das Backend die Methode nicht (oder
        ``None``), wird die Dimension einmalig per Probe-Encode gemessen.
        Der Wert wird gecacht -- der Zugriff loest allerdings einen
        Modell-Load aus, ist also nichts fuer Latenz-kritische Pfade. Die
        Dimension eines BESTANDS kommt deshalb nie von hier, sondern aus
        ``embedding_meta`` (``VaultDB.expected_embedding_dim()``).
        """
        if self._dim is None:
            self._dim = self._probe_dim()
        return self._dim

    def _probe_dim(self) -> int:
        model = self.load()
        getter = getattr(model, "get_sentence_embedding_dimension", None)
        if callable(getter):
            reported = getter()
            if isinstance(reported, int) and reported > 0:
                return reported
        probe = model.encode([self.passage_prefix + "dimension probe"], normalize_embeddings=True)
        return len(list(probe[0]))

    def _encode(self, texts: list[str]) -> list[list[float]]:
        raw = self.load().encode(texts, normalize_embeddings=True)
        # Defensive Normalisierung: nicht jedes Backend haelt sich an
        # normalize_embeddings, und knn_chunks vergleicht per L2-Distanz —
        # die entspricht nur bei Einheitsvektoren der Kosinus-Rangfolge.
        return [l2_normalize(list(row)) for row in raw]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._encode([self.passage_prefix + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._encode([self.query_prefix + text])[0]


class BgeM3Embedder(E5SmallEmbedder):
    """Embedder fuer ``BAAI/bge-m3`` (Issue #732): kein Instruktions-Praefix.

    Nur das Prompting unterscheidet sich von :class:`E5SmallEmbedder` --
    Backend-Laden, Dimension-Probe und L2-Normalisierung sind identisch, daher
    Unterklasse statt Duplikat. Modellkarte von ``BAAI/bge-m3``: "the BGE-M3
    model no longer requires adding instructions to the queries" -- weder
    Query- noch Passage-Praefix. Ein aufgezwungenes ``passage: ``/``query: ``
    waere keine Betriebstreue, sondern eine falsch bediente Schnittstelle
    (gemessen in ``docs/evals/2026-08-08-embedding-candidates-731.md``, das
    denselben Kandidaten mit demselben Prompting-Prinzip fuehrt).
    """

    query_prefix = ""
    passage_prefix = ""


# Modell-IDs, die eine ANDERE Embedder-Klasse als die e5-Basisimplementierung
# brauchen -- bislang nur bge-m3 (#732). Ein per VAULT_EMBEDDING_MODEL
# gesetztes, hier nicht gelistetes Modell faellt auf E5SmallEmbedder zurueck;
# das war schon vor #732 so (jedes Nicht-e5-Modell bekam stillschweigend
# e5-Praefixe aufgezwungen) und wird durch diese Registrierung nur fuer den
# jetzt produktiven Default korrigiert, nicht generell geloest.
_EMBEDDER_CLASSES: dict[str, type["E5SmallEmbedder"]] = {
    "BAAI/bge-m3": BgeM3Embedder,
}


def embedder_for(
    model_id: str, cache_dir: str | None = None, model: Any | None = None
) -> "E5SmallEmbedder":
    """Baut den Embedder MIT DEM RICHTIGEN Prompting fuer ``model_id`` (#732).

    Reine Konstruktion ohne Laden, Caching oder Fehlerbehandlung -- das ist
    :func:`get_embedder`s Job. Diese Funktion existiert, damit Aufrufer, die
    einen Embedder fuer eine EXPLIZITE (ggf. nicht produktive) Modell-ID
    brauchen -- Eval-/Fixture-Skripte, die bewusst ein bestimmtes historisches
    Modell reproduzieren, etwa ``scripts/eval/build_retrieval_chunk_goldset.py``
    fuer #708/#722/#733s eingefrorenes ``intfloat/multilingual-e5-small`` --
    nicht mehr ``E5SmallEmbedder(...)`` direkt konstruieren muessen. Wer das
    tut, bekommt IMMER e5-Praefixe aufgezwungen, unabhaengig von der
    tatsaechlichen Modell-ID -- das war vor #732 folgenlos (nur e5-kompatible
    Modelle liefen produktiv), ist es seit dem bge-m3-Default nicht mehr:
    ``E5SmallEmbedder()`` ohne Argument nimmt sonst ``DEFAULT_MODEL_ID`` als
    Modell-ID (jetzt bge-m3) UND haengt trotzdem ``passage: ``/``query: `` an
    -- exakt die "falsch bediente Schnittstelle", die #731 und
    :class:`BgeM3Embedder` ausschliessen wollen.
    """
    embedder_cls = _EMBEDDER_CLASSES.get(model_id, E5SmallEmbedder)
    return embedder_cls(model_id=model_id, cache_dir=cache_dir, model=model)


# Cache pro Modell-ID: ``None`` bedeutet "Backend fehlt" und wird bewusst
# mitgecacht, damit nicht jeder add_paper-Aufruf erneut einen teuren
# Import-/Ladeversuch startet.
_EMBEDDER_CACHE: dict[str, Embedder | None] = {}

# Fehlerursache pro Modell-ID, parallel zu _EMBEDDER_CACHE gepflegt (Issue #624):
# vorher wurde die Exception nur geloggt, nie zurueckgegeben. ``None`` bedeutet
# "kein Fehler bekannt" -- entweder weil das Backend laedt, oder weil noch kein
# Ladeversuch stattfand.
_EMBEDDER_ERROR_CACHE: dict[str, str | None] = {}


def reset_embedder_cache() -> None:
    """Leert Embedder- und Fehlerursache-Cache (Tests, Modellwechsel zur Laufzeit)."""
    _EMBEDDER_CACHE.clear()
    _EMBEDDER_ERROR_CACHE.clear()


def get_embedder(model_id: str | None = None) -> Embedder | None:
    """Gibt den lokalen Embedder zurueck oder ``None``, wenn keiner nutzbar ist.

    ``None`` ist ein Degradations-, kein Absturzpfad: der Vault bleibt auch ohne
    nutzbares Backend vollstaendig bedienbar (FTS5-only). Der Grund landet im
    Log — eine dauerhaft leere ``chunk_embeddings``-Tabelle soll nicht wieder
    unbemerkt bleiben (#372).

    Der Schalter (:func:`resolve_embedding_enabled`, Issue #719) wertet DIESE
    Funktion nicht selbst aus -- gegated sind ihre AUFRUFER
    (``server._maybe_ingest_embeddings``, ``server._vec0_search``). Explizite
    Aufrufer (``embed_quote``, ``quote_context_similarity``,
    ``migrate.reindex_embeddings``) laden das Backend deshalb immer, auch bei
    abgeschaltetem Schalter -- wer sie aufruft, will das Modell laden.
    """
    key = model_id or os.environ.get(ENV_MODEL_ID) or DEFAULT_MODEL_ID
    if key in _EMBEDDER_CACHE:
        return _EMBEDDER_CACHE[key]

    embedder: Embedder | None
    try:
        candidate = embedder_for(key)
        candidate.load()
        embedder = candidate
        _EMBEDDER_ERROR_CACHE[key] = None
    except Exception as exc:
        # ImportError (Backend deinstalliert), OSError (kein Modell-Download
        # moeglich), RuntimeError (inkompatibles Backend) — gleicher Ausgang,
        # aber sichtbar: ohne Embedder faellt die Suche auf FTS5-only zurueck.
        logger.warning(
            "Embedding-Backend '%s' nicht nutzbar (%s: %s) — Vektor-Suche bleibt "
            "aus, vault.search laeuft FTS5-only.",
            key,
            type(exc).__name__,
            exc,
        )
        embedder = None
        # Reason gecacht neben dem Ergebnis (Issue #624): ein zweiter Aufruf im
        # selben Prozess trifft den Cache-Hit oben und laedt nicht erneut --
        # ohne diesen Cache waere die Fehlerursache nach dem ersten Aufruf
        # verloren, obwohl vault.component_status() sie braucht.
        _EMBEDDER_ERROR_CACHE[key] = f"{type(exc).__name__}: {exc}"

    _EMBEDDER_CACHE[key] = embedder
    return embedder


def get_embedder_error(model_id: str | None = None) -> str | None:
    """Fehlerursache des letzten ``get_embedder()``-Ladeversuchs fuer ``model_id``.

    ``None`` heisst: entweder laedt der Embedder erfolgreich, oder es gab noch
    keinen Ladeversuch (Cache leer) -- ``get_embedder()`` zuerst aufrufen, wenn
    der Ladeversuch garantiert stattgefunden haben soll (Issue #624,
    ``vault.component_status``).
    """
    key = model_id or os.environ.get(ENV_MODEL_ID) or DEFAULT_MODEL_ID
    return _EMBEDDER_ERROR_CACHE.get(key)
