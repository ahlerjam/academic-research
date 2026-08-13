"""Feste Smoke-Stichprobe fuer den taeglichen Eval-Lauf (Issue #848).

Die woechentliche Rotation in `eval-behavior.yml` (Issue #597, `-m
eval_core_set`) deckt jeden Fall nur alle vier Wochen ab -- ein Modell- oder
Harness-Drift in einer gerade nicht rotierten Gruppe bliebe bis zu drei
Wochen unsichtbar. Der taegliche Smoke-Lauf schliesst diese Luecke mit einer
kleinen, FEST committeten Stichprobe auf Testfall-Ebene (nicht Datei-Ebene
wie `eval_core_set` -- ein Datei-Marker waere hier zu grobkoernig, siehe
Plan-Kommentar zu #848).

``SMOKE_SET_NODE_IDS`` ist die **eine Stelle**, an der diese Stichprobe
steht -- der taegliche Workflow-Zweig in `eval-behavior.yml` uebergibt sie
pytest direkt als Positions-Argumente (keine `-k`-Ausdrucks-Fragilitaet).
Der Collect-Only-Guard `test_eval_smoke_set_matches_documented_cases` in
`tests/evals/test_eval_strategy.py` haelt diese Liste gegen einen echten
Collect-Lauf -- eine Umbenennung/Parametrisierungs-Aenderung faellt dort auf,
statt den Smoke-Lauf lautlos leerlaufen zu lassen (genau das Muster aus
Issue #470/#824).

Auswahl-Begruendung je Fall in ``SMOKE_SET_REASONS`` unten. Kandidaten
bewusst NICHT woertlich aus dem Issue-Text uebernommen: "Verbatim-Guard" ist
laut `docs/evals/STRATEGY.md` `metric`, also nicht API-gated und misst
keinen Modell-Drift (dieselbe Korrektur wie schon bei #597).

Wichtig fuer den Workflow: `test_should_trigger_recall`/
`test_should_not_trigger_fpr` in `test_triggers.py` sind ueber
`EVAL_TRIGGER_ROTATION_GROUP` parametrisiert -- diese Node-IDs existieren nur,
wenn die Collection mit `EVAL_TRIGGER_ROTATION_GROUP=all` laeuft (voller
45-Skill-Satz). Der taegliche Workflow-Zweig setzt das explizit, unabhaengig
von der woechentlichen ISO-Wochen-Rotation.
"""

from __future__ import annotations

#: Feste Node-ID-Liste, direkt als pytest-Positionsargumente nutzbar. Drei
#: Skills aus `test_triggers.py` (je Recall + FPR = 6 Faelle) plus zwei
#: funktionale Faelle aus `test_rest_evals.py` (`with_skill`-Modus) -- macht
#: acht Faelle, innerhalb der im Issue vorgegebenen Groessenordnung 5-10.
SMOKE_SET_NODE_IDS: tuple[str, ...] = (
    "tests/evals/test_triggers.py::test_should_trigger_recall[academic-context]",
    "tests/evals/test_triggers.py::test_should_not_trigger_fpr[academic-context]",
    "tests/evals/test_triggers.py::test_should_trigger_recall[citation-extraction]",
    "tests/evals/test_triggers.py::test_should_not_trigger_fpr[citation-extraction]",
    "tests/evals/test_triggers.py::test_should_trigger_recall[chapter-writer]",
    "tests/evals/test_triggers.py::test_should_not_trigger_fpr[chapter-writer]",
    "tests/evals/test_rest_evals.py::test_rest_eval[with_skill-academic-context-ac-01]",
    "tests/evals/test_rest_evals.py::test_rest_eval[with_skill-advisor-ad-01]",
)

#: Menschenlesbare Begruendung je Fall (Plan-Vorgabe zu #848: "Node-IDs +
#: Begruendung je Fall"). Schluessel sind volle Node-IDs, damit die Zuordnung
#: robust gegen Reihenfolge-Aenderungen von SMOKE_SET_NODE_IDS bleibt.
SMOKE_SET_REASONS: dict[str, str] = {
    "tests/evals/test_triggers.py::test_should_trigger_recall[academic-context]": (
        "academic-context ist die von allen REST_SKILLS gemeinsam genutzte "
        "Preamble (Issue #830) -- ein Trigger-Ausfall hier waere ein "
        "Grundlagen-Signal, nicht nur ein Einzelskill-Problem."
    ),
    "tests/evals/test_triggers.py::test_should_not_trigger_fpr[academic-context]": (
        "Gegenstueck zum Recall-Fall oben -- Overtriggering derselben "
        "Grundlagen-Skill waere ebenso ein Grundlagen-Signal."
    ),
    "tests/evals/test_triggers.py::test_should_trigger_recall[citation-extraction]": (
        "citation-extraction ist ein Kernworkflow-Skill mit hoher Nutzungs-"
        "Erwartung; Undertriggering faellt Nutzern sofort auf."
    ),
    "tests/evals/test_triggers.py::test_should_not_trigger_fpr[citation-extraction]": (
        "Gegenstueck zum Recall-Fall oben."
    ),
    "tests/evals/test_triggers.py::test_should_trigger_recall[chapter-writer]": (
        "chapter-writer ist Teil des bestehenden eval_core_set (Datei-Ebene) "
        "und einer der teuersten/kritischsten Generierungs-Skills -- ein "
        "guter Kanarienvogel fuer Modell-Drift auf Testfall-Ebene."
    ),
    "tests/evals/test_triggers.py::test_should_not_trigger_fpr[chapter-writer]": (
        "Gegenstueck zum Recall-Fall oben."
    ),
    "tests/evals/test_rest_evals.py::test_rest_eval[with_skill-academic-context-ac-01]": (
        "Funktionaler (nicht nur Trigger-)Check derselben Grundlagen-Skill --"
        " deckt einen anderen Fehlermodus ab (Skill-Inhalt/Ausgabe statt "
        "Klassifikation)."
    ),
    "tests/evals/test_rest_evals.py::test_rest_eval[with_skill-advisor-ad-01]": (
        "Repraesentativer funktionaler Fall aus den restlichen 9 Skills "
        "(test_rest_evals.py), unabhaengig von academic-context."
    ),
}

assert set(SMOKE_SET_REASONS) == set(SMOKE_SET_NODE_IDS), (
    "SMOKE_SET_REASONS und SMOKE_SET_NODE_IDS sind auseinandergelaufen -- jede "
    "Node-ID braucht genau eine Begruendung (Issue #848)."
)
