"""Guard fuer das Eval-Strategiedokument (Issue #390).

``docs/evals/STRATEGY.md`` legt fuer JEDE Komponente unter ``evals/`` offen,
woran sie tatsaechlich gemessen wird. Ohne diesen Guard waere das Dokument
Prosa, die beim naechsten neuen Eval-Verzeichnis still veraltet — genau die
Sorte stillschweigender Luecke, die Issue #390 beseitigt.

Geprueft wird deshalb die Tabelle gegen das Dateisystem, nicht nur ihre Existenz:
Vollstaendigkeit in beide Richtungen, Status-Vokabular, Pflicht-Begruendung,
Existenz der genannten Runner — plus, dass kein neuer Runner API-Budget kostet.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from tests.evals.eval_runner import claude_cli_available
from tests.evals.smoke_set import SMOKE_SET_NODE_IDS

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
STRATEGY_PATH = REPO_ROOT / "docs" / "evals" / "STRATEGY.md"
EVALS_ROOT = REPO_ROOT / "evals"

VALID_STATUS = {"metric", "structural", "removed"}
MIN_REASON_CHARS = 20


def eval_dirs() -> set[str]:
    """Alle Komponenten-Verzeichnisse unter evals/ (Datenbasis der Tabelle)."""
    return {
        p.name for p in EVALS_ROOT.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))
    }


def _strategy_text() -> str:
    assert STRATEGY_PATH.exists(), f"Strategiedokument fehlt: {STRATEGY_PATH} (Issue #390, AC1)."
    return STRATEGY_PATH.read_text(encoding="utf-8")


def parse_rows(text: str) -> dict[str, dict[str, str]]:
    """Parst die Statustabelle: ``| `komponente` | status | pfad | begruendung |``.

    Bewusst strikt — eine Zeile, die das Format verletzt, wird nicht erkannt und
    faellt damit im Vollstaendigkeits-Test auf, statt still durchzurutschen.
    """
    row_re = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*([a-z]+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$", re.M)
    rows: dict[str, dict[str, str]] = {}
    for name, status, path, reason in row_re.findall(text):
        assert name not in rows, f"Doppelte Tabellenzeile fuer '{name}' in STRATEGY.md."
        rows[name] = {"status": status, "path": path, "reason": reason}
    return rows


@pytest.fixture(scope="module")
def strategy_text() -> str:
    return _strategy_text()


@pytest.fixture(scope="module")
def rows(strategy_text: str) -> dict[str, dict[str, str]]:
    return parse_rows(strategy_text)


# ---------------------------------------------------------------------------
# AC1: Fuer jede evals/-Komponente ist ein Zustand benannt.
# ---------------------------------------------------------------------------


def test_every_eval_dir_has_exactly_one_status(rows):
    """Set-Gleichheit: evals/-Verzeichnisse <-> Tabellenzeilen (ohne ``removed``)."""
    documented = {name for name, row in rows.items() if row["status"] != "removed"}
    on_disk = eval_dirs()
    missing = on_disk - documented
    stale = documented - on_disk
    assert not missing, (
        f"Ohne Eintrag in docs/evals/STRATEGY.md: {sorted(missing)} — jede "
        f"evals/-Komponente braucht einen benannten Zustand (Issue #390, AC1)."
    )
    assert not stale, (
        f"STRATEGY.md nennt Komponenten, die es unter evals/ nicht (mehr) gibt: "
        f"{sorted(stale)}. Status auf 'removed' setzen oder Zeile streichen."
    )


def test_all_37_components_are_covered(rows):
    """Die Tabelle deckt den vollstaendigen Bestand ab — keine stille Teilmenge."""
    active = [name for name, row in rows.items() if row["status"] != "removed"]
    assert len(active) == len(eval_dirs()), (
        f"{len(active)} aktive Tabellenzeilen vs. {len(eval_dirs())} evals/-Verzeichnisse."
    )


def test_status_vocabulary_is_closed(rows):
    """Nur ``metric`` / ``structural`` / ``removed`` — kein schwammiges Zwischenwort."""
    for name, row in rows.items():
        assert row["status"] in VALID_STATUS, (
            f"{name}: ungueltiger Status {row['status']!r}; erlaubt: {sorted(VALID_STATUS)}."
        )


def test_structural_rows_carry_a_reason(rows):
    """``structural`` ist nur mit Begruendung zulaessig — sonst ist es ein stiller Schema-Check."""
    for name, row in rows.items():
        if row["status"] != "structural":
            continue
        assert len(row["reason"]) >= MIN_REASON_CHARS, (
            f"{name}: Status 'structural' ohne belastbare Begruendung "
            f"(>= {MIN_REASON_CHARS} Zeichen), gefunden: {row['reason']!r}."
        )


def test_metric_rows_point_to_existing_runner(rows):
    """``metric`` verlangt einen real existierenden Ausfuehrungspfad im Repo."""
    for name, row in rows.items():
        if row["status"] != "metric":
            continue
        referenced = re.findall(r"`([^`]+)`", row["path"])
        assert referenced, f"{name}: Status 'metric' ohne genannten Ausfuehrungspfad."
        for rel in referenced:
            assert (REPO_ROOT / rel).exists(), (
                f"{name}: genannter Ausfuehrungspfad '{rel}' existiert nicht."
            )


def test_removed_components_are_absent_from_disk(rows):
    """Als ``removed`` gefuehrte Komponenten duerfen nicht mehr unter evals/ liegen."""
    for name, row in rows.items():
        if row["status"] != "removed":
            continue
        assert not (EVALS_ROOT / name).exists(), (
            f"{name}: als 'removed' dokumentiert, liegt aber noch unter evals/."
        )


def test_no_eval_dir_lacks_both_metric_and_reason(rows):
    """Querschnitt: keine Komponente ohne Ausfuehrungspfad UND ohne Begruendung."""
    for name in sorted(eval_dirs()):
        row = rows[name]
        has_path = bool(re.findall(r"`([^`]+)`", row["path"]))
        has_reason = len(row["reason"]) >= MIN_REASON_CHARS
        assert has_path or has_reason, (
            f"{name}: weder Ausfuehrungspfad noch Begruendung — genau die Luecke, "
            f"die Issue #390 schliesst."
        )


# ---------------------------------------------------------------------------
# AC2: Die beiden vormals toten Definitionen haben einen echten Runner.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("component", ["auto-download", "humanizer-de-pipeline"])
def test_formerly_dead_definitions_are_wired_or_removed(component, rows):
    """auto-download und humanizer-de-pipeline: entweder ``metric`` oder ``removed``."""
    row = rows[component]
    assert row["status"] in {"metric", "removed"}, (
        f"{component}: Status {row['status']!r} — AC2 verlangt einen echten "
        f"Ausfuehrungspfad ('metric') oder die Entfernung ('removed')."
    )


# ---------------------------------------------------------------------------
# AC3 / AC4: Pflichtabschnitte des Dokuments.
# ---------------------------------------------------------------------------


def test_strategy_documents_issue_55(strategy_text):
    """AC3: Das Dokument haelt fest, dass Alt-Issue #55 von #390 absorbiert wurde."""
    assert "## Alt-Issue #55" in strategy_text, (
        "STRATEGY.md braucht einen Abschnitt '## Alt-Issue #55' (Issue #390, AC3)."
    )
    section = strategy_text.split("## Alt-Issue #55", 1)[1].split("\n## ", 1)[0]
    assert "#390" in section, "Der #55-Abschnitt muss auf #390 verweisen."
    assert "geschlossen" in section.lower(), "Der #55-Abschnitt muss den Schliess-Status benennen."


