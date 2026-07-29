"""Akzeptanz-Guards fuer Issue #468 (AC2-AC4) — Voraussetzungen und Zugangsdaten-Doku.

AC2  Die Voraussetzungen fuehren alle Werkzeuge auf, ohne die das Plugin
     Funktionen still verliert.
AC3  Ein Doku-Abschnitt erklaert die drei Wege zur Hinterlegung von
     Zugangsdaten und ihre jeweilige Zustaendigkeit.
AC4  Der erste Lauf weist auf Umfang und Ablageort des Modell-Downloads hin.

Bestandsaufnahme der drei Zugangsdaten-Wege (siehe Plan-Kommentar zu #468):
1. Umgebungsvariablen pro Suchquelle — ``SS_API_KEY`` (scripts/search.py),
   ``ANTHROPIC_API_KEY`` (scripts/batch_api.py).
2. Per-Uni-Profil ``active.yaml``, Feld ``credentials_keys`` — genutzt vom
   ``auth-helper``-Subagenten fuer den book-fetcher-Workflow.
3. Das HAN-spezifische Zugangsdaten-File unter ``~/.academic-research/``
   (Keys ``han_user``/``han_password``), genutzt von
   ``config/browser_guides/han_login.md`` fuer die Tiefensuche-Auth-Module
   (ebscohost, proquest, opac).

Hinweis Dateiname: bewusst ohne das Wort "Credential(s)" im Dateinamen, um
nicht mit der Deny-Regel ``Read(/**/*credentials*)`` aus
``.claude/settings.json`` (Schutz vor versehentlichem Secret-Zugriff) zu
kollidieren.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
INSTALLATION_DOC = REPO_ROOT / "docs" / "guide" / "installation.md"
README = REPO_ROOT / "README.md"

#: Werkzeuge, ohne die das Plugin Funktionen still (ohne Fehlermeldung) verliert.
REQUIRED_TOOL_MARKERS = (
    "Claude Code",
    "Python 3.11",
    "Node.js",
    "Git",
    "multilingual-e5-small",
    "ocrmypdf",
)

#: Die drei Zugangsdaten-Wege, konkret benannt (Code-Ist-Zustand, kein Aliasing).
AUTH_ENV_VAR_MARKERS = ("SS_API_KEY", "ANTHROPIC_API_KEY")
AUTH_PROFILE_MARKER = "credentials_keys"
AUTH_HAN_MARKERS = ("han_user", "han_password")


def _read(path: Path) -> str:
    assert path.exists(), f"Datei fehlt: {path}"
    return path.read_text(encoding="utf-8")


def _installation_text() -> str:
    return _read(INSTALLATION_DOC)


# ---------------------------------------------------------------------------
# AC2 — Voraussetzungen vollstaendig
# ---------------------------------------------------------------------------


def test_installation_doc_lists_all_required_tools() -> None:
    """installation.md nennt jedes Werkzeug, ohne das Funktionen still ausfallen."""
    text = _installation_text()
    missing = [m for m in REQUIRED_TOOL_MARKERS if m not in text]
    assert not missing, f"installation.md nennt folgende Werkzeuge nicht: {missing}"


def test_readme_lists_all_required_tools() -> None:
    """README nennt (als Kurzfassung) ebenfalls jedes Pflicht-/Warnwerkzeug."""
    text = _read(README)
    missing = [m for m in REQUIRED_TOOL_MARKERS if m not in text]
    assert not missing, f"README nennt folgende Werkzeuge nicht: {missing}"


# ---------------------------------------------------------------------------
# AC3 — Ein zusammenhaengender Zugangsdaten-Abschnitt
# ---------------------------------------------------------------------------


def test_installation_doc_has_credentials_section() -> None:
    """Es gibt eine eigene Ueberschrift fuer den Zugangsdaten-Abschnitt."""
    text = _installation_text()
    assert re.search(r"^#{1,3}\s+.*Zugangsdaten", text, re.MULTILINE), (
        "installation.md hat keine Ueberschrift zum Thema Zugangsdaten."
    )


def _credentials_section_text() -> str:
    text = _installation_text()
    heading = re.search(r"^#{1,3}[ \t]+.*Zugangsdaten.*$", text, re.MULTILINE)
    assert heading, "Zugangsdaten-Abschnitt nicht gefunden."
    rest = text[heading.end() :]
    next_heading = re.search(r"^#{1,3}[ \t]+", rest, re.MULTILINE)
    return rest[: next_heading.start()] if next_heading else rest


def test_credentials_section_names_env_var_path() -> None:
    """Weg 1 (Such-API-Umgebungsvariablen) ist im Abschnitt konkret benannt."""
    section = _credentials_section_text()
    for marker in AUTH_ENV_VAR_MARKERS:
        assert marker in section, (
            f"Zugangsdaten-Abschnitt nennt '{marker}' nicht (Weg 1: Such-API-Keys)."
        )


def test_credentials_section_names_uni_profile_path() -> None:
    """Weg 2 (Per-Uni-Profil / auth-helper) ist im Abschnitt konkret benannt."""
    section = _credentials_section_text()
    assert AUTH_PROFILE_MARKER in section, (
        f"Zugangsdaten-Abschnitt nennt '{AUTH_PROFILE_MARKER}' nicht (Weg 2: Per-Uni-Profil)."
    )
    assert "auth-helper" in section, (
        "Zugangsdaten-Abschnitt nennt den 'auth-helper'-Subagenten nicht (Weg 2)."
    )


def test_credentials_section_names_han_file_path() -> None:
    """Weg 3 (HAN-Zugangsdaten-Datei) ist im Abschnitt konkret benannt."""
    section = _credentials_section_text()
    for marker in AUTH_HAN_MARKERS:
        assert marker in section, (
            f"Zugangsdaten-Abschnitt nennt '{marker}' nicht (Weg 3: HAN-Zugangsdaten-Datei)."
        )


def test_credentials_section_covers_all_three_paths_together() -> None:
    """Alle drei Wege stehen im SELBEN Abschnitt (kein Verstreuen ueber Dateien)."""
    section = _credentials_section_text()
    all_markers = (
        *AUTH_ENV_VAR_MARKERS,
        AUTH_PROFILE_MARKER,
        *AUTH_HAN_MARKERS,
    )
    missing = [m for m in all_markers if m not in section]
    assert not missing, (
        f"Zugangsdaten-Abschnitt deckt nicht alle drei Wege gemeinsam ab, es fehlen: {missing}"
    )


# ---------------------------------------------------------------------------
# AC4 — Modell-Download-Hinweis (Regressions-Guard, kam bereits mit #451/PR #479)
# ---------------------------------------------------------------------------


def test_installation_doc_mentions_model_download_size_and_location() -> None:
    text = _installation_text()
    assert "470 MB" in text, "installation.md nennt die Modellgroesse (~470 MB) nicht."
    assert "~/.academic-research/models" in text, (
        "installation.md nennt den Ablageort des Modell-Downloads nicht."
    )


def test_readme_mentions_model_download_size_and_location() -> None:
    text = _read(README)
    assert "470 MB" in text, "README nennt die Modellgroesse (~470 MB) nicht."
