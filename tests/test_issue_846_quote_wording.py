"""Wortlaut-Pruefung woertlicher Zitate gegen den Vault-Snapshot (Issue #846).

Zwei Ebenen, bewusst getrennt:

1. **Python-Unit-Tests** der Statusmatrix von
   :func:`academic_vault.server.match_quote_wording` — sie belegen, dass eine
   tolerierte Variante wirklich als ``normalized``/``ellipsis`` erkannt wird
   und nicht bloss "kein Alarm, weil nichts geprueft wurde" (Positivkontrolle,
   Muster aus #513).
2. **Hook-Subprozess-Tests** (`hooks/verbatim-guard.mjs`), die das
   tatsaechliche Blockverhalten samt Meldungstext pruefen — Harness analog
   `tests/test_verbatim_figure_guard.py`.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

HOOK_PATH = Path(__file__).parent.parent / "hooks" / "verbatim-guard.mjs"
WORKTREE_ROOT = Path(__file__).parent.parent
LIMITS_DOC = WORKTREE_ROOT / "docs" / "guide" / "limits.md"

VAULT_QUOTE = (
    "Governance ist ein Prozess der Aushandlung zwischen mehreren Akteuren "
    "und keine einmalige Entscheidung."
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _vault_with_quotes(tmp_path, verbatims, name="wording_vault.db"):
    """Legt eine Vault-DB mit einem Paper und den uebergebenen Zitaten an."""
    from academic_vault.db import VaultDB
    from academic_vault.server import add_paper, add_quote

    db_path = str(tmp_path / name)
    db = VaultDB(db_path)
    db.init_schema()
    add_paper(
        db_path=db_path,
        paper_id="paper-846",
        csl_json=json.dumps({"title": "Governance", "type": "article-journal"}),
    )
    for verbatim in verbatims:
        add_quote(
            db_path=db_path,
            paper_id="paper-846",
            verbatim=verbatim,
            extraction_method="manual",
        )
    return db_path


@pytest.fixture
def vault_db(tmp_path):
    return _vault_with_quotes(tmp_path, [VAULT_QUOTE])


def run_hook(
    tool_name: str, file_path: str, content: str, env_overrides: dict | None = None
) -> subprocess.CompletedProcess:
    """Startet den Hook als Subprocess mit JSON-Eingabe auf stdin."""
    payload = json.dumps(
        {
            "tool_name": tool_name,
            "tool_input": {"file_path": file_path, "content": content},
        }
    )
    env = os.environ.copy()
    env["VAULT_DB_PATH"] = str(WORKTREE_ROOT / "nonexistent_vault_for_tests.db")
    # Guard-Logs nie im Repo/Home ablegen: der Test misst das Blockverhalten,
    # nicht das Logging (dafuer gibt es einen eigenen Test mit tmp_path).
    env["VAULT_GUARD_ENV_SWITCH_LOG"] = str(Path(tempfile.gettempdir()) / "issue846-switch.log")
    env["VAULT_GUARD_BYPASS_LOG"] = str(Path(tempfile.gettempdir()) / "issue846-bypass.log")
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["node", str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# AC2 (Positivkontrolle) — tolerierte Varianten sind erkannt, nicht uebersehen
# ---------------------------------------------------------------------------


def _match_one(db_path, candidate, **kwargs):
    from academic_vault.server import match_quote_wording

    results = match_quote_wording(db_path, [candidate], **kwargs)
    assert len(results) == 1, f"Erwartet genau ein Ergebnis, got {results}"
    return results[0]


def test_identical_wording_is_exact(vault_db):
    result = _match_one(vault_db, VAULT_QUOTE)
    assert result["status"] == "exact", result


def test_typographic_quotes_inside_are_normalized(tmp_path):
    db_path = _vault_with_quotes(
        tmp_path,
        ["Der sogenannte 'weiche' Faktor der Aushandlung entscheidet ueber den Erfolg."],
    )
    result = _match_one(
        db_path,
        "Der sogenannte ‚weiche‘ Faktor der Aushandlung entscheidet ueber den Erfolg.",
    )
    assert result["status"] == "normalized", result


def test_collapsed_whitespace_is_normalized(vault_db):
    candidate = VAULT_QUOTE.replace("Prozess der", "Prozess\n   der")
    result = _match_one(vault_db, candidate)
    assert result["status"] == "normalized", result


def test_hyphenated_linebreak_is_normalized(vault_db):
    candidate = VAULT_QUOTE.replace("Aushandlung", "Aushand-\nlung")
    result = _match_one(vault_db, candidate)
    assert result["status"] == "normalized", result


def test_ellipsis_fragments_are_recognised(vault_db):
    candidate = "Governance ist ein Prozess der Aushandlung […] keine einmalige Entscheidung."
    result = _match_one(vault_db, candidate)
    assert result["status"] == "ellipsis", result


def test_ascii_ellipsis_fragments_are_recognised(vault_db):
    candidate = "Governance ist ein Prozess der Aushandlung [...] keine einmalige Entscheidung."
    result = _match_one(vault_db, candidate)
    assert result["status"] == "ellipsis", result


def test_ellipsis_fragments_out_of_order_are_not_accepted(vault_db):
    """Reihenfolge zaehlt: umgestellte Fragmente sind kein zulaessiges Auslassungszitat."""
    candidate = "keine einmalige Entscheidung […] Governance ist ein Prozess der Aushandlung"
    result = _match_one(vault_db, candidate)
    assert result["status"] != "ellipsis", result


def test_case_only_difference_does_not_count_as_deviation(vault_db):
    candidate = VAULT_QUOTE.replace("Prozess", "PROZESS")
    result = _match_one(vault_db, candidate)
    assert result["status"] == "normalized", result
    assert result["case_only"] is True, result


# ---------------------------------------------------------------------------
# AC1 — abweichender Wortlaut wird als solcher erkannt (nicht als "fehlt")
# ---------------------------------------------------------------------------


def test_changed_word_is_deviation_with_word_diff(vault_db):
    candidate = VAULT_QUOTE.replace("Prozess", "Vorgang")
    result = _match_one(vault_db, candidate)
    assert result["status"] == "deviation", result
    assert "Prozess" in result["vault_verbatim"], result
    pairs = [(d.get("chapter"), d.get("vault")) for d in result["diff"]]
    assert ("Vorgang", "Prozess") in pairs, result


def test_unrelated_text_is_absent(vault_db):
    result = _match_one(
        vault_db,
        "Die Wetterlage im Alpenvorland blieb ueber den gesamten Zeitraum unauffaellig.",
    )
    assert result["status"] == "absent", result


def test_short_candidate_is_absent_not_deviation(vault_db):
    """Kurze Zitate treffen zufaellig hohe Fuzzy-Scores (#520) — keine Zuordnung."""
    result = _match_one(vault_db, "ein Vorgang")
    assert result["status"] == "absent", result


def test_ambiguous_best_match_is_absent(tmp_path):
    """Zwei gleich nahe Vault-Zitate: lieber 'nicht zuordenbar' als falscher Wortlaut-Vorwurf."""
    db_path = _vault_with_quotes(
        tmp_path,
        [
            "Die Steuerung der Entwicklung erfolgt ueber formale Regeln und Prozesse im Betrieb.",
            "Die Steuerung der Entwicklung erfolgt ueber formale Regeln und Prozesse im Konzern.",
        ],
    )
    result = _match_one(
        db_path,
        "Die Steuerung der Entwicklung erfolgt ueber formale Regeln und Prozesse im Verbund.",
    )
    assert result["status"] == "absent", result


# ---------------------------------------------------------------------------
# AC3 — fail-open und Fehler-Isolation
# ---------------------------------------------------------------------------


def test_broken_candidate_does_not_invalidate_batch(vault_db):
    """Ein Eintrag mit falschem Typ liefert {error}, die uebrigen bleiben ausgewertet."""
    from academic_vault.server import match_quote_wording

    results = match_quote_wording(vault_db, [VAULT_QUOTE, None, VAULT_QUOTE])
    assert results[0]["status"] == "exact", results
    assert "error" in results[1], results
    assert results[2]["status"] == "exact", results


def test_hook_failopen_missing_db_keeps_wording():
    content = f'Der Autor schreibt: "{VAULT_QUOTE}"'
    result = run_hook("Write", "kapitel/kap1.md", content)
    assert result.returncode == 0, result.stderr
    assert "Vault-DB nicht gefunden" in result.stderr, result.stderr


def test_hook_failopen_on_corrupt_db(tmp_path):
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_text("keine sqlite-datei")
    candidate = VAULT_QUOTE.replace("Prozess", "Vorgang")
    content = f'Der Autor schreibt: "{candidate}"'
    result = run_hook(
        "Write", "kapitel/kap1.md", content, env_overrides={"VAULT_DB_PATH": str(corrupt)}
    )
    assert result.returncode == 0, result.stderr
    assert "trotz vorhandener DB" in result.stderr, result.stderr


# ---------------------------------------------------------------------------
# AC1 im Hook — Blockmeldung mit Fundstelle und Abweichung
# ---------------------------------------------------------------------------


def test_hook_blocks_wording_deviation_with_location_and_diff(vault_db):
    candidate = VAULT_QUOTE.replace("Prozess", "Vorgang")
    content = "\n".join(
        [
            "# Kapitel 1",
            "",
            f'Der Autor schreibt: "{candidate}"',
        ]
    )
    result = run_hook(
        "Write", "kapitel/kap1.md", content, env_overrides={"VAULT_DB_PATH": vault_db}
    )
    assert result.returncode == 2, f"Erwartet Block, got {result.returncode}: {result.stderr}"
    assert "Wortlaut" in result.stderr, result.stderr
    assert "kapitel/kap1.md:3" in result.stderr, (
        f"Erwartet Fundstelle mit Datei UND Zeilennummer: {result.stderr}"
    )
    assert "Prozess" in result.stderr, result.stderr
    assert "Vorgang" in result.stderr, result.stderr


def test_hook_reports_instead_of_blocking_in_report_mode(vault_db):
    candidate = VAULT_QUOTE.replace("Prozess", "Vorgang")
    content = f'Der Autor schreibt: "{candidate}"'
    result = run_hook(
        "Write",
        "kapitel/kap1.md",
        content,
        env_overrides={
            "VAULT_DB_PATH": vault_db,
            "ACADEMIC_VERBATIM_WORDING": "report",
        },
    )
    assert result.returncode == 0, f"report-Modus darf nicht blocken: {result.stderr}"
    assert "Wortlaut" in result.stderr, result.stderr


def test_hook_logs_wording_switch_as_guard_weakening(vault_db, tmp_path):
    """Der Strenge-Schalter ist guard-schwaechend und muss protokolliert werden (#519)."""
    log_path = tmp_path / "env-switch.log"
    content = f'Der Autor schreibt: "{VAULT_QUOTE}"'
    result = run_hook(
        "Write",
        "kapitel/kap1.md",
        content,
        env_overrides={
            "VAULT_DB_PATH": vault_db,
            "ACADEMIC_VERBATIM_WORDING": "report",
            "VAULT_GUARD_ENV_SWITCH_LOG": str(log_path),
        },
    )
    assert result.returncode == 0, result.stderr
    assert log_path.exists(), "Env-Switch-Log wurde nicht geschrieben"
    assert "ACADEMIC_VERBATIM_WORDING=report" in log_path.read_text(), log_path.read_text()


# ---------------------------------------------------------------------------
# AC2 im Hook — tolerierte Varianten passieren ohne Falschalarm
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "candidate",
    [
        pytest.param(VAULT_QUOTE, id="identisch"),
        pytest.param(VAULT_QUOTE.replace("Prozess der", "Prozess\n   der"), id="whitespace"),
        pytest.param(VAULT_QUOTE.replace("Aushandlung", "Aushand-\nlung"), id="trennstrich"),
        pytest.param(
            "Governance ist ein Prozess der Aushandlung […] keine einmalige Entscheidung.",
            id="auslassung",
        ),
    ],
)
def test_hook_allows_tolerated_variants(vault_db, candidate):
    content = f'Der Autor schreibt: "{candidate}"'
    result = run_hook(
        "Write", "kapitel/kap1.md", content, env_overrides={"VAULT_DB_PATH": vault_db}
    )
    assert result.returncode == 0, f"Falschalarm: {result.stderr}"
    assert "BLOCKIERT" not in result.stderr, result.stderr