def test_strategy_names_api_budget_as_operator_decision(strategy_text):
    """AC4: Budgetbedarf ist beziffert und ausdruecklich als Operator-Entscheid markiert."""
    assert "## API-Budget" in strategy_text, (
        "STRATEGY.md braucht einen Abschnitt '## API-Budget' (Issue #390, AC4)."
    )
    section = strategy_text.split("## API-Budget", 1)[1].split("\n## ", 1)[0]
    assert "Operator" in section, (
        "Der API-Budget-Abschnitt muss die Entscheidung ausdruecklich dem Operator zuordnen."
    )
    assert re.search(r"\d", section), (
        "Der API-Budget-Abschnitt muss eine Groessenordnung beziffern (Calls/Kosten)."
    )
    assert "CLAUDE_CODE_OAUTH_TOKEN" in section, (
        "Der API-Budget-Abschnitt muss benennen, woran die realen Laeufe haengen "
        "(seit Issue #716: OAuth-Session/claude-CLI via CLAUDE_CODE_OAUTH_TOKEN, "
        "kein ANTHROPIC_API_KEY mehr)."
    )


def test_strategy_states_the_skip_count_honestly(strategy_text):
    """Ehrlichkeitsfalle: ``structural`` darf nicht als 'gruen' verkauft werden."""
    assert "skip" in strategy_text.lower(), (
        "STRATEGY.md muss offenlegen, dass die API-gateten Evals weiterhin skippen."
    )


