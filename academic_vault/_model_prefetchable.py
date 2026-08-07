"""Geteilte Modellgroessen + Cache-Check fuer den Modell-Vorab-Download (#718).

Zwei Abnehmer:

* ``scripts/model_prefetch.py`` -- fragt einmal beim Setup, ob alle drei
  lokalen Modelle jetzt geladen werden sollen, und nennt dabei die Groesse.
* Die Lazy-Load-Pfade in ``embedding_model.py``, ``nli_prefilter.py`` und
  ``retrieval.py`` -- melden vor einem impliziten Download dieselbe Groesse
  (AC3), statt den Nutzer unangekuendigt warten zu lassen.

Bewusst ein eigenes, kleines Modul statt Code in einem der drei Backend-Module
unterzubringen: keines der drei darf von einem der anderen beiden abhaengen
(getrennte, optionale Backends -- ``sentence-transformers`` ist Pflicht,
``FlagEmbedding`` explizit nicht, siehe retrieval.py).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Downloadgroessen der Modellgewichte in Byte -- gemessen am 2026-08-07 ueber
# den Content-Length-Header von ``model.safetensors`` je HF-Repo (PR #718).
# Nur fuer die Nutzer-Meldung gedacht (Groessenordnung), keine Downstream-Logik
# haengt an der letzten Nachkommastelle.
#
# Weicht von der Tabelle in Issue #718 ab: die dortigen ~3,1 GB stammen aus
# der Peak-RSS-Messung mit dem damaligen NLI-Modell (mDeBERTa-v3-XNLI,
# 552 MB). Der NLI-Vorfilter wechselte mit #720 (nach Verfassen des Issues,
# vor dieser Implementierung) auf ``bge-m3-zeroshot-v2.0`` (~1,1 GB) --
# ``MDebertaScorer`` existiert weiterhin als Eval-Kandidat, ist aber nicht
# mehr der Default. Praefetcht wird hier der tatsaechliche Default
# (``nli_prefilter.MODEL_ID``), nicht der in der Issue-Tabelle genannte.
APPROX_BYTES: dict[str, int] = {
    "intfloat/multilingual-e5-small": 470_641_600,
    "BAAI/bge-reranker-v2-m3": 2_271_071_852,
    "MoritzLaurer/bge-m3-zeroshot-v2.0": 1_135_561_748,
}


def format_gb(total_bytes: int) -> str:
    """Formatiert Bytes als deutsche GB-Angabe, z. B. ``3_900_000_000 -> "3,9 GB"``."""
    return f"{total_bytes / 1_000_000_000:.1f} GB".replace(".", ",")


def is_cached(repo_id: str, cache_dir: str) -> bool:
    """True, wenn ein vollstaendiger Snapshot von ``repo_id`` lokal in ``cache_dir`` liegt.

    Nutzt ``local_files_only=True`` -- das erzwingt, dass ``huggingface_hub``
    keinen Netzzugriff versucht; ein unvollstaendiger/fehlender Cache liefert
    eine Exception (i.d.R. ``LocalEntryNotFoundError``), die hier bewusst
    breit gefangen wird -- der Rueckgabewert ist ein Bool, keine Diagnose.
    """
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(repo_id=repo_id, cache_dir=cache_dir, local_files_only=True)
        return True
    except Exception:
        return False


def notify_lazy_download(*, label: str, repo_id: str, cache_dir: str) -> None:
    """Meldet vor einem impliziten Download die erwartete Groesse (AC3, #718).

    Greift nur, wenn ``repo_id`` noch NICHT vollstaendig in ``cache_dir``
    liegt -- ein bereits gecachtes Modell laedt ohne Meldung (kein
    Netzzugriff mehr noetig). Schreibt sowohl einen Log-Eintrag (fuer
    Tests/Diagnose) als auch eine Konsolenzeile (fuer interaktive Laeufe).
    """
    if is_cached(repo_id, cache_dir):
        return
    size = APPROX_BYTES.get(repo_id)
    size_str = format_gb(size) if size is not None else "unbekannter Groesse"
    message = (
        f"{label} ('{repo_id}') ist noch nicht im lokalen Cache — Download von "
        f"~{size_str} beginnt jetzt (einmalig, danach aus {cache_dir})."
    )
    logger.info(message)
    print(f"⬇️  {message}")
