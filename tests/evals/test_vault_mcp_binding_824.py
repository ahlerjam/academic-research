"""Hermetische Guards fuer die Vault-MCP-Anbindung der Evals (Issue #824).

Kein Test hier ruft die claude-CLI auf -- der Live-Nachweis der Bindung
liegt in ``docs/evals/2026-08-10-vault-mcp-evals-824.md`` (+ ``-live-results.json``).
Diese Datei sichert die Teile ab, die sich ohne Modell pruefen lassen:

* Der Seeder legt tatsaechlich die Papers/Quotes an, auf die sich
  ``evals/quote-extractor/evals.json`` und ``evals/chapter-writer/evals.json``
  beziehen -- und zwar in einer **Wegwerf-DB**, nie in der Operator-Vault.
* Die Fixture-PDFs haben einen echten Text-Layer mit dem Papertitel in
  Zeile 1 (sonst blockiert der Titel-Plausibilitaetscheck aus
  ``agents/quote-extractor.md`` die Persistenz) und enthalten die
  Seed-Zitate wortgleich (sonst scheitert die fail-closed-Verbatim-Pruefung).
* Die MCP-Config nennt genau einen Server, ohne Netz-Werkzeuge.
* Das ``vault``-Profil reicht ``cwd``/``mcp_config`` bis in die
  CLI-Kommandozeile durch (gemockter Subprozess).
* Das Skip-Inventar ist maschinell lesbar, begruendet und deckt sich mit
  den tatsaechlich existierenden Node-IDs; der Guard schlaegt bei jeder
  Abweichung der Skip-Menge an.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts.dev.summarize_eval_junit import summarize

from tests.evals import eval_runner
from tests.evals.eval_runner import SESSION_PROFILES
from tests.evals.skip_inventory import (
    EVAL_SKIP_PREFIX,
    GOVERNED_SUITES,
    SKIP_INVENTORY,
    check_skip_inventory,
)
from tests.evals.vault_fixture import (
    MCP_SERVER_NAME,
    SEED_PAPERS,
    build_vault_session,
    paper_pdf_lines,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Seeder + Wegwerf-DB
# ---------------------------------------------------------------------------


def test_seeded_vault_contains_expected_papers_and_quotes(tmp_path):
    """AC2: die temporaere DB traegt genau die Papers/Quotes der Eval-Prompts."""
    from academic_vault.db import VaultDB

    session = build_vault_session(tmp_path / "vault-session")
    db = VaultDB(str(session.db_path))

    for paper_id, seed in SEED_PAPERS.items():
        stored = db.get_paper(paper_id)
        assert stored is not None, f"Paper {paper_id} fehlt in der geseedeten Vault"
        assert stored["pdf_path"], f"Paper {paper_id} ohne pdf_path"
        assert Path(stored["pdf_path"]).is_file(), (
            f"pdf_path von {paper_id} zeigt ins Leere: {stored['pdf_path']}"
        )
        quotes = db.find_quotes(paper_id)
        assert len(quotes) == len(seed["_seed_quotes"]), (
            f"Quote-Zahl fuer {paper_id} weicht ab: {len(quotes)} statt {len(seed['_seed_quotes'])}"
        )
        assert {q["verbatim"] for q in quotes} == {q["verbatim"] for q in seed["_seed_quotes"]}


def test_seeded_paper_metadata_carries_author_and_year(tmp_path):
    """cw-01/cw-04 erwarten ``(Smith, 2023)``/``Mueller`` -- ohne Autor/Jahr bliebe nur Raten."""
    from academic_vault.db import VaultDB

    session = build_vault_session(tmp_path / "vault-session")
    db = VaultDB(str(session.db_path))

    csl = json.loads(db.get_paper("smith2023")["csl_json"])
    assert csl["author"][0]["family"] == "Smith"
    assert csl["issued"]["date-parts"][0][0] == 2023


def test_seeded_db_path_is_not_the_operator_vault(tmp_path):
    """AC2: die DB liegt unter tmp_path, niemals unter ``~/.academic-research``."""
    session = build_vault_session(tmp_path / "vault-session")
    operator_vault = Path.home() / ".academic-research"
    assert session.db_path.is_relative_to(tmp_path)
    assert not session.db_path.is_relative_to(operator_vault)
    assert session.root.is_relative_to(tmp_path)


def test_seeding_leaves_process_env_untouched(tmp_path, monkeypatch):
    """``VAULT_DB_PATH`` steht nur in der MCP-Config, nie in der pytest-Umgebung.

    Sonst wuerde ein spaeterer ``VaultDB()``-Aufruf im selben Prozess still
    auf die Wegwerf-DB zeigen -- und ``subprocess.run(env=...)`` haette
    ``PATH``/``HOME``/``CLAUDE_CODE_OAUTH_TOKEN`` aus der Sitzung entfernt.
    """
    monkeypatch.delenv("VAULT_DB_PATH", raising=False)
    build_vault_session(tmp_path / "vault-session")
    import os

    assert "VAULT_DB_PATH" not in os.environ


# ---------------------------------------------------------------------------
# Fixture-PDFs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "paper_id", sorted(pid for pid, p in SEED_PAPERS.items() if p["has_text_layer"])
)
def test_fixture_pdf_has_text_layer_with_title_first(tmp_path, paper_id):
    """Risiko 4/5: Titel in Zeile 1, Seed-Zitate wortgleich im Text-Layer."""
    pypdf = pytest.importorskip("pypdf")

    session = build_vault_session(tmp_path / "vault-session")
    pdf_path = session.root / SEED_PAPERS[paper_id]["pdf_name"]
    text = pypdf.PdfReader(str(pdf_path)).pages[0].extract_text()

    first_line = text.strip().splitlines()[0].strip()
    assert first_line == SEED_PAPERS[paper_id]["title"], (
        f"Titel steht nicht in Zeile 1 von {pdf_path.name}: {first_line!r}"
    )
    for line in paper_pdf_lines(SEED_PAPERS[paper_id]):
        assert line in text, f"Zeile fehlt im Text-Layer von {pdf_path.name}: {line!r}"


def test_scan_only_fixture_has_no_text_layer(tmp_path):
    """qe-03 misst den OCR-losen Scan: pypdf muss dort leer zurueckkommen."""
    pypdf = pytest.importorskip("pypdf")

    session = build_vault_session(tmp_path / "vault-session")
    pdf_path = session.root / SEED_PAPERS["mlops_scan_only"]["pdf_name"]
    assert pypdf.PdfReader(str(pdf_path)).pages[0].extract_text().strip() == ""


def test_quantum_fixture_has_no_cryptography_text(tmp_path):
    """qe-05 erwartet eine leere Zitatliste -- der Text darf kein Thema anbieten."""
    text = " ".join(paper_pdf_lines(SEED_PAPERS["quantum2021"])).lower()
    for forbidden in ("crypt", "post-quantum", "encryption"):
        assert forbidden not in text, (
            f"quantum2021-Fixture enthaelt {forbidden!r} -- qe-05 koennte dann "
            f"zurecht ein Zitat liefern und der Fall misst nichts mehr."
        )


# ---------------------------------------------------------------------------
# MCP-Config + Profil-Durchreichung
# ---------------------------------------------------------------------------


def test_mcp_config_has_exactly_one_server_and_no_network_tools(tmp_path):
    """AC2: genau ein Server, eigener Interpreter, DB-Pfad in tmp_path, kein Netz."""
    session = build_vault_session(tmp_path / "vault-session")
    config = json.loads(session.mcp_config_path.read_text(encoding="utf-8"))

    assert set(config["mcpServers"]) == {MCP_SERVER_NAME}
    server = config["mcpServers"][MCP_SERVER_NAME]
    assert server["command"] == sys.executable
    assert server["args"] == ["-m", "academic_vault.server"]
    assert Path(server["env"]["VAULT_DB_PATH"]).is_relative_to(tmp_path)
    assert Path(server["env"]["PYTHONPATH"]) == REPO_ROOT

    allowed = SESSION_PROFILES["vault"]["allowed_tools"]
    for forbidden in ("WebFetch", "WebSearch", "Bash"):
        assert forbidden not in allowed, (
            f"vault-Profil gibt {forbidden} frei -- Evals waeren damit nicht mehr "
            f"netzfrei/deterministisch."
        )


def test_vault_profile_passes_mcp_config_and_cwd(tmp_path):
    """AC1 (hermetisch): cwd/mcp_config landen tatsaechlich in der Kommandozeile."""
    session = build_vault_session(tmp_path / "vault-session")
    captured: dict[str, object] = {}

    class _Result:
        returncode = 0
        stdout = json.dumps({"result": "ok", "is_error": False})
        stderr = ""

    def _fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs.get("cwd")
        captured["env"] = kwargs.get("env")
        return _Result()

    with (
        patch.object(eval_runner.shutil, "which", return_value="/usr/bin/claude"),
        patch.object(eval_runner.subprocess, "run", _fake_run),
    ):
        eval_runner.call_claude_for_component(
            "quote-extractor",
            system="sys",
            user="usr",
            cwd=session.root,
            mcp_config=session.mcp_config_path,
        )

    command = captured["command"]
    assert "--mcp-config" in command
    assert command[command.index("--mcp-config") + 1] == str(session.mcp_config_path)
    assert "--strict-mcp-config" in command
    assert (
        command[command.index("--allowedTools") + 1] == SESSION_PROFILES["vault"]["allowed_tools"]
    )
    assert captured["cwd"] == str(session.root)
    # env=None: die Prozessumgebung wird geerbt, nicht ersetzt (Risiko 1).
    assert captured["env"] is None


# ---------------------------------------------------------------------------
# Skip-Inventar + Guard
# ---------------------------------------------------------------------------


def test_skipped_eval_cases_carry_machine_readable_reason():
    """AC3: jeder Inventar-Eintrag hat ein ``eval-skip:``-Praefix."""
    assert SKIP_INVENTORY, "Inventar ist leer -- dann fehlt der Guard seine Referenz"
    for node_id, entry in SKIP_INVENTORY.items():
        assert entry.reason.startswith(EVAL_SKIP_PREFIX), (
            f"{node_id}: Grund {entry.reason!r} ohne maschinenlesbares Praefix"
        )
        assert node_id.startswith(GOVERNED_SUITES)


def test_inventory_entries_have_reason_and_decision_reference():
    """AC5: kein Dauer-Skip ohne Begruendung und Verweis -- sonst ist es eine stille Luecke."""
    for node_id, entry in SKIP_INVENTORY.items():
        assert len(entry.reason) > len(EVAL_SKIP_PREFIX) + 5, f"{node_id}: Grund zu duenn"
        assert entry.decision_reference.strip(), f"{node_id}: kein Begruendungsverweis"


def test_skip_inventory_node_ids_exist():
    """Ein Inventar-Eintrag auf einen nicht existierenden Fall ist ein toter Guard."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *GOVERNED_SUITES,
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"Collect-Only-Lauf schlug fehl: {result.stdout[-2000:]}"
    collected = {line.strip() for line in result.stdout.splitlines() if "::" in line}
    missing = sorted(set(SKIP_INVENTORY) - collected)
    assert not missing, (
        f"Skip-Inventar nennt Node-IDs, die es nicht (mehr) gibt: {missing}. "
        f"tests/evals/skip_inventory.py anpassen."
    )


