"""Tests fuer den Claim-Drift-Guard (Issue #397).

Der Hook ``hooks/claim-drift-guard.mjs`` laeuft additiv neben
``hooks/verbatim-guard.mjs`` und WARNT (nie: blockiert), wenn eine
Kapitel-Ueberarbeitung Prosa unmittelbar um ein bereits im Vault belegtes
Zitat veraendert, ohne den Beleg anzupassen.

Protokoll: JSON via stdin, Warnung als ``[Claim-Drift]``-Zeile auf stderr plus
JSON auf stdout (``systemMessage`` + ``hookSpecificOutput.additionalContext``).
Exit-Code ist IMMER 0 — der Hook darf nie blockieren.

Akzeptanzkriterien des Issues:
  AC1  Warnung bei Aenderung nahe einem Vault-Zitat ohne Beleg-Anpassung.
  AC2  Kein False Positive ohne Zitat-Naehe.
  AC3  Kein Code aus Imbad0202/academic-research-skills im Diff.
  AC4  Test deckt beide Faelle ab und ist gruen.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "claim-drift-guard.mjs"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"

WARN_MARKER = "[Claim-Drift]"

# Vault-Zitat (verbatim) und sein Kontext — Fixture-Inhalt, wird im Kapiteltext
# woertlich zitiert.
VAULT_VERBATIM = "Der Effekt war in allen Kohorten nachweisbar."
VAULT_CONTEXT_BEFORE = "KONTEXTVOR-Die Stichprobe umfasste 1200 Schueler."
VAULT_CONTEXT_AFTER = "KONTEXTNACH-Die Effektstaerke lag bei d = 0.31."

CHAPTER_OLD = (
    "## Ergebnisse\n\n"
    "Die Studie zeigt einen moderaten Effekt auf die Lesekompetenz. "
    f'"{VAULT_VERBATIM}" (Mueller 2021, S. 45)\n'
)
# Inhaltliche Aenderung der belegten Aussage, Beleg bleibt unveraendert.
CHAPTER_NEW_DRIFTED = CHAPTER_OLD.replace("moderaten", "starken")


def run_hook(payload: dict, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    """Startet den Hook als Node-Subprocess mit JSON-Payload auf stdin."""
    env = os.environ.copy()
    env["VAULT_DB_PATH"] = str(REPO_ROOT / "nonexistent_vault_for_tests.db")
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["node", str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def warned(result: subprocess.CompletedProcess) -> bool:
    return WARN_MARKER in (result.stdout + result.stderr)


def edit_payload(old: str, new: str, file_path: str = "kapitel/kap1.md") -> dict:
    return {
        "tool_name": "Edit",
        "tool_input": {"file_path": file_path, "old_string": old, "new_string": new},
    }


def chapter_project(tmp_path, content: str, name: str = "kap1.md") -> Path:
    """Legt ein Projektverzeichnis mit einer Kapiteldatei auf Platte an."""
    project_dir = tmp_path / "projekt"
    (project_dir / "kapitel").mkdir(parents=True, exist_ok=True)
    (project_dir / "kapitel" / name).write_text(content, encoding="utf-8")
    return project_dir


@pytest.fixture
def vault_with_quote(tmp_path):
    """Vault-DB mit einem Zitat inkl. context_before/context_after."""
    from academic_vault.db import VaultDB
    from academic_vault.server import add_paper, add_quote

    db_path = str(tmp_path / "claim_drift_vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    add_paper(
        db_path=db_path,
        paper_id="mueller-2021",
        csl_json=json.dumps({"title": "Lesekompetenz", "type": "article-journal"}),
    )
    add_quote(
        db_path=db_path,
        paper_id="mueller-2021",
        verbatim=VAULT_VERBATIM,
        extraction_method="manual",
        printed_page=45,
        context_before=VAULT_CONTEXT_BEFORE,
        context_after=VAULT_CONTEXT_AFTER,
    )
    return db_path


@pytest.fixture
def empty_vault(tmp_path):
    """Vault-DB mit Paper, aber ohne Zitate."""
    from academic_vault.db import VaultDB
    from academic_vault.server import add_paper

    db_path = str(tmp_path / "empty_claim_vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    add_paper(
        db_path=db_path,
        paper_id="mueller-2021",
        csl_json=json.dumps({"title": "Lesekompetenz", "type": "article-journal"}),
    )
    return db_path


# ---------------------------------------------------------------------------
# AC1 — Warnung bei Drift nahe einem Vault-Zitat
# ---------------------------------------------------------------------------


def test_claim_drift_warns_on_edit_near_vault_quote(vault_with_quote):
    """AC1: Edit aendert die belegte Aussage, Beleg bleibt stehen -> Warnung."""
    result = run_hook(
        edit_payload(CHAPTER_OLD, CHAPTER_NEW_DRIFTED),
        env_overrides={"VAULT_DB_PATH": vault_with_quote},
    )
    assert result.returncode == 0, (
        f"Claim-Drift-Guard darf nie blockieren, got {result.returncode}. stderr: {result.stderr}"
    )
    assert warned(result), (
        f"Erwartet Claim-Drift-Warnung. stdout: {result.stdout} stderr: {result.stderr}"
    )


def test_warning_payload_is_valid_hook_json_with_vault_context(vault_with_quote):
    """AC1: stdout ist gueltiges Hook-JSON und traegt den Vault-Kontext des Zitats."""
    result = run_hook(
        edit_payload(CHAPTER_OLD, CHAPTER_NEW_DRIFTED),
        env_overrides={"VAULT_DB_PATH": vault_with_quote},
    )
    payload = json.loads(result.stdout)
    assert "systemMessage" in payload, f"systemMessage fehlt: {payload}"
    hook_output = payload.get("hookSpecificOutput", {})
    assert hook_output.get("hookEventName") == "PreToolUse", f"Falscher Event-Name: {payload}"
    context = hook_output.get("additionalContext", "")
    assert VAULT_CONTEXT_BEFORE in context, f"context_before fehlt im Hinweis: {context}"
    assert VAULT_CONTEXT_AFTER in context, f"context_after fehlt im Hinweis: {context}"
    # Der Hook darf die Berechtigungsentscheidung nicht an sich ziehen (kein
    # stilles Auto-Allow und erst recht kein deny).
    assert "permissionDecision" not in hook_output, (
        f"Warn-Hook setzt permissionDecision: {hook_output}"
    )


def test_claim_drift_warns_on_minimal_edit_against_disk_state(vault_with_quote, tmp_path):
    """AC1: Realistischer Edit — ``old_string``/``new_string`` tragen NUR das
    geaenderte Wort.

    Das belegte Zitat und die Quellenangabe stehen ausschliesslich in der Datei
    auf Platte. Ein Guard, der nur die beiden Tool-Strings vergleicht, sieht
    dort nie ein Zitat und bleibt faelschlich stumm — genau der Alltagsfall,
    den AC1 abdeckt.
    """
    project_dir = chapter_project(tmp_path, CHAPTER_OLD)
    result = run_hook(
        edit_payload("moderaten Effekt", "starken Effekt"),
        env_overrides={
            "VAULT_DB_PATH": vault_with_quote,
            "CLAUDE_PROJECT_DIR": str(project_dir),
        },
    )
    assert result.returncode == 0
    assert warned(result), (
        f"Minimaler Edit neben belegtem Zitat blieb stumm. "
        f"stdout: {result.stdout} stderr: {result.stderr}"
    )


def test_minimal_edit_warning_carries_vault_context(vault_with_quote, tmp_path):
    """AC1: Auch beim minimalen Edit traegt die Warnung den Vault-Kontext."""
    project_dir = chapter_project(tmp_path, CHAPTER_OLD)
    result = run_hook(
        edit_payload("moderaten Effekt", "starken Effekt"),
        env_overrides={
            "VAULT_DB_PATH": vault_with_quote,
            "CLAUDE_PROJECT_DIR": str(project_dir),
        },
    )
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert VAULT_VERBATIM in context, f"Zitat fehlt im Hinweis: {context}"
    assert VAULT_CONTEXT_BEFORE in context, f"context_before fehlt im Hinweis: {context}"


def test_claim_drift_warns_on_minimal_multiedit_against_disk_state(vault_with_quote, tmp_path):
    """AC1: Auch MultiEdit mit minimalen Spans zieht den Dateikontext heran."""
    project_dir = chapter_project(tmp_path, "# Titel\n\n" + CHAPTER_OLD)
    payload = {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": "kapitel/kap1.md",
            "edits": [
                {"old_string": "# Titel", "new_string": "# Ueberschrift"},
                {"old_string": "moderaten Effekt", "new_string": "starken Effekt"},
            ],
        },
    }
    result = run_hook(
        payload,
        env_overrides={
            "VAULT_DB_PATH": vault_with_quote,
            "CLAUDE_PROJECT_DIR": str(project_dir),
        },
    )
    assert result.returncode == 0
    assert warned(result), (
        f"Minimaler MultiEdit neben belegtem Zitat blieb stumm. "
        f"stdout: {result.stdout} stderr: {result.stderr}"
    )


def test_claim_drift_warns_on_absolute_edit_path(vault_with_quote, tmp_path):
    """AC1: Der Dateikontext wird auch bei absolutem Tool-Pfad gefunden."""
    project_dir = chapter_project(tmp_path, CHAPTER_OLD)
    result = run_hook(
        edit_payload(
            "moderaten Effekt",
            "starken Effekt",
            file_path=str(project_dir / "kapitel" / "kap1.md"),
        ),
        env_overrides={"VAULT_DB_PATH": vault_with_quote},
    )
    assert result.returncode == 0
    assert warned(result), f"Absoluter Pfad ohne Warnung: {result.stderr}"


def test_claim_drift_warns_on_nested_chapter_path(vault_with_quote, tmp_path):
    """Issue #516: verschachtelte Kapitelpfade bleiben im Drift-Guard."""
    project_dir = tmp_path / "projekt"
    nested_dir = project_dir / "kapitel" / "teil1"
    nested_dir.mkdir(parents=True)
    (nested_dir / "intro.md").write_text(CHAPTER_OLD, encoding="utf-8")
    result = run_hook(
        edit_payload("moderaten Effekt", "starken Effekt", file_path="kapitel/teil1/intro.md"),
        env_overrides={
            "VAULT_DB_PATH": vault_with_quote,
            "CLAUDE_PROJECT_DIR": str(project_dir),
        },
    )
    assert result.returncode == 0
    assert warned(result), (
        "Verschachtelter Kapitelpfad blieb im claim-drift-guard stumm. "
        f"stdout: {result.stdout} stderr: {result.stderr}"
    )


