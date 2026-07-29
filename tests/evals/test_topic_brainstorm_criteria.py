"""Instrumenten-Test der Fach-Kontrast-Kriterien von topic-brainstorm (#471).

Was hier geprueft wird, ist **das Messinstrument, nicht das Modell**: taugen die
Erfolgskriterien in `evals/topic-brainstorm/evals.json` dazu, den Bug aus #471
zu erkennen? Das ist offline entscheidbar, weil die fehlerhafte Ausgabe bekannt
ist — der geloeschte `_TOPIC_DB`-Scorer lieferte fuer *jede* Studienrichtung
dieselben fuenf Cyber-Security-Themen (Titel woertlich aus der Git-Historie,
siehe `ISSUE_471_FIXED_TITLES`).

Was hier **nicht** geprueft wird: ob das Modell bei einer realen Anfrage
fachlich passende Themen entwirft. Das bleibt Generierungsverhalten, laut
`docs/evals/STRATEGY.md` fuer diese Komponente `structural` und ohne
`ANTHROPIC_API_KEY` nicht messbar. Zur Erinnerung, warum diese Grenze scharf
gezogen wird: `tests/test_issue_471_evidence_honesty.py`.

Die Datei liegt unter `tests/evals/`, weil sie `check_expected()` benutzt —
ausserhalb dieses Verzeichnisses ist das per Guard untersagt.
"""

from __future__ import annotations

import json

import pytest

from tests.evals.eval_runner import EVALS_ROOT, check_expected
from tests.test_topic_brainstorm import ISSUE_471_FIXED_TITLES

# Kriterien, wie sie vor dieser Fix-Runde in evals.json standen. Sie sind hier
# eingefroren, damit der Test zeigt, dass die neue Fassung tatsaechlich etwas
# aendert und nicht bloss anders formuliert ist.
PRE_FIX_CRITERIA = {
    "tb-04": {"type": "regex", "value": "(Fertigung|Maschinenbau|3D-Druck|additiv)"},
    "tb-05": {"type": "regex", "value": "(BWL|Betriebswirtschaft|Nachhaltigkeit)"},
}

_TABLE_HEADER = (
    "| # | Thema | Feasibility | Novelty | Career-Fit | Gesamt |\n"
    "|---|-------|-------------|---------|------------|--------|\n"
)


def _regression_answer(field_sentence: str) -> str:
    """Reproduziert die Antwort, die der Fixed-Set-Scorer vor #471 erzeugte.

    Bewusst der guenstigste Fall fuer den Bug: die Studienrichtung wird im
    Fliesstext aufgegriffen und die Rubrik-Tabelle des Skills ist vorhanden —
    nur die Themen selbst stammen aus der fachunabhaengigen Fixed-Liste.
    """
    rows = "".join(
        f"| {i} | {title} | 8.0/10 | 6.5/10 | 7.0/10 | 21.5/30 |\n"
        for i, title in enumerate(ISSUE_471_FIXED_TITLES, start=1)
    )
    return (
        f"## Topic-Kandidaten\n\n{field_sentence}\n\n"
        f"{_TABLE_HEADER}{rows}\n"
        f"**Empfehlung: {ISSUE_471_FIXED_TITLES[2]}** (Score: 21.5/30)\n"
    )


REGRESSION_ANSWERS = {
    "tb-04": _regression_answer(
        "Fuer dein Maschinenbau-Studium (Bachelor) mit Interesse an additiver "
        "Fertigung habe ich folgende Themen bewertet:"
    ),
    "tb-05": _regression_answer(
        "Fuer dein BWL-Studium mit Interesse an Nachhaltigkeit habe ich folgende Themen bewertet:"
    ),
}

# Satisfiability-Kontrollen: knappe, skill-konforme Antworten. Sie belegen
# ausschliesslich, dass die Kriterien ueberhaupt erfuellbar sind (kein Tippfehler
# im Regex, keine sich widersprechenden Forderungen) — sie sind KEIN Beleg fuer
# Modellverhalten, weil sie hier von Hand geschrieben stehen.
SATISFIABILITY_ANSWERS = {
    "tb-04": (
        "## Topic-Kandidaten\n\n"
        f"{_TABLE_HEADER}"
        "| 1 | Einfluss der Schichtdicke auf die Zugfestigkeit von SLM-Bauteilen "
        "| 8.0/10 | 6.5/10 | 8.0/10 | 22.5/30 |\n\n"
        "Begruendung: Prozessparameter und Werkstoffkennwerte sind Kernstoff des "
        "Maschinenbau-Bachelors; oeffentliche Messdatensaetze machen die Auswertung "
        "in sechs Monaten machbar.\n"
    ),
    "tb-05": (
        "## Topic-Kandidaten\n\n"
        f"{_TABLE_HEADER}"
        "| 1 | Wirkung der CSRD-Berichterstattung auf die Kennzahlensteuerung im "
        "Mittelstand | 7.5/10 | 7.0/10 | 8.5/10 | 23.0/30 |\n\n"
        "Begruendung: Nachhaltigkeitsberichterstattung verbindet Rechnungswesen und "
        "Controlling und ist damit unmittelbar an das BWL-Curriculum anschlussfaehig.\n"
    ),
}


def _criteria() -> dict[str, dict]:
    path = EVALS_ROOT / "topic-brainstorm" / "evals.json"
    return {p["id"]: p["expected"] for p in json.loads(path.read_text(encoding="utf-8"))["prompts"]}


@pytest.mark.parametrize("prompt_id", sorted(REGRESSION_ANSWERS))
def test_pre_fix_criteria_accepted_the_471_regression(prompt_id: str) -> None:
    """Ausgangsbefund, eingefroren: die alten Kriterien meldeten fuer den Bug PASS."""
    assert check_expected(REGRESSION_ANSWERS[prompt_id], PRE_FIX_CRITERIA[prompt_id]), (
        f"{prompt_id}: Der eingefrorene Ausgangsbefund stimmt nicht mehr — "
        "die Regressionsantwort passiert das alte Kriterium nicht mehr. "
        "Dann ist die Reproduktion falsch, nicht das Kriterium."
    )


@pytest.mark.parametrize("prompt_id", sorted(REGRESSION_ANSWERS))
def test_current_criteria_reject_the_471_regression(prompt_id: str) -> None:
    """Die Fach-Kontrast-Prompts muessen die Fixed-Set-Antwort durchfallen lassen."""
    assert not check_expected(REGRESSION_ANSWERS[prompt_id], _criteria()[prompt_id]), (
        f"{prompt_id}: Die fachunabhaengige Themenliste aus #471 besteht das "
        "Kriterium weiterhin. Dann misst dieser Prompt die Fachpassung nicht — "
        "er wuerde den Bug auch mit API-Key als PASS melden."
    )


@pytest.mark.parametrize("prompt_id", sorted(SATISFIABILITY_ANSWERS))
def test_current_criteria_are_satisfiable(prompt_id: str) -> None:
    """Gegenprobe zur Schaerfe: eine fachlich passende Antwort besteht.

    Zweck ist allein, unerfuellbare Kriterien auszuschliessen. Ueber die Guete
    realer Modellausgaben sagt dieser Test nichts.
    """
    assert check_expected(SATISFIABILITY_ANSWERS[prompt_id], _criteria()[prompt_id]), (
        f"{prompt_id}: Selbst eine fachlich passende, skill-konforme Antwort faellt "
        "durch — das Kriterium ist zu eng und wuerde mit API-Key nur Rauschen melden."
    )