def _junit_xml(cases: list[tuple[str, str, str | None]]) -> str:
    """Baut eine synthetische JUnit-XML aus ``(classname, name, skip_message|None)``."""
    parts = ['<?xml version="1.0" encoding="utf-8"?>', "<testsuites>", '<testsuite name="pytest">']
    for classname, name, message in cases:
        if message is None:
            parts.append(f'<testcase classname="{classname}" name="{name}" />')
        else:
            escaped = message.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
            parts.append(
                f'<testcase classname="{classname}" name="{name}">'
                f'<skipped message="{escaped}" type="pytest.skip" /></testcase>'
            )
    parts += ["</testsuite>", "</testsuites>"]
    return "\n".join(parts)


def _inventory_cases() -> list[tuple[str, str, str | None]]:
    cases: list[tuple[str, str, str | None]] = []
    for node_id, entry in SKIP_INVENTORY.items():
        path, _, name = node_id.partition("::")
        classname = path.removesuffix(".py").replace("/", ".")
        cases.append((classname, name, entry.reason))
    return cases


def _write_xml(tmp_path: Path, cases: list[tuple[str, str, str | None]]) -> Path:
    path = tmp_path / "junit.xml"
    path.write_text(_junit_xml(cases), encoding="utf-8")
    return path


def test_check_skip_inventory_accepts_matching_run(tmp_path):
    """Deckt sich die Skip-Menge mit dem Inventar, gibt es keinen Befund."""
    assert check_skip_inventory(_write_xml(tmp_path, _inventory_cases())) == []