def test_claim_drift_warns_on_write_against_disk_state(vault_with_quote, tmp_path):
    """AC1: Write-Pfad vergleicht gegen den Dateizustand auf Platte."""
    project_dir = tmp_path / "projekt"
    (project_dir / "kapitel").mkdir(parents=True)
    (project_dir / "kapitel" / "kap1.md").write_text(CHAPTER_OLD, encoding="utf-8")

    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "kapitel/kap1.md", "content": CHAPTER_NEW_DRIFTED},
    }
    result = run_hook(
        payload,
        env_overrides={
            "VAULT_DB_PATH": vault_with_quote,
            "CLAUDE_PROJECT_DIR": str(project_dir),
        },
    )
    assert result.returncode == 0
    assert warned(result), (
        f"Erwartet Warnung fuer Write-gegen-Platte. stdout: {result.stdout} stderr: {result.stderr}"
    )


def test_claim_drift_warns_on_multiedit(vault_with_quote):
    """AC1: MultiEdit umgeht den Guard nicht (analog Regression #220)."""
    payload = {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": "kapitel/kap1.md",
            "edits": [
                {"old_string": "Vorspann alt", "new_string": "Vorspann neu"},
                {"old_string": CHAPTER_OLD, "new_string": CHAPTER_NEW_DRIFTED},
            ],
        },
    }
    result = run_hook(payload, env_overrides={"VAULT_DB_PATH": vault_with_quote})
    assert result.returncode == 0
    assert warned(result), f"Erwartet Warnung fuer MultiEdit. stderr: {result.stderr}"


