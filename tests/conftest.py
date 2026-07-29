"""Zentrale pytest-Fixtures fuer die academic-research-Testsuite (Issue #183).

Bisher hatte tests/ kein conftest.py; haeufig genutzte Bausteine (Repo-Root bzw.
scripts/ auf sys.path, temporaere Vault-DB, browser-use-Mock, Beispiel-PDF, TUM-
Bibliotheksprofil) waren in Dutzenden einzelnen test_*.py dupliziert. Diese Datei
zentralisiert sie.

sys.path-Setup: pytest haengt das Repo-Root ohnehin ueber die "rootdir"-Erkennung
an sys.path (tests/ ist ein Package mit __init__.py), Repo-Root-Importe wie
`academic_vault` oder `scripts` (als Package) funktionieren daher bereits ohne
Zutun. Viele Tests importieren jedoch einzelne Module aus scripts/ direkt als
Top-Level-Modul (z.B. `from dedup import deduplicate`), was zusaetzlich
`scripts/` selbst auf sys.path erfordert -- das haben zuvor ~36 test_*.py-Dateien
einzeln per sys.path.insert(...) erledigt. Dieser Block deckt beide Faelle zentral
ab, damit die pro-Datei-Duplikate ersatzlos entfallen koennen.

Skill-spezifische scripts/-Pfade (z.B. skills/<name>/scripts) sind bewusst NICHT
Teil dieses zentralen Setups -- sie bleiben in den jeweiligen test_*.py, da sie
keine generischen Duplikate sind.

Bereitgestellte Fixtures:
  - temp_vault_db        Pfad auf eine frisch initialisierte SQLite-Vault-DB
  - mock_browser_use     MagicMock als Ersatz fuer browser-use-Aufrufe
  - sample_pdf           Pfad auf tests/fixtures/sample_book.pdf
  - library_profile_tum  geparstes config/library-profiles/tum.yaml als dict
  - fake_embedder        deterministischer Offline-Embedder (384d, kein Modell-Download)

Autouse-Fixtures (kein expliziter Import noetig, greifen automatisch):
  - block_real_embedding_backend        blockt echtes e5-Embedding-Modell (#372)
  - block_real_local_reranker_backend   blockt echtes bge-reranker-v2-m3-Modell (#376)
"""

import hashlib
import math
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Pfade: Repo-Root UND Repo-Root/scripts auf sys.path, damit sowohl
# `academic_vault`/`scripts` (als Package) als auch einzelne Top-Level-Module
# aus scripts/ (z.B. `import dedup`) importierbar sind. Dieser Block war zuvor
# in ~36 test_*.py dupliziert (mit unterschiedlichen Varianten).
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

for _p in (REPO_ROOT, SCRIPTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

FIXTURES_DIR = Path(__file__).parent / "fixtures"
LIBRARY_PROFILES_DIR = REPO_ROOT / "config" / "library-profiles"


# ---------------------------------------------------------------------------
# Vault-DB
# ---------------------------------------------------------------------------
@pytest.fixture
def temp_vault_db(tmp_path):
    """Frisch initialisierte SQLite-Vault-DB in einem Tempdir.

    Liefert den Pfad (str) auf die DB-Datei mit bereits ausgefuehrtem
    `init_schema()`. Faellt auf ein nacktes sqlite-Setup zurueck, falls
    `academic_vault.db` (noch) nicht importierbar ist, damit Tests, die nur
    eine leere DB-Datei brauchen, die Fixture trotzdem nutzen koennen.
    """
    db_path = tmp_path / "vault.db"
    try:
        from academic_vault.db import VaultDB
    except Exception:
        # Fallback: leere DB-Datei ohne Schema (z.B. wenn sqlite-Extensions fehlen)
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        conn.close()
        return str(db_path)

    db = VaultDB(str(db_path))
    db.init_schema()
    return str(db_path)


# ---------------------------------------------------------------------------
# Embedder-Stub (Issue #372)
# ---------------------------------------------------------------------------
class DeterministicEmbedder:
    """Offline-Stand-in fuer ``intfloat/multilingual-e5-small`` (384d).

    Hashing-Bag-of-Words statt neuronalem Modell: gleiche Tokens ergeben
    gleiche Achsen, das Ergebnis ist L2-normalisiert. Damit verhaelt sich der
    Vektorraum lexikalisch-semantisch genug fuer Retrieval-Tests, ohne dass ein
    Modell heruntergeladen werden muss (CI bleibt hermetisch und offline).
    """

    dim = 384

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in re.findall(r"\w+", text.lower()):
            idx = int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:8], 16) % self.dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


@pytest.fixture
def fake_embedder():
    """Deterministischer 384d-Embedder ohne Netzwerk/Modell-Download (#372)."""
    return DeterministicEmbedder()


