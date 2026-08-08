"""Modell-Vorab-Download beim Setup (Issue #718).

``scripts/setup.sh`` ruft dieses Skript einmal auf und fragt, ob alle drei
lokalen Modelle (Embedding, Reranker, NLI-Zitatscan) jetzt vollstaendig
geladen werden sollen, statt den ersten Download unangekuendigt mitten in
einer Suche oder einem Kapitel-Write auszuloesen (siehe Issue-Begruendung).

Downloadmechanik bewusst ueber ``huggingface_hub.snapshot_download`` je
Modell-Repo -- NICHT ueber die jeweiligen Backend-Klassen
(``SentenceTransformer``/``AutoModel...``/``CrossEncoder``): das ist die
einzige Stelle, die fuer alle drei Modelle Fortschritt + Resume beherrscht,
ohne ``sentence-transformers``/``transformers`` zwingend zu instanziieren.
``huggingface_hub`` liegt bereits transitiv vor (Dependency von
``sentence-transformers``).

Fortsetzen nach Abbruch (AC4) braucht keinen eigenen Code, aber es setzt
NICHT an der Abbruchstelle einer einzelnen Datei an -- die Grenze ist die
DATEI, nicht das Byte:

* Ein bereits vollstaendiges Modell wird hier per ``is_cached`` uebersprungen.
* Innerhalb eines angefangenen Modells liegen die fertigen Dateien im
  Blob-Cache; ``snapshot_download`` laedt sie nicht erneut.
* Die eine Datei, die beim Abbruch in Uebertragung war, beginnt von vorn:
  ``huggingface_hub`` schreibt sie seit
  https://github.com/huggingface/huggingface_hub/pull/4228 in eine
  PROZESS-EIGENE ``<etag>.<uuid>.incomplete``-Datei (Schutz gegen Dateisysteme,
  auf denen ``flock`` nicht greift) und kann deren Zwischenstand danach nicht
  mehr zuordnen.

Belegt an einem echten, hart abgebrochenen und danach wiederholten Lauf:
``tests/test_issue_718_model_prefetch.py::TestResume``.

Ein zweiter Aufruf gegen einen bereits VOLLSTAENDIGEN Cache macht KEINEN
Netzzugriff (siehe ``is_cached`` unten): das ist zugleich die
Idempotenz-Grundlage fuer AC1 ("genau einmal fragen") -- ist bereits alles
gecacht, wird gar nicht erst gefragt.

Sicherer Default bei nicht-interaktivem stdin (CI, ``/setup``-Aufruf durch
Claude Code): KEIN Download, analog ``scihub_optin.py``/``uni_profile_setup.py``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# scripts/setup.sh ruft dieses Skript per "$BASE/venv/bin/python
# $SCRIPT_DIR/model_prefetch.py" auf -- diese venv hat NUR
# scripts/requirements.txt installiert, academic_vault selbst nicht (kein
# "pip install -e ."; die MCP-Server-Variante bekommt PYTHONPATH stattdessen
# per .mcp.json gesetzt). Repo-Root deshalb explizit vorn in sys.path, sonst
# schlaegt der Import unten je nach Aufrufkontext fehl.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from academic_vault import embedding_model, nli_prefilter, retrieval  # noqa: E402
from academic_vault._model_prefetchable import (  # noqa: E402
    APPROX_BYTES,
    format_gb,
    is_cached,
)


@dataclass(frozen=True)
class ModelSpec:
    label: str
    repo_id: str
    cache_dir: str


def build_model_specs() -> list[ModelSpec]:
    """Die drei lokalen Modelle mit ihrem jeweils TATSAECHLICH gelesenen Cache-Ziel.

    Reihenfolge/Quelle bewusst aus den Produktionsmodulen bezogen statt hier
    dupliziert -- ein Modellwechsel (wie #720: mDeBERTa -> bge-m3-zeroshot fuer
    den NLI-Vorfilter) wird dadurch automatisch mitgezogen, ohne dieses Skript
    anzufassen.
    """
    return [
        ModelSpec(
            label="Embedding (bge-m3)",
            repo_id=embedding_model.DEFAULT_MODEL_ID,
            cache_dir=embedding_model.default_cache_dir(),
        ),
        ModelSpec(
            label="Reranker (bge-reranker-v2-m3)",
            repo_id=retrieval.LOCAL_RERANKER_MODEL_ID,
            cache_dir=retrieval.default_cache_dir(),
        ),
        ModelSpec(
            label="NLI-Zitatscan (bge-m3-zeroshot-v2.0)",
            repo_id=nli_prefilter.MODEL_ID,
            cache_dir=nli_prefilter.default_cache_dir(),
        ),
    ]


def total_download_bytes(specs: list[ModelSpec]) -> int:
    """Summe der bekannten Downloadgroessen (unbekannte Modelle zaehlen 0)."""
    return sum(APPROX_BYTES.get(spec.repo_id, 0) for spec in specs)


def all_cached(specs: list[ModelSpec]) -> bool:
    """True, wenn alle drei Modelle bereits vollstaendig lokal vorliegen."""
    return all(is_cached(spec.repo_id, spec.cache_dir) for spec in specs)


def _prompt_prefetch(specs: list[ModelSpec]) -> bool:
    """Interaktive Vorab-Download-Frage. Bei nicht-interaktivem stdin: sicherer Default ``False``."""
    if not sys.stdin.isatty():
        return False
    total = format_gb(total_download_bytes(specs))
    prompt = (
        f"Alle drei lokalen Modelle jetzt herunterladen (~{total} gesamt)?\n"
        "Ohne Vorab-Download laedt jedes Modell beim ersten Gebrauch nach "
        "(mit Hinweis auf die Downloadgroesse). [j/N] "
    )
    answer = input(prompt).strip().lower()
    return answer in ("j", "ja", "y", "yes")


def download_model(spec: ModelSpec) -> str:
    """Laedt die noch fehlenden Dateien eines Modells (siehe Modul-Docstring, AC4)."""
    from huggingface_hub import snapshot_download

    return snapshot_download(repo_id=spec.repo_id, cache_dir=spec.cache_dir)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    specs = build_model_specs()

    if all_cached(specs):
        print("✅ Alle drei Modelle bereits vollstaendig im Cache — kein Download noetig.")
        return 0

    if "--yes" in args or "-y" in args:
        proceed = True
    elif "--no" in args:
        proceed = False
    else:
        proceed = _prompt_prefetch(specs)

    if not proceed:
        total = format_gb(total_download_bytes(specs))
        print(
            f"ℹ️  Modell-Download uebersprungen (~{total} gesamt) — Modelle werden beim "
            "ersten Gebrauch einzeln nachgeladen, jeweils mit vorheriger Groessen-Meldung."
        )
        return 0

    for spec in specs:
        if is_cached(spec.repo_id, spec.cache_dir):
            print(f"✅ {spec.label}: bereits im Cache.")
            continue
        print(f"⬇️  Lade {spec.label} ({spec.repo_id}) …")
        download_model(spec)
        print(f"✅ {spec.label}: geladen.")

    print("✅ Alle drei Modelle im Cache — ein anschliessender Such-/Scan-Lauf laedt nicht erneut.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
