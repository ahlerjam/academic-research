"""Shared helpers fuer Evals-Suites.

Laedt Eval-JSON-Dateien, ruft Claude auf und prueft Expectations.

Aufrufweg (Issue #716, vormals #631): Wird die ``claude``-CLI im PATH
gefunden, laeuft ein Subprozess-Aufruf ueber die OAuth-Session
(``claude --print``, Vorbild ``evals/sparring-partner/record.py`` -- kein
separat abgerechnetes API-Budget noetig, CI setzt dafuer
``CLAUDE_CODE_OAUTH_TOKEN``, das die CLI automatisch liest). Ist die CLI
nicht vorhanden, bleibt es beim bisherigen ``pytest.skip()``. Der frueher
parallele SDK-Pfad (``ANTHROPIC_API_KEY``) ist mit #716 entfallen -- keine
Plugin- oder Repo-Infrastruktur braucht mehr einen eigenen API-Schluessel
(#632).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

EVALS_ROOT = Path(__file__).parent.parent.parent / "evals"
SKILLS_ROOT = Path(__file__).parent.parent.parent / "skills"
AGENTS_ROOT = Path(__file__).parent.parent.parent / "agents"
BASELINES_ROOT = Path(__file__).parent.parent / "baselines"

# Suiteneigenes Arbeitsverzeichnis fuer die "context-fs"-Fixture (Issue #823):
# academic_context.md, literature_state.md, writing_state.md, thematisch an
# DevOps Governance in KMU ausgerichtet. Wird ueber das "context-fs"-Profil
# (Issue #830, SESSION_PROFILES) als cwd= an call_claude_for_component
# durchgereicht -- nicht im Repo-Root abgelegt, damit sie fuer andere Suiten
# unsichtbar bleibt. SESSION_PROFILES enthaelt bewusst keinen Fixture-Pfad
# (das ist Sache der jeweiligen Suite/Fixture), diese Konstante schliesst die
# Luecke fuer die context-fs-Suiten.
CONTEXT_FS_DIR = Path(__file__).parent / "fixtures" / "context_fs"

# Harter Deckel fuer einen einzelnen CLI-Subprozess-Aufruf (Issue #631).
# Grosszuegig wie evals/sparring-partner/record.py, damit ein haengender
# Aufruf nicht den ganzen Testlauf blockiert.
CLI_TIMEOUT_SECONDS = 300

# Maximal zulaessiger Quality-Drop (PASS-Rate) gegenueber Baseline.
# README verspricht Schwelle Delta >= 20 pp; konfigurierbar via ENV.
DEFAULT_DELTA_THRESHOLD = 0.20


def quality_delta_threshold() -> float:
    """Liefert die Quality-Delta-Schwelle (Default 0.20).

    Ueberschreibbar via Umgebungsvariable EVAL_DELTA_THRESHOLD.
    Ungueltige Werte fallen auf den Default zurueck.
    """
    raw = os.environ.get("EVAL_DELTA_THRESHOLD", "")
    if not raw:
        return DEFAULT_DELTA_THRESHOLD
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_DELTA_THRESHOLD


def check_quality_delta(
    current_score: float,
    baseline_score: float,
    threshold: float | None = None,
) -> float:
    """Enforced die README-Schwelle: PASS-Rate-Drop darf 20 pp nicht ueberschreiten.

    Vergleicht die aktuelle PASS-Rate (current_score) mit der Baseline
    (baseline_score). Faellt der Score um mehr als ``threshold`` (Default
    0.20 bzw. EVAL_DELTA_THRESHOLD), wird ein AssertionError ausgeloest.

    Args:
        current_score: PASS-Rate des aktuellen Laufs (z.B. with_skill), 0.0-1.0.
        baseline_score: PASS-Rate der Baseline (z.B. without_skill), 0.0-1.0.
        threshold: Optionale Override-Schwelle; sonst quality_delta_threshold().

    Returns:
        Das gemessene Delta (current_score - baseline_score).

    Raises:
        AssertionError: Wenn der Quality-Drop die Schwelle ueberschreitet.
    """
    limit = quality_delta_threshold() if threshold is None else threshold
    delta = current_score - baseline_score
    # Kleine Epsilon-Toleranz gegen Float-Rundung, damit der exakte
    # Schwellenwert (Drop == limit) zuverlaessig besteht.
    assert delta >= -limit - 1e-9, (
        f"Quality drop > {limit * 100:.0f}pp: delta={delta:+.2f} "
        f"(current={current_score:.2f}, baseline={baseline_score:.2f})"
    )
    return delta


def load_eval_file(component: str, filename: str) -> dict[str, Any]:
    path = EVALS_ROOT / component / filename
    if not path.exists():
        pytest.skip(f"Eval-Datei fehlt: {path}")
    return json.loads(path.read_text())


def load_skill_content(skill: str) -> str:
    return (SKILLS_ROOT / skill / "SKILL.md").read_text()


def load_agent_content(agent: str) -> str:
    return (AGENTS_ROOT / f"{agent}.md").read_text()


class ClaudeCliError(RuntimeError):
    """Auth-/Rate-Limit-/API-Fehler des claude-CLI-Subprozess-Pfads (Issue #631, AC5).

    Getrennt von einer regulaeren (moeglicherweise inhaltlich falschen)
    Modellantwort: eine Trigger- oder Quality-Eval-Callsite, die diese
    Exception nicht abfaengt, bricht den Testlauf sichtbar ab statt den
    Fehler stillschweigend als Fehlklassifikation in die Recall/FPR-Quote
    einfliessen zu lassen.
    """

    def __init__(
        self,
        message: str,
        *,
        exit_code: int | None = None,
        api_error_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.api_error_status = api_error_status


def claude_cli_available() -> bool:
    """True wenn die claude-CLI im PATH gefunden wird (Issue #631)."""
    return shutil.which("claude") is not None


def _log_model_used(mode: str, model: str) -> None:
    """Macht die je Aufruf verwendete Modellkennung sichtbar (Issue #631, AC4).

    Schreibt nach stderr statt stdout, damit pytest -q/-v die Zeile nicht als
    Testausgabe verschluckt (stderr wird bei Fehlschlaegen ohnehin angezeigt;
    bei -v/-s ist sie live sichtbar).
    """
    print(f"[eval_runner] mode={mode} model={model}", file=sys.stderr)


def _run_claude_cli(
    system: str,
    user: str,
    model: str,
    *,
    cwd: str | Path | None = None,
    allowed_tools: str | None = None,
    mcp_config: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Ruft ``claude --print`` als Subprozess auf, liefert das geparste JSON.

    Muster analog ``evals/sparring-partner/record.py``: keine Projekt-/
    User-Settings (``--setting-sources ""``), damit die Umgebung des
    Ausfuehrungsrechners nicht in die Antwort einfaerbt. ``--output-format
    json`` liefert u.a. ``result``, ``is_error``, ``usage`` und
    ``stop_reason`` in einer Antwort.

    Vier Achsen sind ueber Issue #830 (Eval-Sitzungsprofile) konfigurierbar
    statt fest verdrahtet -- Default fuer jede Achse ist das bisherige
    ``bare``-Verhalten (Rueckwaertskompatibilitaet):

    - ``cwd``: Arbeitsverzeichnis des Subprozesses. ``None`` (Default)
      laesst den Aufrufer erben (unveraendertes Verhalten -- vorher wurde
      ``cwd`` gar nicht gesetzt). Eine Suite mit eigenem Fixture-Verzeichnis
      gibt hier ihr eigenes Verzeichnis an, damit Fixtures anderer Suiten
      nicht sichtbar sind (siehe ``tests/evals/test_session_profiles.py``).
    - ``allowed_tools``: Wert fuer ``--allowedTools``. ``None`` faellt auf
      ``""`` zurueck (bisheriges ``bare``-Verhalten: keine Tools).
    - ``mcp_config``: Pfad zu einer MCP-Config-Datei. Wird nur gesetzt,
      wenn angegeben -- dann zusaetzlich ``--mcp-config <pfad>
      --strict-mcp-config``, Vorbild der Live-Nachweis in
      ``docs/evals/2026-08-09-context-enrichment-710.md``.
    - ``env``: Umgebungsvariablen fuer den Subprozess (z. B.
      ``VAULT_DB_PATH`` fuer das ``vault``-Profil). ``None`` erbt die
      Prozessumgebung (unveraendertes ``subprocess.run``-Verhalten).

    Bekannte Luecke (Issue #631, AC6, weiterhin gueltig nach #716): die CLI
    kennt kein ``--temperature``-Flag (lt. ``claude --help``) -- ein
    Determinismus-Schutz wie ``temperature=0`` ist auf diesem Pfad nicht
    verfuegbar. Dokumentiert in docs/evals/STRATEGY.md.

    Raises:
        ClaudeCliError: bei Timeout, ungueltigem JSON, nicht-null Exit-Code
            oder ``is_error: true`` in der Antwort (Auth-/Rate-Limit-/
            API-Fehler) -- unterscheidbar von einer regulaeren Antwort.
    """
    command = [
        "claude",
        "--print",
        "--model",
        model,
        "--output-format",
        "json",
        "--system-prompt",
        system,
        "--allowedTools",
        allowed_tools if allowed_tools is not None else "",
        "--setting-sources",
        "",
    ]
    if mcp_config is not None:
        command += ["--mcp-config", str(mcp_config), "--strict-mcp-config"]
    command.append(user)

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=CLI_TIMEOUT_SECONDS,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise ClaudeCliError(f"claude --print Timeout nach {CLI_TIMEOUT_SECONDS}s") from exc
    except FileNotFoundError as exc:
        raise ClaudeCliError("claude-CLI nicht gefunden") from exc

    try:
        parsed: dict[str, Any] = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ClaudeCliError(
            f"claude --print lieferte kein gueltiges JSON (exit={result.returncode}): "
            f"{(result.stderr or result.stdout)[:500]}",
            exit_code=result.returncode,
        ) from exc

    if result.returncode != 0 or parsed.get("is_error"):
        raise ClaudeCliError(
            str(parsed.get("result") or result.stderr[:500] or "claude --print schlug fehl"),
            exit_code=result.returncode,
            api_error_status=parsed.get("api_error_status"),
        )
    return parsed


def call_claude(
    system: str,
    user: str,
    model: str = "claude-sonnet-4-6",
    *,
    cwd: str | Path | None = None,
    allowed_tools: str | None = None,
    mcp_config: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Ruft Claude ueber die claude-CLI (OAuth-Session) auf, sonst Skip (Issue #716).

    ``cwd``/``allowed_tools``/``mcp_config``/``env`` reichen die vier
    Sitzungsachsen aus Issue #830 durch -- siehe ``_run_claude_cli`` und
    ``profile_for()``. Ohne Angabe identisch zum bisherigen ``bare``-Verhalten.
    """
    if claude_cli_available():
        parsed = _run_claude_cli(
            system,
            user,
            model,
            cwd=cwd,
            allowed_tools=allowed_tools,
            mcp_config=mcp_config,
            env=env,
        )
        _log_model_used("cli", model)
        return str(parsed.get("result", ""))
    pytest.skip("claude-CLI nicht verfuegbar - Eval uebersprungen")


def _as_patterns(value: Any) -> list[str]:
    """Normalisiert ``value``/``reject`` auf eine Liste von Mustern.

    Ein einzelner String bleibt abwaertskompatibel; eine Liste bedeutet UND
    (alle Muster muessen zutreffen) bzw. bei ``reject`` NOR (keines darf
    zutreffen).
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    raise ValueError(f"expected.value/reject muss str oder list[str] sein, ist: {type(value)}")


def check_expected(output: str, expected: dict[str, Any]) -> bool:
    """Prueft ``output`` gegen eine expected-Definition aus einer evals.json.

    ``value`` darf eine Liste sein (alle Muster muessen zutreffen). Optional
    definiert ``reject`` Muster, von denen **keines** zutreffen darf --
    Negativbedingungen, ohne die ein Kriterium nur Formattreue misst statt
    Verhalten (Issue #454: eine rein bestaetigende Antwort erfuellte die
    sparring-partner-Erwartungen, obwohl der Agent widersprechen soll).
    """
    t = expected.get("type")
    rejects = _as_patterns(expected.get("reject"))
    if t in {"substring", "regex"} and any(re.search(r, output, re.DOTALL) for r in rejects):
        return False
    if t == "substring":
        return all(v in output for v in _as_patterns(expected["value"]))
    if t == "regex":
        return all(re.search(v, output, re.DOTALL) for v in _as_patterns(expected["value"]))
    if rejects:
        raise ValueError(f"expected.reject wird fuer type={t!r} nicht unterstuetzt")
    if t == "json_field":
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            return False
        return _jsonpath_check(parsed, expected)
    raise ValueError(f"Unbekannter expected.type: {t}")


def read_token_baseline(baseline_file: Path | None = None) -> dict[str, Any]:
    """Liest tests/baselines/tokens.json (oder angegebene Datei).

    Gibt {} zurueck wenn Datei fehlt oder leer.
    """
    path = baseline_file or (BASELINES_ROOT / "tokens.json")
    if not path.exists():
        return {}
    text = path.read_text().strip()
    if not text:
        return {}
    return json.loads(text)


def write_token_baseline(
    suite: str,
    case_id: str,
    tokens_in: int,
    tokens_out: int,
    baseline_file: Path | None = None,
) -> None:
    """Schreibt tokens_in/tokens_out fuer eine Suite+Case in tokens.json.

    Mergt mit vorhandenen Daten (ueberschreibt nur den eigenen Eintrag).
    """
    path = baseline_file or (BASELINES_ROOT / "tokens.json")
    data = read_token_baseline(baseline_file=path)
    if suite not in data:
        data[suite] = {}
    data[suite][case_id] = {"tokens_in": tokens_in, "tokens_out": tokens_out}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def call_claude_with_tokens(
    system: str,
    user: str,
    model: str = "claude-sonnet-4-6",
    *,
    cwd: str | Path | None = None,
    allowed_tools: str | None = None,
    mcp_config: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> tuple[str, int, int]:
    """Ruft Claude auf und gibt (text, tokens_in, tokens_out) zurueck.

    CLI-Pfad (Issue #631, AC1; SDK-Pfad entfallen seit #716): das oberste
    ``usage``-Feld aus ``claude --print --output-format json`` traegt
    input_tokens/output_tokens fuer genau diesen Aufruf (ohne die interne,
    session-weite Cache-Erstellung des Agenten-Scaffolds mitzuzaehlen).
    Ohne CLI: pytest.skip(). ``cwd``/``allowed_tools``/``mcp_config``/``env``
    wie bei ``call_claude`` (Issue #830).
    """
    if claude_cli_available():
        parsed = _run_claude_cli(
            system,
            user,
            model,
            cwd=cwd,
            allowed_tools=allowed_tools,
            mcp_config=mcp_config,
            env=env,
        )
        _log_model_used("cli", model)
        text = str(parsed.get("result", ""))
        usage = parsed.get("usage") or {}
        tokens_in = int(usage.get("input_tokens", 0))
        tokens_out = int(usage.get("output_tokens", 0))
        return text, tokens_in, tokens_out
    pytest.skip("claude-CLI nicht verfuegbar - Eval uebersprungen")


def _jsonpath_check(obj: Any, expected: dict[str, Any]) -> bool:
    path = expected.get("path", "$")
    check = expected.get("check", "exists")
    # Minimaler JSONPath: $.a.b[0].c - kein Full-Feature JSONPath noetig.
    # Akzeptiert optionales $-Prefix (wie im Schema dokumentiert).
    normalized = path.lstrip("$") if path != "$" else ""
    current: Any = obj
    if normalized:
        segments = re.findall(r"\.(\w+)|\[(\d+)\]", normalized)
        # Ohne Segmente, aber nicht-leerer Path = Syntaxfehler (z.B. "a.b" ohne fuehrendes .)
        if not segments:
            raise ValueError(f"Ungueltiger JSONPath: {path!r} - erwartet '$', '$.key' oder '.key'")
        for key, idx in segments:
            if key:
                if not isinstance(current, dict) or key not in current:
                    return False
                current = current[key]
            elif idx:
                if not isinstance(current, list) or int(idx) >= len(current):
                    return False
                current = current[int(idx)]
    if check == "exists":
        return current is not None
    if check == "non_empty":
        return bool(current)
    if check.startswith("equals:"):
        return str(current) == check.split(":", 1)[1]
    raise ValueError(f"Unbekannter check: {check}")


# ---------------------------------------------------------------------------
# Eval-Sitzungsprofile (Issue #830).
#
# Vier Achsen (cwd, allowed_tools, mcp_config, env; siehe _run_claude_cli)
# werden zu einer kleinen Zahl benannter Profile gebuendelt, statt sie je
# Suite frei zu kombinieren -- ausfuehrlich begruendet in
# docs/evals/STRATEGY.md, Abschnitt "Sitzungsprofile". Diese Tabelle ist die
# eine Stelle, an der ein Profil seine Achsenwerte definiert; sie enthaelt
# bewusst keine Fixture-Pfade (die sind Sache der jeweiligen Suite/Fixture,
# Issue #823/#824) -- nur die Policy je Achse.
# ---------------------------------------------------------------------------

SESSION_PROFILES: dict[str, dict[str, Any]] = {
    "bare": {
        "allowed_tools": "",
        "needs_cwd": False,
        "needs_mcp": False,
    },
    "context-fs": {
        "allowed_tools": "Read",
        "needs_cwd": True,
        "needs_mcp": False,
    },
    "vault": {
        "allowed_tools": "mcp__academic-vault__*,Read",
        "needs_cwd": True,
        "needs_mcp": True,
    },
    "net-excluded": {
        "allowed_tools": None,
        "needs_cwd": False,
        "needs_mcp": False,
    },
}

# Komponente (evals/-Verzeichnisname) -> Profilname. Deckungsgleich mit
# eval_dirs() aus tests/evals/test_eval_strategy.py; ein Coverage-Test in
# tests/evals/test_session_profiles.py haelt das gegen das Dateisystem.
#
# Herleitung (dokumentiert, nicht erraten -- siehe STRATEGY.md fuer die
# ausformulierte Begruendung je Gruppe):
# - "vault": Skill ruft laut SKILL.md/evals.json direkt vault_*-MCP-Tools auf.
# - "context-fs": Skill laedt skills/_common/preamble.md (das die
#   Vorbedingung "academic_context.md/literature_state.md vorhanden" stellt)
#   oder referenziert academic_context.md/writing_state.md sonst direkt.
# - "bare": weder noch -- entweder eine offene Aufgabe ohne Referenzloesung
#   (advisor, research-question-refiner, ...) oder eine Suite, die
#   eval_runner.call_claude gar nicht aufruft (reine Schema-/Netz-Tests wie
#   fetch/oa-fetchers, oder ein rein offline messender metric-Runner).
COMPONENT_PROFILES: dict[str, str] = {
    # vault -- direkter vault_*-MCP-Tool-Aufruf im Skill bzw. in den Evals.
    "anchor-paper-survey": "vault",
    "chapter-writer": "vault",
    "citation-extraction": "vault",
    "material-passport": "vault",
    "quote-extractor": "vault",
    "reading-notes": "vault",
    "word-export": "vault",
    # context-fs -- laedt skills/_common/preamble.md oder referenziert
    # academic_context.md/literature_state.md/writing_state.md direkt.
    "abstract-generator": "context-fs",
    "academic-context": "context-fs",
    "advisor": "context-fs",
    "ai-disclosure": "context-fs",
    "bibliography-auditor": "context-fs",
    "book-handler": "context-fs",
    "citation-style-import": "context-fs",
    "cluster-visualizer": "context-fs",
    "conference-poster": "context-fs",
    "data-management-plan": "context-fs",
    "defense-prep": "context-fs",
    "extraction-matrix": "context-fs",
    "github-repo-research": "context-fs",
    "grant-proposal": "context-fs",
    "humanizer-de": "context-fs",
    "instrument-design": "context-fs",
    "latex-export": "context-fs",
    "latex-layout-auditor": "context-fs",
    "literature-excel": "context-fs",
    "literature-gap-analysis": "context-fs",
    "methodology-advisor": "context-fs",
    "notebook-bundle": "context-fs",
    "parallel-screening": "context-fs",
    "peer-review": "context-fs",
    "plagiarism-check": "context-fs",
    "preregistration": "context-fs",
    "prisma-flow": "context-fs",
    "qualitative-coding": "context-fs",
    "quantitative-analysis": "context-fs",
    "query-generator": "context-fs",
    "reading-list-import": "context-fs",
    "research-question-refiner": "context-fs",
    "reviewer-response": "context-fs",
    "slide-export": "context-fs",
    "source-quality-audit": "context-fs",
    "style-evaluator": "context-fs",
    "submission-checker": "context-fs",
    "title-generator": "context-fs",
    "topic-brainstorm": "context-fs",
    "workflow-status": "context-fs",
    "zotero-import": "context-fs",
    # bare -- offene Aufgabe ohne Referenzloesung, ODER ruft call_claude gar
    # nicht auf (reiner Schema-/Netz-Test bzw. rein offline messender Runner).
    "524-nli-prefilter": "bare",
    "auto-download": "bare",
    "fetch": "bare",
    "figure-verifier": "bare",
    "free-archive-fetchers": "bare",
    "generic-fetcher": "bare",
    "humanizer-de-pipeline": "bare",
    "oa-fetchers": "bare",
    "publisher-fetchers": "bare",
    "quality-reviewer": "bare",
    "sparring-partner": "bare",
    "verbatim-guard": "bare",
}


def profile_for(component: str) -> str:
    """Liefert den Profilnamen fuer eine ``evals/``-Komponente (Issue #830).

    Raises:
        KeyError: Komponente ist weder in COMPONENT_PROFILES noch ist die
            fehlende Zuordnung beabsichtigt -- kein Fall bleibt stillschweigend
            unzugeordnet (AC1).
    """
    try:
        return COMPONENT_PROFILES[component]
    except KeyError as exc:
        raise KeyError(
            f"Kein Sitzungsprofil fuer Komponente {component!r} hinterlegt "
            f"(Issue #830) -- COMPONENT_PROFILES in eval_runner.py ergaenzen."
        ) from exc


def call_claude_for_component(
    component: str,
    system: str,
    user: str,
    model: str = "claude-sonnet-4-6",
    *,
    cwd: str | Path | None = None,
    mcp_config: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Ruft ``call_claude`` mit dem per ``profile_for(component)`` bestimmten Profil auf.

    Die Callsite-Anbindung aus Issue #830 (Task 5): ``allowed_tools`` kommt
    ab hier aus ``SESSION_PROFILES[profile_for(component)]`` statt dass jede
    Suite den Wert selbst (oder implizit den ``bare``-Default) verdrahtet.
    Eine Suite mit unbekannter Komponente (Tippfehler, fehlender
    ``COMPONENT_PROFILES``-Eintrag) faellt nicht still auf ``bare`` zurueck,
    sondern erbt den ``KeyError`` aus ``profile_for()`` (AC1).

    ``cwd``/``mcp_config`` sind optionale Overrides. Profile, die laut
    ``needs_cwd`` ein Fixture-Verzeichnis erfordern, bekommen automatisch
    ein leeres Temp-Dir als cwd, falls die Callsite kein eigenes cwd stellt.
    Das verhindert den Root-Leak (cwd=None zeigt sonst auf den Repo-Root und
    macht Skill-Dateien/Eval-Erwartungen fuer die without_skill-Kontrollgruppe
    sichtbar), ohne ``allowed_tools`` zu verwerfen -- die Werkzeugfreigabe aus
    ``SESSION_PROFILES`` ist die Kernzusage dieses Profils und muss auch vor
    Landung der Fixture-Integration (#823/#824) im CLI-Aufruf ankommen.
    ``mcp_config`` bleibt bewusst unangetastet: faellt es weg, laeuft der
    Aufruf ohne funktionierende MCP-Tools -- das ist kein Sicherheitsleck wie
    beim cwd, sondern der erwartete Zwischenstand vor #824.
    """
    profile = profile_for(component)
    profile_config = SESSION_PROFILES[profile]
    allowed_tools = profile_config["allowed_tools"]

    # Wenn das Profil ein eigenes cwd braucht, aber keins gestellt wurde,
    # nutzen wir ein leeres Temp-Dir als Fallback. Das verhindert, dass
    # cwd=None auf den Repo-Root zeigt und die Kontrollgruppe verfaelscht --
    # ohne allowed_tools zu verwerfen (Regression-Fix zu #830).
    effective_cwd = cwd
    if profile_config["needs_cwd"] and cwd is None:
        effective_cwd = tempfile.mkdtemp()

    return call_claude(
        system,
        user,
        model,
        cwd=effective_cwd,
        allowed_tools=allowed_tools,
        mcp_config=mcp_config,
        env=env,
    )