# ---------------------------------------------------------------------------
# AC2 — keine False Positives
# ---------------------------------------------------------------------------


def test_no_warning_when_change_far_from_quote(vault_with_quote):
    """AC2: Aenderung weit ausserhalb des Zitat-Fensters -> stumm."""
    filler = "Ein Fuellsatz ohne jeden Belegbezug steht hier. " * 20  # ~940 Zeichen
    old = "## Einleitung\n\nDer Aufbau folgt einer moderaten Gliederung.\n\n" + filler + CHAPTER_OLD
    new = old.replace("moderaten Gliederung", "strengen Gliederung")
    result = run_hook(edit_payload(old, new), env_overrides={"VAULT_DB_PATH": vault_with_quote})
    assert result.returncode == 0
    assert not warned(result), (
        f"False Positive: Aenderung ist >300 Zeichen vom Zitat entfernt. "
        f"stdout: {result.stdout} stderr: {result.stderr}"
    )


def test_no_warning_for_minimal_edit_far_from_quote(vault_with_quote, tmp_path):
    """AC2: Der Dateikontext darf keine Fernwirkung erzeugen.

    Gegenprobe zum minimalen Edit: derselbe Mechanismus, aber die Aenderung
    liegt weit ausserhalb des Zitat-Fensters -> stumm.
    """
    filler = "Ein Fuellsatz ohne jeden Belegbezug steht hier. " * 20  # ~940 Zeichen
    content = (
        "## Einleitung\n\nDer Aufbau folgt einer moderaten Gliederung.\n\n" + filler + CHAPTER_OLD
    )
    project_dir = chapter_project(tmp_path, content)
    result = run_hook(
        edit_payload("moderaten Gliederung", "strengen Gliederung"),
        env_overrides={
            "VAULT_DB_PATH": vault_with_quote,
            "CLAUDE_PROJECT_DIR": str(project_dir),
        },
    )
    assert result.returncode == 0
    assert not warned(result), (
        f"False Positive: Aenderung ist >300 Zeichen vom Zitat entfernt. "
        f"stdout: {result.stdout} stderr: {result.stderr}"
    )


