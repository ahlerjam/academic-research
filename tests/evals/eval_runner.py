"""Shared helpers fuer Evals-Suites.

Laedt Eval-JSON-Dateien, ruft Claude auf und prueft Expectations.

Aufrufweg (Issue #631): Ist ``ANTHROPIC_API_KEY`` gesetzt, laeuft der
bestehende SDK-Pfad unveraendert (AC2). Sonst, wenn die ``claude``-CLI im
PATH gefunden wird, laeuft ein Subprozess-Aufruf ueber die OAuth-Session
(``claude --print``, Vorbild ``evals/sparring-partner/record.py`` -- kein
separat abgerechnetes API-Budget noetig, CI setzt dafuer
``CLAUDE_CODE_OAUTH_TOKEN``, das die CLI automatisch liest). Ist weder ein
Key gesetzt noch die CLI vorhanden, bleibt es beim bisherigen
``pytest.skip()``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]

EVALS_ROOT = Path(__file__).parent.parent.parent / "evals"
SKILLS_ROOT = Path(__file__).parent.parent.parent / "skills"
AGENTS_ROOT = Path(__file__).parent.parent.parent / "agents"
BASELINES_ROOT = Path(__file__).parent.parent / "baselines"

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


def require_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY nicht gesetzt - Eval uebersprungen")
    return key


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


def _call_claude_sdk(system: str, user: str, model: str) -> tuple[str, int, int]:
    """SDK-Pfad: unveraendert gegenueber vor Issue #631 (AC2)."""
    if anthropic is None:
        pytest.skip("anthropic-Package nicht installiert")
    assert anthropic is not None  # narrow fuer Type-Checker nach pytest.skip
    key = require_api_key()
    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(
        model=model,
        max_tokens=2048,
        temperature=0,  # deterministisch — verhindert flaky Trigger-Evals (#231)
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(getattr(block, "text", "") for block in resp.content)
    tokens_in = resp.usage.input_tokens if resp.usage else 0
    tokens_out = resp.usage.output_tokens if resp.usage else 0
    _log_model_used("sdk", model)
    return text, tokens_in, tokens_out


def _run_claude_cli(system: str, user: str, model: str) -> dict[str, Any]:
    """Ruft ``claude --print`` als Subprozess auf, liefert das geparste JSON.

    Muster analog ``evals/sparring-partner/record.py``: keine Tools
    (``--allowedTools ""``), keine Projekt-/User-Settings
    (``--setting-sources ""``), damit die Umgebung des Ausfuehrungsrechners
    nicht in die Antwort einfaerbt. ``--output-format json`` liefert u.a.
    ``result``, ``is_error``, ``usage`` und ``stop_reason`` in einer Antwort.

    Bekannte Luecke gegenueber dem SDK-Pfad (Issue #631, AC6): die CLI kennt
    kein ``--temperature``-Flag (lt. ``claude --help``), der
    Determinismus-Schutz aus Issue #231 (``temperature=0``) greift auf
    diesem Pfad also nicht. Dokumentiert in docs/evals/STRATEGY.md.

    Raises:
        ClaudeCliError: bei Timeout, ungueltigem JSON, nicht-null Exit-Code
            oder ``is_error: true`` in der Antwort (Auth-/Rate-Limit-/
            API-Fehler) -- unterscheidbar von einer regulaeren Antwort.
    """
    try:
        result = subprocess.run(
            [
                "claude",
                "--print",
                "--model",
                model,
                "--output-format",
                "json",
                "--system-prompt",
                system,
                "--allowedTools",
                "",
                "--setting-sources",
                "",
                user,
            ],
            capture_output=True,
            text=True,
            timeout=CLI_TIMEOUT_SECONDS,
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


def call_claude(system: str, user: str, model: str = "claude-sonnet-4-6") -> str:
    """Ruft Claude auf: SDK bei ``ANTHROPIC_API_KEY`` (AC2 unveraendert),
    sonst die claude-CLI ueber die OAuth-Session (Issue #631, AC1), sonst
    Skip -- exakt das bisherige Verhalten (AC7).
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        text, _, _ = _call_claude_sdk(system, user, model)
        return text
    if claude_cli_available():
        parsed = _run_claude_cli(system, user, model)
        _log_model_used("cli", model)
        return str(parsed.get("result", ""))
    pytest.skip("Weder ANTHROPIC_API_KEY noch claude-CLI verfuegbar - Eval uebersprungen")


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
    if t in {"substring", "regex"} and any(re.search(r, output) for r in rejects):
        return False
    if t == "substring":
        return all(v in output for v in _as_patterns(expected["value"]))
    if t == "regex":
        return all(re.search(v, output) for v in _as_patterns(expected["value"]))
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
) -> tuple[str, int, int]:
    """Ruft Claude auf und gibt (text, tokens_in, tokens_out) zurueck.

    SDK bei ``ANTHROPIC_API_KEY`` (AC2 unveraendert). Sonst CLI-Pfad (Issue
    #631, AC1): das oberste ``usage``-Feld aus ``claude --print
    --output-format json`` traegt input_tokens/output_tokens fuer genau
    diesen Aufruf (ohne die interne, session-weite Cache-Erstellung des
    Agenten-Scaffolds mitzuzaehlen) -- semantisch vergleichbar mit
    ``resp.usage`` im SDK-Pfad, s. AC6-Vermerk in docs/evals/STRATEGY.md.
    Ohne Key und ohne CLI: pytest.skip() (AC7 unveraendert).
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _call_claude_sdk(system, user, model)
    if claude_cli_available():
        parsed = _run_claude_cli(system, user, model)
        _log_model_used("cli", model)
        text = str(parsed.get("result", ""))
        usage = parsed.get("usage") or {}
        tokens_in = int(usage.get("input_tokens", 0))
        tokens_out = int(usage.get("output_tokens", 0))
        return text, tokens_in, tokens_out
    pytest.skip("Weder ANTHROPIC_API_KEY noch claude-CLI verfuegbar - Eval uebersprungen")


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