# ---------------------------------------------------------------------------
# Issue #619: Die Bilanzzeile und die Skip-Zahl sind Prosa ueber pruefbare
# Zahlen — der Guard muss sie gegen die Tabelle bzw. einen echten Lauf halten,
# statt sie nur auf das Wort "skip" zu pruefen (das faengt keine veraltete
# Zahl).
# ---------------------------------------------------------------------------


def _parse_balance_line(text: str) -> tuple[int, int, int]:
    match = re.search(
        r"\*\*Bilanz:\*\*\s*(\d+)\s*×\s*`metric`,\s*(\d+)\s*×\s*`structural`,"
        r"\s*(\d+)\s*×\s*`removed`",
        text,
    )
    assert match, "STRATEGY.md: Bilanzzeile nicht im erwarteten Format gefunden (Issue #619)."
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def test_balance_line_matches_table_counts(strategy_text, rows):
    """Die Bilanzzeile muss der tatsaechlichen Tabelle entsprechen (Issue #619)."""
    doc_metric, doc_structural, doc_removed = _parse_balance_line(strategy_text)
    counts = Counter(row["status"] for row in rows.values())
    assert doc_metric == counts.get("metric", 0), (
        f"Bilanzzeile nennt {doc_metric} × metric, Tabelle hat "
        f"{counts.get('metric', 0)} (Issue #619)."
    )
    assert doc_structural == counts.get("structural", 0), (
        f"Bilanzzeile nennt {doc_structural} × structural, Tabelle hat "
        f"{counts.get('structural', 0)} (Issue #619)."
    )
    assert doc_removed == counts.get("removed", 0), (
        f"Bilanzzeile nennt {doc_removed} × removed, Tabelle hat "
        f"{counts.get('removed', 0)} (Issue #619)."
    )


def _current_skip_sentence(text: str) -> str:
    marker = "Heutiger Stand"
    idx = text.find(marker)
    assert idx != -1, (
        "STRATEGY.md braucht einen als 'Heutiger Stand' markierten Satz mit der "
        "aktuellen passed/skipped-Zahl (Issue #619)."
    )
    return text[idx : idx + 400]


# ---------------------------------------------------------------------------
# Issue #677: Die strikte Gleichheit auf die 'passed'-Zahl kostete einen
# Zwangs-Commit pro main-Merge, weil jeder neue (gruene) Test unter
# tests/evals/ diesen Guard rot faerbte, ohne dass STRATEGY.md je angefasst
# wurde. Die Kern-Vergleichslogik ist deshalb in pure Helper-Funktionen
# extrahiert, die ohne echten Subprozess-Lauf unit-testbar sind. Die
# 'passed'-Assertion wird auf eine Untergrenze gelockert (echte Regressionen
# bleiben rot); die 'skipped'-Gleichheit bleibt scharf.
# ---------------------------------------------------------------------------

_ENV_KEYS_TO_STRIP_EXACT = {"RUN_LIVE_NLI_PREFILTER"}


def _clean_subprocess_env() -> dict[str, str]:
    """Kopie von ``os.environ`` ohne live-gatete/Coverage-Core-Variablen.

    ``RUN_LIVE_NLI_PREFILTER`` wuerde ~1 GB Modellgewichte in den 120s-Timeout
    dieses Guards laden (Issue #677); ``COV_CORE_*`` stammt aus einem
    coverage-Lauf des AEUSSEREN pytest-Prozesses und wuerde den INNEREN Lauf
    stoeren, wenn es vererbt wird.
    """
    env = dict(os.environ)
    for key in list(env):
        if key in _ENV_KEYS_TO_STRIP_EXACT or key.startswith("COV_CORE_"):
            del env[key]
    return env