def test_check_skip_inventory_ignores_unprefixed_and_foreign_skips(tmp_path):
    """Ein CLI-loser Lauf (Skip ohne Praefix) und fremde Suiten faerben nicht rot."""
    cases = _inventory_cases()
    cases.append(
        (
            "tests.evals.test_rest_evals",
            "test_rest_eval[with_skill-ac-01]",
            "claude-CLI nicht verfuegbar - Eval uebersprungen",
        )
    )
    cases.append(
        (
            "tests.evals.test_quote_extractor_evals",
            "test_quote_extractor_eval[with_skill-qe-01]",
            "claude-CLI nicht verfuegbar - Eval uebersprungen",
        )
    )
    assert check_skip_inventory(_write_xml(tmp_path, cases)) == []


def test_check_skip_inventory_flags_additional_skip(tmp_path):
    """AC3: ein zusaetzlicher Dauer-Skip ist ein Befund, kein stilles Gruen."""
    cases = _inventory_cases()
    cases.append(
        (
            "tests.evals.test_quote_extractor_evals",
            "test_quote_extractor_eval[with_skill-qe-01]",
            f"{EVAL_SKIP_PREFIX}vault-unavailable MCP-Server startete nicht",
        )
    )
    problems = check_skip_inventory(_write_xml(tmp_path, cases))
    assert len(problems) == 1
    assert "Nicht inventarisierter Skip" in problems[0]
    assert "qe-01" in problems[0]


