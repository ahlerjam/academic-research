"""Regressionstests für zwei Funde im Code-Review von hooks/verbatim-guard.mjs.

FINDING 1 (kritisch): verbatim-guard rief den Vault über ein hartkodiertes
`python3` auf statt über die Interpreter-Kaskade aus
hooks/lib/vault-bridge.mjs (`runVaultPython`). Auf einem PATH, dessen
`python3` `academic_vault` nicht importieren kann (z. B. macOS-System-Python
3.9), warf execFileSync in allen drei Lookups -> warnFailOpen() -> Bypass:
ein Write mit einem komplett erfundenen Zitat lief durch (exit 0) statt
geblockt zu werden (exit 2). Fix: alle drei Lookups laufen jetzt über
runVaultPython(), das mehrere Interpreter-Kandidaten probiert — u. a. das
kanonische Setup-venv unter ~/.academic-research/venv/bin/python,
unabhängig vom PATH.

FINDING 4: der Zitat-Span-Scan (extractQuoteSpans) und der
Figure-Referenz-Scan liefen auf dem UNMASKIERTEN Content. Ein Quellentitel
im eigenen Literaturverzeichnis ("… "Digitalisierung im deutschen
Mittelstand" …") wurde fälschlich als unverifiziertes wörtliches Zitat
gewertet und blockte den Write hart — obwohl citation-parse.mjs::
maskSkipRegions() genau diese Region (Literaturverzeichnis-Überschrift bis
Dateiende, Code-Fences, LaTeX-Makros) bereits maskiert, aber nur für
extractCitations() angewendet wurde. Fix: beide Scans laufen jetzt auf
maskSkipRegions(content) statt auf content.

REGRESSION A (Zweitreview des Fixes zu Finding 4): der Fix wendete
maskSkipRegions() an, BEVOR extractQuoteSpans() daraus die Spans zog — und
schlug anschließend den MASKIERTEN Spantext im Vault nach. Ein Zitat, das
Inline-Code oder ein LaTeX-Makro enthält, ging damit mit Leerzeichen an der
Makro-Stelle in den Lookup, traf nicht mehr und wurde als „unbelegtes Zitat"
hart geblockt — obwohl es korrekt im Vault stand. Fix: die Maskierung
bestimmt nur noch, WELCHE Regionen übersprungen werden; die Span-Positionen
werden auf dem maskierten Text ermittelt (maskSkipRegions ist
längenerhaltend) und der nachzuschlagende Text an genau diesen Offsets aus
dem ORIGINALINHALT geschnitten.

REGRESSION B: ein Python-Subprozess PRO Quote-Span und PRO Figure-Referenz.
Bei je 8 s Budget sprengte ein Kapitel mit vier Zitaten und zwei
Abbildungsverweisen das 30-s-Hook-Timeout aus hooks/hooks.json. Fix: alle
Quote-Spans und Figure-Referenzen laufen in EINEM Subprozess (Muster aus
hooks/claim-drift-guard.mjs::PY_LOOKUP).

Alle Befunde werden über den echten node-Hook als Subprozess getestet (wie
tests/test_issue_378_citation_guard.py) gegen eine echte, isolierte
Vault-DB (wie tests/helpers/smoke_core.py::check_hook_verbatim_guard).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "verbatim-guard.mjs"
VENV_PYTHON = Path.home() / ".academic-research" / "venv" / "bin" / "python"

pytest.importorskip("academic_vault", reason="academic_vault-Paket nicht importierbar")


def _resolve_real_node_bin() -> str | None:
    """Liefert den ECHTEN node-Binärpfad (process.execPath), nicht bloß den
    ersten PATH-Treffer: Versionsmanager (asdf/nvm/volta) legen dort oft nur
    einen Shim-Wrapper ab, der selbst wieder `bash` + weitere PATH-Einträge
    braucht. Der Finding-1-Test fälscht das PATH des Hook-Subprozesses
    absichtlich auf ein Verzeichnis mit einem kaputten "python3"-Stub — darin
    wäre ein Shim-Wrapper nicht mehr lauffähig. Aufgelöst wird deshalb einmal
    MIT dem echten PATH der Testumgebung, danach per Vollpfad gestartet
    (siehe _run_hook_with_env unten).
    """
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

if not VENV_PYTHON.exists():
    pytest.skip(
        f"venv-Python fehlt ({VENV_PYTHON}) — /academic-research:setup ausführen",
        allow_module_level=True,
    )


def _run_hook_with_env(
    content: str, file_path: str, env: dict[str, str]
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
        timeout=30,
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


# ---------------------------------------------------------------------------
# Finding 1: hartkodiertes python3 statt Interpreter-Kaskade
# ---------------------------------------------------------------------------


@pytest.fixture
def broken_path_python3(tmp_path: Path) -> Path:
    """Ein Verzeichnis, dessen `python3` IMMER fehlschlägt — simuliert das
    macOS-System-Python (3.9), das `academic_vault` mangels PEP-604-Syntax
    nicht importieren kann (Finding 1, academic_vault/embedding_model.py:93).
    """
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_python3 = fake_bin / "python3"
    fake_python3.write_text(
        "#!/bin/sh\n"
        "echo \"TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'\" >&2\n"
        "exit 1\n"
    )
    fake_python3.chmod(0o755)
    return fake_bin


def test_finding1_blockiert_erfundenes_zitat_trotz_kaputtem_path_python3(
    vault_with_quote: tuple[str, Path], broken_path_python3: Path
) -> None:
    """Guard muss auch dann blocken, wenn PATH nur ein kaputtes `python3`
    enthält — solange das kanonische Setup-venv unter
    ~/.academic-research/venv/bin/python (unabhängig vom PATH) erreichbar
    ist. Regression: vor dem Fix rief der Guard IMMER das hartkodierte
    `python3` auf, scheiterte daran und ließ den Write fail-open durch
    (verifiziert gegen den Pre-Fix-Stand: dieselbe Umgebung lieferte dort
    rc=0 statt rc=2).
    """
    db, proj = vault_with_quote
    # PATH enthält NUR den kaputten python3-Stub — kein System-/Homebrew-
    # Python, kein venv/bin. HOME zeigt auf das ECHTE Home, damit der
    # venv-Kandidat aus vault-bridge.mjs::pythonCandidates() (Kandidat 3,
    # unabhängig vom PATH) den echten, funktionierenden Interpreter trifft.
    env = {
        "PATH": str(broken_path_python3),
        "HOME": os.environ.get("HOME", ""),
        "VAULT_DB_PATH": db,
        "CLAUDE_PROJECT_DIR": str(proj),
    }
    chapter_file = str(proj / "kapitel" / "x.md")
    invented = "Dieses Zitat wurde frei erfunden und niemals in den Vault eingepflegt"
    result = _run_hook_with_env(f'Angeblich: "{invented}" — falsch.', chapter_file, env)
    assert result.returncode == 2, (
        "verbatim-guard hätte das erfundene Zitat blockieren müssen, auch mit "
        f"kaputtem PATH-python3 (rc={result.returncode}). stdout={result.stdout[:300]!r} "
        f"stderr={result.stderr[:500]!r}"
    )
    decision = json.loads(result.stdout.strip())
    assert decision.get("decision") == "block", f"Block-Payload ohne decision:block: {decision}"


def test_finding1_erlaubt_verifiziertes_zitat_trotz_kaputtem_path_python3(
    vault_with_quote: tuple[str, Path], broken_path_python3: Path
) -> None:
    """Gegenprobe zum vorigen Test: ein ECHTES, im Vault hinterlegtes Zitat
    darf trotz kaputtem PATH-python3 NICHT blockiert werden — die Kaskade
    muss den echten Treffer über das venv finden, nicht bloß "irgendwie"
    blocken.
    """
    db, proj = vault_with_quote
    env = {
        "PATH": str(broken_path_python3),
        "HOME": os.environ.get("HOME", ""),
        "VAULT_DB_PATH": db,
        "CLAUDE_PROJECT_DIR": str(proj),
    }
    chapter_file = str(proj / "kapitel" / "x.md")
    verbatim = "Wissenschaft ist die Kunst des Moeglichen im akademischen Kontext"
    result = _run_hook_with_env(f'Im Text steht: "{verbatim}" als Beleg.', chapter_file, env)
    assert result.returncode == 0, (
        f"verbatim-guard blockierte ein VERIFIZIERTES Zitat (rc={result.returncode}). "
        f"stderr={result.stderr[:500]!r}"
    )


# ---------------------------------------------------------------------------
# Finding 4: Quote-/Figure-Scan lief auf unmaskiertem Content
# ---------------------------------------------------------------------------


def _run_hook_normal_env(
    content: str, file_path: str, db: str, proj: Path
) -> subprocess.CompletedProcess:
    """Wie _run_hook_with_env, aber mit funktionierendem python3 (echtes venv
    vorn im PATH) — isoliert Finding 4 (Masking) von Finding 1 (Kaskade).
    """
    venv_bin = str(VENV_PYTHON.parent)
    env = {
        "PATH": venv_bin + os.pathsep + os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "VAULT_DB_PATH": db,
        "CLAUDE_PROJECT_DIR": str(proj),
    }
    return _run_hook_with_env(content, file_path, env)


def test_finding4_literaturverzeichnis_titel_blockiert_nicht(
    vault_with_quote: tuple[str, Path],
) -> None:
    """Ein zitierter Quellentitel im EIGENEN Literaturverzeichnis darf nicht
    als unverifiziertes wörtliches Zitat gewertet werden. Regression:
    extractQuoteSpans() lief vor dem Fix auf unmaskiertem Content und
    blockte hart (exit 2), obwohl maskSkipRegions() genau diese Region
    (BIBLIOGRAPHY_HEADING bis EOF) bereits für extractCitations() maskiert
    (verifiziert gegen den Pre-Fix-Stand: dieselbe Datei lieferte dort
    rc=2 statt rc=0).
    """
    db, proj = vault_with_quote
    content = (
        "## Kapitel 3\n\n"
        "Ein Beispieltext ohne wörtliches Zitat im Fließtext.\n\n"
        "## Literaturverzeichnis\n\n"
        'Mueller, T. (2021). "Digitalisierung im deutschen Mittelstand". Springer.\n'
    )
    result = _run_hook_normal_env(content, str(proj / "kapitel" / "03-hauptteil.md"), db, proj)
    assert result.returncode == 0, (
        "verbatim-guard blockierte einen Quellentitel im eigenen "
        f"Literaturverzeichnis (rc={result.returncode}). stderr={result.stderr[:500]!r}"
    )


def test_finding4_code_fence_zitat_blockiert_nicht(vault_with_quote: tuple[str, Path]) -> None:
    """Ein Anführungszeichen-Span INNERHALB eines Code-Fence ist kein
    wörtliches Zitat und darf nicht blocken (maskSkipRegions() maskiert
    Code-Fences bereits für extractCitations(); dieselbe Maskierung muss
    jetzt auch für den Quote-Span-Scan gelten).
    """
    db, proj = vault_with_quote
    content = (
        "Codebeispiel:\n\n"
        "```text\n"
        '"Dies ist nur ein Beispiel im Codefence und kein echtes Zitat wirklich"\n'
        "```\n"
    )
    result = _run_hook_normal_env(content, str(proj / "kapitel" / "03-hauptteil.md"), db, proj)
    assert result.returncode == 0, (
        f"verbatim-guard blockierte ein Zitat INNERHALB eines Code-Fence (rc={result.returncode}). "
        f"stderr={result.stderr[:500]!r}"
    )


def test_finding4_echtes_unverifiziertes_zitat_im_fliesstext_blockiert_weiterhin(
    vault_with_quote: tuple[str, Path],
) -> None:
    """Kontrollprobe: ein ECHTES, unverifiziertes wörtliches Zitat im
    normalen Fließtext (außerhalb jeder maskierten Region) muss weiterhin
    blockieren — die Maskierung aus Finding 4 darf den Guard nicht generell
    entschärfen.
    """
    db, proj = vault_with_quote
    content = (
        'Angeblich behauptet die Quelle: "Dies ist ein komplett erfundenes '
        'wörtliches Zitat im Fließtext" und das steht nirgends im Vault.'
    )
    result = _run_hook_normal_env(content, str(proj / "kapitel" / "03-hauptteil.md"), db, proj)
    assert result.returncode == 2, (
        "verbatim-guard hätte ein echtes unverifiziertes Zitat im Fließtext "
        f"weiterhin blockieren müssen (rc={result.returncode}). stderr={result.stderr[:500]!r}"
    )
    decision = json.loads(result.stdout.strip())
    assert decision.get("decision") == "block", f"Block-Payload ohne decision:block: {decision}"


# ---------------------------------------------------------------------------
# Regression A: maskierter statt echter Spantext ging in den Vault-Lookup
# ---------------------------------------------------------------------------

LATEX_QUOTE = r"Die Einfuehrung von \emph{Continuous Delivery} veraendert die Governance"
INLINE_CODE_QUOTE = "Der Parameter `--force` erzwingt die Pruefung vor dem Deployment"


@pytest.fixture
def vault_with_markup_quotes(tmp_path: Path) -> tuple[str, Path]:
    """Vault-DB mit zwei verifizierten Zitaten, die MARKUP enthalten (LaTeX-Makro
    bzw. Markdown-Inline-Code) — genau die Regionen, die maskSkipRegions()
    INNERHALB des Zitats ausblendet.
    """
    from academic_vault.server import add_paper, add_quote

    proj = tmp_path / "proj-markup"
    (proj / "kapitel").mkdir(parents=True)
    db = str(proj / "vault.db")
    add_paper(db, "g1", json.dumps({"type": "article-journal", "title": "T"}))
    add_quote(db, "g1", LATEX_QUOTE, "manual")
    add_quote(db, "g1", INLINE_CODE_QUOTE, "manual")
    return db, proj


def test_regression_a_zitat_mit_latex_makro_wird_mit_echtem_text_geprueft(
    vault_with_markup_quotes: tuple[str, Path],
) -> None:
    """Ein im Vault hinterlegtes LaTeX-Zitat mit ``\\emph{...}`` darf nicht blocken.

    Regression: der Finding-4-Fix schlug den MASKIERTEN Spantext nach
    ("Die Einfuehrung von                          veraendert die Governance"),
    fand nichts und blockte den Write hart.
    """
    db, proj = vault_with_markup_quotes
    content = f"Der Autor schreibt: ``{LATEX_QUOTE}'' und begruendet das ausfuehrlich.\n"
    result = _run_hook_normal_env(content, str(proj / "kapitel" / "03-hauptteil.tex"), db, proj)
    assert result.returncode == 0, (
        "verbatim-guard blockierte ein VERIFIZIERTES Zitat, das ein LaTeX-Makro enthält "
        f"(rc={result.returncode}) — der Lookup lief offenbar auf dem maskierten Text. "
        f"stderr={result.stderr[:600]!r}"
    )


def test_regression_a_zitat_mit_inline_code_wird_mit_echtem_text_geprueft(
    vault_with_markup_quotes: tuple[str, Path],
) -> None:
    """Wie oben, aber Markdown-Inline-Code innerhalb des Zitats."""
    db, proj = vault_with_markup_quotes
    content = f'Die Quelle sagt: "{INLINE_CODE_QUOTE}" und das ist belegt.\n'
    result = _run_hook_normal_env(content, str(proj / "kapitel" / "03-hauptteil.md"), db, proj)
    assert result.returncode == 0, (
        "verbatim-guard blockierte ein VERIFIZIERTES Zitat mit Inline-Code "
        f"(rc={result.returncode}). stderr={result.stderr[:600]!r}"
    )


def test_regression_a_unbelegtes_zitat_mit_makro_blockiert_mit_echtem_text(
    vault_with_markup_quotes: tuple[str, Path],
) -> None:
    """Gegenprobe: ein NICHT hinterlegtes Zitat mit Makro muss weiter blocken —
    und die Blockmeldung muss den ECHTEN Text nennen (inkl. Makro), nicht die
    ausgeleerte Fassung. Sonst ist für den Autor nicht erkennbar, welcher Satz
    gemeint ist.
    """
    db, proj = vault_with_markup_quotes
    invented = r"Diese Aussage mit \emph{Beleg} wurde frei erfunden und nie eingepflegt"
    content = f"Angeblich: ``{invented}'' — falsch.\n"
    result = _run_hook_normal_env(content, str(proj / "kapitel" / "03-hauptteil.tex"), db, proj)
    assert result.returncode == 2, (
        "Ein unbelegtes Zitat mit LaTeX-Makro muss weiterhin blockieren "
        f"(rc={result.returncode}). stderr={result.stderr[:600]!r}"
    )
    assert r"\emph{Beleg}" in result.stdout, (
        "Blockmeldung muss den ECHTEN Zitattext nennen, nicht den maskierten: "
        f"{result.stdout[:400]!r}"
    )


# ---------------------------------------------------------------------------
# Regression B: ein Python-Subprozess pro Span statt eines pro Hook-Aufruf
# ---------------------------------------------------------------------------

BATCH_QUOTES = [
    "Governance braucht klare Verantwortlichkeiten im laufenden Betrieb",
    "Automatisierung ersetzt keine Entscheidungsrechte im Unternehmen",
    "Messbarkeit ist die Grundlage jeder Steuerung im DevOps-Umfeld",
    "Kultur schlaegt Werkzeug in jeder Transformation des Betriebs",
]


@pytest.fixture
def vault_for_batch(tmp_path: Path) -> tuple[str, Path]:
    """Vault mit vier verifizierten Zitaten und zwei Figures — ein Write, der vor
    dem Fix sechs Interpreterstarts auslöste.
    """
    from academic_vault.server import add_figure, add_paper, add_quote

    proj = tmp_path / "proj-batch"
    (proj / "kapitel").mkdir(parents=True)
    db = str(proj / "vault.db")
    add_paper(db, "g1", json.dumps({"type": "article-journal", "title": "T"}))
    for quote in BATCH_QUOTES:
        add_quote(db, "g1", quote, "manual")
    add_figure(db, "g1", 3, "Abbildung 3.4: Governance-Modell", None, None)
    add_figure(db, "g1", 5, "Abbildung 5.1: Reifegradstufen", None, None)
    return db, proj


@pytest.fixture
def counting_python(tmp_path: Path) -> tuple[Path, Path]:
    """Ein Python-Wrapper, der jeden Aufruf mitzählt und dann an das echte
    venv-Python durchreicht. Wird über ACADEMIC_PYTHON als erster Kandidat der
    Interpreter-Kaskade (vault-bridge.mjs::pythonCandidates) gesetzt.
    """
    counter = tmp_path / "python-calls.log"
    wrapper = tmp_path / "counting-python"
    wrapper.write_text(
        "#!/bin/sh\n" + f'printf "call\\n" >> "{counter}"\n' + f'exec "{VENV_PYTHON}" "$@"\n'
    )
    wrapper.chmod(0o755)
    return wrapper, counter


def test_regression_b_ein_subprozess_fuer_alle_spans_und_figures(
    vault_for_batch: tuple[str, Path], counting_python: tuple[Path, Path]
) -> None:
    """Vier Zitate + zwei Abbildungsverweise dürfen NICHT sechs Interpreterstarts
    kosten. Vor dem Fix startete der Guard je Span/Referenz einen eigenen
    Python-Prozess mit je 8 s Budget — in Summe bis zu 48 s gegen ein
    30-s-Hook-Timeout aus hooks/hooks.json.
    """
    db, proj = vault_for_batch
    wrapper, counter = counting_python
    env = {
        "PATH": str(VENV_PYTHON.parent) + os.pathsep + os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "ACADEMIC_PYTHON": str(wrapper),
        "VAULT_DB_PATH": db,
        "CLAUDE_PROJECT_DIR": str(proj),
    }
    content = (
        "## Kapitel 4\n\n"
        + "".join(f'Erkenntnis: "{q}".\n' for q in BATCH_QUOTES)
        + "\nSiehe Abb. 3.4 sowie Abb. 5.1 fuer die Details.\n"
    )
    result = _run_hook_with_env(content, str(proj / "kapitel" / "04-hauptteil.md"), env)
    assert result.returncode == 0, (
        "Alle Zitate und Figures sind im Vault — der Guard darf nicht blocken "
        f"(rc={result.returncode}). stderr={result.stderr[:600]!r}"
    )
    calls = counter.read_text().count("call") if counter.exists() else 0
    assert calls == 1, (
        "Erwartet GENAU einen Python-Subprozess für alle vier Quote-Spans und beide "
        f"Figure-Referenzen, gezählt: {calls}. stderr={result.stderr[:600]!r}"
    )