def _last_summary_line(stdout: str) -> str | None:
    """Verankert auf die pytest-Abschlusszeile (``N passed[, M skipped] in Ts``).

    Verhindert, dass eine Zahl aus einem Traceback oder einer FAILURES-Sektion
    als Summary fehlinterpretiert wird (Issue #677, P2-Finding aus PR #664).
    """
    candidates = [
        line
        for line in stdout.splitlines()
        if re.search(r"\bin\s[\d.]+s\b", line) and re.search(r"\d+\s+\w+", line)
    ]
    return candidates[-1] if candidates else None


def _diagnose_or_compare(
    *, returncode: int, stdout: str, doc_passed: int, doc_skipped: int
) -> None:
    """Pure Vergleichslogik, extrahiert fuer Unit-Tests (Issue #677).

    Meldet einen echten Testfehler des inneren Laufs als Testfehler, nicht als
    Doku-Mismatch. Prueft die ``passed``-Zahl nur noch als Untergrenze, die
    ``skipped``-Zahl weiterhin per Gleichheit.
    """
    summary_line = _last_summary_line(stdout)
    if returncode != 0:
        raise AssertionError(
            f"Innerer pytest-Lauf (tests/evals/) ist fehlgeschlagen (returncode="
            f"{returncode}): {summary_line or stdout[-500:]!r}. Das ist ein "
            "Testfehler in tests/evals/, kein veralteter Doku-Wert (Issue #677)."
        )

    assert summary_line, f"Konnte pytest-Summary-Zeile nicht finden:\n{stdout}"
    passed_match = re.search(r"(\d+) passed", summary_line)
    skipped_match = re.search(r"(\d+) skipped", summary_line)
    assert passed_match, f"Summary-Zeile ohne 'passed': {summary_line!r}"
    inner_passed = int(passed_match.group(1))
    inner_skipped = int(skipped_match.group(1)) if skipped_match else 0

    assert inner_passed + 1 >= doc_passed, (
        f"Dokumentiert: {doc_passed} passed. Realer Lauf (ohne diesen Test): "
        f"{inner_passed} passed (+1 fuer diesen Test = {inner_passed + 1}) liegt "
        "darunter — das ist eine echte Regression, nicht nur ein neuer Test "
        "(Issue #677)."
    )
    assert inner_skipped == doc_skipped, (
        f"Dokumentiert: {doc_skipped} skipped. Realer Lauf: {inner_skipped} skipped (Issue #619)."
    )


def _run_inner_pytest(deselect_nodeid: str) -> subprocess.CompletedProcess[str]:
    """Fuehrt den inneren ``tests/evals/``-Lauf mit bereinigter Umgebung aus."""
    env = _clean_subprocess_env()
    try:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/evals/",
                "--deselect",
                deselect_nodeid,
                "-p",
                "no:cacheprovider",
                "-q",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            "Innerer pytest-Lauf (tests/evals/) hat das 120s-Timeout ueberschritten "
            f"(Issue #677), statt mit Roh-Traceback zu sterben: {exc}"
        )


def test_skip_count_matches_real_pytest_run(strategy_text, request):
    """Die dokumentierte Skip-Zahl muss zu einem echten Lauf passen (Issue #619)."""
    if claude_cli_available():
        pytest.skip(
            "Mit installierter claude-CLI (Issue #631, CLI-Aufrufweg in "
            "eval_runner.call_claude, seit #716 der einzige Weg) laufen deutlich "
            "weniger Tests still durch/echt statt zu skippen; die dokumentierte "
            "Zahl gilt nur fuer den Lauf ohne CLI."
        )
    sentence = _current_skip_sentence(strategy_text)
    match = re.search(r"(\d+)\s*passed,\s*(\d+)\s*skipped", sentence)
    assert match, (
        f"Keine 'N passed, M skipped'-Angabe im 'Heutiger Stand'-Satz gefunden: {sentence!r}"
    )
    doc_passed, doc_skipped = int(match.group(1)), int(match.group(2))

    result = _run_inner_pytest(request.node.nodeid)
    _diagnose_or_compare(
        returncode=result.returncode,
        stdout=result.stdout,
        doc_passed=doc_passed,
        doc_skipped=doc_skipped,
    )


# ---------------------------------------------------------------------------
# Unit-Tests fuer die extrahierten Helper (Issue #677) — laufen ohne echten
# Subprozess-Lauf, decken AC1/AC2 der Vergleichslogik direkt ab.
# ---------------------------------------------------------------------------


