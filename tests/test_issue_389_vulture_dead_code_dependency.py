"""Regressionstest fuer Issue #389 — vulture als Dev-Dependency + sichtbarer Fehlschlag.

Befund (verifiziert): .github/workflows/pr-deep-review.yml:215 rief `uv run vulture`
mit einem pauschalen `|| true` auf; vulture stand weder in pyproject.toml noch in
uv.lock. Ein echter vulture-Fehlschlag (Exit-Code 1 = Syntaxfehler/ungueltige Eingabe,
2 = ungueltige CLI-Argumente) wurde dadurch stillschweigend verschluckt.

Test-Cases:
1. pyproject.toml listet vulture im dev-Extra (AC1-Voraussetzung).
2. uv.lock enthaelt einen vulture-Eintrag (AC2).
3. Der dead-code-Job in pr-deep-review.yml haengt vulture NICHT mehr pauschal an
   `|| true` (der bisherige Ist-Defekt aus dem Issue).
4. Der neue vulture-Aufruf wertet den Exit-Code aus und laesst den Step bei einem
   echten Fehlschlag (nicht 0/3) sichtbar rot werden (AC4), waehrend Exit-Code 3
   (totem Code gefunden — der Normalfall) den Step weiterhin nicht rot macht.
5. AC3 (Test-PR erzeugt echten vulture-Fund im Sticky-Comment): rein strukturelle
   Tests (1-4) koennen das nicht belegen — dafuer braucht es einen echten
   `pr-deep-review`-Lauf. Test 5 verlangt ein committetes Belegdokument mit dem
   woertlichen Sticky-Comment-Auszug eines echten Live-Test-PRs (siehe
   docs/audit/2026-07-27-issue-389-ac3-vulture-live-verification.md). Fehlt es,
   schlaegt der Test fehl — das war exakt die Luecke aus dem ac-verify:v1-Befund
   auf PR #415 ("Kein Test-PR existiert, kein Sticky-Comment-Nachweis vorhanden").
6.-8. AC4 als VERHALTENSTEST: die strukturellen Tests 3/4 pruefen nur den
   YAML-Text und haben deshalb einen Defekt uebersehen — siehe Root-Cause unten.
   Diese Tests schneiden den vulture-Teil woertlich aus dem echten Run-Block
   heraus und fuehren ihn gegen einen Fixture-Baum aus, der die REALE
   deadCodePaths-Situation nachstellt (vorbestehender 100%-Fund + kaputte Datei).

Root-Cause (verifiziert an vulture 2.16, .venv/.../vulture/core.py:364):
`Vulture.report()` setzt fuer JEDEN gemeldeten Fund bedingungslos
`self.exit_code = ExitCode.DeadCode` (3) und ueberschreibt damit ein zuvor in
`scan()`/`scavenge()` gesetztes `ExitCode.InvalidInput` (1) — unabhaengig davon,
in welcher Datei der Eingabefehler auftrat. Der reale Scope
(`deadCodePaths` = scripts/ + academic_vault/) enthaelt mit
`academic_vault/db.py:147` dauerhaft einen Fund mit 100% Confidence. Damit ist
der Exit-Code dieses Aufrufs praktisch auf 3 festgenagelt und als ALLEINIGES
Fehlersignal unbrauchbar: die Pruefung `VULTURE_EXIT ∉ {0, 3}` greift nie.
Live reproduziert: `vulture scripts/ academic_vault/ --min-confidence 80`
liefert mit UND ohne injizierten Syntaxfehler konstant Exit 3.

Konsequenz fuer den Fix: vulture schreibt Funde nach stdout, aber jeden echten
Eingabefehler nach stderr (die vier `file=sys.stderr`-Stellen in vulture 2.16:
Syntaxfehler, Null-Bytes/ungueltiger Quelltext, nicht lesbare Datei,
Config-`InputError`). Der Workflow muss stderr deshalb GETRENNT auffangen und
jede Ausgabe dort als Fehlschlag werten — zusaetzlich zur Exit-Code-Pruefung.

Faustregel fuer kuenftige manuelle Nachverifikation: eine schlicht ungenutzte
Top-Level-Funktion/-Klasse hat bei vulture nur 60% Default-Confidence und faellt
damit unter die im Workflow gesetzte Schwelle --min-confidence 80 (Issue-Scope
verbietet deren Aenderung). Nur "unreachable code" und "unused function-argument"
erreichen dort 100% und sind zugleich ausserhalb von ruff F401 (90%, aber
deckungsgleich mit F401) — das sind die Faelle, die AC3 tatsaechlich testbar
machen (empirisch verifiziert mit vulture 2.16, siehe Belegdokument).
"""

