"""Tests fuer Issue #602 — Active Learning fuer das Titel-/Abstract-Screening.

Der Klassifikator sortiert die noch offene Restliste um, damit wahrscheinlich
relevante Treffer zuerst geurteilt werden. Er entscheidet nichts: keine Quelle
wird ausgeschlossen, keine uebersprungen, kein Screening abgebrochen.

Akzeptanzkriterium -> Testfall:

- AC1 Umsortierung nach konfigurierbarer Urteilszahl, Reihenfolge sichtbar ->
  ``test_reorder_happens_only_after_the_configured_number_of_labels``,
  ``test_retrain_interval_precedence_arg_env_config_default``,
  ``test_cli_rank_prints_the_new_order``
- AC2 lokal, ohne Netz, ohne API-Key ->
  ``test_ranking_runs_with_every_socket_blocked``,
  ``test_module_imports_only_stdlib``
- AC3 Fortschritt: bearbeiteter Anteil + Ausbeute der letzten Abschnitte ->
  ``test_progress_reports_share_done_and_yield_per_block``,
  ``test_progress_report_is_markdown_without_float_artifacts``
- AC4 nichts wird ausgeschlossen oder uebersprungen ->
  ``test_reorder_is_a_permutation_of_the_pending_list``,
  ``test_papers_without_text_keep_their_relative_position``,
  ``test_module_exposes_no_stopping_or_filtering_api``,
  ``test_module_never_touches_the_vault``
- AC5 abgeschaltet == Verhalten ohne Feature ->
  ``test_disabled_run_matches_a_run_without_the_feature``,
  ``test_active_learning_precedence_arg_env_config_default``,
  ``test_legacy_screening_suites_are_untouched``
- AC6 Validierungslauf gegen bekannte Trefferliste ->
  ``test_validation_run_reports_the_recall_curve``,
  ``test_validation_run_is_deterministic``,
  ``test_cli_validate_outputs_a_table``
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "parallel-screening"
SCRIPTS_DIR = SKILL_DIR / "scripts"
MODULE_PATH = SCRIPTS_DIR / "active_learning.py"
SKILL_MD = SKILL_DIR / "SKILL.md"
REFERENCE_MD = SKILL_DIR / "references" / "active-learning.md"
CONFIG_PATH = REPO_ROOT / "config" / "parallel_agents.json"
GOLD_PATH = REPO_ROOT / "tests" / "fixtures" / "active_learning" / "gold_screening.jsonl"

# Skill-spezifischer Pfad, keine Repo-Root-Boilerplate (#183): der Ausdruck
# nennt SKILL_DIR, damit die Herkunft aus skills/ auch statisch erkennbar ist.
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import active_learning as al  # noqa: E402
import screening_ledger as sl  # noqa: E402


@pytest.fixture
def session_dir(tmp_path: Path) -> str:
    d = tmp_path / "session"
    d.mkdir()
    return str(d)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kein Env-Rest aus einem anderen Test darf die Praezedenz verschieben."""
    for name in (
        al.ACTIVE_LEARNING_ENV,
        al.RETRAIN_INTERVAL_ENV,
        al.BLOCK_SIZE_ENV,
        sl.DOUBLE_SCREENING_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------

_RELEVANT_TEXT = (
    "Randomisierte Studie: Interventionsgruppe und Kontrollgruppe, Praetest und "
    "Posttest, Effektstaerke signifikant."
)
_IRRELEVANT_TEXT = (
    "Positionspapier ohne eigene Datenerhebung, theoretische Erwaegungen zum "
    "Curriculum in der Grundschule."
)


def _papers(relevant: list[str], irrelevant: list[str]) -> dict[str, dict[str, str]]:
    papers: dict[str, dict[str, str]] = {}
    for pid in relevant:
        papers[pid] = {"title": "Wirksamkeit digitaler Lernvideos", "abstract": _RELEVANT_TEXT}
    for pid in irrelevant:
        papers[pid] = {
            "title": "Zum Stellenwert digitaler Lernvideos",
            "abstract": _IRRELEVANT_TEXT,
        }
    return papers


def _decide(session_dir: str, paper_id: str, decision: str) -> None:
    sl.record_decision(
        session_dir,
        {"paper_id": paper_id, "decision": decision, "reason": "Testurteil"},
        agent="screening-judge#1",
    )


# ---------------------------------------------------------------------------
# AC1 — Umsortierung ab konfigurierbarer Urteilszahl, Reihenfolge sichtbar
# ---------------------------------------------------------------------------


def test_reorder_happens_only_after_the_configured_number_of_labels(session_dir: str) -> None:
    ids = [f"p{i:02d}" for i in range(1, 13)]
    papers = _papers(relevant=ids[6:], irrelevant=ids[:6])

    # 4 Urteile bei interval=5 -> noch keine Umsortierung, kein Log.
    for pid in ["p01", "p02", "p03"]:
        _decide(session_dir, pid, "exclude")
    _decide(session_dir, "p07", "include")
    rest = sl.pending(ids, session_dir)
    assert al.reorder_pending(
        rest, papers, session_dir, interval=5, enabled=True, double=False
    ) == (rest)
    assert al.read_log(session_dir) == []

    # Das fuenfte Urteil loest die Umsortierung aus.
    _decide(session_dir, "p04", "exclude")
    rest = sl.pending(ids, session_dir)
    ranked = al.reorder_pending(rest, papers, session_dir, interval=5, enabled=True, double=False)
    assert ranked != rest, "Bei 5 Urteilen muss die Restliste umsortiert sein"
    assert sorted(ranked) == sorted(rest)

    log = al.read_log(session_dir)
    assert len(log) == 1, f"genau eine Protokollzeile erwartet, waren {len(log)}"
    entry = log[0]
    assert entry["n_labels"] == 5
    assert entry["n_include"] == 1
    assert entry["n_exclude"] == 4
    assert entry["order"] == ranked, (
        "Das Protokoll muss die geltende Reihenfolge vollstaendig nennen"
    )
    assert entry["model"], "Trainingsgrundlage ohne Modellkennung ist nicht nachvollziehbar"
    assert isinstance(entry["ts"], int)


def test_reorder_puts_the_likely_relevant_first(session_dir: str) -> None:
    ids = [f"p{i:02d}" for i in range(1, 13)]
    relevant = ["p07", "p08", "p09", "p10", "p11", "p12"]
    papers = _papers(relevant=relevant, irrelevant=ids[:6])
    for pid in ["p01", "p02", "p03"]:
        _decide(session_dir, pid, "exclude")
    for pid in ["p07", "p08"]:
        _decide(session_dir, pid, "include")

    rest = sl.pending(ids, session_dir)
    ranked = al.reorder_pending(rest, papers, session_dir, interval=5, enabled=True, double=False)
    still_relevant = [pid for pid in relevant if pid in rest]
    assert ranked[: len(still_relevant)] == still_relevant


def test_retrain_interval_precedence_arg_env_config_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "parallel_agents.json"
    config.write_text(json.dumps({"active_learning_retrain_interval": 7}), encoding="utf-8")

    monkeypatch.setenv(al.RETRAIN_INTERVAL_ENV, "3")
    assert al.resolve_retrain_interval(explicit=99, config_path=config) == 99

    monkeypatch.setenv(al.RETRAIN_INTERVAL_ENV, "3")
    assert al.resolve_retrain_interval(config_path=config) == 3

    monkeypatch.delenv(al.RETRAIN_INTERVAL_ENV, raising=False)
    assert al.resolve_retrain_interval(config_path=config) == 7

    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    assert al.resolve_retrain_interval(config_path=empty) == al.DEFAULT_RETRAIN_INTERVAL


def test_block_size_precedence_arg_env_config_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "parallel_agents.json"
    config.write_text(json.dumps({"active_learning_block_size": 40}), encoding="utf-8")

    monkeypatch.setenv(al.BLOCK_SIZE_ENV, "12")
    assert al.resolve_block_size(explicit=5, config_path=config) == 5

    monkeypatch.setenv(al.BLOCK_SIZE_ENV, "12")
    assert al.resolve_block_size(config_path=config) == 12

    monkeypatch.delenv(al.BLOCK_SIZE_ENV, raising=False)
    assert al.resolve_block_size(config_path=config) == 40

    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    assert al.resolve_block_size(config_path=empty) == al.DEFAULT_BLOCK_SIZE


def test_cli_rank_prints_the_new_order(session_dir: str, tmp_path: Path, capsys) -> None:
    ids = [f"p{i:02d}" for i in range(1, 13)]
    papers = _papers(relevant=ids[6:], irrelevant=ids[:6])
    papers_file = tmp_path / "papers.json"
    papers_file.write_text(json.dumps(papers, ensure_ascii=False), encoding="utf-8")

    for pid in ["p01", "p02", "p03"]:
        _decide(session_dir, pid, "exclude")
    for pid in ["p07", "p08"]:
        _decide(session_dir, pid, "include")

    rest = sl.pending(ids, session_dir)
    rc = al.main(
        [
            "rank",
            "--session-dir",
            session_dir,
            "--papers",
            str(papers_file),
            "--ids",
            ",".join(rest),
            "--interval",
            "5",
            "--active-learning",
            "true",
            "--double-screening",
            "false",
        ]
    )
    assert rc == 0
    printed = json.loads(capsys.readouterr().out)
    assert sorted(printed) == sorted(rest)
    assert printed != rest


# ---------------------------------------------------------------------------
# AC2 — lokal, ohne Netz, ohne API-Key
# ---------------------------------------------------------------------------


def test_ranking_runs_with_every_socket_blocked(
    session_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Netzzugriff im Active Learning ist unzulaessig (#602)")

    monkeypatch.setattr(socket, "socket", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    for name in list(os.environ):
        if name.endswith("_API_KEY") or name.endswith("_OAUTH_TOKEN"):
            monkeypatch.delenv(name, raising=False)

    ids = [f"p{i:02d}" for i in range(1, 13)]
    papers = _papers(relevant=ids[6:], irrelevant=ids[:6])
    for pid in ["p01", "p02", "p03", "p04"]:
        _decide(session_dir, pid, "exclude")
    _decide(session_dir, "p07", "include")

    rest = sl.pending(ids, session_dir)
    ranked = al.reorder_pending(rest, papers, session_dir, interval=5, enabled=True, double=False)
    assert sorted(ranked) == sorted(rest)


def test_module_imports_only_stdlib() -> None:
    """Kein Netz-, Modell- oder Anbieter-Paket — auch nicht transitiv ueber Imports."""
    forbidden = {
        "anthropic",
        "httpx",
        "openai",
        "requests",
        "sentence_transformers",
        "sklearn",
        "torch",
        "urllib",
        "urllib3",
    }
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & forbidden), f"Verbotene Imports: {sorted(imported & forbidden)}"

    source = MODULE_PATH.read_text(encoding="utf-8")
    for literal in ("http://", "https://", "API_KEY", "OAUTH"):
        assert literal not in source, f"'{literal}' im Modul — Active Learning laeuft lokal"


# ---------------------------------------------------------------------------
# AC3 — Fortschrittsanzeige
# ---------------------------------------------------------------------------


def test_progress_reports_share_done_and_yield_per_block(session_dir: str) -> None:
    ids = [f"p{i:03d}" for i in range(1, 201)]
    # 60 von 200 entschieden, Treffer frueh geballt: Block 1 acht, Block 2 drei,
    # Block 3 einer (Blockgroesse 20).
    include_positions = set(range(0, 8)) | {20, 21, 22} | {40}
    for pos in range(60):
        _decide(session_dir, ids[pos], "include" if pos in include_positions else "exclude")

    report = al.progress(ids, session_dir, block_size=20, double=False)
    assert report["n_total"] == 200
    assert report["n_decided"] == 60
    assert report["n_pending"] == 140
    assert report["share_done_pct"] == 30.0
    assert report["n_include"] == 12
    assert [b["n_include"] for b in report["blocks"]] == [8, 3, 1]
    assert [b["n_decided"] for b in report["blocks"]] == [20, 20, 20]
    assert [b["index"] for b in report["blocks"]] == [1, 2, 3]
    assert [b["n_include"] for b in report["recent_blocks"]] == [3, 1]


def test_progress_report_is_markdown_without_float_artifacts(session_dir: str) -> None:
    ids = [f"p{i:03d}" for i in range(1, 4)]
    _decide(session_dir, ids[0], "include")
    text = al.progress_report(ids, session_dir, block_size=1, double=False)
    assert text.startswith("## Screening-Fortschritt")
    assert "33.3" in text or "33,3" in text
    assert "33.33333" not in text
    assert "| Abschnitt |" in text


# ---------------------------------------------------------------------------
# AC4 — nichts wird ausgeschlossen oder uebersprungen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "labels",
    [
        [("p01", "exclude"), ("p02", "exclude"), ("p03", "exclude")],
        [("p01", "include"), ("p02", "include"), ("p03", "include")],
        [("p01", "include"), ("p02", "exclude"), ("p03", "unclear")],
        [("p01", "include"), ("p02", "exclude"), ("p03", "exclude"), ("p04", "include")],
    ],
)
def test_reorder_is_a_permutation_of_the_pending_list(
    session_dir: str, labels: list[tuple[str, str]]
) -> None:
    ids = [f"p{i:02d}" for i in range(1, 13)]
    papers = _papers(relevant=ids[6:], irrelevant=ids[:6])
    for pid, decision in labels:
        _decide(session_dir, pid, decision)

    rest = sl.pending(ids, session_dir)
    ranked = al.reorder_pending(rest, papers, session_dir, interval=2, enabled=True, double=False)
    assert sorted(ranked) == sorted(rest)
    assert len(ranked) == len(rest)
    assert len(set(ranked)) == len(ranked)


def test_reorder_without_enough_labels_keeps_the_original_order(session_dir: str) -> None:
    ids = [f"p{i:02d}" for i in range(1, 13)]
    papers = _papers(relevant=ids[6:], irrelevant=ids[:6])
    _decide(session_dir, "p01", "exclude")
    rest = sl.pending(ids, session_dir)
    assert al.reorder_pending(
        rest, papers, session_dir, interval=5, enabled=True, double=False
    ) == (rest)
    assert al.read_log(session_dir) == []


def test_reorder_with_only_one_class_keeps_the_original_order(session_dir: str) -> None:
    """Ohne Gegenklasse liefert der Klassifikator konstante Werte — nicht permutieren."""
    ids = [f"p{i:02d}" for i in range(1, 13)]
    papers = _papers(relevant=ids[6:], irrelevant=ids[:6])
    for pid in ["p01", "p02", "p03", "p04", "p05"]:
        _decide(session_dir, pid, "exclude")
    rest = sl.pending(ids, session_dir)
    assert al.reorder_pending(
        rest, papers, session_dir, interval=2, enabled=True, double=False
    ) == (rest)
    assert al.read_log(session_dir) == []


def test_papers_without_text_keep_their_relative_position(session_dir: str) -> None:
    ids = [f"p{i:02d}" for i in range(1, 13)]
    papers = _papers(relevant=ids[6:], irrelevant=ids[:6])
    del papers["p09"]
    del papers["p05"]
    for pid in ["p01", "p02", "p03"]:
        _decide(session_dir, pid, "exclude")
    for pid in ["p07", "p08"]:
        _decide(session_dir, pid, "include")

    rest = sl.pending(ids, session_dir)
    ranked = al.reorder_pending(rest, papers, session_dir, interval=5, enabled=True, double=False)
    assert sorted(ranked) == sorted(rest)
    without_text = [pid for pid in ranked if pid in {"p05", "p09"}]
    assert without_text == ["p05", "p09"], "ohne Text: Ursprungsreihenfolge untereinander"


def test_reorder_is_deterministic(session_dir: str) -> None:
    ids = [f"p{i:02d}" for i in range(1, 13)]
    papers = _papers(relevant=ids[6:], irrelevant=ids[:6])
    for pid in ["p01", "p02", "p03"]:
        _decide(session_dir, pid, "exclude")
    for pid in ["p07", "p08"]:
        _decide(session_dir, pid, "include")
    rest = sl.pending(ids, session_dir)
    runs = [al.rank_pending(rest, papers, session_dir, interval=5, double=False) for _ in range(5)]
    assert all(run == runs[0] for run in runs)


def test_module_exposes_no_stopping_or_filtering_api() -> None:
    """Der Ranker sortiert. Er kuerzt nicht, filtert nicht und stoppt nicht (Scope-Grenze)."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    public = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    }
    forbidden_fragments = ("stop", "abort", "cutoff", "prune", "truncate", "drop", "discard")
    offenders = [
        name for name in public if any(frag in name.lower() for frag in forbidden_fragments)
    ]
    assert not offenders, f"Abbruch-/Kuerzungs-API im Modul: {sorted(offenders)}"


def test_module_never_touches_the_vault() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in ("VaultDB", "add_excluded_source", "academic_vault", "db_path"):
        assert forbidden not in source, f"'{forbidden}' im Modul — Active Learning schreibt nichts"


# ---------------------------------------------------------------------------
# AC5 — abgeschaltet == Verhalten ohne das Feature
# ---------------------------------------------------------------------------


def test_active_learning_precedence_arg_env_config_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "parallel_agents.json"
    config.write_text(json.dumps({"active_learning": True}), encoding="utf-8")

    monkeypatch.setenv(al.ACTIVE_LEARNING_ENV, "false")
    assert al.resolve_active_learning(explicit=True, config_path=config) is True

    monkeypatch.setenv(al.ACTIVE_LEARNING_ENV, "false")
    assert al.resolve_active_learning(config_path=config) is False

    monkeypatch.delenv(al.ACTIVE_LEARNING_ENV, raising=False)
    assert al.resolve_active_learning(config_path=config) is True

    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    assert al.resolve_active_learning(config_path=empty) is al.DEFAULT_ACTIVE_LEARNING


def test_default_is_opt_in() -> None:
    """Ein bestehender Screening-Lauf darf nicht still umsortiert werden."""
    assert al.DEFAULT_ACTIVE_LEARNING is False
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["active_learning"] is False
    assert config["active_learning_retrain_interval"] == al.DEFAULT_RETRAIN_INTERVAL
    assert config["active_learning_block_size"] == al.DEFAULT_BLOCK_SIZE


def test_disabled_run_matches_a_run_without_the_feature(tmp_path: Path) -> None:
    ids = [f"p{i:02d}" for i in range(1, 13)]
    papers = _papers(relevant=ids[6:], irrelevant=ids[:6])
    decisions = [(pid, "include" if pid in ids[6:] else "exclude") for pid in ids]

    def run(dir_name: str, use_module: bool) -> dict[str, object]:
        d = tmp_path / dir_name
        d.mkdir()
        session = str(d)
        order: list[list[str]] = []
        remaining = list(ids)
        for pid, decision in decisions:
            todo = sl.pending(remaining, session)
            if use_module:
                todo = al.reorder_pending(
                    todo, papers, session, interval=3, enabled=False, double=False
                )
            order.append(sl.plan_waves(todo, 4)[0])
            _decide(session, pid, decision)
        return {
            "waves": order,
            "ledger": [{k: v for k, v in e.items() if k != "ts"} for e in sl.read_ledger(session)],
            "counters": sl.to_prisma_counters(session),
            "log_exists": al.log_path(session).exists(),
            "files": sorted(p.name for p in d.iterdir()),
        }

    with_module = run("with_module", use_module=True)
    without_module = run("without_module", use_module=False)
    assert with_module == without_module
    assert with_module["log_exists"] is False
    assert with_module["files"] == [sl.LEDGER_FILENAME]


#: SHA-256 der Bestandssuiten. Aendert sie ein spaeterer Lauf, faellt dieser Test
#: auf — AC5 ("verhaelt sich exakt wie ohne das Feature") ist dann nicht mehr
#: belegt, sondern wegdefiniert. Legitime Aenderungen aktualisieren die Werte
#: bewusst und begruenden sie im PR.
_LEGACY_SUITE_HASHES = {
    "tests/test_issue_460_parallel_screening.py": (
        "ac9fba6e0e62d6a4b7be347e43c7b01f8cfc9c4327a7f289300e4e6a8da7bdbf"
    ),
    "tests/test_issue_598_double_screening.py": (
        "abbc9ed51ab10654c0704c226187621525daae5ac2687cc4b80c1a0383302611"
    ),
}


@pytest.mark.parametrize("relpath", sorted(_LEGACY_SUITE_HASHES))
def test_legacy_screening_suites_are_untouched(relpath: str) -> None:
    digest = hashlib.sha256((REPO_ROOT / relpath).read_bytes()).hexdigest()
    assert digest == _LEGACY_SUITE_HASHES[relpath], (
        f"{relpath} wurde veraendert — AC5 verlangt, dass die Bestandssuite "
        "unveraendert gruen bleibt, nicht dass sie angepasst wird"
    )


def test_legacy_screening_suites_still_pass() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_issue_460_parallel_screening.py",
            "tests/test_issue_598_double_screening.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout[-3000:]


# ---------------------------------------------------------------------------
# AC6 — Validierungslauf gegen eine Trefferliste mit bekanntem Ergebnis
# ---------------------------------------------------------------------------


def _gold_records() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in GOLD_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_gold_fixture_is_not_built_around_the_classifier() -> None:
    """Anti-Gaming: gemeinsames Vokabular, harte Negative, harte Positive."""
    records = _gold_records()
    assert len(records) == 150
    relevant = [r for r in records if r["relevant"]]
    assert len(relevant) == 15

    def topics(rows: list[dict[str, object]]) -> set[str]:
        found = set()
        for row in rows:
            for topic in ("Lernvideos", "Online-Kursen", "Lernplattformen", "Webinaren"):
                if topic in str(row["title"]) or topic in str(row["abstract"]):
                    found.add(topic)
        return found

    irrelevant = [r for r in records if not r["relevant"]]
    assert topics(relevant) & topics(irrelevant), "Themenwoerter muessen sich ueberlappen"

    hard_negatives = [
        r
        for r in irrelevant
        if "Kontrollgruppe" in str(r["abstract"]) and "randomisierte" in str(r["abstract"])
    ]
    assert len(hard_negatives) >= 8, f"zu wenige harte Negative: {len(hard_negatives)}"

    sparse_positives = [r for r in relevant if "Kontrollgruppe" not in str(r["abstract"])]
    assert len(sparse_positives) >= 3, f"zu wenige harte Positive: {len(sparse_positives)}"


def test_validation_run_reports_the_recall_curve() -> None:
    result = al.validate_ranking(_gold_records(), interval=10)

    assert result["n_total"] == 150
    assert result["n_relevant"] == 15
    assert result["interval"] == 10

    curve = {point["share_pct"]: point for point in result["curve"]}
    assert set(curve) >= {10.0, 20.0, 50.0, 100.0}
    assert curve[100.0]["recall_pct"] == 100.0, "Die Liste wird vollstaendig abgearbeitet"
    assert curve[100.0]["n_screened"] == 150

    # Zufallsbaseline: nach 20 % der Liste waeren im Mittel 20 % der relevanten
    # Arbeiten gefunden. Alles darunter oder knapp darueber waere kein Nutzen.
    random_baseline_pct = 20.0
    assert curve[20.0]["recall_pct"] >= 3 * random_baseline_pct, (
        f"Recall@20% = {curve[20.0]['recall_pct']} — kaum besser als die "
        f"Zufallsbaseline {random_baseline_pct}"
    )
    assert curve[50.0]["recall_pct"] >= 90.0


def test_validation_run_finds_nothing_less_than_the_full_list() -> None:
    """Umsortiert, nicht gekuerzt: am Ende ist jede Quelle geurteilt."""
    result = al.validate_ranking(_gold_records(), interval=10)
    screened = result["screened_order"]
    assert sorted(screened) == sorted(str(r["paper_id"]) for r in _gold_records())


def test_validation_run_is_deterministic() -> None:
    first = al.validate_ranking(_gold_records(), interval=10)
    second = al.validate_ranking(_gold_records(), interval=10)
    assert first == second


def test_cli_validate_outputs_a_table(capsys) -> None:
    rc = al.main(["validate", "--gold", str(GOLD_PATH), "--interval", "10"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "| Anteil der Liste |" in out
    assert "| Anteil der gefundenen Treffer |" in out or "Anteil gefundener" in out
    assert "100.0" in out


def test_cli_progress_outputs_the_report(session_dir: str, capsys) -> None:
    ids = [f"p{i:03d}" for i in range(1, 21)]
    for pid in ids[:5]:
        _decide(session_dir, pid, "exclude")
    rc = al.main(
        [
            "progress",
            "--session-dir",
            session_dir,
            "--ids",
            ",".join(ids),
            "--block-size",
            "5",
            "--double-screening",
            "false",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "## Screening-Fortschritt" in out
    assert "25.0" in out


# ---------------------------------------------------------------------------
# Doppel-Screening: Trainingsgrundlage sind die konsolidierten Urteile
# ---------------------------------------------------------------------------


def test_training_labels_use_consolidated_double_screening_decisions(session_dir: str) -> None:
    for pid, d1, d2 in [
        ("p01", "exclude", "exclude"),
        ("p02", "exclude", "exclude"),
        ("p03", "include", "include"),
        ("p04", "include", "exclude"),  # Dissens -> kein Trainingsbeispiel
    ]:
        sl.record_decision(session_dir, {"paper_id": pid, "decision": d1, "reason": "r1"}, round=1)
        sl.record_decision(session_dir, {"paper_id": pid, "decision": d2, "reason": "r2"}, round=2)

    labels = al.training_labels(session_dir, double=True)
    assert labels == {"p01": "exclude", "p02": "exclude", "p03": "include"}


# ---------------------------------------------------------------------------
# Dokumentation
# ---------------------------------------------------------------------------


def test_reference_documents_the_scope_boundary() -> None:
    text = REFERENCE_MD.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "kein automatischer abbruch" in lowered or "keinen automatischen abbruch" in lowered
    assert "ACADEMIC_RESEARCH_ACTIVE_LEARNING" in text
    assert "blind" in text.lower(), "Die Blindheitsregel aus #598 muss ausdruecklich stehen"


def test_skill_md_points_to_the_reference() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "references/active-learning.md" in text


def test_size_baseline_stays_bound_to_the_actual_growth() -> None:
    sizes = json.loads((REPO_ROOT / "tests" / "baselines" / "skill_sizes.json").read_text())
    baseline = sizes["parallel-screening"]
    current = len(SKILL_MD.read_text(encoding="utf-8"))
    delta = baseline - current
    assert delta >= 1400, f"Guard-Marge zu klein: {delta} (Baseline {baseline}, aktuell {current})"
    assert delta < 1500, (
        f"Baseline {baseline} liegt {delta} Zeichen ueber der Datei — mehr als der "
        "Netto-Zuwachs, die Anhebung waere damit ein Freibrief statt einer Korrektur"
    )


def test_token_baseline_is_the_measured_value_not_a_head_start() -> None:
    tokens = json.loads((REPO_ROOT / "tests" / "baselines" / "tokens.json").read_text())
    baseline = tokens["parallel-screening"]
    current = -(-len(SKILL_MD.read_text(encoding="utf-8")) // 4)
    assert baseline == current, (
        f"Token-Baseline {baseline} != gemessener Wert {current} — kein Vorschuss"
    )