def test_diagnose_or_compare_accepts_extra_passed_test():
    """AC1: ein zusaetzlicher gruener Test (mehr passed als dokumentiert) faerbt nicht rot."""
    _diagnose_or_compare(
        returncode=0, stdout="100 passed in 1.23s\n", doc_passed=101, doc_skipped=0
    )  # darf nicht raisen


def test_diagnose_or_compare_reports_inner_failure_not_doc_mismatch():
    """AC2: ein Fehlschlag-Returncode meldet den Testfehler, nicht einen Doku-Mismatch."""
    with pytest.raises(AssertionError) as exc_info:
        _diagnose_or_compare(
            returncode=1,
            stdout="1 failed, 273 passed in 3.21s\n",
            doc_passed=274,
            doc_skipped=194,
        )
    message = str(exc_info.value)
    assert "Testfehler" in message
    assert "Dokumentiert" not in message


def test_diagnose_or_compare_still_fails_on_fewer_passed():
    """Untergrenze bleibt eine Grenze: weniger passed als dokumentiert ist weiterhin rot."""
    with pytest.raises(AssertionError):
        _diagnose_or_compare(
            returncode=0, stdout="273 passed in 1.00s\n", doc_passed=300, doc_skipped=0
        )


def test_diagnose_or_compare_still_fails_on_skip_mismatch():
    """Die Skip-Zahl bleibt scharf per Gleichheit geprueft."""
    with pytest.raises(AssertionError):
        _diagnose_or_compare(
            returncode=0,
            stdout="300 passed, 10 skipped in 1.00s\n",
            doc_passed=300,
            doc_skipped=194,
        )


def test_run_inner_pytest_strips_live_gated_and_coverage_env(monkeypatch):
    """Der Subprozess erbt weder RUN_LIVE_NLI_PREFILTER noch COV_CORE_*-Keys."""
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(cmd, 0, stdout="1 passed in 0.01s\n", stderr="")

    monkeypatch.setenv("RUN_LIVE_NLI_PREFILTER", "1")
    monkeypatch.setenv("COV_CORE_SOURCE", "tests")
    monkeypatch.setenv("COV_CORE_CONFIG", ".coveragerc")
    monkeypatch.setattr(subprocess, "run", fake_run)

    _run_inner_pytest("tests/evals/test_eval_strategy.py::dummy")

    env = captured["env"]
    assert env is not None
    assert "RUN_LIVE_NLI_PREFILTER" not in env
    assert "COV_CORE_SOURCE" not in env
    assert "COV_CORE_CONFIG" not in env
    cmd = captured["cmd"]
    assert "-p" in cmd and "no:cacheprovider" in cmd


# ---------------------------------------------------------------------------
# AC4: Kein neuer Runner verbrennt Budget.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Issue #597: Das Kern-Set fuer den woechentlichen geplanten Lauf
# (eval-behavior.yml) ist ausschliesslich ueber den pytest-Marker
# `eval_core_set` definiert (pyproject.toml registriert ihn, die neun Dateien
# unten tragen ihn als module-level pytestmark). Dieser Guard haelt die
# Marker-Treffer gegen eine explizite Liste -- eine neue API-gatete Suite, die
# den Marker vergisst, faellt sonst stillschweigend aus dem geplanten Lauf
# (Analogie zu test_every_eval_dir_has_exactly_one_status).
# ---------------------------------------------------------------------------

EXPECTED_EVAL_CORE_SET_FILES = frozenset(
    {
        "tests/evals/test_abstract_generator_evals.py",
        "tests/evals/test_chapter_writer_evals.py",
        "tests/evals/test_citation_extraction_evals.py",
        "tests/evals/test_quote_extractor_evals.py",
        "tests/evals/test_quality_reviewer_evals.py",
        "tests/evals/test_source_quality_audit_evals.py",
        "tests/evals/test_sparring_partner_evals.py",
        "tests/evals/test_rest_evals.py",
        "tests/evals/test_triggers.py",
    }
)


# Review-Korrektur (PR #682): test_triggers.py läuft im geplanten Lauf als
# rotierende Stichprobe (siehe tests/evals/test_triggers.py, ROTATION_GROUPS).
# Kleinste dokumentierte Gruppengroesse ist 10 Skills (Operator-Vorgabe
# 10-15) x 2 Tests (should_trigger_recall + should_not_trigger_fpr) = 20
# Node-IDs als Untergrenze -- unabhaengig davon, welche Gruppe die jeweils
# aktuelle ISO-Woche zieht.
MIN_ROTATION_NODE_IDS = 20