import importlib.util
import os
import re
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).parent.parent
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
PR_DEEP_REVIEW_WORKFLOW = ROOT / ".github" / "workflows" / "pr-deep-review.yml"


def _dead_code_job() -> dict:
    data = yaml.safe_load(PR_DEEP_REVIEW_WORKFLOW.read_text(encoding="utf-8"))
    jobs = data.get("jobs", {})
    assert "dead-code" in jobs, "pr-deep-review.yml hat keinen dead-code-Job mehr."
    return jobs["dead-code"]


# 'uv run vulture', optional mit uv-eigenen Flags dazwischen (z.B. '--quiet').
_VULTURE_CALL_RE = re.compile(r"\buv run\b(?:\s+-\S+)*\s+vulture\b")


def _vulture_step_run() -> str:
    job = _dead_code_job()
    for step in job["steps"]:
        run = str(step.get("run", ""))
        if _VULTURE_CALL_RE.search(run):
            return run
    raise AssertionError("Kein Step im dead-code-Job ruft 'uv run [flags] vulture' auf.")


# --------------------------------------------------------------------------- #
# 1. pyproject.toml: vulture im dev-Extra
# --------------------------------------------------------------------------- #
def test_pyproject_dev_extra_lists_vulture():
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    dev_deps = data["project"]["optional-dependencies"]["dev"]
    assert any(
        dep.split(">")[0].split("=")[0].split("<")[0].strip() == "vulture" for dep in dev_deps
    ), f"vulture fehlt im [project.optional-dependencies].dev-Extra: {dev_deps}"


# --------------------------------------------------------------------------- #
# 2. uv.lock: vulture-Eintrag vorhanden
# --------------------------------------------------------------------------- #
def test_uv_lock_has_vulture_entry():
    text = UV_LOCK.read_text(encoding="utf-8")
    assert re.search(r'^name = "vulture"$', text, re.MULTILINE), (
        "uv.lock enthaelt keinen vulture-Eintrag."
    )


# --------------------------------------------------------------------------- #
# 3. dead-code-Job: vulture-Aufruf haengt nicht mehr pauschal an '|| true'
# --------------------------------------------------------------------------- #
def test_vulture_invocation_no_longer_swallows_all_exit_codes():
    run = _vulture_step_run()
    # Der bisherige Ist-Defekt: direkt nach der Umleitung nach vulture.txt ein
    # pauschales '|| true', das JEDEN Exit-Code (auch 1/2 = echter Fehlschlag)
    # verschluckt.
    assert not re.search(r"vulture\.txt\"\s*2>&1\s*\|\|\s*true", run), (
        "Der vulture-Aufruf haengt weiterhin pauschal an '|| true' — "
        "ein echter Fehlschlag (Exit 1/2) bleibt unsichtbar (Ist-Defekt aus Issue #389)."
    )


