#!/usr/bin/env python3
"""Active Learning für das Titel-/Abstract-Screening (Issue #602).

Aus den bereits gefällten Ein-/Ausschluss-Urteilen wird ein kleiner
Klassifikator trainiert, der die **noch offene Restliste umsortiert**: was
wahrscheinlich relevant ist, kommt nach vorn. Das Verfahren stammt aus
ASReview; übernommen ist die Idee, nicht das Paket.

Was dieses Modul **nicht** tut, und zwar mit Absicht:

- Es entscheidet nichts. Kein Ein- oder Ausschluss, keine Empfehlung.
- Es kürzt nichts. Die Rückgabe ist stets eine Permutation der Eingabe —
  gleiche Menge, gleiche Länge. Umsortiert, nicht gefiltert.
- Es bricht nichts ab. Wann genug gescreent ist, entscheidet ein Mensch am
  Fortschrittsbericht; eine Quelle, die niemand angesehen hat, weil ein Modell
  sie für unwichtig hielt, ist ein methodischer Schaden.

Alles läuft lokal: reine Standardbibliothek, kein Netzzugriff, kein Schlüssel.
Der Klassifikator ist eine multinomiale Naive-Bayes-Variante mit
Laplace-Glättung über Titel + Abstract — bewusst das einfachste Verfahren, das
die Aufgabe erfüllt.

Buchführung: ``$SESSION_DIR/active_learning_log.jsonl``, append-only, eine
Zeile je Umsortierung. Sie beantwortet „welche Reihenfolge galt ab wann, auf
welcher Trainingsgrundlage".

CLI:
  python active_learning.py rank --session-dir DIR --papers papers.json --ids a,b,c
  python active_learning.py progress --session-dir DIR --ids a,b,c
  python active_learning.py validate --gold gold_screening.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from screening_ledger import (  # noqa: E402
    STAGE_SCREENING,
    merge,
    merge_double,
    read_ledger,
    resolve_double_screening,
)

# ---------------------------------------------------------------------------
# Verträge
# ---------------------------------------------------------------------------

LOG_FILENAME = "active_learning_log.jsonl"

#: Kennung der Trainingsgrundlage im Protokoll. Wechselt das Verfahren, wechselt
#: die Kennung — sonst behaupten alte und neue Zeilen dasselbe.
MODEL_ID = "multinomial-nb/laplace/1"

ACTIVE_LEARNING_ENV = "ACADEMIC_RESEARCH_ACTIVE_LEARNING"
RETRAIN_INTERVAL_ENV = "ACADEMIC_RESEARCH_ACTIVE_LEARNING_INTERVAL"
BLOCK_SIZE_ENV = "ACADEMIC_RESEARCH_ACTIVE_LEARNING_BLOCK"

#: Opt-in. Anders als das Doppel-Screening (#598) folgt Active Learning keiner
#: methodischen Pflicht — ein Default-on würde jeden bestehenden Screening-Lauf
#: still umsortieren.
DEFAULT_ACTIVE_LEARNING = False

#: Nachtrainiert wird in Intervallen, nicht nach jedem einzelnen Urteil.
DEFAULT_RETRAIN_INTERVAL = 10

#: Abschnittsgröße der Fortschrittsanzeige (Trefferausbeute je Block).
DEFAULT_BLOCK_SIZE = 25

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "parallel_agents.json"

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}

#: Labels, die als Trainingsbeispiel taugen. ``unclear`` und ``dissent`` sind
#: keine Urteile, sondern offene Fragen — sie trainieren nichts.
TRAINING_LABELS = ("include", "exclude")


def _config_value(config_path: str | Path | None, key: str) -> Any:
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data[key]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def resolve_active_learning(
    explicit: bool | None = None,
    config_path: str | Path | None = None,
) -> bool:
    """Schalter für Active Learning.

    Vorrang: Argument > Env ``ACADEMIC_RESEARCH_ACTIVE_LEARNING`` > Config-Datei
    > Default ``False``. Bei ``False`` verhält sich das Screening exakt wie ohne
    dieses Feature: keine Umsortierung, kein Protokoll, kein Fortschrittsbericht.
    """
    if explicit is not None:
        return bool(explicit)

    raw_env = os.environ.get(ACTIVE_LEARNING_ENV)
    if raw_env is not None:
        stripped = raw_env.strip().lower()
        if stripped in _TRUTHY:
            return True
        if stripped in _FALSY:
            return False

    value = _config_value(config_path, "active_learning")
    if isinstance(value, bool):
        return value

    return DEFAULT_ACTIVE_LEARNING


def _resolve_positive_int(
    explicit: int | None,
    env_name: str,
    config_path: str | Path | None,
    config_key: str,
    default: int,
) -> int:
    if explicit is not None:
        value = int(explicit)
        if value < 1:
            raise ValueError(f"{config_key} muss >= 1 sein, war {explicit}")
        return value

    raw_env = os.environ.get(env_name)
    if raw_env is not None:
        try:
            value = int(str(raw_env).strip())
        except ValueError:
            value = 0
        if value >= 1:
            return value

    raw_config = _config_value(config_path, config_key)
    try:
        value = int(raw_config)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        value = 0
    if value >= 1:
        return value

    return default


def resolve_retrain_interval(
    explicit: int | None = None,
    config_path: str | Path | None = None,
) -> int:
    """Zahl der Urteile zwischen zwei Nachtrainings.

    Vorrang: Argument > Env ``ACADEMIC_RESEARCH_ACTIVE_LEARNING_INTERVAL`` >
    Config-Datei > Default ``10``.
    """
    return _resolve_positive_int(
        explicit,
        RETRAIN_INTERVAL_ENV,
        config_path,
        "active_learning_retrain_interval",
        DEFAULT_RETRAIN_INTERVAL,
    )


def resolve_block_size(
    explicit: int | None = None,
    config_path: str | Path | None = None,
) -> int:
    """Abschnittsgröße der Fortschrittsanzeige.

    Vorrang: Argument > Env ``ACADEMIC_RESEARCH_ACTIVE_LEARNING_BLOCK`` >
    Config-Datei > Default ``25``.
    """
    return _resolve_positive_int(
        explicit,
        BLOCK_SIZE_ENV,
        config_path,
        "active_learning_block_size",
        DEFAULT_BLOCK_SIZE,
    )


# ---------------------------------------------------------------------------
# Klassifikator — multinomiale Naive Bayes, reine Standardbibliothek
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

#: Minimalliste. Sie soll den häufigsten Funktionswortballast wegnehmen, nicht
#: den Wortschatz kuratieren — jede Streichung ist eine Vorannahme darüber, was
#: relevant sein darf.
STOPWORDS = frozenset(
    {
        "aber",
        "auch",
        "auf",
        "aus",
        "bei",
        "dem",
        "den",
        "der",
        "des",
        "die",
        "das",
        "dass",
        "ein",
        "eine",
        "einem",
        "einen",
        "einer",
        "eines",
        "für",
        "fuer",
        "hat",
        "ist",
        "mit",
        "nach",
        "nicht",
        "oder",
        "sich",
        "sind",
        "und",
        "von",
        "vom",
        "vor",
        "wie",
        "wird",
        "werden",
        "zum",
        "zur",
        "über",
        "ueber",
        "and",
        "are",
        "for",
        "the",
        "this",
        "was",
        "were",
        "with",
    }
)

MIN_TOKEN_LENGTH = 3


def tokenize(text: str) -> list[str]:
    """Zerlegt Text in kleingeschriebene Worttoken (unicode-fähig, ohne Ziffern)."""
    return [
        token
        for token in (match.group(0).lower() for match in _TOKEN_RE.finditer(text or ""))
        if len(token) >= MIN_TOKEN_LENGTH and token not in STOPWORDS
    ]


def paper_text(record: dict[str, Any] | None) -> str:
    """Titel + Abstract eines Treffers als ein Textfeld."""
    if not record:
        return ""
    title = str(record.get("title") or "")
    abstract = str(record.get("abstract") or "")
    return f"{title} {abstract}".strip()


class NaiveBayesRanker:
    """Multinomiale Naive Bayes mit Laplace-Glättung über ``include``/``exclude``.

    Bewusst das einfachste Verfahren, das die Aufgabe erfüllt: kein Embedding,
    kein neuronales Modell, keine externe Abhängigkeit. Wer belegt, dass es
    nicht reicht, hat das Argument für den nächsten Schritt.
    """

    def __init__(self) -> None:
        self.token_counts: dict[str, dict[str, int]] = {label: {} for label in TRAINING_LABELS}
        self.total_tokens: dict[str, int] = dict.fromkeys(TRAINING_LABELS, 0)
        self.doc_counts: dict[str, int] = dict.fromkeys(TRAINING_LABELS, 0)
        self.vocabulary: set[str] = set()

    @property
    def is_trained(self) -> bool:
        """Beide Klassen belegt? Sonst sind alle Bewertungen konstant."""
        return all(self.doc_counts[label] > 0 for label in TRAINING_LABELS)

    def train(self, documents: list[tuple[str, str]]) -> NaiveBayesRanker:
        """Trainiert aus ``(label, text)``-Paaren. Reihenfolgeunabhängig."""
        for label, text in documents:
            if label not in TRAINING_LABELS:
                continue
            tokens = tokenize(text)
            if not tokens:
                continue
            self.doc_counts[label] += 1
            counts = self.token_counts[label]
            for token in tokens:
                counts[token] = counts.get(token, 0) + 1
                self.total_tokens[label] += 1
                self.vocabulary.add(token)
        return self

    def score(self, text: str) -> float:
        """Log-Wahrscheinlichkeitsverhältnis ``include`` gegen ``exclude``.

        Höher heißt „wahrscheinlicher relevant". Unbekannte Token tragen nichts
        bei — sie sagen über beide Klassen dasselbe.
        """
        if not self.is_trained:
            return 0.0
        vocab_size = len(self.vocabulary) or 1
        n_docs = sum(self.doc_counts[label] for label in TRAINING_LABELS)
        result = math.log(self.doc_counts["include"] / n_docs) - math.log(
            self.doc_counts["exclude"] / n_docs
        )
        for token in tokenize(text):
            if token not in self.vocabulary:
                continue
            p_include = (self.token_counts["include"].get(token, 0) + 1) / (
                self.total_tokens["include"] + vocab_size
            )
            p_exclude = (self.token_counts["exclude"].get(token, 0) + 1) / (
                self.total_tokens["exclude"] + vocab_size
            )
            result += math.log(p_include) - math.log(p_exclude)
        return result


# ---------------------------------------------------------------------------
# Trainingsgrundlage aus dem Ledger
# ---------------------------------------------------------------------------


def training_labels(
    session_dir: str | Path,
    stage: str = STAGE_SCREENING,
    double: bool | None = None,
    config_path: str | Path | None = None,
) -> dict[str, str]:
    """Die bereits gefällten Urteile als ``{paper_id: include|exclude}``.

    Bei aktivem Doppel-Screening (#598) zählen die **konsolidierten** Urteile
    aus ``merge_double`` (inklusive menschlicher Auflösungen), sonst die aus
    ``merge``. ``unclear`` und ``dissent`` sind keine Trainingsbeispiele: sie
    sind offene Fragen, keine Entscheidungen.
    """
    if double is None:
        double = resolve_double_screening(config_path=config_path)
    buckets = merge_double(session_dir, stage=stage) if double else merge(session_dir, stage=stage)
    labels: dict[str, str] = {}
    for label in TRAINING_LABELS:
        for paper_id in buckets.get(label, []):
            labels[paper_id] = label
    return labels


def _order_by_labels(
    pending_ids: list[str],
    papers: dict[str, dict[str, Any]],
    labels: dict[str, str],
) -> tuple[list[str], dict[str, Any] | None]:
    """Kern der Umsortierung. Liefert ``(reihenfolge, meta)``.

    ``meta is None`` heißt: nicht umsortiert. Das passiert, wenn eine der beiden
    Klassen fehlt (dann liefert der Klassifikator konstante Werte und würde die
    Liste still permutieren) oder wenn zu keinem offenen Fall Text vorliegt.

    Die Rückgabe ist immer eine Permutation von ``pending_ids``: gleiche Menge,
    gleiche Länge, keine Duplikate. Fälle ohne Text behalten ihre
    **Ursprungsposition** — fehlender Text ist kein Argument gegen eine Quelle.
    """
    ids = list(pending_ids)
    documents = [
        (label, paper_text(papers.get(paper_id)))
        for paper_id, label in labels.items()
        if paper_text(papers.get(paper_id))
    ]
    ranker = NaiveBayesRanker().train(documents)
    if not ranker.is_trained:
        return ids, None

    scored: list[tuple[int, str, float]] = []
    for index, paper_id in enumerate(ids):
        text = paper_text(papers.get(paper_id))
        if not text:
            continue
        scored.append((index, paper_id, ranker.score(text)))
    if not scored:
        return ids, None

    ranked = sorted(scored, key=lambda item: (-item[2], item[0]))
    result = list(ids)
    for slot, item in zip([entry[0] for entry in scored], ranked, strict=True):
        result[slot] = item[1]

    n_include = sum(1 for label in labels.values() if label == "include")
    meta = {
        "n_labels": len(labels),
        "n_include": n_include,
        "n_exclude": len(labels) - n_include,
        "n_pending": len(ids),
        "n_scored": len(scored),
        "vocabulary_size": len(ranker.vocabulary),
        "model": MODEL_ID,
    }
    return result, meta


def rank_pending(
    pending_ids: list[str],
    papers: dict[str, dict[str, Any]],
    session_dir: str | Path,
    *,
    stage: str = STAGE_SCREENING,
    interval: int | None = None,
    double: bool | None = None,
    config_path: str | Path | None = None,
) -> list[str]:
    """Umsortierte Restliste — ohne Protokollzeile und ohne Schalterprüfung.

    Für Aufrufer, die nur die Reihenfolge wollen (Vorschau, Tests). Der Weg im
    Screening-Ablauf ist ``reorder_pending``.
    """
    order, _ = _ranked_with_meta(
        pending_ids,
        papers,
        session_dir,
        stage=stage,
        interval=interval,
        double=double,
        config_path=config_path,
    )
    return order


def _ranked_with_meta(
    pending_ids: list[str],
    papers: dict[str, dict[str, Any]],
    session_dir: str | Path,
    *,
    stage: str,
    interval: int | None,
    double: bool | None,
    config_path: str | Path | None,
) -> tuple[list[str], dict[str, Any] | None]:
    labels = training_labels(session_dir, stage=stage, double=double, config_path=config_path)
    threshold = resolve_retrain_interval(interval, config_path=config_path)
    if len(labels) < threshold:
        # Kaltstart: zu wenig Urteile für eine belastbare Trainingsgrundlage.
        return list(pending_ids), None
    return _order_by_labels(list(pending_ids), papers, labels)


def reorder_pending(
    pending_ids: list[str],
    papers: dict[str, dict[str, Any]],
    session_dir: str | Path,
    *,
    stage: str = STAGE_SCREENING,
    enabled: bool | None = None,
    interval: int | None = None,
    double: bool | None = None,
    config_path: str | Path | None = None,
) -> list[str]:
    """Sortiert die offene Restliste um und protokolliert die neue Reihenfolge.

    Bei abgeschaltetem Active Learning (Default) wird die Eingabe unverändert
    zurückgegeben und **nichts** geschrieben — ein solcher Lauf ist von einem
    Lauf ohne dieses Modul nicht unterscheidbar.

    Umsortiert wird erst ab ``interval`` vorliegenden Urteilen und nur, wenn
    beide Klassen belegt sind. Jede tatsächliche Umsortierung hängt genau eine
    Zeile an ``$SESSION_DIR/active_learning_log.jsonl`` an.
    """
    if not resolve_active_learning(enabled, config_path=config_path):
        return list(pending_ids)

    order, meta = _ranked_with_meta(
        pending_ids,
        papers,
        session_dir,
        stage=stage,
        interval=interval,
        double=double,
        config_path=config_path,
    )
    if meta is not None:
        _append_log(session_dir, {**meta, "stage": stage, "ts": int(time.time()), "order": order})
    return order


# ---------------------------------------------------------------------------
# Protokoll
# ---------------------------------------------------------------------------


def log_path(session_dir: str | Path) -> Path:
    """Pfad des Umsortierungs-Protokolls innerhalb einer ``/search``-Session."""
    return Path(session_dir) / LOG_FILENAME


def _append_log(session_dir: str | Path, entry: dict[str, Any]) -> None:
    path = log_path(session_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_log(session_dir: str | Path) -> list[dict[str, Any]]:
    """Alle vollständigen Protokollzeilen; eine halbe letzte Zeile wird übersprungen."""
    path = log_path(session_dir)
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and "order" in entry:
            entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# Fortschritt
# ---------------------------------------------------------------------------


def _decision_map(session_dir: str | Path, stage: str, double: bool) -> dict[str, str]:
    buckets = merge_double(session_dir, stage=stage) if double else merge(session_dir, stage=stage)
    return {paper_id: bucket for bucket, paper_ids in buckets.items() for paper_id in paper_ids}


def progress(
    paper_ids: list[str],
    session_dir: str | Path,
    *,
    stage: str = STAGE_SCREENING,
    block_size: int | None = None,
    double: bool | None = None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Wie viel der Liste ist bearbeitet, und was kam zuletzt noch dazu?

    Das ist die Datengrundlage der Abbruchentscheidung — und nur die
    Grundlage: entschieden wird sie von einem Menschen. Die Abschnitte folgen
    der **Urteilsreihenfolge** aus dem Ledger, nicht der Listenreihenfolge;
    genau darum ist an den letzten Abschnitten ablesbar, ob die Ausbeute
    versiegt.
    """
    if double is None:
        double = resolve_double_screening(config_path=config_path)
    size = resolve_block_size(block_size, config_path=config_path)
    decisions = _decision_map(session_dir, stage, double)

    known = set(paper_ids)
    seen: set[str] = set()
    sequence: list[tuple[str, str]] = []
    for entry in read_ledger(session_dir):
        if entry.get("stage") != stage:
            continue
        paper_id = entry["paper_id"]
        if paper_id in seen or paper_id not in known or paper_id not in decisions:
            continue
        seen.add(paper_id)
        sequence.append((paper_id, decisions[paper_id]))

    blocks: list[dict[str, Any]] = []
    for index, start in enumerate(range(0, len(sequence), size), start=1):
        chunk = sequence[start : start + size]
        blocks.append(
            {
                "index": index,
                "n_decided": len(chunk),
                "n_include": sum(1 for _, decision in chunk if decision == "include"),
            }
        )

    n_total = len(paper_ids)
    n_decided = len(sequence)
    return {
        "n_total": n_total,
        "n_decided": n_decided,
        "n_pending": n_total - n_decided,
        "share_done_pct": round(100.0 * n_decided / n_total, 1) if n_total else 0.0,
        "n_include": sum(1 for _, decision in sequence if decision == "include"),
        "block_size": size,
        "blocks": blocks,
        "recent_blocks": blocks[-2:],
    }


def progress_report(
    paper_ids: list[str],
    session_dir: str | Path,
    *,
    stage: str = STAGE_SCREENING,
    block_size: int | None = None,
    double: bool | None = None,
    config_path: str | Path | None = None,
) -> str:
    """Der Fortschritt als Markdown — ohne Empfehlung, wann Schluss ist."""
    data = progress(
        paper_ids,
        session_dir,
        stage=stage,
        block_size=block_size,
        double=double,
        config_path=config_path,
    )
    lines = [
        "## Screening-Fortschritt",
        "",
        f"{data['n_decided']} von {data['n_total']} Quellen geurteilt "
        f"({data['share_done_pct']} %), {data['n_pending']} offen. "
        f"Bisher {data['n_include']} Treffer.",
        "",
        "| Abschnitt | Geurteilt | Treffer |",
        "|-----------|-----------|---------|",
    ]
    for block in data["blocks"]:
        first = (block["index"] - 1) * data["block_size"] + 1
        last = first + block["n_decided"] - 1
        lines.append(f"| {first}–{last} | {block['n_decided']} | {block['n_include']} |")
    if not data["blocks"]:
        lines.append("| — | 0 | 0 |")
    lines += [
        "",
        "Die letzten Abschnitte zeigen, ob die Ausbeute versiegt. Ob das reicht, "
        "entscheidet ein Mensch — dieser Bericht bricht nichts ab und schliesst "
        "nichts aus.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Validierungslauf gegen eine Trefferliste mit bekanntem Ergebnis
# ---------------------------------------------------------------------------

DEFAULT_CHECKPOINTS = (10.0, 20.0, 30.0, 50.0, 75.0, 100.0)


def validate_ranking(
    records: list[dict[str, Any]],
    *,
    interval: int | None = None,
    checkpoints: tuple[float, ...] = DEFAULT_CHECKPOINTS,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Simuliert einen Screening-Lauf gegen bekannte Urteile und misst die Ausbeute.

    ``records`` sind Zeilen mit ``paper_id``, ``title``, ``abstract`` und
    ``relevant`` (bool). Der Lauf beginnt in der gegebenen Reihenfolge, urteilt
    Fall für Fall und sortiert die Restliste alle ``interval`` Urteile neu.

    Ergebnis ist die Recall-Kurve: nach welchem Anteil der Liste war welcher
    Anteil der relevanten Arbeiten gefunden. Die Zufallsbaseline ist die
    Diagonale (nach 20 % der Liste 20 % der Treffer) — daran misst sich der
    Nutzen. Deterministisch: gleiche Eingabe, gleiche Kurve.
    """
    step = resolve_retrain_interval(interval, config_path=config_path)
    papers = {
        str(record["paper_id"]): {
            "title": record.get("title", ""),
            "abstract": record.get("abstract", ""),
        }
        for record in records
    }
    relevance = {str(record["paper_id"]): bool(record.get("relevant")) for record in records}

    remaining = [str(record["paper_id"]) for record in records]
    screened: list[str] = []
    labels: dict[str, str] = {}

    while remaining:
        paper_id = remaining.pop(0)
        screened.append(paper_id)
        labels[paper_id] = "include" if relevance[paper_id] else "exclude"
        if remaining and len(labels) >= step and len(labels) % step == 0:
            remaining, _ = _order_by_labels(remaining, papers, labels)

    n_total = len(screened)
    n_relevant = sum(1 for paper_id in screened if relevance[paper_id])
    curve = []
    for share in checkpoints:
        n_screened = min(n_total, max(1, int(round(n_total * share / 100.0))))
        n_found = sum(1 for paper_id in screened[:n_screened] if relevance[paper_id])
        curve.append(
            {
                "share_pct": round(float(share), 1),
                "n_screened": n_screened,
                "n_found": n_found,
                "recall_pct": round(100.0 * n_found / n_relevant, 1) if n_relevant else 0.0,
            }
        )

    return {
        "n_total": n_total,
        "n_relevant": n_relevant,
        "interval": step,
        "model": MODEL_ID,
        "curve": curve,
        "screened_order": screened,
    }


def validation_report(result: dict[str, Any]) -> str:
    """Die Recall-Kurve als Markdown-Tabelle."""
    lines = [
        "## Validierungslauf Active Learning",
        "",
        f"{result['n_total']} Quellen, davon {result['n_relevant']} relevant. "
        f"Nachtraining alle {result['interval']} Urteile ({result['model']}).",
        "",
        "| Anteil der Liste | Geurteilte Quellen | Gefundene Treffer "
        "| Anteil der gefundenen Treffer |",
        "|------------------|--------------------|-------------------"
        "|-------------------------------|",
    ]
    for point in result["curve"]:
        lines.append(
            f"| {point['share_pct']} % | {point['n_screened']} | {point['n_found']} "
            f"| {point['recall_pct']} % |"
        )
    lines += [
        "",
        "Zufallsbaseline ist die Diagonale: ohne Umsortierung waeren nach x % der "
        "Liste im Mittel x % der Treffer gefunden.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _split_ids(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _tristate(raw: str) -> bool | None:
    stripped = raw.strip().lower()
    if stripped in _TRUTHY:
        return True
    if stripped in _FALSY:
        return False
    return None


def _load_papers(path: str) -> dict[str, dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {str(row["paper_id"]): row for row in data if row.get("paper_id")}
    return {str(key): value for key, value in data.items()}


def _load_gold(path: str) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Active Learning fuer das Screening (Issue #602)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_rank = sub.add_parser("rank", help="Offene Restliste umsortieren")
    p_rank.add_argument("--session-dir", required=True)
    p_rank.add_argument("--papers", required=True, help="JSON mit title/abstract je paper_id")
    p_rank.add_argument("--ids", required=True, help="Komma-separierte offene paper_ids")
    p_rank.add_argument("--stage", default=STAGE_SCREENING)
    p_rank.add_argument("--interval", type=int, default=None)
    p_rank.add_argument("--active-learning", default="auto")
    p_rank.add_argument("--double-screening", default="auto")

    p_progress = sub.add_parser("progress", help="Fortschritt als Markdown")
    p_progress.add_argument("--session-dir", required=True)
    p_progress.add_argument("--ids", required=True)
    p_progress.add_argument("--stage", default=STAGE_SCREENING)
    p_progress.add_argument("--block-size", type=int, default=None)
    p_progress.add_argument("--double-screening", default="auto")

    p_validate = sub.add_parser("validate", help="Recall-Kurve gegen bekannte Urteile")
    p_validate.add_argument(
        "--gold", required=True, help="JSONL mit paper_id/title/abstract/relevant"
    )
    p_validate.add_argument("--interval", type=int, default=None)
    p_validate.add_argument("--json", action="store_true", help="Rohdaten statt Tabelle")

    args = parser.parse_args(argv)

    if args.command == "rank":
        order = reorder_pending(
            _split_ids(args.ids),
            _load_papers(args.papers),
            args.session_dir,
            stage=args.stage,
            enabled=_tristate(args.active_learning),
            interval=args.interval,
            double=_tristate(args.double_screening),
        )
        print(json.dumps(order, ensure_ascii=False))
    elif args.command == "progress":
        print(
            progress_report(
                _split_ids(args.ids),
                args.session_dir,
                stage=args.stage,
                block_size=args.block_size,
                double=_tristate(args.double_screening),
            )
        )
    elif args.command == "validate":
        result = validate_ranking(_load_gold(args.gold), interval=args.interval)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(validation_report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