def test_eval_core_set_matches_documented_files():
    """`-m eval_core_set --collect-only` deckt exakt die neun dokumentierten
    Dateien ab -- weder mehr (versehentlich zu breiter Marker) noch weniger
    (Suite vergisst den Marker und faellt lautlos aus dem geplanten Lauf,
    Issue #597 AC2).

    Explizites `env` statt Vererbung des Ambient-Envs: der Subprozess soll
    unabhaengig davon, ob EVAL_TRIGGER_ROTATION_GROUP in der aufrufenden
    Shell zufaellig gesetzt ist, ein deterministisches Ergebnis liefern
    (Rotationsgruppe "0", die kleinste dokumentierte Gruppe).

    Die reine Datei-Zugehoerigkeits-Pruefung unten waere nach Einfuehrung der
    Rotation (PR #682) unempfindlich gegen eine Regression, die
    ROTATION_SKILLS versehentlich leerlaufen laesst: die beiden
    nicht-parametrisierten Tests in test_triggers.py (Kollisions-Checks) und
    die hermetischen Rotations-Tests selbst wuerden die Datei weiterhin als
    "collected" ausweisen, auch wenn beide API-gateten Trigger-Tests
    (should_trigger_recall/should_not_trigger_fpr) keine einzige Node-ID mehr
    beitragen. Die zusaetzliche Untergrenzen-Pruefung unten haelt genau das
    fest, damit der Guard bei einer solchen Regression tatsaechlich rot
    wird statt wirkungslos gruen zu bleiben."""
    env = dict(os.environ, EVAL_TRIGGER_ROTATION_GROUP="0")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/evals/",
            "-m",
            "eval_core_set",
            "--collect-only",
            "-q",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert result.returncode == 0, (
        f"--collect-only fuer eval_core_set schlug fehl:\n{result.stdout}\n{result.stderr}"
    )
    collected_lines = [line for line in result.stdout.splitlines() if "::" in line]
    collected_files = {line.split("::", 1)[0] for line in collected_lines}
    missing = EXPECTED_EVAL_CORE_SET_FILES - collected_files
    unexpected = collected_files - EXPECTED_EVAL_CORE_SET_FILES
    assert not missing, (
        f"Dateien ohne eval_core_set-Marker, obwohl im Kern-Set erwartet: {sorted(missing)} "
        f"(Issue #597 AC2)."
    )
    assert not unexpected, (
        f"Dateien mit eval_core_set-Marker, die nicht zum dokumentierten Kern-Set "
        f"gehoeren: {sorted(unexpected)} (Issue #597 AC2)."
    )

    trigger_test_ids = [
        line
        for line in collected_lines
        if line.startswith("tests/evals/test_triggers.py::")
        and ("test_should_trigger_recall" in line or "test_should_not_trigger_fpr" in line)
    ]
    assert len(trigger_test_ids) >= MIN_ROTATION_NODE_IDS, (
        f"test_triggers.py liefert nur {len(trigger_test_ids)} API-gatete Node-IDs fuer "
        f"Rotationsgruppe '0' -- erwartet mindestens {MIN_ROTATION_NODE_IDS} (Untergrenze aus "
        "der kleinsten dokumentierten Gruppengroesse). Die Rotation laeuft moeglicherweise leer "
        "(Issue #597 Review-Korrektur, PR #682)."
    )


# ---------------------------------------------------------------------------
# Issue #606: ``metric`` war bisher nur in eine Richtung geschuetzt — der Guard
# prueft, DASS ein Pfad existiert, nicht, dass er ohne API-Key laeuft. Ohne die
# folgenden drei Tests koennte eine API-gatete Suite als ``metric`` gefuehrt
# werden und der Bestand still zurueckrutschen.
# ---------------------------------------------------------------------------

MIN_METRIC_COMPONENTS = 8

DELIBERATE_STRUCTURAL_SECTION = "## Auswahl der Kern-Skills und bewusst `structural` (Issue #606)"

DELIBERATELY_STRUCTURAL = [
    "advisor",
    "methodology-advisor",
    "research-question-refiner",
    "title-generator",
    "topic-brainstorm",
    "literature-gap-analysis",
    "peer-review",
]


