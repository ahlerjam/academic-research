"""Lokales Embedding-Modell fuer academic_vault (Issue #372).

Kapselt ``intfloat/multilingual-e5-small`` (MIT, 384 Dimensionen) hinter einem
schmalen ``Embedder``-Protokoll:

* ``embed_documents(texts)`` — Chunks fuer den Ingest (e5-Praefix ``passage: ``)
* ``embed_query(text)``      — Suchanfragen (e5-Praefix ``query: ``)

Beide Praefixe sind bei der e5-Familie kein Detail, sondern Teil des
Trainings-Setups: ohne sie sinkt die Retrieval-Qualitaet spuerbar.

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

Das Modell selbst (~470 MB) wird beim ersten Gebrauch nach
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

# Dimensionalitaet von intfloat/multilingual-e5-small und damit die Breite, in
# der ein FRISCHER Vault seine vec0-Tabellen anlegt (Issue #629). Bewusst KEINE
# Aussage mehr ueber "die" Embedding-Dimension: die eines Bestands steht in
# ``embedding_meta`` (siehe schema.sql), die eines Modells liefert der Embedder
# selbst (``Embedder.dim``). Wer hier wieder eine globale Konstante hineinliest,
# baut den Fehler aus #629 nach.
DEFAULT_EMBEDDING_DIM = 384

DEFAULT_MODEL_ID = "intfloat/multilingual-e5-small"

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

    return SentenceTransformer(model_id, cache_folder=cache_dir)


class E5SmallEmbedder:
    """Embedder auf Basis von ``intfloat/multilingual-e5-small``.

    ``model`` kann injiziert werden (Tests/alternative Backends); ohne
    Injektion wird das Backend beim ersten Encode lazy geladen.
    """

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
        probe = model.encode([PASSAGE_PREFIX + "dimension probe"], normalize_embeddings=True)
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
        return self._encode([PASSAGE_PREFIX + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._encode([QUERY_PREFIX + text])[0]


# Cache pro Modell-ID: ``None`` bedeutet "Backend fehlt" und wird bewusst
# mitgecacht, damit nicht jeder add_paper-Aufruf erneut einen teuren
# Import-/Ladeversuch startet.
_EMBEDDER_CACHE: dict[str, Embedder | None] = {}


def reset_embedder_cache() -> None:
    """Leert den Embedder-Cache (Tests, Modellwechsel zur Laufzeit)."""
    _EMBEDDER_CACHE.clear()


def get_embedder(model_id: str | None = None) -> Embedder | None:
    """Gibt den lokalen Embedder zurueck oder ``None``, wenn keiner nutzbar ist.

    ``None`` ist ein Degradations-, kein Absturzpfad: der Vault bleibt auch ohne
    nutzbares Backend vollstaendig bedienbar (FTS5-only). Der Grund landet im
    Log — eine dauerhaft leere ``chunk_embeddings``-Tabelle soll nicht wieder
    unbemerkt bleiben (#372).
    """
    key = model_id or os.environ.get(ENV_MODEL_ID) or DEFAULT_MODEL_ID
    if key in _EMBEDDER_CACHE:
        return _EMBEDDER_CACHE[key]

    embedder: Embedder | None
    try:
        candidate = E5SmallEmbedder(model_id=key)
        candidate.load()
        embedder = candidate
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

    _EMBEDDER_CACHE[key] = embedder
    return embedder
