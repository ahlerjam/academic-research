"""NLI-Batch-Vorfilter vor dem Zitat-Richter (Issue #592, Vorarbeit #524,
Modellwechsel #720).

Der Vorfilter laedt ``MoritzLaurer/bge-m3-zeroshot-v2.0`` (MIT) lokal und
bewertet, ob eine deutsche Kapitelbehauptung durch den englischen
Quote-Kontext (``context_before`` + ``verbatim`` + ``context_after``) gedeckt
ist. A/B gegen ``MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7``
auf 278 Faellen (Issue #720): bei Schwelle 0.95 laesst bge-m3-zeroshot nur 1
Verzerrung durchrutschen, mDeBERTa saettigt bei 10 durchgerutschten Faellen
auch bei dieser Schwelle -- ausschlaggebend ist die Kalibrierbarkeit ueber die
Schwelle, nicht ein einzelner Precision/Recall-Wert. Details, Schwellenkurve
und die verworfenen Zusatzansaetze: ``docs/evals/2026-08-07-bge-m3-nli-scorer-720.md``.

**Zweck ist Abdeckung, nicht Kostenersparnis.** Ohne diesen Vorfilter wird ein
Zitat nur dann inhaltlich geprueft (``agents/quote-fidelity-auditor.md``), wenn
entweder der ``claim-drift-guard``-Hook eine Aenderung neben einem
unveraenderten Zitat bemerkt, oder explizit dazu aufgefordert wird. Ein Zitat,
das von Anfang an falsch verwendet wurde und seither nie wieder angefasst
wurde, faellt durch dieses Raster. :func:`scan_chapter_quotes` +
:func:`run_batch_prefilter` schliessen genau diese Luecke, indem sie ALLE im
Vault belegten Zitate eines Kapitels in einem Durchgang bewerten.

**Default ist AUS** (:data:`DEFAULT_PREFILTER_ENABLED`), bis eine Validierung
gegen echtes Zitatmaterial vorliegt (AC in Issue #592). Bei ``enabled=False``
verhaelt sich :func:`run_batch_prefilter` bytegleich zum Zustand ohne
Vorfilter: alle Items werden unveraendert weitergereicht, keines wird
uebersprungen.

Konservative Schwelle: im Zweifel wird weitergeleitet (``verzerrend``). Ein zu
viel geprueftes Zitat kostet Tokens im nachgelagerten Sonnet-Lauf, ein
durchgewunkenes bleibt unbemerkt in der Arbeit stehen -- die teurere Richtung
ist die falsche.

**Priorisierer, nicht Torwaechter.** Der Scan entscheidet, welches Zitat
ZUERST inhaltlich vom ``quote-fidelity-auditor`` geprueft wird -- er
entscheidet nicht, was durchgeht. Ein Zitat ohne Meldung ist nicht
"geprueft", nur nicht priorisiert. Bekannte strukturelle Schwaeche:
weggelassene Randbedingungen (``condition-stripped``) werden nur zur Haelfte
erkannt, siehe Eval-Report #720 -- das ist eine Eigenschaft von NLI ("folgt
daraus?"), nicht durch Modellwahl behebbar.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Protocol

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "parallel_agents.json"

# ---------------------------------------------------------------------------
# Modell / Cache
# ---------------------------------------------------------------------------

ENV_CACHE_DIR = "NLI_PREFILTER_MODEL_CACHE"

#: Produktivmodell seit Issue #720 (zuvor mDeBERTa-XNLI, weiterhin als
#: Eval-Kandidat verfuegbar ueber :class:`MDebertaScorer`).
MODEL_ID = "MoritzLaurer/bge-m3-zeroshot-v2.0"
MDEBERTA_MODEL_ID = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"

# Konservative Entailment-Schwelle: "faithful" nur bei eindeutigem
# Entailment-Ausschlag UND einer Score-Mindesthoehe -- ein knapper Ausschlag
# gilt als Zweifelsfall und wird weitergeleitet (Issue-AC "im Zweifel
# weiterleiten"). 0.95 seit #720: bge-m3-zeroshot laesst sich ueber die
# Schwelle kalibrieren (22->1 Durchrutscher zwischen 0.50 und 0.95),
# mDeBERTa saettigt bei 10 Durchrutschern -- siehe Eval-Report.
DEFAULT_THRESHOLD = 0.95

#: Eigener, niedrigerer Default fuer den mDeBERTa-Eval-Kandidaten (dessen
#: Kalibrierung wurde in #720 nicht neu bewertet -- 0.5 reproduziert
#: weiterhin die #524-Zahlen, siehe ``evals/524-nli-prefilter/README.md``).
MDEBERTA_DEFAULT_THRESHOLD = 0.5


def default_cache_dir() -> str:
    """Ablageort fuer heruntergeladene Modellgewichte (Env-Override moeglich).

    Identisches Muster wie ``academic_vault.embedding_model.default_cache_dir``
    (#372) und ``evals/524-nli-prefilter/runner.py`` (#524).
    """
    env = os.environ.get(ENV_CACHE_DIR)
    if env:
        return env
    return str(Path.home() / ".academic-research" / "models")


def build_premise(context_before: str | None, verbatim: str, context_after: str | None) -> str:
    """Baut die englische Praemisse aus Kontext + Zitat (Vault-Quote-Format)."""
    parts = [context_before or "", verbatim, context_after or ""]
    return " ".join(p.strip() for p in parts if p and p.strip())


# ---------------------------------------------------------------------------
# Toggle (Muster: skills/parallel-screening/scripts/screening_ledger.py::resolve_double_screening, #598)
# ---------------------------------------------------------------------------

ENV_PREFILTER_ENABLED = "ACADEMIC_RESEARCH_NLI_PREFILTER"
CONFIG_KEY = "nli_prefilter_enabled"
DEFAULT_PREFILTER_ENABLED = False

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def resolve_nli_prefilter_enabled(
    explicit: bool | None = None,
    config_path: str | Path | None = None,
) -> bool:
    """Schalter fuer den NLI-Batch-Vorfilter (#592).

    Vorrang: Argument > Env ``ACADEMIC_RESEARCH_NLI_PREFILTER`` >
    ``config/parallel_agents.json`` (Schluessel ``nli_prefilter_enabled``) >
    Default ``False``. Der Default bleibt AUS, bis eine Validierung gegen
    echtes Zitatmaterial vorliegt -- siehe ``evals/524-nli-prefilter/README.md``.
    """
    if explicit is not None:
        return bool(explicit)

    raw_env = os.environ.get(ENV_PREFILTER_ENABLED)
    if raw_env is not None:
        stripped = raw_env.strip().lower()
        if stripped in _TRUTHY:
            return True
        if stripped in _FALSY:
            return False

    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data[CONFIG_KEY]
    except (OSError, ValueError, KeyError, TypeError):
        value = None
    if isinstance(value, bool):
        return value

    return DEFAULT_PREFILTER_ENABLED


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class NliScorer(Protocol):
    """Minimales Interface: ein (premise, hypothesis)-Paar rein, ein
    binaeres Urteil + Rohwert raus. Identisch zu
    ``evals/524-nli-prefilter/runner.py::NliScorer`` (dort weiterverwendet,
    kein Duplikat -- siehe Modul-Import dort)."""

    name: str

    def predict(self, premise: str, hypothesis: str) -> tuple[str, float]: ...


class NliModelScorer:
    """Generischer NLI-Scorer ueber ``AutoModelForSequenceClassification``.

    Kanonische Implementierung (Issue #592, generalisiert in #720) --
    ``evals/524-nli-prefilter/runner.py`` und
    ``tests/evals/test_nli_prefilter_evals.py`` importieren die Subklassen
    (:class:`BgeM3ZeroshotScorer`, :class:`MDebertaScorer`) statt sie zu
    duplizieren.

    Der Entailment-Index wird aus ``model.config.id2label`` abgeleitet --
    NICHT fest auf Index 0 verdrahtet. Das ist notwendig, weil verschiedene
    Modelle unterschiedliche Label-Schemata tragen: bge-m3-zeroshot ist
    binaer (``{0: entailment, 1: not_entailment}``), die mDeBERTa-Familie
    dreiklassig (``{0: entailment, 1: neutral, 2: contradiction}``). Ein
    Modell mit abweichender Reihenfolge wuerde bei fest verdrahtetem Index 0
    stillschweigend falsche Urteile liefern.
    """

    def __init__(
        self,
        model_id: str,
        name: str | None = None,
        cache_dir: str | None = None,
        model: Any | None = None,
        tokenizer: Any | None = None,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        self.model_id = model_id
        self.name = name if name is not None else model_id.rsplit("/", 1)[-1]
        self.cache_dir = cache_dir if cache_dir is not None else default_cache_dir()
        self._model = model
        self._tokenizer = tokenizer
        self._entailment_idx: int | None = None
        self.threshold = threshold

    def load(self) -> tuple[Any, Any]:
        if self._model is None or self._tokenizer is None:
            # Lazy Import: zieht transformers/torch nach, nicht beim Modul-Import.
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            if self._tokenizer is None:
                self._tokenizer = AutoTokenizer.from_pretrained(
                    self.model_id, cache_dir=self.cache_dir
                )
            if self._model is None:
                self._model = AutoModelForSequenceClassification.from_pretrained(
                    self.model_id, cache_dir=self.cache_dir
                )
        if self._entailment_idx is None:
            id2label = {int(k): v for k, v in self._model.config.id2label.items()}
            self._entailment_idx = next(
                (idx for idx, label in id2label.items() if label.lower().startswith("entail")),
                0,
            )
        return self._model, self._tokenizer

    def predict(self, premise: str, hypothesis: str) -> tuple[str, float]:
        import torch

        model, tokenizer = self.load()
        inputs = tokenizer(
            premise, hypothesis, truncation=True, max_length=512, return_tensors="pt"
        )
        with torch.no_grad():
            logits = model(**inputs).logits[0]
        probs = torch.softmax(logits, dim=-1).tolist()
        assert self._entailment_idx is not None  # von load() gesetzt
        entailment_prob = float(probs[self._entailment_idx])
        predicted_idx = max(range(len(probs)), key=lambda i: probs[i])
        # Konservativ: "faithful" nur bei eindeutigem Entailment-Ausschlag UND
        # einer Mindest-Score-Hoehe -- alles andere (auch ein knapper
        # Entailment-Ausschlag unter der Schwelle) gilt als Zweifelsfall und
        # wird weitergeleitet.
        verdict = (
            "faithful"
            if predicted_idx == self._entailment_idx and entailment_prob >= self.threshold
            else "verzerrend"
        )
        return verdict, entailment_prob


class BgeM3ZeroshotScorer(NliModelScorer):
    """Produktivscorer seit Issue #720: bge-m3-zeroshot-v2.0, Schwelle 0.95."""

    def __init__(
        self,
        cache_dir: str | None = None,
        model: Any | None = None,
        tokenizer: Any | None = None,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        super().__init__(
            model_id=MODEL_ID,
            name="bge-m3-zeroshot",
            cache_dir=cache_dir,
            model=model,
            tokenizer=tokenizer,
            threshold=threshold,
        )


class MDebertaScorer(NliModelScorer):
    """mDeBERTa-v3-XNLI -- seit #720 nur noch Eval-Kandidat (Praezedenzfall
    #524), nicht mehr Produktivmodell. Name/Import bleiben stabil fuer
    ``evals/524-nli-prefilter/runner.py`` und ``run_real_validation.py``."""

    def __init__(
        self,
        cache_dir: str | None = None,
        model: Any | None = None,
        tokenizer: Any | None = None,
        threshold: float = MDEBERTA_DEFAULT_THRESHOLD,
    ) -> None:
        super().__init__(
            model_id=MDEBERTA_MODEL_ID,
            name="mdeberta-xnli",
            cache_dir=cache_dir,
            model=model,
            tokenizer=tokenizer,
            threshold=threshold,
        )


# ---------------------------------------------------------------------------
# Batch-Vorfilter (AC: alle Zitate eines Kapitels in einem Durchgang)
# ---------------------------------------------------------------------------

#: Report-Marker fuer vorgefilterte, NICHT inhaltlich geprüfte Zitate. Muss
#: im Report sichtbar sein -- weder stillschweigend fehlend noch als
#: "geprueft" ausgewiesen (Issue-AC).
SKIP_MARKER = "vorgefiltert, nicht inhaltlich geprueft"


def prefilter_quote(
    scorer: NliScorer,
    quote_id: str,
    chapter_claim: str,
    paper_id: str,
    context_before: str | None,
    verbatim: str,
    context_after: str | None,
) -> dict:
    """Bewertet EIN Zitat-Kapitel-Paar. Reine Funktion, kein Vault-Zugriff."""
    premise = build_premise(context_before, verbatim, context_after)
    verdict, raw_score = scorer.predict(premise, chapter_claim)
    forwarded = verdict != "faithful"
    result: dict[str, Any] = {
        "quote_id": quote_id,
        "chapter_claim": chapter_claim,
        "paper_id": paper_id,
        "verdict": verdict,
        "raw_score": raw_score,
        "forwarded": forwarded,
    }
    if not forwarded:
        result["report"] = SKIP_MARKER
    return result


def run_batch_prefilter(
    items: list[dict],
    scorer: NliScorer | None = None,
    enabled: bool | None = None,
    config_path: str | Path | None = None,
) -> dict:
    """Vorfilter fuer ALLE Zitate eines Kapitels/einer Arbeit in einem Durchgang.

    ``items``: Liste von ``{"quote_id", "chapter_claim", "paper_id",
    "context_before", "verbatim", "context_after"}`` -- z. B. aus
    :func:`scan_chapter_quotes`.

    Verdaechtige Items (Verdict ``"verzerrend"``) werden UNVERAENDERT als
    ``{quote_id, chapter_claim, paper_id}`` weitergereicht (Input-Format von
    ``agents/quote-fidelity-auditor.md`` bleibt unangetastet). Treue Items
    werden uebersprungen und tragen den Report-Marker :data:`SKIP_MARKER`.

    Bei ``enabled=False`` (Default, solange keine Validierung an echtem
    Material vorliegt) verhaelt sich der Pruefpfad EXAKT wie ohne Vorfilter:
    alle Items werden unveraendert weitergereicht, keines wird uebersprungen.
    """
    prefilter_on = resolve_nli_prefilter_enabled(enabled, config_path)
    if not prefilter_on:
        forwarded_off = [
            {
                "quote_id": item["quote_id"],
                "chapter_claim": item["chapter_claim"],
                "paper_id": item["paper_id"],
            }
            for item in items
        ]
        return {"enabled": False, "forwarded": forwarded_off, "skipped": [], "results": []}

    active_scorer = scorer if scorer is not None else BgeM3ZeroshotScorer()

    results = [
        prefilter_quote(
            active_scorer,
            item["quote_id"],
            item["chapter_claim"],
            item["paper_id"],
            item.get("context_before"),
            item["verbatim"],
            item.get("context_after"),
        )
        for item in items
    ]
    forwarded = [
        {"quote_id": r["quote_id"], "chapter_claim": r["chapter_claim"], "paper_id": r["paper_id"]}
        for r in results
        if r["forwarded"]
    ]
    skipped = [r for r in results if not r["forwarded"]]
    return {"enabled": True, "forwarded": forwarded, "skipped": skipped, "results": results}


# ---------------------------------------------------------------------------
# Vollkapitel-Scan: findet ALLE im Vault belegten Zitate eines Kapitels
# ---------------------------------------------------------------------------

#: Mindestlaenge einer zitierten Spanne (identisches Mass wie
#: ``hooks/claim-drift-guard.mjs::MIN_QUOTE_LEN``).
MIN_QUOTE_LEN = 20

#: Zeichenfenster fuer den Satz-Fallback, falls um eine Zitat-Spanne keine
#: erkennbare Satzgrenze liegt (z. B. Zitat am Absatzanfang/-ende).
_CLAIM_WINDOW = 200

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ])")


def extract_quote_spans(content: str, min_len: int = MIN_QUOTE_LEN) -> list[dict]:
    """Findet alle zitierten Textspannen im Kapitel.

    Pendant zu ``hooks/claim-drift-guard.mjs::extractQuoteSpans``, aber ohne
    dessen Beschraenkung auf ein Aenderungsfenster -- hier wird das GESAMTE
    Kapitel gescannt (Issue-AC "alle Zitate eines Kapitels in einem
    Durchgang").
    """
    patterns = [
        re.compile(rf'"([^"]{{{min_len},}})"'),
        re.compile(rf"„([^“]{{{min_len},}})“"),
        re.compile(rf"«([^»]{{{min_len},}})»"),
    ]
    spans: list[dict] = []
    for pattern in patterns:
        for match in pattern.finditer(content):
            if not match.group(1):
                continue
            spans.append({"text": match.group(1), "start": match.start(), "end": match.end()})
    return spans


def claim_sentence_for_span(content: str, span: dict) -> str:
    """Naehert die Kapitelbehauptung an: der Satz, der die Zitat-Spanne
    umschliesst. Fallback auf ein Zeichenfenster, wenn keine Satzgrenze in
    Content-Reichweite erkennbar ist (z. B. Zitat direkt am Textanfang)."""
    pos = 0
    sentence_bounds = []
    for m in _SENTENCE_SPLIT.finditer(content):
        sentence_bounds.append((pos, m.start()))
        pos = m.end()
    sentence_bounds.append((pos, len(content)))

    for start, end in sentence_bounds:
        if start <= span["start"] < end or start < span["end"] <= end:
            claim = content[start:end].strip()
            if claim:
                return claim

    window = _CLAIM_WINDOW
    fallback = content[max(0, span["start"] - window) : min(len(content), span["end"] + window)]
    return fallback.strip()


def scan_chapter_quotes(content: str, db_path: str, min_len: int = MIN_QUOTE_LEN) -> list[dict]:
    """Findet ALLE im Vault belegten Zitate eines Kapitels -- nicht nur die
    mit Claim-Drift-Warnung (Issue-AC2).

    Fuer jede erkannte Zitat-Spanne wird per ``search_quote_text`` nach dem
    passenden Vault-Eintrag gesucht. Spans ohne Treffer sind kein
    Vault-Zitat und werden uebersprungen (kein Erfindungsrisiko -- nur
    tatsaechlich im Vault belegte Zitate werden bewertet). Jede ``quote_id``
    erscheint hoechstens einmal im Ergebnis, auch wenn dieselbe Passage
    mehrfach im Kapitel zitiert wird.
    """
    from .server import get_quote, search_quote_text

    spans = extract_quote_spans(content, min_len)
    items: list[dict] = []
    seen_quote_ids: set[str] = set()
    for span in spans:
        hits = search_quote_text(db_path, span["text"], 1)
        if not hits:
            continue
        quote_id = hits[0]["quote_id"]
        if quote_id in seen_quote_ids:
            continue
        seen_quote_ids.add(quote_id)
        record = get_quote(db_path, quote_id)
        if record is None:
            continue
        items.append(
            {
                "quote_id": quote_id,
                "paper_id": record["paper_id"],
                "chapter_claim": claim_sentence_for_span(content, span),
                "context_before": record.get("context_before"),
                "verbatim": record["verbatim"],
                "context_after": record.get("context_after"),
            }
        )
    return items
