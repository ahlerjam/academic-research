"""Lokales Embedding-Modell fuer academic_vault (Issue #372).

Kapselt ``intfloat/multilingual-e5-small`` (MIT, 384 Dimensionen) hinter einem
schmalen ``Embedder``-Protokoll:

* ``embed_documents(texts)`` — Chunks fuer den Ingest (e5-Praefix ``passage: ``)
* ``embed_query(text)``      — Suchanfragen (e5-Praefix ``query: ``)

Beide Praefixe sind bei der e5-Familie kein Detail, sondern Teil des
Trainings-Setups: ohne sie sinkt die Retrieval-Qualitaet spuerbar.

Backend-Politik (bewusst): Das schwere Backend (``sentence-transformers`` inkl.
Torch, ~2,5 GB) ist **keine** harte Dependency des Plugins. Es wird erst beim
ersten ``get_embedder()``-Aufruf lazy importiert; fehlt es, liefert
``get_embedder()`` ``None`` und der Vault laeuft unveraendert im FTS5-only-Modus
weiter (keine Exception, kein Funktionsverlust ausserhalb der Vektor-Suche).
Installation des Backends: ``pip install sentence-transformers`` (siehe README
und scripts/requirements.txt).
"""

import math
import os
import struct
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# Dimensionalitaet von intfloat/multilingual-e5-small. Muss mit der vec0-Tabelle
# chunk_vectors (FLOAT[384]) und quote_embeddings uebereinstimmen.
EMBEDDING_DIM = 384

DEFAULT_MODEL_ID = "intfloat/multilingual-e5-small"

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

    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Vektorisiert Chunks (Passage-Seite des asymmetrischen Retrievals)."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Vektorisiert eine Suchanfrage (Query-Seite)."""
        ...


def _load_backend_model(model_id: str, cache_dir: str | None = None) -> Any:
    """Laedt das sentence-transformers-Backend. Wirft ImportError ohne Extra.

    Separate Funktion, damit Tests das Fehlen des Backends deterministisch
    simulieren koennen, ohne echte Modellgewichte zu laden.
    """
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_id, cache_folder=cache_dir)


class E5SmallEmbedder:
    """Embedder auf Basis von ``intfloat/multilingual-e5-small``.

    ``model`` kann injiziert werden (Tests/alternative Backends); ohne
    Injektion wird das Backend beim ersten Encode lazy geladen.
    """

    dim = EMBEDDING_DIM

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        cache_dir: str | None = None,
        model: Any | None = None,
    ) -> None:
        self.model_id = model_id
        self.cache_dir = cache_dir if cache_dir is not None else default_cache_dir()
        self._model = model

    def load(self) -> Any:
        """Laedt das Backend-Modell (idempotent) und gibt es zurueck."""
        if self._model is None:
            self._model = _load_backend_model(self.model_id, self.cache_dir)
        return self._model

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

    ``None`` ist ein regulaerer Rueckgabewert, kein Fehlerfall: ohne
    installiertes Backend bleibt der Vault vollstaendig nutzbar (FTS5-only).
    """
    key = model_id or os.environ.get(ENV_MODEL_ID) or DEFAULT_MODEL_ID
    if key in _EMBEDDER_CACHE:
        return _EMBEDDER_CACHE[key]

    embedder: Embedder | None
    try:
        candidate = E5SmallEmbedder(model_id=key)
        candidate.load()
        embedder = candidate
    except Exception:
        # ImportError (Extra fehlt), OSError (kein Modell-Download moeglich),
        # RuntimeError (inkompatibles Backend) — alles derselbe Ausgang.
        embedder = None

    _EMBEDDER_CACHE[key] = embedder
    return embedder
