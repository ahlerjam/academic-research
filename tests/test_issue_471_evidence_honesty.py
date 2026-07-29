"""Ehrlichkeits-Guards fuer den AC1-Nachweis von Issue #471 (Fix-Runde zu PR #484).

Hintergrund — ausgefuehrte Gegenprobe, nicht Vermutung:

PR #484 ergaenzte `evals/topic-brainstorm/evals.json` um zwei Fach-Kontrast-
Prompts (tb-04 Maschinenbau, tb-05 BWL) und fuehrte anschliessend eine
Testklasse ein, die behauptete, AC1 sei damit "mit ausgefuehrten Tests belegt".
Der Nachweis war eine Tautologie: die Klasse bewertete vom Testautor selbst
geschriebene Kandidaten-Strings per `check_expected()` gegen genau die Regex,
auf die diese Strings geschrieben worden waren — durch einen Scorer, der
`title`/`keywords`/`reason` nachweislich unveraendert durchreicht.

Gegenprobe (ausgefuehrt): ersetzt man die Maschinenbau-Kandidaten durch die
fachfremden Cyber-Security-Themen der in diesem Issue geloeschten `_TOPIC_DB`
und schreibt lediglich das Wort "Maschinenbau" in jede `reason`, bleiben alle
fuenf Tests gruen. Der "Nachweis" konnte also genau den Bug nicht erkennen, um
den es in #471 geht.

Lehre, hier maschinell festgehalten:

1. `check_expected()` bewertet **Modell-Ausgaben**. Wird es auf Fixtures
   angewendet, die derselbe Autor geschrieben hat, misst es nichts.
2. Fuer eine Komponente, die `docs/evals/STRATEGY.md` als `structural`
   (API-gated, ohne Key Skip) fuehrt, darf das CHANGELOG nicht behaupten, ihr
   Modellverhalten sei durch ausgefuehrte Tests belegt.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_ROOT = REPO_ROOT / "tests"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
STRATEGY = REPO_ROOT / "docs" / "evals" / "STRATEGY.md"

_SELF = Path(__file__).name

# Formulierungen, die einen ausgefuehrten Beleg fuer Modellverhalten behaupten.
_EXECUTED_PROOF_CLAIM = re.compile(r"ausgef[uü]hrte[nrs]?\s+Tests?\s+bele(?:gt|gen|gbar)", re.I)

# Statustabelle aus STRATEGY.md: | `komponente` | status | pfad | begruendung |
_STRATEGY_ROW = re.compile(
    r"^\|\s*`([^`]+)`\s*\|\s*([a-z]+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$", re.M
)


def _structural_components() -> set[str]:
    text = STRATEGY.read_text(encoding="utf-8")
    return {
        name
        for name, status, _path, _reason in _STRATEGY_ROW.findall(text)
        if status == "structural"
    }


def test_eval_expectations_do_not_grade_self_authored_fixtures() -> None:
    """`check_expected()` gehoert zu Modell-Ausgaben, nicht zu Test-Fixtures.

    Ausserhalb von `tests/evals/` gibt es keine Modell-Ausgabe zu bewerten — dort
    kann die Funktion nur eigene Fixtures gegen eigene Erwartungen pruefen und
    erzeugt so den Anschein eines Eval-Ergebnisses, das nie gelaufen ist.
    """
    offenders: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        if path.name == _SELF:
            continue
        if "evals" in path.relative_to(TESTS_ROOT).parts:
            continue
        if "check_expected" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "check_expected() aus tests/evals/eval_runner.py bewertet Modell-Ausgaben. "
        f"Ausserhalb von tests/evals/ verwendet in: {offenders}. Dort bewertet es "
        "zwangslaeufig selbstgeschriebene Fixtures gegen selbstgeschriebene "
        "Erwartungen (Tautologie, siehe Modul-Docstring)."
    )


def test_changelog_claims_no_executed_proof_for_structural_components() -> None:
    """Was `structural` ist, darf im CHANGELOG nicht als ausgefuehrt belegt gelten."""
    structural = _structural_components()
    assert structural, "STRATEGY.md liefert keine structural-Zeilen — Parser oder Doku kaputt."

    violations: list[str] = []
    for lineno, line in enumerate(CHANGELOG.read_text(encoding="utf-8").splitlines(), start=1):
        if not _EXECUTED_PROOF_CLAIM.search(line):
            continue
        named = sorted(
            c for c in structural if re.search(rf"(?<![\w-]){re.escape(c)}(?![\w-])", line)
        )
        if named:
            violations.append(f"CHANGELOG.md:{lineno} nennt {named}")
    assert not violations, (
        "CHANGELOG behauptet einen ausgefuehrten Test-Beleg fuer Komponenten, die "
        "docs/evals/STRATEGY.md als 'structural' (API-gated, ohne Key Skip) fuehrt: "
        f"{violations}. Entweder die Komponente auf 'metric' heben (echter "
        "Offline-Runner) oder die Aussage auf das beschraenken, was wirklich laeuft."
    )