def test_hook_allows_typographic_quotes_inside_span(tmp_path):
    db_path = _vault_with_quotes(
        tmp_path,
        ["Der sogenannte 'weiche' Faktor der Aushandlung entscheidet ueber den Erfolg."],
    )
    content = (
        "Der Autor schreibt: "
        "„Der sogenannte ‚weiche‘ Faktor der Aushandlung entscheidet ueber den Erfolg.“"
    )
    result = run_hook("Write", "kapitel/kap1.md", content, env_overrides={"VAULT_DB_PATH": db_path})
    assert result.returncode == 0, f"Falschalarm bei Typografie: {result.stderr}"


# ---------------------------------------------------------------------------
# AC4 — Pruefkontingent
# ---------------------------------------------------------------------------


def test_wording_limit_caps_the_expensive_stage(vault_db):
    """Ueber dem Kontingent laeuft die Wortlaut-Zuordnung nicht mehr — geblockt wird trotzdem."""
    from academic_vault.server import match_quote_wording

    deviating = VAULT_QUOTE.replace("Prozess", "Vorgang")
    results = match_quote_wording(vault_db, [deviating, deviating], wording_limit=1)
    assert results[0]["status"] == "deviation", results
    assert results[1]["status"] == "absent", results
    assert results[1]["quota_capped"] is True, results


