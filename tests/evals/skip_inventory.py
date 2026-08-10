"""Skip-Inventar der vault-abhaengigen Eval-Suiten + Guard (Issue #824).

Warum ueberhaupt ein Inventar? Der bestehende Guard
``tests/evals/test_eval_strategy.py::test_skip_count_matches_real_pytest_run``
**deaktiviert sich selbst, sobald die claude-CLI verfuegbar ist** -- also
genau im geplanten OAuth-Lauf, in dem ein neuer Dauer-Skip entstuende. Ein
gruener Lauf mit stillen Dauer-Skips meldet damit nie wieder etwas; genau
das Muster, das Issue #470 im Repo schon einmal behoben hat ("taeuschend
gruen, 0 real geprueft, N geskippt").

Dieses Modul schliesst die Luecke von der anderen Seite:

* Jeder bewusste Skip in ``test_quote_extractor_evals.py`` /
  ``test_chapter_writer_evals.py`` traegt eine **maschinell erkennbare**
  Begruendung mit dem Praefix ``eval-skip:``.
* ``SKIP_INVENTORY`` listet jeden davon namentlich (Node-ID -> Grund +
  Begruendungsverweis).
* ``check_skip_inventory()`` haelt eine echte JUnit-XML dagegen: ein
  zusaetzlicher Skip **oder** ein fehlender Eintrag ist ein Befund.

Der Guard greift damit **mit** installierter CLI (invers zum Zaehl-Guard
oben) und faerbt den CLI-losen ``pytest tests/``-Lauf nicht rot -- dort
skippt ohnehin alles mit "claude-CLI nicht verfuegbar".
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

#: Praefix jeder maschinell erkennbaren Skip-Begruendung. Ein Skip ohne
#: dieses Praefix gilt als Umgebungsrauschen (fehlende CLI, fehlende
#: evals.json) und wird vom Guard nicht bewertet.
EVAL_SKIP_PREFIX = "eval-skip:"

#: Suiten, deren Skip-Menge dieses Inventar abdeckt. Skips ausserhalb dieser
#: Dateien sind nicht Gegenstand des Guards (andere Suiten haben eigene
#: Vorbedingungen).
GOVERNED_SUITES = (
    "tests/evals/test_quote_extractor_evals.py",
    "tests/evals/test_chapter_writer_evals.py",
)


def mode_mismatch_reason(case_id: str, mode: str) -> str:
    """Skip-Grund fuer einen Fall, der laut ``evals.json`` diesen Mode nicht kennt."""
    return (
        f"{EVAL_SKIP_PREFIX}mode-mismatch Prompt {case_id} ist in evals.json nicht "
        f"fuer Mode {mode} definiert"
    )


def net_excluded_reason(case_id: str) -> str:
    """Skip-Grund fuer einen Fall, der echten Netz-Egress voraussetzt."""
    return (
        f"{EVAL_SKIP_PREFIX}net-excluded Prompt {case_id} setzt Live-Abruf einer Quelle "
        f"voraus; Netz-Egress in Evals waere nichtdeterministisch "
        f"(docs/evals/STRATEGY.md, Abschnitt 'Sitzungsprofile', Profil net-excluded)"
    )


#: Faelle, die trotz gebundener Test-Vault uebersprungen bleiben -- mit Grund.
#: ``qe-04`` ist der einzige: er scheitert nicht am Vault, sondern an
#: fehlenden Web-Werkzeugen. Die Entscheidung (nicht Netz freigeben, sondern
#: dokumentiert ueberspringen) steht in docs/evals/STRATEGY.md.
NET_EXCLUDED_CASES = ("qe-04",)


@dataclass(frozen=True)
class SkipEntry:
    """Ein erwarteter Skip: Node-ID, Grund und wo die Entscheidung steht."""

    node_id: str
    reason: str
    decision_reference: str


def _quote_extractor_entries() -> list[SkipEntry]:
    suite = "tests/evals/test_quote_extractor_evals.py::test_quote_extractor_eval"
    entries: list[SkipEntry] = []
    # qe-01/02/03/05 sind in evals.json nur fuer with_skill definiert.
    for case_id in ("qe-01", "qe-02", "qe-03", "qe-05"):
        entries.append(
            SkipEntry(
                node_id=f"{suite}[without_skill-{case_id}]",
                reason=mode_mismatch_reason(case_id, "without_skill"),
                decision_reference="evals/quote-extractor/evals.json (mode: with_skill)",
            )
        )
    # qe-04 laeuft laut evals.json in beiden Modi, bleibt aber net-excluded.
    for mode in ("with_skill", "without_skill"):
        entries.append(
            SkipEntry(
                node_id=f"{suite}[{mode}-qe-04]",
                reason=net_excluded_reason("qe-04"),
                decision_reference=(
                    "docs/evals/STRATEGY.md, 'Entscheidung fuer die zehn "
                    "Widerspruchsfaelle' (#830) + Issue #824 Scope 4"
                ),
            )
        )
    return entries


def _chapter_writer_entries() -> list[SkipEntry]:
    suite = "tests/evals/test_chapter_writer_evals.py::test_chapter_writer_eval"
    return [
        SkipEntry(
            node_id=f"{suite}[without_skill-{case_id}]",
            reason=mode_mismatch_reason(case_id, "without_skill"),
            decision_reference="evals/chapter-writer/evals.json (mode: with_skill)",
        )
        for case_id in ("cw-02", "cw-04", "cw-05", "cw-vault-01")
    ]


#: Node-ID -> erwarteter Skip. Die eine Stelle, an der ein Dauer-Skip als
#: Entscheidung dokumentiert ist -- ohne Eintrag hier ist ein Skip ein Befund.
SKIP_INVENTORY: dict[str, SkipEntry] = {
    entry.node_id: entry for entry in _quote_extractor_entries() + _chapter_writer_entries()
}


def _node_id(classname: str, name: str) -> str:
    """Baut aus JUnit-``classname``/``name`` die pytest-Node-ID."""
    return classname.replace(".", "/") + ".py::" + name


def parse_skipped(junit_path: Path) -> dict[str, str]:
    """Liest alle uebersprungenen Tests einer JUnit-XML als ``{node_id: message}``."""
    root = ET.parse(junit_path).getroot()
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
    skipped: dict[str, str] = {}
    for suite in suites:
        for case in suite.findall("testcase"):
            element = case.find("skipped")
            if element is None:
                continue
            classname = case.get("classname", "")
            name = case.get("name", "")
            skipped[_node_id(classname, name)] = element.get("message", "")
    return skipped


def _present_governed_suites(junit_path: Path) -> set[str]:
    """Liefert die ``GOVERNED_SUITES``-Eintraege, die im Lauf ueberhaupt Testcases haben.

    Ein gefilterter Lauf (``workflow_dispatch`` mit ``component``-Input, z.B.
    ``pytest -k "quote_extractor"``) fuehrt nur eine Teilmenge der Suiten aus
    -- die JUnit-XML enthaelt fuer die nicht ausgewaehlten Suiten dann gar
    keine Testcases, weder bestanden noch uebersprungen. Das ist kein Befund
    fuer die Richtung "inventarisierter Skip fehlt im Lauf" (Issue #824,
    P1-Review-Finding zu .github/workflows/eval-behavior.yml:205): die Suite
    ist nicht fehlgeschlagen, sie war schlicht nicht Teil des Laufs.
    """
    root = ET.parse(junit_path).getroot()
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
    present: set[str] = set()
    for suite in suites:
        for case in suite.findall("testcase"):
            node_id = _node_id(case.get("classname", ""), case.get("name", ""))
            for governed in GOVERNED_SUITES:
                if node_id.startswith(governed):
                    present.add(governed)
    return present


def check_skip_inventory(junit_path: Path) -> list[str]:
    """Haelt die Skip-Menge eines echten Laufs gegen ``SKIP_INVENTORY``.

    Bewertet werden ausschliesslich Skips aus ``GOVERNED_SUITES``, deren
    Meldung mit ``eval-skip:`` beginnt -- Umgebungs-Skips (fehlende CLI,
    fehlende evals.json) bleiben aussen vor, sonst waere der Guard im
    CLI-losen Lauf dauerhaft rot.

    Die Richtung "inventarisierter Skip fehlt im Lauf" wird nur fuer Suiten
    geprueft, die im Lauf ueberhaupt Testcases haben (``_present_governed_
    suites``) -- ein gefilterter ``workflow_dispatch``-Lauf (``component``-
    Input) fuehrt sonst faelschlich zu vier bzw. sechs Befunden fuer die
    Suite, die er gar nicht ausgewaehlt hat.

    Returns:
        Liste der Befunde (leer = Skip-Menge entspricht dem Inventar).
    """
    actual = {
        node_id: message
        for node_id, message in parse_skipped(junit_path).items()
        if node_id.startswith(GOVERNED_SUITES) and message.startswith(EVAL_SKIP_PREFIX)
    }
    present_suites = _present_governed_suites(junit_path)
    problems: list[str] = []
    for node_id in sorted(set(actual) - set(SKIP_INVENTORY)):
        problems.append(
            f"Nicht inventarisierter Skip: {node_id} -- Grund {actual[node_id]!r}. "
            f"Entweder den Fall reparieren oder ihn in tests/evals/skip_inventory.py "
            f"mit Begruendung eintragen (Issue #824)."
        )
    for node_id in sorted(set(SKIP_INVENTORY) - set(actual)):
        if not any(node_id.startswith(governed) for governed in present_suites):
            continue
        problems.append(
            f"Inventarisierter Skip fehlt im Lauf: {node_id}. Wenn der Fall jetzt "
            f"echt laeuft, gehoert der Eintrag aus tests/evals/skip_inventory.py "
            f"entfernt (Issue #824)."
        )
    for node_id in sorted(set(actual) & set(SKIP_INVENTORY)):
        expected = SKIP_INVENTORY[node_id].reason
        if actual[node_id] != expected:
            problems.append(
                f"Skip-Grund weicht ab fuer {node_id}: erwartet {expected!r}, "
                f"gemeldet {actual[node_id]!r}."
            )
    return problems
