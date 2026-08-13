"""Regressionstest fuer Issue #906.

Die Browser-Guides und Fetcher-Agenten beschrieben eine `browser-use`-CLI, die
es nicht mehr gibt: `open`, `state`, `click`, `input`, `download`, `screenshot`
sowie die Prompt-Form `browser-use "…"`. Die installierte CLI (0.1.8, CLI-3-Form)
nimmt Python ueber ein Heredoc und stellt vorimportierte Helfer bereit.

Der Guard arbeitet mit einer **Allowlist** der real existierenden Unterbefehle
statt einer Blockliste der alten — so faellt auch eine kuenftig erfundene Form
auf, nicht nur die eine historische. Zusaetzlich prueft ein live-gateter Test
die Allowlist gegen `browser-use --help` der tatsaechlich installierten CLI.

Bewusst NICHT gescannt: historische Protokolle (`docs/superpowers/`,
`docs/audit/`, `docs/evals/`, `CHANGELOG.md`) — dort ist die alte Form Teil des
Protokolls und darf stehen bleiben.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GUIDES_DIR = REPO_ROOT / "config" / "browser_guides"
AGENTS_DIR = REPO_ROOT / "agents"
COMMANDS_DIR = REPO_ROOT / "commands"
SKILLS_DIR = REPO_ROOT / "skills"

CANONICAL_DOC = GUIDES_DIR / "_cli.md"
CANONICAL_REF = "browser_guides/_cli.md"

# Die Aufrufform der CLI 3: Python auf stdin, Helfer vorimportiert.
INVOCATION_FORM = "browser-use <<'PY'"

# Unterbefehle, die `browser-use --help` (0.1.8) tatsaechlich auflistet.
# `<<`-Praefix (Heredoc) und `*` (Permission-Glob in Frontmattern) sind
# gesondert erlaubt, siehe _first_token_ok().
KNOWN_SUBCOMMANDS = frozenset(
    {
        "--version",
        "--doctor",
        "doctor",
        "auth",
        "skill",
        "recordings",
        "video",
        "telemetry",
        "--update",
        "--reload",
    }
)

# `browser-use` in Kommando-Position: Zeilenanfang (auch als Listenpunkt),
# hinter einem Backtick, hinter Shell-Prompt oder Verkettungsoperator.
# Fliesstext ("… per browser-use.", "Nur browser-use — kein curl") faellt
# damit nicht in den Scanner.
_COMMAND_POSITION = re.compile(
    r"(?:^[ \t]*(?:(?:[-*+]|\d+[.)])[ \t]+)?|`|\$[ \t]|&&[ \t]|\|\|[ \t])browser-use[ \t]+(\S+)",
    re.MULTILINE,
)

# Die Prompt-Form `browser-use "Klick auf …"` ist unter CLI 3 nicht bloss
# veraltet, sondern ein Syntaxfehler: der Text wird als Python ausgefuehrt.
_PROMPT_FORM = re.compile(r"browser-use[ \t]+[\"']")


def _clean(token: str) -> str:
    """Markdown-Randzeichen abstreifen (`browser-use doctor` → doctor)."""
    return token.rstrip("`.,;:!?)»\"'")


def _first_token_ok(token: str) -> bool:
    """True, wenn das Token hinter `browser-use ` eine gueltige Aufrufform ist."""
    if token.startswith("<<"):  # Heredoc — die eigentliche CLI-3-Form
        return True
    if token.startswith("*"):  # Permission-Glob: Bash(browser-use *)
        return True
    if token.startswith("("):  # Fliesstext: "browser-use (menschliches Tempo)"
        return True
    return _clean(token) in KNOWN_SUBCOMMANDS


def unknown_subcommand_hits(text: str) -> list[str]:
    """Alle `browser-use <token>`-Fundstellen, die die CLI nicht kennt."""
    return [tok for tok in _COMMAND_POSITION.findall(text) if not _first_token_ok(tok)]


def prompt_form_hits(text: str) -> list[str]:
    """Alle Fundstellen der Natursprach-Prompt-Form `browser-use "…"`."""
    return _PROMPT_FORM.findall(text)


def _instruction_files() -> list[Path]:
    """Alle Dateien, die einen Agenten zur Browser-Bedienung anleiten."""
    files: list[Path] = []
    files += sorted(GUIDES_DIR.glob("*.md"))
    files += sorted(AGENTS_DIR.glob("*.md"))
    files += sorted(COMMANDS_DIR.glob("*.md"))
    files += sorted(SKILLS_DIR.rglob("*.md"))
    return files


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


# ---------------------------------------------------------------------------
# AC1 — keine Datei nennt einen Unterbefehl, den die CLI nicht kennt
# ---------------------------------------------------------------------------


def test_no_unknown_browser_use_subcommands():
    offenders: dict[str, list[str]] = {}
    for path in _instruction_files():
        hits = unknown_subcommand_hits(_read(path))
        if hits:
            offenders[_rel(path)] = sorted(set(hits))
    assert not offenders, (
        "Diese Dateien rufen browser-use-Unterbefehle auf, die die installierte "
        f"CLI nicht kennt: {offenders}. Gueltig ist nur die Heredoc-Form "
        f"({INVOCATION_FORM}) bzw. {sorted(KNOWN_SUBCOMMANDS)} — siehe {CANONICAL_REF}."
    )


def test_no_natural_language_prompt_form():
    offenders = [_rel(p) for p in _instruction_files() if prompt_form_hits(_read(p))]
    assert not offenders, (
        'Prompt-Form `browser-use "…"` gefunden in: '
        f"{offenders}. Unter CLI 3 wird der Text als Python ausgefuehrt."
    )


# ---------------------------------------------------------------------------
# AC4 — der Guard selbst greift (Negativpruefung gegen Inline-Fixtures)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "legacy",
    [
        "1. `browser-use open https://example.org`",
        "- `browser-use state` → Button-Index identifizieren",
        "   browser-use download <pdf-idx> --to <output_path>",
        '`browser-use input <idx> "$BROWSER_USE_PASS"`',
        "browser-use click 7",
        "browser-use screenshot",
        "$ browser-use connect --cdp-url http://localhost:9222",
    ],
)
def test_guard_rejects_legacy_form_fixture(legacy: str):
    assert unknown_subcommand_hits(legacy), f"Guard uebersieht die alte Form: {legacy!r}"


@pytest.mark.parametrize(
    "valid",
    [
        "```bash\nbrowser-use <<'PY'\nprint(page_info())\nPY\n```",
        "Fuehrt anschliessend `browser-use doctor` aus.",
        "- `browser-use --doctor` als Fehlerpfad",
        "  - Bash(browser-use *)",
        "  - Bash(browser-use:*)",
        "Du bedienst jstor.org wie ein Mensch. Nur browser-use — kein curl.",
        "Holt OA-Buecher von oapen.org per browser-use. Alle Inhalte offen.",
    ],
)
def test_guard_accepts_current_form_fixture(valid: str):
    assert not unknown_subcommand_hits(valid), f"Guard schlaegt faelschlich an: {valid!r}"


def test_guard_rejects_prompt_form_fixture():
    assert prompt_form_hits('browser-use "navigate to https://example.org"')
    assert not prompt_form_hits("browser-use <<'PY'\nnew_tab('https://example.org')\nPY")


# ---------------------------------------------------------------------------
# AC2 — die Aufrufform steht genau einmal, die Guides verweisen darauf
# ---------------------------------------------------------------------------


def test_canonical_cli_doc_exists():
    assert CANONICAL_DOC.exists(), f"Kanonische CLI-Doku fehlt: {_rel(CANONICAL_DOC)}"


def test_invocation_form_appears_exactly_once():
    carriers = [_rel(p) for p in _instruction_files() if INVOCATION_FORM in _read(p)]
    assert carriers == [_rel(CANONICAL_DOC)], (
        f"Die Aufrufform '{INVOCATION_FORM}' darf nur in {_rel(CANONICAL_DOC)} stehen, "
        f"gefunden in: {carriers}. Guides und Agenten verweisen stattdessen."
    )


def _browser_driving_files() -> list[Path]:
    """Guides/Agenten/Commands, die den Browser tatsaechlich steuern."""
    files = [p for p in GUIDES_DIR.glob("*.md") if p != CANONICAL_DOC]
    files += list(AGENTS_DIR.glob("*.md"))
    files.append(COMMANDS_DIR / "search.md")
    return sorted(p for p in files if "browser-use" in _read(p))


def test_browser_files_reference_canonical_cli_doc():
    missing = [_rel(p) for p in _browser_driving_files() if CANONICAL_REF not in _read(p)]
    assert not missing, (
        f"Diese Dateien nennen browser-use, verweisen aber nicht auf {CANONICAL_REF}: {missing}"
    )


# ---------------------------------------------------------------------------
# AC5 — die Helfer der CLI sind dokumentiert
# ---------------------------------------------------------------------------

CORE_HELPERS = (
    "new_tab",
    "goto_url",
    "page_info",
    "js",
    "cdp",
    "click_at_xy",
    "type_text",
    "fill_input",
    "press_key",
    "scroll",
    "wait_for_load",
    "wait_for_element",
    "wait_for_network_idle",
    "capture_screenshot",
    "list_tabs",
    "switch_tab",
    "close_tab",
    "ensure_real_tab",
    "upload_file",
    "http_get",
)


def test_cli_doc_lists_core_helpers():
    text = _read(CANONICAL_DOC)
    missing = [h for h in CORE_HELPERS if h not in text]
    assert not missing, f"{CANONICAL_REF} nennt diese Kern-Helfer nicht: {missing}"


def test_cli_doc_documents_download_recipe():
    """Es gibt keinen `download`-Helfer — das Ersatzrezept muss dastehen."""
    text = _read(CANONICAL_DOC)
    assert "Browser.setDownloadBehavior" in text
    assert ".crdownload" in text


def test_cli_doc_warns_that_http_get_destroys_pdf_bytes():
    text = _read(CANONICAL_DOC)
    assert "http_get" in text
    assert "PDF" in text


def test_cli_doc_replaces_index_model_with_ax_tree():
    """Das Index-Modell aus `browser-use state` hat keine Entsprechung mehr."""
    text = _read(CANONICAL_DOC)
    assert "Accessibility.getFullAXTree" in text
    assert "DOM.getBoxModel" in text


def test_cli_doc_documents_non_interactive_attach():
    """AC3-Blocker: der Attach an das Default-Chrome ist nicht agententauglich.

    Chrome (M144+) verlangt fuer jede neue DevTools-Verbindung an das laufende
    Default-Profil einen Klick auf „Allow remote debugging?"; der Harness
    bricht sonst mit `permission-blocked` ab. Ein Agent kann diesen Klick nicht
    ausloesen — steht in der kanonischen Doku nur dieser eine Weg, ist jeder
    Guide fuer ihn unbenutzbar. Der Harness selbst kennt den Ausweg
    (`BU_CDP_URL` gegen ein eigenes Automations-Chrome mit eigenem
    `--user-data-dir`), also muss er hier dokumentiert sein.
    """
    text = _read(CANONICAL_DOC)
    missing = [
        marker
        for marker in (
            "permission-blocked",
            "BU_CDP_URL",
            "--remote-debugging-port",
            "--user-data-dir",
        )
        if marker not in text
    ]
    assert not missing, (
        f"{CANONICAL_REF} beschreibt den nicht-interaktiven Verbindungsweg nicht: {missing}. "
        "Ohne ihn bleibt jeder Guide hinter Chromes Allow-Popup stehen."
    )


def test_google_scholar_guide_has_no_index_language():
    """Der belegte Nutzfall darf nicht mehr auf Element-Indizes verweisen."""
    text = _read(GUIDES_DIR / "google_scholar.md")
    assert "Index" not in text, "google_scholar.md nennt weiterhin das Index-Modell"
    assert CANONICAL_REF in text


# ---------------------------------------------------------------------------
# Allowlist gegen die installierte CLI (live-gatet, damit CI ohne CLI gruen bleibt)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("browser-use") is None, reason="browser-use CLI nicht installiert")
def test_known_subcommands_match_installed_cli():
    out = subprocess.run(
        ["browser-use", "--help"], capture_output=True, text=True, timeout=60
    ).stdout
    listed = set(re.findall(r"^\s+browser-use\s+(\S+)", out, re.MULTILINE))
    unknown = {s for s in KNOWN_SUBCOMMANDS if s not in listed}
    assert not unknown, (
        f"Allowlist nennt Unterbefehle, die `browser-use --help` nicht mehr auflistet: {unknown}"
    )