# --------------------------------------------------------------------------- #
# 4. dead-code-Job: Exit-Code wird ausgewertet, {0,3} bleiben unkritisch,
#    alles andere macht den Step sichtbar rot.
# --------------------------------------------------------------------------- #
def test_vulture_invocation_evaluates_exit_code_and_allows_only_0_and_3():
    run = _vulture_step_run()
    # Der Exit-Code muss erfasst werden (z.B. via $? nach 'set +e' oder einer
    # eigenen if/case-Verzweigung) UND explizit auf die vulture-Normalfaelle
    # 0 (kein Fund) und 3 (totem Code gefunden) eingeschraenkt werden.
    assert "$?" in run or "VULTURE_EXIT" in run, (
        "Der vulture-Schritt wertet den Exit-Code nicht sichtbar aus."
    )
    assert re.search(r"[^0-9](0|3)[^0-9].*(0|3)[^0-9]", run) or ("0" in run and "3" in run), (
        "Der vulture-Schritt referenziert nicht beide erlaubten Exit-Codes (0 und 3)."
    )
    # Ein Fehlschlag muss den Step sichtbar (GitHub-Annotation und/oder exit
    # ungleich 0) machen statt ihn stillschweigend weiterlaufen zu lassen.
    assert "::error::" in run and re.search(r"\bexit 1\b", run), (
        "Der vulture-Schritt macht einen echten Fehlschlag nicht sichtbar "
        "(erwartet '::error::'-Annotation + 'exit 1')."
    )


# --------------------------------------------------------------------------- #
# 5. AC3: Test-PR mit totem Code erzeugt echten vulture-Fund im Sticky-Comment
#    — Live-Verifikationsbeleg muss committet und konkret sein (kein
#    struktureller Proxy: das genau war der ac-verify:v1-Befund auf PR #415).
# --------------------------------------------------------------------------- #
AC3_EVIDENCE = ROOT / "docs" / "audit" / "2026-07-27-issue-389-ac3-vulture-live-verification.md"


def test_ac3_live_verification_evidence_documented():
    assert AC3_EVIDENCE.exists(), (
        f"AC3-Live-Verifikationsbeleg fehlt: {AC3_EVIDENCE}. Ohne einen echten "
        "Test-PR-Nachweis bleibt AC3 unbelegt (ac-verify:v1-Befund auf PR #415: "
        "'Kein Test-PR existiert, kein Sticky-Comment-Nachweis vorhanden')."
    )
    text = AC3_EVIDENCE.read_text(encoding="utf-8")
    assert re.search(r"#41\d\b", text), (
        "Beleg referenziert keine konkrete Test-PR-Nummer (erwartet z. B. '#416')."
    )
    assert "flowkit-review:v1" in text, (
        "Beleg zitiert nicht den echten Sticky-Comment-Marker '<!-- flowkit-review:v1 -->' "
        "— ohne diesen Marker ist unklar, ob der Auszug wirklich aus dem echten "
        "Coordinator-Kommentar stammt."
    )
    assert "Reviewer: `dead-code`" in text, (
        "Beleg zeigt keinen Finding-Eintrag mit Reviewer 'dead-code' aus dem echten "
        "Sticky-Comment (render.py-Format, vgl. .github/scripts/flowkit_review/render.py)."
    )
    assert "vulture" in text.lower(), "Beleg erwaehnt vulture nicht als Quelle des Fundes."
    assert "ruff" in text.lower() and "F401" in text, (
        "Beleg belegt nicht explizit die Abgrenzung zu ruff F401 (AC3 verlangt "
        "'nicht nur ruff F401')."
    )


# --------------------------------------------------------------------------- #
# 6.-8. AC4 als Verhaltenstest: der echte Shell-Block wird ausgefuehrt.
#
# Warum das noetig ist: die strukturellen Tests 3/4 pruefen nur YAML-Text und
# haben deshalb uebersehen, dass vulture den Exit-Code 1 (InvalidInput) durch 3
# (DeadCode) ueberschreibt, sobald irgendein Fund oberhalb der Schwelle
# existiert (vulture/core.py::report()). Im realen deadCodePaths-Scope existiert
# so ein Fund dauerhaft (academic_vault/db.py:147, 100% Confidence) — die reine
# Exit-Code-Pruefung greift dort also nie. Die folgenden Tests stellen genau
# diese Situation im Fixture-Baum nach.
# --------------------------------------------------------------------------- #
_VULTURE_GUARD_START = "set +e"
_VULTURE_GUARD_END = "uv run ruff check"

requires_vulture = pytest.mark.skipif(
    importlib.util.find_spec("vulture") is None,
    reason="vulture nicht installiert — 'uv sync --extra dev' noetig (AC1 deckt die Deklaration ab)",
)