def test_metric_rows_are_not_api_gated(rows):
    """Ein ``metric``-Pfad, der ohne Key skippt, misst bei keinem CI-Lauf etwas."""
    for name, row in rows.items():
        if row["status"] != "metric":
            continue
        for rel in re.findall(r"`([^`]+)`", row["path"]):
            path = REPO_ROOT / rel
            if not path.suffix == ".py" or not path.exists():
                continue
            source = path.read_text(encoding="utf-8")
            # Auf den AUFRUF pruefen, nicht auf den blossen Namen: eine Testdatei
            # darf die Key-Freiheit ihres Runners selbst asserten, ohne dadurch
            # als API-gatet zu gelten.
            assert not re.search(r"require_api_key\s*\(", source), (
                f"{name}: '{rel}' ist als 'metric'-Ausfuehrungspfad genannt, haengt "
                f"aber an require_api_key() und skippt ohne Schluessel (Issue #606)."
            )


def test_metric_count_does_not_regress(rows):
    """Ratchet: der in #606 erreichte Stand darf nicht stillschweigend zurueckfallen."""
    metric_rows = sorted(name for name, row in rows.items() if row["status"] == "metric")
    assert len(metric_rows) >= MIN_METRIC_COMPONENTS, (
        f"Nur {len(metric_rows)} × metric ({metric_rows}), erwartet mindestens "
        f"{MIN_METRIC_COMPONENTS} (Issue #606). Eine Komponente auf 'structural' "
        f"zurueckzustufen ist eine bewusste Entscheidung — dann diese Schwelle "
        f"mit Begruendung senken, statt sie zu umgehen."
    )


def test_the_five_core_skills_are_metric(rows):
    """Die in #606 ausgewaehlten Kern-Skills sind namentlich geschuetzt."""
    for name in (
        "chapter-writer",
        "abstract-generator",
        "quality-reviewer",
        "parallel-screening",
        "source-quality-audit",
    ):
        assert rows[name]["status"] == "metric", (
            f"{name}: Status {rows[name]['status']!r} — Issue #606 hat diese "
            f"Komponente auf 'metric' gehoben."
        )


def test_strategy_documents_deliberate_structural_choice(strategy_text, rows):
    """Bewusst ``structural`` gebliebene Skills sind mit Begruendung ausgewiesen.

    Scope-Cut auf den Abschnitt statt Volltext-Suche: sonst bliebe der Test
    gruen, wenn der Abschnitt geloescht und die Namen anderswo stehen (#626).
    """
    assert DELIBERATE_STRUCTURAL_SECTION in strategy_text, (
        f"STRATEGY.md braucht den Abschnitt '{DELIBERATE_STRUCTURAL_SECTION}' (Issue #606, AC6)."
    )
    section = strategy_text.split(DELIBERATE_STRUCTURAL_SECTION, 1)[1].split("\n## ", 1)[0]
    for name in DELIBERATELY_STRUCTURAL:
        assert f"`{name}`" in section, (
            f"'{name}' bleibt bewusst 'structural', wird im Begruendungsabschnitt "
            f"aber nicht genannt (Issue #606, AC6)."
        )
        assert rows[name]["status"] == "structural", (
            f"{name}: als bewusst 'structural' ausgewiesen, Tabelle sagt "
            f"{rows[name]['status']!r} — eine der beiden Stellen ist falsch."
        )
    assert "Referenzlösung" in section or "Referenzloesung" in section, (
        "Der Abschnitt muss begruenden, WARUM diese Komponenten structural bleiben."
    )


def test_strategy_documents_eval_core_set_schedule():
    """AC6: STRATEGY.md nennt Rhythmus und Umfang des geplanten Kern-Set-Laufs."""
    text = _strategy_text()
    assert "woechentlich" in text.lower() or "wöchentlich" in text.lower(), (
        "STRATEGY.md muss den Rhythmus des geplanten Laufs (woechentlich) benennen "
        "(Issue #597 AC6)."
    )
    assert "eval_core_set" in text, (
        "STRATEGY.md muss auf den Marker eval_core_set als Quelle der Wahrheit fuer "
        "das Kern-Set verweisen (Issue #597 AC6)."
    )


