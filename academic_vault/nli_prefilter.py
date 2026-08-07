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

**Detektor, kein Filter (Issue #717).** Bis #717 uebersprang
:func:`run_batch_prefilter` als "treu" eingestufte Zitate und entfernte sie
damit dauerhaft aus dem Pruefpfad -- ein Fehlurteil des Modells kostete die
Pruefung. Seither wird NICHTS uebersprungen: alle Items erreichen den
bestehenden Pruefpfad wie ohne Scan, verdaechtige Items werden ZUSAETZLICH
gemeldet (Schluessel ``suspicious``). Ein Fehlurteil entspricht damit im
schlimmsten Fall dem Zustand ohne Scan.

**Default ist AN** (:data:`DEFAULT_PREFILTER_ENABLED`, seit #717). Das Risiko
aus der Rule-of-Three-Grenze der Eval (~10 %,
``evals/524-nli-prefilter/README.md``) entfaellt als Argument gegen Default-an,
weil im Detektor-Modus kein Zitat verloren geht. Bei ``enabled=False``
verhaelt sich der Pruefpfad bytegleich zum Zustand ohne Scan: alle Items
werden unveraendert weitergereicht, nichts wird gemeldet.

Konservative Schwelle: im Zweifel gilt ein Item als verdaechtig
(``verzerrend``). Eine zu viel gemeldete Fundstelle kostet einen Blick, eine
uebersehene bleibt unbemerkt in der Arbeit stehen -- die teurere Richtung ist
die falsche.

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
DEFAULT_PREFILTER_ENABLED = True

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def resolve_nli_prefilter_enabled(
    explicit: bool | None = None,
    config_path: str | Path | None = None,
) -> bool:
    """Schalter fuer den NLI-Zitatscan (#592, Default-Umkehr #717).

    Vorrang: Argument > Env ``ACADEMIC_RESEARCH_NLI_PREFILTER`` >
    ``config/parallel_agents.json`` (Schluessel ``nli_prefilter_enabled``) >
    Default ``True``. Der Default ist seit #717 AN, weil der Scan im
    Detektor-Modus laeuft und kein Zitat aus dem Pruefpfad entfernen kann.
    Abschalten: ``ACADEMIC_RESEARCH_NLI_PREFILTER=0`` oder
    ``"nli_prefilter_enabled": false`` in ``config/parallel_agents.json``.
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
        self.threshold = threshold

    def load(self) -> tuple[Any, Any]:
        if self._model is None or self._tokenizer is None:
            # Lazy Import: zieht transformers/torch nach, nicht beim Modul-Import.
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            from academic_vault._model_prefetchable import notify_lazy_download

            notify_lazy_download(
                label="NLI-Zitatscan-Modell", repo_id=self.model_id, cache_dir=self.cache_dir
            )
            if self._tokenizer is None:
                self._tokenizer = AutoTokenizer.from_pretrained(
                    self.model_id, cache_dir=self.cache_dir
                )
            if self._model is None:
                self._model = AutoModelForSequenceClassification.from_pretrained(
                    self.model_id, cache_dir=self.cache_dir
                )
        return self._model, self._tokenizer

    def entailment_index(self) -> int:
        """Index der Entailment-Klasse, gelesen aus ``model.config.id2label``.

        Bis #717 stand hier eine harte ``probs[0]``-Annahme ("Label-Reihenfolge
        lt. Modellkarte"). Solange nur die Eval darauf zugriff, war das
        folgenlos; ab Default-an (#717) waere es ein stiller Fehlurteils-Pfad,
        sobald ein Modell die Klassen anders sortiert (Learning #720:
        ``id2label``-Reihenfolge unterscheidet sich zwischen Modellen).
        Kein lautloser Fallback -- fehlt das Label, ist das ein ``ValueError``.
        """
        model, _ = self.load()
        id2label = getattr(getattr(model, "config", None), "id2label", None) or {}
        for idx, label in id2label.items():
            if "entail" in str(label).strip().lower():
                return int(idx)
        raise ValueError(
            f"Kein 'entailment'-Label in model.config.id2label ({id2label!r}) — "
            "der Entailment-Index laesst sich nicht bestimmen."
        )

    def predict(self, premise: str, hypothesis: str) -> tuple[str, float]:
        import torch

        model, tokenizer = self.load()
        entail_idx = self.entailment_index()
        inputs = tokenizer(
            premise, hypothesis, truncation=True, max_length=512, return_tensors="pt"
        )
        with torch.no_grad():
            logits = model(**inputs).logits[0]
        probs = torch.softmax(logits, dim=-1).tolist()
        entailment_prob = float(probs[entail_idx])
        predicted_idx = max(range(len(probs)), key=lambda i: probs[i])
        # Konservativ: "faithful" nur bei eindeutigem Entailment-Ausschlag UND
        # einer Mindest-Score-Hoehe -- alles andere (auch ein knapper
        # Entailment-Ausschlag unter der Schwelle) gilt als Zweifelsfall und
        # wird gemeldet.
        verdict = (
            "faithful"
            if predicted_idx == entail_idx and entailment_prob >= self.threshold
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
# Batch-Detektor (AC: alle Zitate eines Kapitels in einem Durchgang)
# ---------------------------------------------------------------------------


def prefilter_quote(
    scorer: NliScorer,
    quote_id: str,
    chapter_claim: str,
    paper_id: str,
    context_before: str | None,
    verbatim: str,
    context_after: str | None,
) -> dict:
    """Bewertet EIN Zitat-Kapitel-Paar. Reine Funktion, kein Vault-Zugriff.

    ``suspicious`` ist das einzige Urteilsfeld: True bedeutet "melden", nicht
    "aus dem Pruefpfad nehmen" (Detektor-Semantik seit #717).
    """
    premise = build_premise(context_before, verbatim, context_after)
    verdict, raw_score = scorer.predict(premise, chapter_claim)
    return {
        "quote_id": quote_id,
        "chapter_claim": chapter_claim,
        "paper_id": paper_id,
        "verdict": verdict,
        "raw_score": raw_score,
        "suspicious": verdict != "faithful",
    }


def run_batch_prefilter(
    items: list[dict],
    scorer: NliScorer | None = None,
    enabled: bool | None = None,
    config_path: str | Path | None = None,
) -> dict:
    """Detektor ueber ALLE Zitate eines Kapitels in einem Durchgang.

    ``items``: Liste von ``{"quote_id", "chapter_claim", "paper_id",
    "context_before", "verbatim", "context_after"}`` -- z. B. aus
    :func:`scan_chapter_quotes`.

    Rueckgabe:

    ``forwarded``
        IMMER alle Items als ``{quote_id, chapter_claim, paper_id}``
        (Input-Format von ``agents/quote-fidelity-auditor.md``). Seit #717
        wird hier nichts mehr aussortiert -- der Pruefpfad ist mit und ohne
        Scan derselbe.
    ``suspicious``
        Teilmenge mit Verdict ``"verzerrend"``, inklusive ``raw_score`` --
        das, was gemeldet wird.
    ``skipped``
        Bleibt aus Aufruferkompatibilitaet erhalten und ist IMMER leer:
        im Detektor-Modus wird nichts uebersprungen.
    ``results``
        Rohurteile je Item (leer, wenn abgeschaltet).

    Bei ``enabled=False`` verhaelt sich der Pfad bytegleich zum Zustand ohne
    Scan: alle Items werden weitergereicht, nichts wird bewertet oder
    gemeldet.
    """
    detector_on = resolve_nli_prefilter_enabled(enabled, config_path)
    forwarded = [
        {
            "quote_id": item["quote_id"],
            "chapter_claim": item["chapter_claim"],
            "paper_id": item["paper_id"],
        }
        for item in items
    ]
    if not detector_on:
        return {
            "enabled": False,
            "forwarded": forwarded,
            "suspicious": [],
            "skipped": [],
            "results": [],
        }

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
    suspicious = [r for r in results if r["suspicious"]]
    return {
        "enabled": True,
        "forwarded": forwarded,
        "suspicious": suspicious,
        "skipped": [],
        "results": results,
    }


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


def _find_matched_quote_spans(
    content: str, db_path: str, min_len: int = MIN_QUOTE_LEN
) -> list[dict]:
    """Findet alle Zitat-Spannen mit tatsaechlichem Vault-Treffer (Issue #739).

    Basis fuer :func:`scan_chapter_quotes` (dort dedupliziert nach
    ``quote_id``) und fuer :func:`compute_citation_density` (dort zaehlt
    JEDE Fundstelle, auch Mehrfachzitate derselben Passage, weil es um
    Belegabdeckung im Kapiteltext geht, nicht um eindeutige Zitate). Spans
    ohne Treffer sind kein Vault-Zitat und werden uebersprungen (kein
    Erfindungsrisiko -- nur tatsaechlich im Vault belegte Zitate zaehlen als
    Beleg).
    """
    from .server import get_quote, search_quote_text

    spans = extract_quote_spans(content, min_len)
    results: list[dict] = []
    for span in spans:
        hits = search_quote_text(db_path, span["text"], 1)
        if not hits:
            continue
        quote_id = hits[0]["quote_id"]
        record = get_quote(db_path, quote_id)
        if record is None:
            continue
        results.append(
            {"start": span["start"], "end": span["end"], "quote_id": quote_id, "record": record}
        )
    return results


def scan_chapter_quotes(content: str, db_path: str, min_len: int = MIN_QUOTE_LEN) -> list[dict]:
    """Findet ALLE im Vault belegten Zitate eines Kapitels -- nicht nur die
    mit Claim-Drift-Warnung (Issue-AC2).

    Jede ``quote_id`` erscheint hoechstens einmal im Ergebnis, auch wenn
    dieselbe Passage mehrfach im Kapitel zitiert wird.
    """
    items: list[dict] = []
    seen_quote_ids: set[str] = set()
    for match in _find_matched_quote_spans(content, db_path, min_len):
        quote_id = match["quote_id"]
        if quote_id in seen_quote_ids:
            continue
        seen_quote_ids.add(quote_id)
        record = match["record"]
        span = {"start": match["start"], "end": match["end"]}
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


# ---------------------------------------------------------------------------
# Belegdichte: welcher Anteil der Aussagesaetze eines Kapitels traegt einen
# Vault-Beleg (Issue #739). Kein Gate, keine Meldung -- reine Kennzahl.
# ---------------------------------------------------------------------------

#: Markdown-Strukturzeilen zaehlen nie als Aussagesatz: Ueberschriften
#: (``## Titel``) und Listenpunkte (``- Punkt`` / ``1. Punkt`` / ``2) Punkt``).
_HEADING_LINE = re.compile(r"^#{1,6}\s")
_LIST_LINE = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s)")

#: Kuratierte, dokumentierte Liste reiner Ueberleitungsfloskeln (Issue #739).
#: Bewusst klein und explizit -- keine geschlossene Menge, sondern ein
#: nachvollziehbarer Ausschnitt, der in ``docs/reference/vault.md`` gespiegelt
#: wird. Ein Satz zaehlt nur dann als Ueberleitung, wenn er (getrimmt,
#: kleingeschrieben) mit einer dieser Phrasen BEGINNT -- z. B. "Im Folgenden
#: wird die Methodik erlaeutert." oder "Zusammenfassend laesst sich sagen,
#: dass..." transportieren selbst keine Aussage, sie kuendigen nur an, was
#: als naechstes kommt bzw. fasst zusammen, was schon gesagt wurde.
TRANSITION_PREFIXES = (
    "im folgenden",
    "im naechsten abschnitt",
    "im nächsten abschnitt",
    "im vorigen abschnitt",
    "wie oben gezeigt",
    "wie im vorigen abschnitt gezeigt",
    "kommen wir nun zu",
    "zusammenfassend laesst sich sagen",
    "zusammenfassend lässt sich sagen",
    "abschliessend laesst sich festhalten",
    "abschließend lässt sich festhalten",
    "im weiteren verlauf dieser arbeit",
)


def _non_structural_runs(content: str) -> list[tuple[int, int]]:
    """Zeichenspannen der Textbloecke ZWISCHEN Ueberschrift-/Listenpunkt-
    Zeilen (Plan: Filterung VOR dem Satzsplit, nicht danach). Eine
    Strukturzeile ist eine harte Blockgrenze -- ein Satz wird nie ueber sie
    hinweg mit dem folgenden Absatz verschmolzen."""
    runs: list[tuple[int, int]] = []
    pos = 0
    run_start: int | None = None
    for line in content.splitlines(keepends=True):
        stripped_line = line.rstrip("\n")
        is_structural = bool(_HEADING_LINE.match(stripped_line) or _LIST_LINE.match(stripped_line))
        if is_structural:
            if run_start is not None:
                runs.append((run_start, pos))
                run_start = None
        elif run_start is None:
            run_start = pos
        pos += len(line)
    if run_start is not None:
        runs.append((run_start, pos))
    return runs


def _is_transition_sentence(text: str) -> bool:
    return text.strip().lower().startswith(TRANSITION_PREFIXES)


def extract_statement_sentences(content: str) -> list[dict]:
    """Findet alle Aussagesaetze eines Kapiteltexts (Issue #739).

    Ein Aussagesatz ist ein Satz (Split ueber :data:`_SENTENCE_SPLIT`, wie
    :func:`claim_sentence_for_span`) innerhalb eines Textblocks zwischen
    Ueberschrift-/Listenpunkt-Zeilen (:func:`_non_structural_runs` --
    solche Zeilen sind harte Blockgrenzen, ein Satz verschmilzt nie mit dem
    Absatz vor/nach ihnen), der NICHT auf ``?`` endet (Fragesatz) und NICHT
    mit einer der :data:`TRANSITION_PREFIXES` beginnt (reine Ueberleitung).

    Beispiele:
      - ``"## Methodik"`` -- Ueberschrift, zaehlt nicht.
      - ``"- Erstens dies."`` -- Listenpunkt, zaehlt nicht.
      - ``"Ist das plausibel?"`` -- Frage, zaehlt nicht.
      - ``"Im Folgenden wird die Methodik erlaeutert."`` -- Ueberleitung,
        zaehlt nicht.
      - ``"DevOps-Governance hat sich seit 2015 in der Praxis durchgesetzt."``
        -- Aussagesatz, zaehlt.

    Rueckgabe: Liste von ``{text, start, end}`` (Zeichenoffsets im
    ``content``, fuehrende/nachgestellte Whitespace bereits entfernt).
    """
    sentences: list[dict] = []
    for run_start, run_end in _non_structural_runs(content):
        block = content[run_start:run_end]
        bounds: list[tuple[int, int]] = []
        pos = 0
        for m in _SENTENCE_SPLIT.finditer(block):
            bounds.append((pos, m.start()))
            pos = m.end()
        bounds.append((pos, len(block)))

        for start, end in bounds:
            raw = block[start:end]
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.endswith("?"):
                continue
            if _is_transition_sentence(stripped):
                continue
            leading_ws = len(raw) - len(raw.lstrip())
            real_start = run_start + start + leading_ws
            real_end = real_start + len(stripped)
            sentences.append({"text": stripped, "start": real_start, "end": real_end})
    return sentences


def _longest_uncovered_run(
    sentences: list[dict], covered_flags: list[bool], content: str
) -> dict | None:
    """Laengste zusammenhaengende Strecke von Aussagesaetzen ohne Beleg, mit
    Fundstelle (1-indexierte Zeilennummer + Textausschnitt des ersten Satzes
    der Strecke). ``None``, wenn jeder Satz belegt ist oder es keine gibt."""
    best_start_idx: int | None = None
    best_len = 0
    cur_start_idx: int | None = None
    cur_len = 0
    for i, covered in enumerate(covered_flags):
        if covered:
            cur_start_idx = None
            cur_len = 0
            continue
        if cur_start_idx is None:
            cur_start_idx = i
        cur_len += 1
        if cur_len > best_len:
            best_len = cur_len
            best_start_idx = cur_start_idx

    if best_start_idx is None:
        return None

    first_sentence = sentences[best_start_idx]
    line_no = content.count("\n", 0, first_sentence["start"]) + 1
    return {
        "sentence_count": best_len,
        "line": line_no,
        "excerpt": first_sentence["text"],
    }


def compute_citation_density(content: str, db_path: str) -> dict:
    """Belegdichte eines Kapitels (Issue #739): welcher Anteil der
    Aussagesaetze durch ein tatsaechlich im Vault gematchtes Zitat gedeckt
    ist -- reine Kennzahl, kein Gate, keine Meldung, kein Schwellwert.

    Ein Aussagesatz gilt als "belegt", wenn seine Zeichenspanne eine
    Vault-gematchte Zitat-Spanne (:func:`_find_matched_quote_spans`)
    ueberlappt. Massgeblich ist der tatsaechliche Vault-Treffer, nicht das
    blosse Vorhandensein von Anfuehrungszeichen -- sonst zaehlte ein
    erfundenes Zitat faelschlich als Beleg.

    WICHTIG: eine hohe Belegdichte ist kein Qualitaetsmerkmal. Ein Kapitel
    aus lauter Zitaten ist keine eigene Leistung -- die Zahl macht nur
    sichtbar, wo eine Aussage auf einer Quelle statt auf einem selbst steht.

    Args:
        content: Kapiteltext (Markdown).
        db_path: Pfad zur Vault-SQLite-Datei.

    Returns:
        Dict mit ``statement_sentences_total``, ``statement_sentences_covered``,
        ``citation_density`` (Anteil 0.0-1.0, ``None`` bei 0 Aussagesaetzen --
        ein Anteil von nichts ist keine 0, sondern nicht definiert) und
        ``longest_uncovered_run`` (``None`` oder Dict mit ``sentence_count``,
        ``line``, ``excerpt``).
    """
    sentences = extract_statement_sentences(content)
    matched_spans = [(m["start"], m["end"]) for m in _find_matched_quote_spans(content, db_path)]

    def _is_covered(sentence: dict) -> bool:
        return any(
            span_start < sentence["end"] and span_end > sentence["start"]
            for span_start, span_end in matched_spans
        )

    covered_flags = [_is_covered(s) for s in sentences]
    total = len(sentences)
    covered = sum(covered_flags)

    return {
        "statement_sentences_total": total,
        "statement_sentences_covered": covered,
        "citation_density": (covered / total) if total else None,
        "longest_uncovered_run": _longest_uncovered_run(sentences, covered_flags, content),
    }