# Loest bei --min-confidence 80 einen Fund mit 100% Confidence aus
# ("unreachable code after 'return'") und steht damit fuer den vorbestehenden,
# den Exit-Code auf 3 nagelnden Fund im echten Scope.
_DEAD_CODE_FIXTURE = 'def stable_helper():\n    return 1\n    print("unreachable")\n'
# Nicht parsebar -> vulture setzt ExitCode.InvalidInput (1) und schreibt die
# Meldung nach stderr. Genau dieser Fehlschlag darf nicht verschluckt werden.
_UNPARSEABLE_FIXTURE = "def broken(:\n    pass\n"


def _vulture_guard_script() -> str:
    """Schneidet den vulture-Teil (Aufruf + Fehlerauswertung) WOERTLICH aus dem
    echten Run-Block des dead-code-Jobs heraus — inklusive der `uv run`-Zeile.

    Es wird nichts ersetzt: `uv` selbst wird im Test durch einen Shim auf dem
    PATH gestellt (siehe _write_uv_shim), damit der Aufruf exakt so geprueft
    wird, wie er im Workflow steht.
    """
    lines = _vulture_step_run().splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.strip() == _VULTURE_GUARD_START]
    ends = [i for i, ln in enumerate(lines) if _VULTURE_GUARD_END in ln]
    assert starts, f"Kein '{_VULTURE_GUARD_START}' im vulture-Step gefunden."
    assert ends, f"Kein '{_VULTURE_GUARD_END}' im vulture-Step gefunden."
    assert starts[0] < ends[0], "vulture-Block liegt nicht vor dem ruff-Aufruf."
    segment = "\n".join(lines[starts[0] : ends[0]])
    assert "uv run" in segment and "vulture" in segment, (
        "Extrahiertes Segment enthaelt den 'uv run vulture'-Aufruf nicht."
    )
    return segment


# Ein KALTES `uv run` schreibt Fortschrittsmeldungen nach stderr
# ("Using CPython ...", "Creating virtual environment at: ...", "Installed N
# packages in ...ms") — verifiziert mit uv gegen ein leeres
# UV_PROJECT_ENVIRONMENT. Ohne '--quiet' wuerde die stderr-Pruefung im Guard
# davon faelschlich ausgeloest und JEDER PR rot. Der Shim reproduziert genau
# dieses Verhalten, damit der Test das absichert, ohne im Test ein echtes
# uv-Sync (Netzwerk) auszuloesen.
_UV_SHIM = """#!/usr/bin/env bash
# Test-Shim fuer `uv`: bildet nur `uv run [uv-flags] vulture <args>` ab.
[ "$1" = "run" ] || {{ echo "uv-shim: unerwarteter Subcommand '$1'" >&2; exit 99; }}
shift
QUIET=0
while [ $# -gt 0 ]; do
  case "$1" in
    -q|--quiet|-qq) QUIET=1; shift ;;
    -*) shift ;;
    *) break ;;
  esac
done
if [ "$QUIET" -eq 0 ]; then
  # stderr-Rauschen eines kalten `uv run` ohne --quiet
  printf 'Using CPython 3.12.13\\nCreating virtual environment at: .venv\\n' >&2
  printf 'Installed 92 packages in 788ms\\n' >&2
fi
[ "$1" = "vulture" ] || {{ echo "uv-shim: unerwartetes Kommando '$1'" >&2; exit 98; }}
shift
exec {python} -m vulture "$@"
"""