def test_hook_respects_quota_without_silent_pass(vault_db):
    """Ueberzaehlige Zitat-Spans werden nicht still durchgewunken, nur billiger geprueft."""
    deviating = VAULT_QUOTE.replace("Prozess", "Vorgang")
    content = "\n".join(
        [
            f'Erstens: "{VAULT_QUOTE}"',
            f'Zweitens: "{deviating}"',
        ]
    )
    result = run_hook(
        "Write",
        "kapitel/kap1.md",
        content,
        env_overrides={
            "VAULT_DB_PATH": vault_db,
            "ACADEMIC_CITATION_MAX_PER_WRITE": "1",
        },
    )
    assert result.returncode == 2, f"Kein stiller Durchlass erwartet: {result.stderr}"
    assert "Prüfkontingent" in result.stderr, result.stderr
    # Der teure Wortlaut-Abgleich lief fuer den zweiten Span nicht — die Meldung
    # muss das sagen, statt eine Wortlaut-Abweichung zu behaupten oder sie zu
    # verschweigen.
    assert "Wortlaut-Abgleich lief für dieses Zitat nicht" in result.stderr, result.stderr


# ---------------------------------------------------------------------------
# AC5 — Dokumentation
# ---------------------------------------------------------------------------


def test_limits_doc_reflects_the_wording_check():
    text = LIMITS_DOC.read_text(encoding="utf-8")
    assert "der Wortlaut selbst\nbleibt ungeprüft" not in text
    assert "Wortlaut selbst bleibt ungeprüft" not in text
    assert "#846" in text, "limits.md nennt die geschlossene Luecke nicht"
    # Verbleibende Grenzen muessen benannt bleiben, sonst verspricht die Doku zu viel.
    assert "Mindestlänge" in text, text[-2000:]
    assert "Paraphrase" in text or "NLI" in text, text[-2000:]