def test_no_eval_runner_requires_api_key():
    """Alle Runner unter evals/ laufen offline — kein anthropic-Client, kein API-Key."""
    for runner in sorted(EVALS_ROOT.glob("*/runner.py")):
        source = runner.read_text(encoding="utf-8")
        assert "anthropic" not in source, (
            f"{runner.relative_to(REPO_ROOT)} wuerde API-Budget verbrauchen (Issue #390, AC4)."
        )
        assert "require_api_key" not in source, (
            f"{runner.relative_to(REPO_ROOT)} haengt an require_api_key() und wuerde skippen."
        )


# ---------------------------------------------------------------------------
# Issue #848: taeglicher Smoke-Lauf. Guard analog zu
# test_eval_core_set_matches_documented_files oben, aber auf Testfall-Ebene
# (SMOKE_SET_NODE_IDS in tests/evals/smoke_set.py) statt Datei-Ebene, weil
# der Smoke-Lauf explizit eine Stichprobe auf Fallebene ist (Issue-AC1).
# ---------------------------------------------------------------------------


def test_eval_smoke_set_matches_documented_cases():
    """`SMOKE_SET_NODE_IDS` sind real collectible (Issue #848 AC1/AC3).

    Explizites `EVAL_TRIGGER_ROTATION_GROUP=all`: die drei Smoke-Skills aus
    `test_triggers.py` muessen unabhaengig von der woechentlichen ISO-Wochen-
    Rotation kollektierbar sein -- der taegliche Workflow-Zweig setzt dieselbe
    Umgebungsvariable (siehe Modul-Kommentar in smoke_set.py). Eine
    Umbenennung/Parametrisierungs-Aenderung an einem der Faelle faellt hier
    auf, statt den taeglichen Smoke-Lauf lautlos leer laufen zu lassen (Muster
    Issue #470/#824)."""
    env = dict(os.environ, EVAL_TRIGGER_ROTATION_GROUP="all")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *SMOKE_SET_NODE_IDS, "--collect-only", "-q"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert result.returncode == 0, (
        f"--collect-only fuer SMOKE_SET_NODE_IDS schlug fehl:\n{result.stdout}\n{result.stderr}"
    )
    collected = {line for line in result.stdout.splitlines() if "::" in line}
    missing = set(SMOKE_SET_NODE_IDS) - collected
    assert not missing, (
        f"Smoke-Set-Node-IDs nicht mehr collectible (umbenannt/entfernt?): {sorted(missing)} "
        "(Issue #848)."
    )
    assert 5 <= len(SMOKE_SET_NODE_IDS) <= 10, (
        f"SMOKE_SET_NODE_IDS hat {len(SMOKE_SET_NODE_IDS)} Faelle -- Issue #848 gibt die "
        "Groessenordnung 5-10 vor."
    )


def test_pytest_exits_nonzero_when_no_tests_collected():
    """AC3: ein leer treffender Filter beendet pytest mit Exitcode != 0.

    Haelt die Annahme fest, auf der das Skip-Inventar-Gate (Issue #824) im
    taeglichen Workflow-Zweig aufbaut: faellt das Node-ID-Inventar durch eine
    Umbenennung leer aus, darf der Lauf NICHT taeuschend gruen durchgehen
    (0 real geprueft, 0 gemeldet) -- Standard-pytest-Verhalten ist Exit 5
    ("no tests collected"), dieser Test pinnt genau das."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/evals/",
            "-k",
            "definitely_no_such_smoke_case_xyz",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0, (
        "pytest mit leer treffendem -k muss ungleich 0 zurueckgeben (erwartet: Exit 5 'no "
        "tests collected') -- sonst waere ein leerer Smoke-Lauf taeuschend gruen (Issue #848 "
        "AC3)."
    )


def test_strategy_documents_eval_smoke_set_schedule():
    """AC4: STRATEGY.md nennt Rhythmus, Stichprobe und Budget des taeglichen Smoke-Laufs."""
    text = _strategy_text()
    assert "taeglich" in text.lower() or "täglich" in text.lower(), (
        "STRATEGY.md muss den Rhythmus des taeglichen Smoke-Laufs benennen (Issue #848 AC4)."
    )
    assert "smoke_set" in text or "SMOKE_SET_NODE_IDS" in text, (
        "STRATEGY.md muss auf smoke_set.py/SMOKE_SET_NODE_IDS als Quelle der Wahrheit fuer die "
        "Smoke-Stichprobe verweisen (Issue #848 AC4)."
    )
