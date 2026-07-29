"""Tests fuer Issue #460 — Subagent-Struktur fuer Screening und Verzerrungsbewertung.

Die deterministische Buchfuehrung des Fan-outs (Wellen-Planung, Ledger, Resume,
PRISMA-Zaehler, Unklar-Sammlung) liegt in
``skills/parallel-screening/scripts/screening_ledger.py`` — damit ist jedes
Akzeptanzkriterium hier beweisbar statt nur in Prosa behauptet.

Akzeptanzkriterium -> Testfall:

- Screening ueber >= 20 Treffer, je begruendete Entscheidung
  -> ``test_twenty_hits_all_decided_with_reason``,
     ``test_plan_waves_covers_every_id_exactly_once``
- Ausgeschlossene in ``excluded_sources``, eingeschlossene in ``papers``,
  PRISMA-Summe stimmt
  -> ``test_excluded_land_in_vault_included_stay_in_papers``,
     ``test_prisma_counters_match_ledger_sum``
- ``prisma-flow`` rendert ohne Zwischenschritt
  -> ``test_ledger_counters_feed_render_flow``
- Uneindeutige Faelle werden vorgelegt statt entschieden
  -> ``test_unclear_never_written_to_vault``, ``test_merge_returns_unclear_bucket``
- Verzerrungsbewertung ueber mehrere Studien im vorhandenen Domain-Format
  -> ``test_rob_fanout_writes_existing_domain_format``
- Resume nach Abbruch
  -> ``test_resume_returns_only_pending_ids``,
     ``test_resume_does_not_duplicate_rob_assessments``
- Parallelitaet begrenzt und konfigurierbar
  -> ``test_max_parallel_precedence``, ``test_max_parallel_hard_cap``,
     ``test_no_wave_exceeds_max_parallel``
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "parallel-screening"
SCRIPTS_DIR = SKILL_DIR / "scripts"
AGENT_MD = REPO_ROOT / "agents" / "screening-judge.md"
CONFIG_PATH = REPO_ROOT / "config" / "parallel_agents.json"

sys.path.insert(0, str(REPO_ROOT / "skills" / "parallel-screening" / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "skills" / "prisma-flow" / "scripts"))


# ---------------------------------------------------------------------------
# Fixtures / Helfer
# ---------------------------------------------------------------------------


def _hit_ids(n: int) -> list[str]:
    return [f"paper{i:03d}" for i in range(1, n + 1)]


def _decision_for(paper_id: str) -> dict:
    """Deterministische Stand-in-Entscheidung eines screening-judge-Laufs.

    In Produktion liefert der Subagent dieses JSON; hier wird es regelbasiert
    erzeugt, damit der Test ohne LLM-Call laeuft (analog rob_agent_helper).
    """
    idx = int(paper_id.removeprefix("paper"))
    if idx % 5 == 0:
        return {
            "paper_id": paper_id,
            "decision": "exclude",
            "reason": "Population passt nicht zur Einschlussfrage",
            "criterion": "population",
            "confidence": 0.9,
            "evidence": "title_abstract",
        }
    if idx % 7 == 0:
        return {
            "paper_id": paper_id,
            "decision": "unclear",
            "reason": "Abstract nennt die Stichprobengroesse nicht",
            "criterion": "population",
            "confidence": 0.4,
            "evidence": "title_abstract",
        }
    return {
        "paper_id": paper_id,
        "decision": "include",
        "reason": "Thema und Studientyp erfuellen die Einschlusskriterien",
        "criterion": "topic",
        "confidence": 0.8,
        "evidence": "title_abstract",
    }


def _run_screening(session_dir, paper_ids, *, db_path=None, max_parallel=4):
    """Simuliert den Fan-out: Wellen planen, je Fall entscheiden, protokollieren."""
    import screening_ledger as sl

    waves = sl.plan_waves(sl.pending(paper_ids, session_dir), max_parallel)
    for wave_no, wave in enumerate(waves, start=1):
        for slot, paper_id in enumerate(wave, start=1):
            sl.record_decision(
                session_dir,
                _decision_for(paper_id),
                agent=f"screening-judge#{slot}",
                wave=wave_no,
                db_path=db_path,
            )
    return waves


@pytest.fixture
def session_dir(tmp_path):
    d = tmp_path / "session"
    d.mkdir()
    return str(d)


# ---------------------------------------------------------------------------
# AC7: Parallelitaet begrenzt und konfigurierbar
# ---------------------------------------------------------------------------


def test_max_parallel_default_when_nothing_configured(monkeypatch, tmp_path):
    import screening_ledger as sl

    monkeypatch.delenv(sl.MAX_PARALLEL_ENV, raising=False)
    missing = tmp_path / "nope.json"
    assert sl.resolve_max_parallel(config_path=missing) == sl.DEFAULT_MAX_PARALLEL


def test_max_parallel_precedence(monkeypatch, tmp_path):
    """Argument > Env > Config > Default."""
    import screening_ledger as sl

    cfg = tmp_path / "parallel_agents.json"
    cfg.write_text(json.dumps({"max_parallel_agents": 3}), encoding="utf-8")

    monkeypatch.delenv(sl.MAX_PARALLEL_ENV, raising=False)
    assert sl.resolve_max_parallel(config_path=cfg) == 3, "Config schlaegt Default"

    monkeypatch.setenv(sl.MAX_PARALLEL_ENV, "6")
    assert sl.resolve_max_parallel(config_path=cfg) == 6, "Env schlaegt Config"

    assert sl.resolve_max_parallel(explicit=2, config_path=cfg) == 2, "Argument schlaegt Env"


def test_max_parallel_hard_cap(monkeypatch, tmp_path):
    import screening_ledger as sl

    monkeypatch.setenv(sl.MAX_PARALLEL_ENV, "999")
    assert sl.resolve_max_parallel(config_path=tmp_path / "nope.json") == sl.MAX_PARALLEL_HARD_CAP
    assert sl.resolve_max_parallel(explicit=999) == sl.MAX_PARALLEL_HARD_CAP


def test_max_parallel_rejects_non_positive():
    import screening_ledger as sl

    with pytest.raises(ValueError):
        sl.resolve_max_parallel(explicit=0)


def test_max_parallel_ignores_garbage_env(monkeypatch, tmp_path):
    import screening_ledger as sl

    monkeypatch.setenv(sl.MAX_PARALLEL_ENV, "viele")
    assert sl.resolve_max_parallel(config_path=tmp_path / "nope.json") == sl.DEFAULT_MAX_PARALLEL


def test_repo_config_file_is_valid():
    """Das mitgelieferte config/parallel_agents.json ist lesbar und plausibel."""
    import screening_ledger as sl

    assert CONFIG_PATH.exists(), f"Fehlt: {CONFIG_PATH}"
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    value = data["max_parallel_agents"]
    assert isinstance(value, int) and 1 <= value <= sl.MAX_PARALLEL_HARD_CAP


def test_no_wave_exceeds_max_parallel():
    import screening_ledger as sl

    waves = sl.plan_waves(_hit_ids(22), 4)
    assert waves, "plan_waves liefert keine Wellen"
    assert all(len(w) <= 4 for w in waves), [len(w) for w in waves]


def test_plan_waves_covers_every_id_exactly_once():
    import screening_ledger as sl

    ids = _hit_ids(22)
    flat = [pid for wave in sl.plan_waves(ids, 4) for pid in wave]
    assert flat == ids, "plan_waves darf keine ID verlieren oder doppeln"


def test_plan_waves_rejects_invalid_limit():
    import screening_ledger as sl

    with pytest.raises(ValueError):
        sl.plan_waves(_hit_ids(3), 0)


# ---------------------------------------------------------------------------
# AC1: >= 20 Treffer, je begruendete Entscheidung
# ---------------------------------------------------------------------------


def test_twenty_hits_all_decided_with_reason(session_dir):
    import screening_ledger as sl

    ids = _hit_ids(22)
    _run_screening(session_dir, ids)

    entries = sl.read_ledger(session_dir)
    by_id: dict[str, list[dict]] = {}
    for e in entries:
        by_id.setdefault(e["paper_id"], []).append(e)

    assert sorted(by_id) == sorted(ids), "Nicht jeder Treffer hat eine Ledger-Zeile"
    for paper_id, rows in by_id.items():
        assert len(rows) == 1, f"{paper_id}: {len(rows)} Ledger-Zeilen statt genau einer"
        row = rows[0]
        assert row["decision"] in sl.SCREENING_DECISIONS
        assert row["reason"].strip(), f"{paper_id}: leere Begruendung"


def test_ledger_records_agent_and_wave(session_dir):
    """Protokoll: welche Quelle wurde von welchem Agent (in welcher Welle) bewertet."""
    import screening_ledger as sl

    _run_screening(session_dir, _hit_ids(22), max_parallel=4)
    for row in sl.read_ledger(session_dir):
        assert row["agent"].startswith("screening-judge#"), row
        assert isinstance(row["wave"], int) and row["wave"] >= 1, row
        assert row["stage"] == "screening"
        assert isinstance(row["ts"], int)


def test_record_decision_rejects_unknown_decision(session_dir):
    import screening_ledger as sl

    with pytest.raises(ValueError):
        sl.record_decision(
            session_dir,
            {"paper_id": "p1", "decision": "maybe", "reason": "…"},
            agent="screening-judge#1",
            wave=1,
        )


def test_record_decision_rejects_empty_reason(session_dir):
    import screening_ledger as sl

    with pytest.raises(ValueError):
        sl.record_decision(
            session_dir,
            {"paper_id": "p1", "decision": "exclude", "reason": "   "},
            agent="screening-judge#1",
            wave=1,
        )


def test_record_decision_is_idempotent(session_dir):
    """Ein zweiter Lauf desselben Falls haengt keine zweite Ledger-Zeile an."""
    import screening_ledger as sl

    payload = _decision_for("paper005")
    sl.record_decision(session_dir, payload, agent="screening-judge#1", wave=1)
    sl.record_decision(session_dir, payload, agent="screening-judge#2", wave=2)

    rows = [r for r in sl.read_ledger(session_dir) if r["paper_id"] == "paper005"]
    assert len(rows) == 1
    assert rows[0]["agent"] == "screening-judge#1", "Erstentscheidung bleibt bestehen"


# ---------------------------------------------------------------------------
# AC2: Vault-Zielstrukturen + PRISMA-Summe
# ---------------------------------------------------------------------------


def _seed_papers(db_path: str, paper_ids: list[str]) -> None:
    from academic_vault.db import VaultDB

    db = VaultDB(db_path)
    for pid in paper_ids:
        db.add_paper(
            paper_id=pid,
            csl_json=json.dumps({"type": "article-journal", "title": f"Titel {pid}"}),
        )


def test_excluded_land_in_vault_included_stay_in_papers(session_dir, temp_vault_db):
    import screening_ledger as sl
    from academic_vault.db import VaultDB

    ids = _hit_ids(22)
    _seed_papers(temp_vault_db, ids)
    _run_screening(session_dir, ids, db_path=temp_vault_db)

    buckets = sl.merge(session_dir)
    db = VaultDB(temp_vault_db)

    assert buckets["exclude"], "Fixture liefert keine Ausschluesse"
    for pid in buckets["exclude"]:
        assert db.is_excluded(pid), f"{pid} fehlt in excluded_sources"

    assert buckets["include"], "Fixture liefert keine Einschluesse"
    for pid in buckets["include"]:
        assert not db.is_excluded(pid), f"{pid} faelschlich in excluded_sources"
        assert db.get_paper(pid) is not None, f"{pid} nicht mehr in papers"


def test_excluded_reason_carries_stage_prefix(session_dir, temp_vault_db):
    import screening_ledger as sl
    from academic_vault.db import VaultDB

    ids = _hit_ids(22)
    _seed_papers(temp_vault_db, ids)
    _run_screening(session_dir, ids, db_path=temp_vault_db)

    rows = {r["paper_id"]: r for r in VaultDB(temp_vault_db).list_excluded_sources()}
    buckets = sl.merge(session_dir)
    for pid in buckets["exclude"]:
        assert rows[pid]["reason"].startswith("screening: "), rows[pid]


def test_prisma_counters_match_ledger_sum(session_dir):
    import screening_ledger as sl

    ids = _hit_ids(22)
    _run_screening(session_dir, ids)

    counters = sl.to_prisma_counters(session_dir, n_identified=30)
    buckets = sl.merge(session_dir)

    assert counters["n_after_dedup"] == len(ids)
    assert counters["n_after_dedup"] == (
        counters["n_excluded_screening"] + counters["n_included"] + counters["n_unclear_screening"]
    )
    assert counters["n_excluded_screening"] == len(buckets["exclude"])
    assert counters["n_included"] == len(buckets["include"])
    assert counters["n_unclear_screening"] == len(buckets["unclear"])
    assert counters["n_identified"] == 30


def test_prisma_counters_account_for_eligibility_stage(session_dir):
    """Volltextpruefung: Eligibility-Ausschluesse verschieben n_included."""
    import screening_ledger as sl

    ids = _hit_ids(22)
    _run_screening(session_dir, ids)
    included = sl.merge(session_dir)["include"]

    dropped = included[:2]
    for pid in dropped:
        sl.record_decision(
            session_dir,
            {
                "paper_id": pid,
                "decision": "exclude",
                "reason": "Volltext ohne Kontrollgruppe",
                "evidence": "fulltext",
            },
            stage="eligibility",
            agent="quality-reviewer#1",
            wave=1,
        )

    counters = sl.to_prisma_counters(session_dir)
    assert counters["n_excluded_eligibility"] == len(dropped)
    assert counters["n_included"] == len(included) - len(dropped)


# ---------------------------------------------------------------------------
# AC3: prisma-flow rendert ohne Zwischenschritt
# ---------------------------------------------------------------------------


def test_ledger_counters_feed_render_flow(session_dir):
    import screening_ledger as sl
    from render_flow import render_prisma_flow

    from search import save_prisma_counters

    _run_screening(session_dir, _hit_ids(22))
    counters = sl.to_prisma_counters(session_dir, n_identified=30)
    save_prisma_counters(session_dir, counters)

    reloaded = json.loads(Path(session_dir, "prisma_counters.json").read_text(encoding="utf-8"))
    mermaid = render_prisma_flow(reloaded)

    assert "```mermaid" in mermaid
    assert f"n = {counters['n_identified']}" in mermaid
    assert f"n = {counters['n_after_dedup']}" in mermaid
    assert f"n = {counters['n_excluded_screening']}" in mermaid
    assert f"n = {counters['n_included']}" in mermaid


def test_render_flow_shows_unclear_bucket_separately(session_dir):
    """Unklare Faelle zaehlen nicht als Volltextkandidaten (AC3 + AC4)."""
    import screening_ledger as sl
    from render_flow import render_prisma_flow

    _run_screening(session_dir, _hit_ids(22))
    counters = sl.to_prisma_counters(session_dir, n_identified=30)
    assert counters["n_unclear_screening"] > 0, "Fixture liefert keine unklaren Faelle"

    mermaid = render_prisma_flow(counters)
    n_fulltext = (
        counters["n_after_dedup"]
        - counters["n_excluded_screening"]
        - counters["n_unclear_screening"]
    )
    assert f"n = {n_fulltext}" in mermaid
    assert "Unklar" in mermaid


def test_render_flow_without_unclear_key_is_unchanged():
    """Rueckwaertskompatibel: ohne n_unclear_screening bleibt der Output identisch."""
    from render_flow import render_prisma_flow

    counters = {
        "n_identified": 100,
        "n_after_dedup": 60,
        "n_excluded_screening": 30,
        "n_excluded_eligibility": 12,
        "n_included": 8,
    }
    mermaid = render_prisma_flow(counters)
    assert "Unklar" not in mermaid
    assert "n = 30" in mermaid


# ---------------------------------------------------------------------------
# AC4: Unklare Faelle werden vorgelegt, nicht entschieden
# ---------------------------------------------------------------------------


def test_merge_returns_unclear_bucket(session_dir):
    import screening_ledger as sl

    _run_screening(session_dir, _hit_ids(22))
    buckets = sl.merge(session_dir)

    assert set(buckets) == {"include", "exclude", "unclear"}
    assert buckets["unclear"], "Unklare Faelle fehlen als eigener Bucket"
    assert not (set(buckets["unclear"]) & set(buckets["include"]))
    assert not (set(buckets["unclear"]) & set(buckets["exclude"]))


def test_unclear_never_written_to_vault(session_dir, temp_vault_db):
    import screening_ledger as sl
    from academic_vault.db import VaultDB

    ids = _hit_ids(22)
    _seed_papers(temp_vault_db, ids)
    _run_screening(session_dir, ids, db_path=temp_vault_db)

    db = VaultDB(temp_vault_db)
    unclear = sl.merge(session_dir)["unclear"]
    assert unclear, "Fixture liefert keine unklaren Faelle"
    for pid in unclear:
        assert not db.is_excluded(pid), f"{pid} wurde selbstaendig ausgeschlossen"
        assert db.list_risk_of_bias(pid) == [], f"{pid} bekam eine RoB-Bewertung"


def test_open_cases_report_lists_unclear_with_reason(session_dir):
    """Die Vorlage fuer die menschliche Entscheidung nennt Fall und Begruendung."""
    import screening_ledger as sl

    _run_screening(session_dir, _hit_ids(22))
    report = sl.open_cases_report(session_dir)

    for pid in sl.merge(session_dir)["unclear"]:
        assert pid in report
    assert "Stichprobengroesse" in report


# ---------------------------------------------------------------------------
# AC5: RoB-Fan-out im vorhandenen Domain-Format
# ---------------------------------------------------------------------------

_RCT_TEXT = (
    "Participants were randomly assigned using sealed envelope allocation concealment. "
    "Blinding of outcome assessors was maintained. Attrition was 5% with reasons "
    "documented and no imputation needed. All pre-specified outcomes are reported."
)


def _run_rob(session_dir, paper_ids, db_path, *, max_parallel=2):
    import screening_ledger as sl

    from tests.helpers.rob_agent_helper import assess_risk_of_bias

    todo = sl.pending_rob(paper_ids, session_dir, db_path)
    for wave_no, wave in enumerate(sl.plan_waves(todo, max_parallel), start=1):
        for slot, pid in enumerate(wave, start=1):
            assess_risk_of_bias(db_path, pid, "RCT", _RCT_TEXT)
            sl.record_decision(
                session_dir,
                {"paper_id": pid, "decision": "assessed", "reason": "RoB 2 Domains bewertet"},
                stage="rob",
                agent=f"risk-of-bias#{slot}",
                wave=wave_no,
                db_path=db_path,
            )
    return todo


def test_rob_fanout_writes_existing_domain_format(session_dir, temp_vault_db):
    from academic_vault.db import VaultDB

    from tests.helpers.rob_agent_helper import RCT_DOMAINS

    ids = ["rob001", "rob002", "rob003"]
    _seed_papers(temp_vault_db, ids)
    _run_rob(session_dir, ids, temp_vault_db)

    db = VaultDB(temp_vault_db)
    for pid in ids:
        rows = db.list_risk_of_bias(pid)
        assert len(rows) == 1, f"{pid}: {len(rows)} Assessments"
        scores = json.loads(rows[0]["domain_scores_json"])
        for domain in RCT_DOMAINS:
            assert domain in scores, f"{pid}: Domain {domain} fehlt"
            assert scores[domain]["score"] in ("low", "some concerns", "high")
        assert scores["overall"] in ("low", "some concerns", "high")


def test_rob_ledger_protocols_agent_per_source(session_dir, temp_vault_db):
    import screening_ledger as sl

    ids = ["rob001", "rob002", "rob003"]
    _seed_papers(temp_vault_db, ids)
    _run_rob(session_dir, ids, temp_vault_db)

    rob_rows = [r for r in sl.read_ledger(session_dir) if r["stage"] == "rob"]
    assert sorted(r["paper_id"] for r in rob_rows) == sorted(ids)
    assert all(r["agent"].startswith("risk-of-bias#") for r in rob_rows)


# ---------------------------------------------------------------------------
# AC6: Resume nach Abbruch
# ---------------------------------------------------------------------------


def test_resume_returns_only_pending_ids(session_dir):
    import screening_ledger as sl

    ids = _hit_ids(22)
    done, rest = ids[:12], ids[12:]
    for pid in done:
        sl.record_decision(session_dir, _decision_for(pid), agent="screening-judge#1", wave=1)

    assert sl.pending(ids, session_dir) == rest


def test_resume_second_run_does_not_rescreen(session_dir):
    import screening_ledger as sl

    ids = _hit_ids(22)
    first_waves = _run_screening(session_dir, ids[:12])
    assert sum(len(w) for w in first_waves) == 12

    second_waves = _run_screening(session_dir, ids)
    assert sum(len(w) for w in second_waves) == 10, "Bereits bewertete Quellen erneut geprueft"
    assert len(sl.read_ledger(session_dir)) == 22


def test_resume_does_not_duplicate_rob_assessments(session_dir, temp_vault_db):
    """``add_risk_of_bias`` ist reines INSERT — Resume muss vorher pruefen."""
    from academic_vault.db import VaultDB

    ids = ["rob001", "rob002", "rob003"]
    _seed_papers(temp_vault_db, ids)
    _run_rob(session_dir, ids, temp_vault_db)
    second = _run_rob(session_dir, ids, temp_vault_db)

    assert second == [], "Zweiter Lauf haette nichts mehr zu tun"
    db = VaultDB(temp_vault_db)
    for pid in ids:
        assert len(db.list_risk_of_bias(pid)) == 1, f"{pid} doppelt bewertet"


def test_pending_rob_skips_papers_already_assessed_outside_ledger(session_dir, temp_vault_db):
    """Ein Assessment aus einem frueheren Lauf ohne Ledger zaehlt ebenfalls als erledigt."""
    import screening_ledger as sl

    from tests.helpers.rob_agent_helper import assess_risk_of_bias

    ids = ["rob001", "rob002"]
    _seed_papers(temp_vault_db, ids)
    assess_risk_of_bias(temp_vault_db, "rob001", "RCT", _RCT_TEXT)

    assert sl.pending_rob(ids, session_dir, temp_vault_db) == ["rob002"]


def test_read_ledger_on_missing_file_is_empty(session_dir):
    import screening_ledger as sl

    assert sl.read_ledger(session_dir) == []
    assert sl.pending(["a", "b"], session_dir) == ["a", "b"]


def test_ledger_survives_corrupt_line(session_dir):
    """Eine abgebrochene Schreiboperation darf den Resume nicht sprengen."""
    import screening_ledger as sl

    sl.record_decision(session_dir, _decision_for("paper001"), agent="screening-judge#1", wave=1)
    path = Path(sl.ledger_path(session_dir))
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"paper_id": "paper002", "deci\n')

    assert [r["paper_id"] for r in sl.read_ledger(session_dir)] == ["paper001"]


# ---------------------------------------------------------------------------
# Artefakte: Skill + Agent
# ---------------------------------------------------------------------------


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path}: kein Frontmatter"
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end])


def test_skill_md_exists_with_frontmatter():
    skill_md = SKILL_DIR / "SKILL.md"
    assert skill_md.exists(), f"Fehlt: {skill_md}"
    fm = _frontmatter(skill_md)
    assert fm["name"] == "parallel-screening"
    assert fm.get("license")
    assert isinstance(fm.get("allowed-tools"), list)


def test_skill_md_documents_resume_and_limit():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "ACADEMIC_RESEARCH_MAX_PARALLEL" in text
    assert "screening_ledger.py" in text
    assert "pending" in text


def test_skill_md_python_api_import_is_executable():
    """Der in der SKILL.md dokumentierte Import muss real funktionieren."""
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    stmts = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith(("from screening_ledger import", "import screening_ledger"))
    ]
    assert stmts, "SKILL.md dokumentiert keinen screening_ledger-Import"
    namespace: dict = {}
    for stmt in stmts:
        exec(compile(stmt, "<skill-md>", "exec"), namespace)


def test_agent_md_defines_single_case_json_contract():
    assert AGENT_MD.exists(), f"Fehlt: {AGENT_MD}"
    fm = _frontmatter(AGENT_MD)
    assert fm["name"] == "screening-judge"
    assert fm.get("description", "").strip()

    body = AGENT_MD.read_text(encoding="utf-8")
    for field in ("paper_id", "decision", "reason", "criterion", "confidence", "evidence"):
        assert field in body, f"Agent-Vertrag nennt '{field}' nicht"
    for value in ("include", "exclude", "unclear"):
        assert value in body, f"Agent-Vertrag nennt Entscheidung '{value}' nicht"


def test_agent_md_forbids_deciding_unclear_cases():
    body = AGENT_MD.read_text(encoding="utf-8")
    assert re.search(r"nie(mals)? selbst(ständig|staendig)? entscheid", body, re.I), (
        "Agent-Datei enthaelt keine explizite Unklar-Regel"
    )


def test_agent_md_declares_no_vault_write_tools():
    """Der Judge urteilt nur — Vault-Schreibzugriffe laufen ueber die Buchfuehrung."""
    fm = _frontmatter(AGENT_MD)
    tools = fm.get("tools", [])
    assert isinstance(tools, list) and tools
    for tool in tools:
        assert "add_" not in tool, f"screening-judge darf nicht schreiben: {tool}"
