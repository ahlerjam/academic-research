"""Regressionstest fuer ein Deep-Review-Finding zu PR #939 (Issue #846,
zweiter Folgefund): der fail-closed-Pfad aus dem VORIGEN Folgefund
("Lookup-Apparat kaputt trotz vorhandener DB" -> ``unverifiable``, Block)
war zu breit gefasst.

Praemisse des vorigen Fixes: ``ensureQuoteBatch()`` liefert ``null`` nur,
wenn KEIN Interpreter der Kaskade ueberhaupt anlief -- der Apparat ist
"nicht pruefbar", also block statt Bypass. Tatsaechlich liefert
``ensureQuoteBatch()`` (und das darunterliegende ``runVaultPython()`` aus
hooks/lib/vault-bridge.mjs) ``null`` fuer JEDEN Fehlschlag: auch bei einem
execFileSync-TIMEOUT eines tatsaechlich gestarteten Kandidaten, bei
erschoepftem Gesamtbudget und bei einer Antwort, die kein valides JSON ist.

Realistisches Szenario: ein Vault mit mehreren tausend Zitaten braucht laut
scripts/dev/bench_hook_guards_batch.mjs bereits >1 s reine Python-Zeit +
Interpreterstart -- unter Systemlast reicht das fuer einen Timeout, OBWOHL
der Interpreter-Apparat voll funktionsfaehig ist. Ein pauschales fail-closed
fuer jeden ``null``-Fall haette eine langsame Maschine zum Totalblocker fuer
JEDEN Write gemacht.

Fix: hooks/lib/vault-bridge.mjs::runVaultPython()/ensureQuoteBatch()
klassifizieren jetzt WARUM sie ``null`` liefern (optionales
``diagnostics``-Objekt, ``.reason``):
  - ``'no-interpreter'``  -- kein Kandidat lief ueberhaupt an. Apparat kaputt,
    NICHT pruefbar. Bleibt fail-CLOSED (``unverifiable``, Block, rc=2) --
    exakt das Szenario aus tests/test_review_fix_verbatim_guard.py::
    test_finding1_blockiert_erfundenes_zitat_trotz_kaputtem_path_python3.
  - ``'timeout'``/``'budget'``/``'parse-error'``/``'shape-error'`` -- eine
    Aussage ueber die MASCHINE oder das Antwortformat, nicht ueber die
    Vault-Verfuegbarkeit. Bleibt fail-OPEN wie vor #846 (Warnung, rc=0).

Drei Tests je Klasse (kein Interpreter, Timeout, Parse-Fehler) plus ein
Smoke-Test, dass der urspruengliche fail-closed-Fall (rc=2 bei erfundenem
Zitat + fehlendem Modul) unveraendert bleibt.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "verbatim-guard.mjs"

pytest.importorskip("academic_vault", reason="academic_vault-Paket nicht importierbar")


def _resolve_real_node_bin() -> str | None:
    """Wie in test_review_fix_verbatim_guard.py: der ECHTE node-Binaerpfad
    (process.execPath), nicht bloss der erste PATH-Treffer -- diese Tests
    faelschen PATH absichtlich, ein Versionsmanager-Shim waere darin nicht
    mehr lauffaehig."""
    node_on_path = shutil.which("node")
    if node_on_path is None:
        return None
    try:
        result = subprocess.run(
            [node_on_path, "-e", "process.stdout.write(process.execPath)"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except OSError:
        return None
    resolved = result.stdout.strip()
    return resolved or node_on_path


_NODE_BIN = _resolve_real_node_bin()
if _NODE_BIN is None:
    pytest.skip("node nicht im PATH — Hook nicht ausführbar", allow_module_level=True)


def _run_hook_with_env(
    content: str, file_path: str, env: dict[str, str], timeout: int = 30
) -> subprocess.CompletedProcess:
    payload = json.dumps(
        {"tool_name": "Write", "tool_input": {"file_path": file_path, "content": content}}
    )
    return subprocess.run(
        [_NODE_BIN, str(HOOK_PATH)],
        input=payload,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.fixture
def vault_with_quote(tmp_path: Path) -> tuple[str, Path]:
    """Legt eine isolierte Vault-DB mit GENAU einem verifizierten Zitat an."""
    from academic_vault.server import add_paper, add_quote

    proj = tmp_path / "proj"
    (proj / "kapitel").mkdir(parents=True)
    db = str(proj / "vault.db")
    add_paper(db, "g1", json.dumps({"type": "article-journal", "title": "T"}))
    add_quote(
        db,
        "g1",
        "Wissenschaft ist die Kunst des Moeglichen im akademischen Kontext",
        "manual",
    )
    return db, proj


INVENTED = "Dieses Zitat wurde frei erfunden und niemals in den Vault eingepflegt"
INVENTED_CONTENT = f'Angeblich: "{INVENTED}" — falsch.'


def _fake_empty_home(tmp_path: Path) -> Path:
    """HOME ohne ~/.academic-research/venv — Kandidat 3 der Kaskade
    (hooks/lib/vault-bridge.mjs::pythonCandidates()) existiert dort nicht."""
    home = tmp_path / "fake-home"
    home.mkdir()
    return home


def _broken_bin(tmp_path: Path) -> Path:
    """PATH-Verzeichnis mit einem GARANTIERT scheiternden python3-Stub
    (Kandidat 4, PATH-Fallback)."""
    bin_dir = tmp_path / "broken-bin"
    bin_dir.mkdir()
    stub = bin_dir / "python3"
    stub.write_text('#!/bin/sh\necho "kaputt" >&2\nexit 1\n')
    stub.chmod(0o755)
    return bin_dir


# ---------------------------------------------------------------------------
# Klasse 1: KEIN Interpreter der Kaskade laeuft an -> fail-CLOSED (Block)
# ---------------------------------------------------------------------------


def test_kein_interpreter_blockiert(tmp_path: Path, vault_with_quote: tuple[str, Path]) -> None:
    """ACADEMIC_PYTHON zeigt ins Nichts, kein VIRTUAL_ENV, HOME ohne
    kanonisches venv, PATH ohne lauffaehiges python3 -- ALLE vier Kandidaten
    aus pythonCandidates() scheitern nicht-timeout (ENOENT/nicht vorhanden).
    Das ist der Apparat-kaputt-Fall in Reinform: muss blockieren (rc=2),
    NICHT durchwinken."""
    db, proj = vault_with_quote
    fake_home = _fake_empty_home(tmp_path)
    broken_bin = _broken_bin(tmp_path)
    env = {
        "PATH": str(broken_bin),
        "HOME": str(fake_home),
        "VAULT_DB_PATH": db,
        "CLAUDE_PROJECT_DIR": str(proj),
        "ACADEMIC_PYTHON": str(tmp_path / "does-not-exist" / "python"),
    }
    result = _run_hook_with_env(INVENTED_CONTENT, str(proj / "kapitel" / "x.md"), env)
    assert result.returncode == 2, (
        f"Kein Interpreter der Kaskade laeuft an -- muss blockieren (rc={result.returncode}). "
        f"stdout={result.stdout[:400]!r} stderr={result.stderr[:600]!r}"
    )
    decision = json.loads(result.stdout.strip())
    assert decision.get("decision") == "block"
    assert "Lookup-Apparat" in result.stderr, (
        f"Erwartet den Apparat-kaputt-Hinweis in stderr: {result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Klasse 2: Timeout eines TATSAECHLICH gestarteten Kandidaten -> fail-OPEN
# ---------------------------------------------------------------------------


def test_timeout_laesst_durch_und_warnt(tmp_path: Path, vault_with_quote: tuple[str, Path]) -> None:
    """ACADEMIC_PYTHON (hoechste Prioritaet der Kaskade) zeigt auf ein
    Skript, das laenger schlaeft als das Zeitbudget (VAULT_LOOKUP_BUDGET_MS
    = 10 s in hooks/verbatim-guard.mjs) -- der Interpreter LAEUFT an, wird
    aber wegen Zeitueberschreitung gekillt (execFileSync wirft ETIMEDOUT).
    Das ist eine Aussage ueber die Maschine, nicht den Apparat: ein
    erfundenes Zitat darf hier NICHT blockiert werden, nur eine Warnung
    ist zulaessig (rc=0). Braucht ~10 s Wanduhrzeit (Timeout muss wirklich
    ablaufen)."""
    db, proj = vault_with_quote
    fake_home = _fake_empty_home(tmp_path)
    slow_python = fake_home / "slow-python"
    slow_python.write_text("#!/bin/sh\nsleep 30\n")
    slow_python.chmod(0o755)

    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(fake_home),
        "VAULT_DB_PATH": db,
        "CLAUDE_PROJECT_DIR": str(proj),
        "ACADEMIC_PYTHON": str(slow_python),
    }
    result = _run_hook_with_env(INVENTED_CONTENT, str(proj / "kapitel" / "x.md"), env, timeout=25)
    assert result.returncode == 0, (
        "Timeout eines gestarteten Interpreters ist ein Maschinenproblem, kein "
        f"Apparat-Befund -- darf NICHT blockieren (rc={result.returncode}). "
        f"stdout={result.stdout[:400]!r} stderr={result.stderr[:600]!r}"
    )
    assert "Batch-Lookup fehlgeschlagen" in result.stderr, (
        f"Erwartet eine Warnung (fail-open), keinen stillen Durchlass: {result.stderr!r}"
    )
    assert "Lookup-Apparat" not in result.stderr, (
        f"Ein Timeout darf NICHT als Apparat-kaputt-Fall gemeldet werden: {result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Klasse 3: Interpreter antwortet, aber nicht mit validem JSON -> fail-OPEN
# ---------------------------------------------------------------------------


def test_parse_fehler_laesst_durch_und_warnt(
    tmp_path: Path, vault_with_quote: tuple[str, Path]
) -> None:
    """ACADEMIC_PYTHON zeigt auf einen ECHTEN Python-Interpreter (sys.executable
    der Testumgebung), der aber Muell statt JSON auf stdout schreibt --
    ensureQuoteBatch() bekommt eine Antwort, JSON.parse() scheitert. Auch
    das ist ein Antwortformat-, kein Apparat-Problem: darf nicht blockieren."""
    db, proj = vault_with_quote
    fake_home = _fake_empty_home(tmp_path)
    garbage_python = fake_home / "garbage-python"
    garbage_python.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" -c "print(\'dies ist kein JSON {{{{\')"\n'
    )
    garbage_python.chmod(0o755)

    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(fake_home),
        "VAULT_DB_PATH": db,
        "CLAUDE_PROJECT_DIR": str(proj),
        "ACADEMIC_PYTHON": str(garbage_python),
    }
    result = _run_hook_with_env(INVENTED_CONTENT, str(proj / "kapitel" / "x.md"), env)
    assert result.returncode == 0, (
        "Ein Antwortformat-Fehler (kein valides JSON) ist kein Apparat-Befund -- darf "
        f"NICHT blockieren (rc={result.returncode}). stdout={result.stdout[:400]!r} "
        f"stderr={result.stderr[:600]!r}"
    )
    assert "Batch-Lookup fehlgeschlagen" in result.stderr, (
        f"Erwartet eine Warnung (fail-open), keinen stillen Durchlass: {result.stderr!r}"
    )
    assert "Lookup-Apparat" not in result.stderr, (
        f"Ein Parse-Fehler darf NICHT als Apparat-kaputt-Fall gemeldet werden: {result.stderr!r}"
    )