def _write_uv_shim(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "uv"
    shim.write_text(_UV_SHIM.format(python=shlex.quote(sys.executable)), encoding="utf-8")
    shim.chmod(0o755)


def _run_vulture_guard(tmp_path: Path, *, unparseable: bool):
    """Fuehrt den extrahierten Guard gegen einen Fixture-Baum aus.

    Der Baum enthaelt immer einen vorbestehenden 100%-Fund; `unparseable`
    ergaenzt zusaetzlich eine nicht parsebare Datei.
    """
    workdir = tmp_path / "repo"
    (workdir / "pkg").mkdir(parents=True)
    (workdir / "pkg" / "preexisting.py").write_text(_DEAD_CODE_FIXTURE, encoding="utf-8")
    if unparseable:
        (workdir / "pkg" / "broken.py").write_text(_UNPARSEABLE_FIXTURE, encoding="utf-8")

    bin_dir = tmp_path / "bin"
    _write_uv_shim(bin_dir)
    runner_temp = tmp_path / "runner_temp"
    runner_temp.mkdir()
    script = tmp_path / "guard.sh"
    script.write_text('DEAD_PATHS="pkg/"\n' + _vulture_guard_script() + "\n", encoding="utf-8")

    # GitHub Actions fuehrt `run:`-Bloecke unter `bash -e {0}` aus.
    proc = subprocess.run(
        ["bash", "-e", str(script)],
        cwd=str(workdir),
        env={
            **os.environ,
            "RUNNER_TEMP": str(runner_temp),
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        },
        capture_output=True,
        text=True,
    )
    return proc, runner_temp


@requires_vulture
def test_vulture_guard_fails_when_input_error_is_masked_by_dead_code_exit_code(tmp_path):
    """AC4: ein echter vulture-Fehlschlag wird sichtbar — auch wenn der
    Exit-Code durch einen regulaeren Dead-Code-Fund auf 3 maskiert wird."""
    proc, _ = _run_vulture_guard(tmp_path, unparseable=True)
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, (
        "Der vulture-Guard laeuft trotz nicht parsebarer Datei gruen durch. "
        "Ursache: vulture/core.py::report() ueberschreibt ExitCode.InvalidInput (1) "
        "bedingungslos mit ExitCode.DeadCode (3), sobald ein Fund oberhalb der "
        "Schwelle existiert — im echten Scope ist das dauerhaft der Fall "
        "(academic_vault/db.py:147). Eine reine Exit-Code-Pruefung reicht nicht; "
        f"stderr muss getrennt ausgewertet werden.\nAusgabe:\n{combined}"
    )
    assert "::error::" in combined, (
        f"Fehlschlag erzeugt keine sichtbare GitHub-Annotation.\nAusgabe:\n{combined}"
    )
    assert "invalid syntax" in combined, (
        "Die konkrete vulture-Fehlermeldung taucht im Log nicht auf — der Grund "
        f"des Fehlschlags bleibt unsichtbar.\nAusgabe:\n{combined}"
    )


@requires_vulture
def test_vulture_guard_stays_green_on_regular_dead_code_finding(tmp_path):
    """Gegenprobe: der Normalfall (toter Code gefunden, kein Tool-Fehler) darf
    den Step weiterhin NICHT rot machen, sonst waere jeder PR blockiert."""
    proc, runner_temp = _run_vulture_guard(tmp_path, unparseable=False)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, (
        "Der Guard laesst einen regulaeren Dead-Code-Fund (vulture-Exit 3) "
        f"fehlschlagen — das blockiert jeden PR.\nAusgabe:\n{combined}"
    )
    findings = (runner_temp / "vulture.txt").read_text(encoding="utf-8")
    assert "unreachable code" in findings, (
        f"Der regulaere Fund landet nicht in vulture.txt.\nInhalt:\n{findings}"
    )


@requires_vulture
def test_vulture_findings_file_is_not_contaminated_by_error_output(tmp_path):
    """vulture.txt speist den dead-code-Reviewer. Fehlermeldungen (stderr) haben
    dasselbe `pfad:zeile:`-Praefix wie Funde und wuerden vom nachgelagerten
    Filter als Finding durchgereicht — sie duerfen dort nicht landen."""
    _, runner_temp = _run_vulture_guard(tmp_path, unparseable=True)
    findings = (runner_temp / "vulture.txt").read_text(encoding="utf-8")
    assert "invalid syntax" not in findings, (
        "Die stderr-Fehlermeldung steht in vulture.txt und wuerde dem "
        f"dead-code-Reviewer als echter Fund untergeschoben.\nInhalt:\n{findings}"
    )