def test_check_skip_inventory_flags_missing_skip(tmp_path):
    """AC3: laeuft ein inventarisierter Fall wieder echt, muss der Eintrag weg.

    Die uebrigen Faelle der Suite bleiben in der XML -- die Suite lief also,
    nur dieser eine Fall fehlt. Das ist ein echter Regressionsbefund, kein
    gefilterter Lauf (siehe Test unten), und muss weiterhin anschlagen.
    """
    cases = _inventory_cases()[1:]
    problems = check_skip_inventory(_write_xml(tmp_path, cases))
    assert len(problems) == 1
    assert "Inventarisierter Skip fehlt im Lauf" in problems[0]


def test_check_skip_inventory_ignores_missing_skips_for_suite_not_run(tmp_path):
    """P1-Review-Finding zu .github/workflows/eval-behavior.yml:205 (Issue #824).

    Ein gefilterter workflow_dispatch-Lauf (``component: chapter_writer``
    bzw. ``component: quote_extractor``, ``pytest -k "${FILTER}"``) fuehrt
    nur eine der beiden GOVERNED_SUITES aus -- die andere taucht in der
    JUnit-XML ueberhaupt nicht auf (kein einziges Testcase-Element, weder
    bestanden noch uebersprungen). Das darf keinen Befund erzeugen: die Suite
    ist nicht fehlgeschlagen, sie war schlicht nicht Teil des Laufs.
    """
    cases = [c for c in _inventory_cases() if "test_chapter_writer_evals" not in c[0]]
    assert any("test_quote_extractor_evals" in c[0] for c in cases), (
        "Testaufbau fehlerhaft: quote-extractor-Faelle muessen in der Fixture bleiben, "
        "sonst waere die gesamte GOVERNED_SUITES-Menge nicht im Lauf und der Test "
        "ueberpruefte gar nichts."
    )
    problems = check_skip_inventory(_write_xml(tmp_path, cases))
    assert problems == [], (
        f"Ein Filter-Lauf ohne chapter-writer-Suite darf deren inventarisierte Skips "
        f"nicht als fehlend melden: {problems}"
    )


def test_check_skip_inventory_flags_changed_reason(tmp_path):
    """Ein umgeschriebener Grund darf nicht unbemerkt durchrutschen."""
    cases = _inventory_cases()
    classname, name, _ = cases[0]
    cases[0] = (classname, name, f"{EVAL_SKIP_PREFIX}anderer-grund")
    problems = check_skip_inventory(_write_xml(tmp_path, cases))
    assert len(problems) == 1
    assert "Skip-Grund weicht ab" in problems[0]


# ---------------------------------------------------------------------------
# Sichtbarkeit im Lauf-Protokoll
# ---------------------------------------------------------------------------


def test_summarize_eval_junit_lists_skipped_cases_with_reason(tmp_path):
    """AC4: ein Skip steht namentlich mit Grund im Step-Summary, nicht nur als Zahl."""
    reason = f"{EVAL_SKIP_PREFIX}net-excluded Prompt qe-04 setzt Live-Abruf voraus"
    xml = _write_xml(
        tmp_path,
        [
            (
                "tests.evals.test_quote_extractor_evals",
                "test_quote_extractor_eval[with_skill-qe-04]",
                reason,
            ),
            (
                "tests.evals.test_quote_extractor_evals",
                "test_quote_extractor_eval[with_skill-qe-01]",
                None,
            ),
        ],
    )
    output = summarize(xml)
    assert "Uebersprungene Faelle" in output
    assert "test_quote_extractor_eval[with_skill-qe-04]" in output
    assert "net-excluded" in output


def test_summarize_eval_junit_without_skips_has_no_skip_section(tmp_path):
    """Ohne Skips bleibt das Summary so knapp wie vorher."""
    xml = _write_xml(
        tmp_path,
        [
            (
                "tests.evals.test_quote_extractor_evals",
                "test_quote_extractor_eval[with_skill-qe-01]",
                None,
            )
        ],
    )
    assert "Uebersprungene Faelle" not in summarize(xml)