def test_no_warning_for_minimal_edit_when_citation_changed_too(vault_with_quote, tmp_path):
    """AC2: Wird die Quellenangabe im selben Edit-Lauf mitgeaendert -> stumm."""
    project_dir = chapter_project(tmp_path, CHAPTER_OLD)
    payload = {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": "kapitel/kap1.md",
            "edits": [
                {"old_string": "moderaten Effekt", "new_string": "starken Effekt"},
                {"old_string": "(Mueller 2021, S. 45)", "new_string": "(Schmidt 2022, S. 12)"},
            ],
        },
    }
    result = run_hook(
        payload,
        env_overrides={
            "VAULT_DB_PATH": vault_with_quote,
            "CLAUDE_PROJECT_DIR": str(project_dir),
        },
    )
    assert result.returncode == 0
    assert not warned(result), (
        f"False Positive trotz mitgeaenderter Quellenangabe: {result.stdout} {result.stderr}"
    )


def test_no_warning_when_edit_does_not_match_disk_content(vault_with_quote, tmp_path):
    """AC2: Passt ``old_string`` nicht auf den Dateistand, wird nichts geraten.

    Der Edit wuerde ohnehin fehlschlagen; der Guard darf daraus keine Warnung
    ueber einen Dateistand konstruieren, der so nie entsteht.
    """
    project_dir = chapter_project(tmp_path, CHAPTER_OLD)
    result = run_hook(
        edit_payload("hier steht gar nichts dergleichen", "irgendwas anderes"),
        env_overrides={
            "VAULT_DB_PATH": vault_with_quote,
            "CLAUDE_PROJECT_DIR": str(project_dir),
        },
    )
    assert result.returncode == 0
    assert not warned(result), f"Warnung fuer nicht passenden Edit: {result.stdout} {result.stderr}"


def test_no_warning_for_minimal_formatting_only_edit(vault_with_quote, tmp_path):
    """AC2: Reine Markup-Aenderung bleibt auch mit Dateikontext stumm."""
    project_dir = chapter_project(tmp_path, CHAPTER_OLD)
    result = run_hook(
        edit_payload("moderaten", "**moderaten**"),
        env_overrides={
            "VAULT_DB_PATH": vault_with_quote,
            "CLAUDE_PROJECT_DIR": str(project_dir),
        },
    )
    assert result.returncode == 0
    assert not warned(result), f"False Positive bei reiner Formatierung: {result.stderr}"