@pytest.fixture(autouse=True)
def block_real_embedding_backend(monkeypatch):
    """Verhindert, dass die Suite echte e5-Artefakte laedt (#372, #374).

    Blockiert zwei Ladepfade: die Modellgewichte (``_load_backend_model``, #372)
    und den Tokenizer, den das Chunking fuer exakte Tokenbudgets nutzt
    (``chunking._load_tokenizer``, #374). Ohne den zweiten Guard zoege jeder
    ``chunk_pages``-Aufruf Tokenizer-Dateien von HuggingFace; das Chunking
    faellt stattdessen auf ``approximate_token_count`` zurueck.

    ``sentence-transformers`` ist seit #372 eine harte Dependency, also laeuft
    ``get_embedder()`` in der CI nicht mehr in einen ImportError. Ohne diesen
    Guard wuerde jeder ``add_paper``-Aufruf der Suite ``multilingual-e5-small``
    (~470 MB) von HuggingFace ziehen — die Suite waere netzabhaengig und um
    Groessenordnungen langsamer.

    Gepatcht wird bewusst nur ``_load_backend_model`` (die unterste Schicht):
    Tests, die ihren Embedder ueber ``get_embedder`` bzw. die Parameter von
    ``ingest_paper_embeddings`` injizieren, bleiben unberuehrt, und der
    Degradations-Pfad (``get_embedder() is None``) wird realistisch geprobt.

    Ausnahme: mit ``VAULT_E5_LIVE_TEST=1`` greift der Guard nicht — das ist das
    bestehende Gate des Live-Tests gegen das echte Modell.
    """
    import os

    if os.environ.get("VAULT_E5_LIVE_TEST") == "1":
        yield
        return

    try:
        import academic_vault.embedding_model as em
    except Exception:
        yield
        return

    def _blocked(*_args, **_kwargs):
        raise RuntimeError(
            "Embedding-Backend im Testlauf blockiert (tests/conftest.py). "
            "Tests injizieren den fake_embedder; fuer das echte Modell "
            "VAULT_E5_LIVE_TEST=1 setzen."
        )

    monkeypatch.setattr(em, "_load_backend_model", _blocked)
    em.reset_embedder_cache()

    try:
        import academic_vault.chunking as chunking
    except Exception:
        chunking = None
    if chunking is not None:
        monkeypatch.setattr(chunking, "_load_tokenizer", _blocked)
        chunking.reset_token_counter_cache()

    try:
        yield
    finally:
        em.reset_embedder_cache()
        if chunking is not None:
            chunking.reset_token_counter_cache()


# ---------------------------------------------------------------------------
# Lokaler Reranker-Backend-Guard (Issue #376)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def block_real_local_reranker_backend(monkeypatch):
    """Verhindert, dass die Suite das echte bge-reranker-v2-m3-Modell laedt (#376).

    Seit #376 ruft ``search_papers(..., rerank=True)`` ``apply_reranker`` immer
    auf -- auch ohne Cloud-API-Keys. Ohne diesen Guard wuerde jeder derartige
    Testaufruf versuchen, ``BAAI/bge-reranker-v2-m3`` (FlagEmbedding-Backend)
    von HuggingFace zu laden, sobald FlagEmbedding manuell installiert ist
    (kein uv-Extra, vgl. pyproject.toml) -- die Suite waere netzabhaengig und
    um Groessenordnungen langsamer.

    Analog ``block_real_embedding_backend``: gepatcht wird bewusst nur
    ``_load_local_reranker_backend`` (die unterste Schicht), Tests, die den
    lokalen Reranker ueber ``_get_local_reranker`` mocken, bleiben unberuehrt.

    Ausnahme: mit ``VAULT_RERANK_LOCAL_LIVE_TEST=1`` greift der Guard nicht —
    das ist das bestehende Gate des Live-Tests gegen das echte Modell.
    """
    import os

    if os.environ.get("VAULT_RERANK_LOCAL_LIVE_TEST") == "1":
        yield
        return

    try:
        import academic_vault.retrieval as retrieval
    except Exception:
        yield
        return

    def _blocked(*_args, **_kwargs):
        raise RuntimeError(
            "Lokaler Reranker im Testlauf blockiert (tests/conftest.py). Tests "
            "mocken _get_local_reranker; fuer das echte Modell "
            "VAULT_RERANK_LOCAL_LIVE_TEST=1 setzen."
        )

    monkeypatch.setattr(retrieval, "_load_local_reranker_backend", _blocked)
    retrieval.reset_local_reranker_cache()
    try:
        yield
    finally:
        retrieval.reset_local_reranker_cache()


# ---------------------------------------------------------------------------
# browser-use-Mock
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_browser_use():
    """MagicMock als Ersatz fuer browser-use-Interaktionen.

    Verhindert echte Browser-Automation in Unit-Tests. `.run(...)` liefert
    standardmaessig einen leeren Erfolgs-String; einzelne Tests koennen
    Rueckgabewerte/Seiteneffekte ueber den Mock konfigurieren.
    """
    mock = MagicMock(name="browser_use")
    mock.run.return_value = ""
    mock.navigate.return_value = ""
    mock.extract.return_value = {}
    return mock


# ---------------------------------------------------------------------------
# Beispiel-PDF
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_pdf():
    """Pfad auf eine kleine, echte Beispiel-PDF (tests/fixtures/sample_book.pdf)."""
    pdf_path = FIXTURES_DIR / "sample_book.pdf"
    if not pdf_path.is_file():
        pytest.skip(f"Beispiel-PDF fehlt: {pdf_path}")
    return pdf_path


# ---------------------------------------------------------------------------
# Bibliotheksprofil TUM
# ---------------------------------------------------------------------------
@pytest.fixture
def library_profile_tum():
    """Geparstes TUM-Bibliotheksprofil (config/library-profiles/tum.yaml) als dict."""
    import yaml

    profile_path = LIBRARY_PROFILES_DIR / "tum.yaml"
    if not profile_path.is_file():
        pytest.skip(f"TUM-Profil fehlt: {profile_path}")
    with open(profile_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)