def test_dollar_signs_in_replacement_do_not_corrupt_reconstruction(vault_with_quote, tmp_path):
    """Die Rekonstruktion des neuen Dateistands ist kein Regex-Replace.

    ``$&``/``$'`` sind in ``String.replace`` Sonderzeichen. Werden sie nicht
    literal eingesetzt, verschiebt sich der rekonstruierte Text und damit das
    Zitat-Fenster.
    """
    project_dir = chapter_project(tmp_path, CHAPTER_OLD)
    result = run_hook(
        edit_payload("moderaten Effekt", "starken Effekt von $99 (kein $& und kein $')"),
        env_overrides={
            "VAULT_DB_PATH": vault_with_quote,
            "CLAUDE_PROJECT_DIR": str(project_dir),
        },
    )
    assert result.returncode == 0
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert VAULT_VERBATIM in context, f"Zitat nach $-Ersetzung nicht gefunden: {context}"


def test_no_warning_without_any_vault_quote(empty_vault):
    """AC2: Zitierter Span ist gar nicht im Vault -> stumm (Sache des verbatim-guard)."""
    result = run_hook(
        edit_payload(CHAPTER_OLD, CHAPTER_NEW_DRIFTED),
        env_overrides={"VAULT_DB_PATH": empty_vault},
    )
    assert result.returncode == 0
    assert not warned(result), (
        f"False Positive ohne Vault-Zitat. stdout: {result.stdout} stderr: {result.stderr}"
    )


def test_no_warning_when_citation_marker_also_changed(vault_with_quote):
    """AC2: Beleg wurde mitgeaendert -> bewusste Anpassung, keine Warnung."""
    new = CHAPTER_NEW_DRIFTED.replace("(Mueller 2021, S. 45)", "(Schmidt 2022, S. 12)")
    result = run_hook(
        edit_payload(CHAPTER_OLD, new),
        env_overrides={"VAULT_DB_PATH": vault_with_quote},
    )
    assert result.returncode == 0
    assert not warned(result), (
        f"False Positive trotz mitgeaenderter Quellenangabe. stderr: {result.stderr}"
    )


def test_no_warning_for_formatting_only_change(vault_with_quote):
    """AC2: Reine Markup-/Whitespace-Aenderung ist keine Aussagenaenderung."""
    old = CHAPTER_OLD.replace("moderaten", "**moderaten**")
    new = CHAPTER_OLD
    result = run_hook(edit_payload(old, new), env_overrides={"VAULT_DB_PATH": vault_with_quote})
    assert result.returncode == 0
    assert not warned(result), f"False Positive bei reiner Formatierungsaenderung: {result.stderr}"


def test_no_warning_when_only_the_quote_itself_was_swapped(vault_with_quote):
    """AC2: Wird das Zitat selbst ausgetauscht, hat sich die Prosa nicht geaendert.

    Der Guard ankert nur an Zitaten, die in Alt- UND Neu-Text woertlich
    identisch vorkommen. Ein getauschtes Zitat ist Sache des verbatim-guard,
    nicht dieses Hooks.
    """
    from academic_vault.server import add_quote

    other_quote = "Die Intervention wirkte nur in einzelnen Teilgruppen."
    add_quote(
        db_path=vault_with_quote,
        paper_id="mueller-2021",
        verbatim=other_quote,
        extraction_method="manual",
        printed_page=46,
    )
    new = CHAPTER_OLD.replace(VAULT_VERBATIM, other_quote)
    result = run_hook(
        edit_payload(CHAPTER_OLD, new),
        env_overrides={"VAULT_DB_PATH": vault_with_quote},
    )
    assert result.returncode == 0
    assert not warned(result), (
        f"False Positive: nur das Zitat wurde getauscht, die Prosa blieb gleich. "
        f"stdout: {result.stdout} stderr: {result.stderr}"
    )


def test_silent_when_vault_unavailable():
    """AC2: Ohne erreichbare Vault-DB schweigt der Hook (keine Raterei)."""
    result = run_hook(edit_payload(CHAPTER_OLD, CHAPTER_NEW_DRIFTED))
    assert result.returncode == 0
    assert not warned(result), f"Warnung ohne Vault-Datenbasis: {result.stdout} {result.stderr}"


def test_no_warning_on_unprotected_path(vault_with_quote):
    """AC2: Nur Kapitel-/LaTeX-Dateien werden geprueft."""
    result = run_hook(
        edit_payload(CHAPTER_OLD, CHAPTER_NEW_DRIFTED, file_path="README.md"),
        env_overrides={"VAULT_DB_PATH": vault_with_quote},
    )
    assert result.returncode == 0
    assert not warned(result), f"Warnung auf ungeschuetztem Pfad: {result.stderr}"


def test_no_warning_on_non_write_tool(vault_with_quote):
    """AC2: Lesende Tools loesen nichts aus."""
    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": "kapitel/kap1.md"},
    }
    result = run_hook(payload, env_overrides={"VAULT_DB_PATH": vault_with_quote})
    assert result.returncode == 0
    assert not warned(result)


def test_bypass_marker_silences_hook(vault_with_quote):
    """AC2: Der etablierte Bypass-Marker gilt auch hier."""
    new = CHAPTER_NEW_DRIFTED + "\n<!-- vault-guard: skip -->\n"
    result = run_hook(
        edit_payload(CHAPTER_OLD, new),
        env_overrides={"VAULT_DB_PATH": vault_with_quote},
    )
    assert result.returncode == 0
    assert not warned(result), f"Bypass-Marker wurde ignoriert: {result.stderr}"


def test_no_warning_for_new_file_without_predecessor(vault_with_quote, tmp_path):
    """AC2: Write auf eine noch nicht existierende Datei hat keinen Alt-Text."""
    project_dir = tmp_path / "leeres_projekt"
    (project_dir / "kapitel").mkdir(parents=True)
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "kapitel/neu.md", "content": CHAPTER_NEW_DRIFTED},
    }
    result = run_hook(
        payload,
        env_overrides={
            "VAULT_DB_PATH": vault_with_quote,
            "CLAUDE_PROJECT_DIR": str(project_dir),
        },
    )
    assert result.returncode == 0
    assert not warned(result), f"Warnung ohne Vorgaengerdatei: {result.stderr}"


def test_malformed_stdin_is_silent():
    """Robustheit: kaputte Eingabe darf weder warnen noch blockieren."""
    env = os.environ.copy()
    env["VAULT_DB_PATH"] = str(REPO_ROOT / "nonexistent_vault_for_tests.db")
    result = subprocess.run(
        ["node", str(HOOK_PATH)],
        input="{nicht json",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0
    assert WARN_MARKER not in (result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# AC3 — kein Fremdcode
# ---------------------------------------------------------------------------


def test_no_upstream_code_or_attribution_in_hook():
    """AC3: Kein Code/Verweis aus Imbad0202/academic-research-skills im Hook."""
    source = HOOK_PATH.read_text(encoding="utf-8")
    for needle in ("Imbad0202", "academic-research-skills"):
        assert needle not in source, (
            f"Hook referenziert das CC-BY-NC-Fremdrepo ({needle}) — nur das Konzept "
            "darf nachgebaut sein, kein Code."
        )


# ---------------------------------------------------------------------------
# Verdrahtung — additiv, ohne die bestehende Kernlogik zu ersetzen
# ---------------------------------------------------------------------------


def test_hook_is_wired_additively_in_hooks_json():
    """Scope 'Out': verbatim-guard bleibt verdrahtet, claim-drift-guard kommt dazu."""
    hooks = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]
    pre_tool_use = json.dumps(hooks["PreToolUse"])
    assert "verbatim-guard.mjs" in pre_tool_use, "verbatim-guard wurde verdraengt"
    assert "claim-drift-guard.mjs" in pre_tool_use, "claim-drift-guard ist nicht verdrahtet"

    matchers = [
        entry.get("matcher")
        for entry in hooks["PreToolUse"]
        if any("claim-drift-guard.mjs" in h.get("command", "") for h in entry.get("hooks", []))
    ]
    assert matchers == ["Write|Edit|MultiEdit"], (
        f"claim-drift-guard haengt an unerwarteten Matchern: {matchers}"
    )


def test_hook_is_documented_in_hooks_reference():
    """Die Hooks-Referenz nennt den neuen Hook (Doku-Drift-Schutz analog #205)."""
    doc = (REPO_ROOT / "docs" / "reference" / "hooks.md").read_text(encoding="utf-8")
    assert "claim-drift-guard.mjs" in doc, (
        "docs/reference/hooks.md fuehrt claim-drift-guard.mjs nicht auf."
    )
    assert "4 Skript-Dateien" not in doc, (
        "Hooks-Referenz behauptet weiterhin 4 Skript-Dateien, es sind jetzt 5."
    )
