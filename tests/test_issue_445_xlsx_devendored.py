"""Regressionstests fuer Issue #445 — xlsx-Skill entvendoriert.

Der Claude-eigene Excel-Skill lag als Kopie unter ``skills/xlsx/`` im
Repository. Dessen ``LICENSE.txt`` untersagt abgeleitete Werke und die
Weitergabe an Dritte — genau das tut ein MIT-lizenziertes Marketplace-Plugin
mit 54 versionierten Dateien. Die Kopie ist entfernt; stattdessen deklariert
``.claude-plugin/plugin.json`` das Upstream-Plugin ``document-skills`` als
Abhaengigkeit.

Verifizierte Upstream-Fakten (nicht geraten, Stand 2026-07-29):
- ``gh api repos/anthropics/skills/contents/.claude-plugin/marketplace.json``
  → Marketplace ``anthropic-agent-skills``, Plugin ``document-skills``.
- ``gh api repos/anthropics/skills/tags`` → leer. Das Repository hat KEINE
  Git-Tags, und die Marketplace-Eintraege tragen kein ``version``-Feld.

Nicht CI-fahrbar und deshalb Operator-Smoke statt Test: der Laufzeitteil von
AC2/AC3 (``claude plugin list --json`` ohne ``errors``-Feld, echter
Workbook-Lauf von ``/academic-research:excel``). Im Runner ist kein Plugin
installiert.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = REPO_ROOT / ".claude-plugin" / "marketplace.json"
EXCEL_CMD = REPO_ROOT / "commands" / "excel.md"
PICKUP_CMD = REPO_ROOT / "commands" / "pickup.md"

UPSTREAM_PLUGIN = "document-skills"
UPSTREAM_MARKETPLACE = "anthropic-agent-skills"

#: Pfad der ehemaligen Vendor-Kopie, stueckweise gebaut, damit dieser Test
#: nicht selbst als Live-Referenz im Scan unten auftaucht.
VENDOR_PATH = "skills/" + "xlsx"

#: Gemeinsamer Textbaustein, der die Herkunft des Excel-Backends beschreibt.
#: Muss in beiden Command-Dateien byte-gleich stehen (AC4).
BLOCK_START = "<!-- xlsx-backend:start -->"
BLOCK_END = "<!-- xlsx-backend:end -->"

#: Historische Dokumente: dort darf der alte Pfad stehen bleiben.
HISTORY_EXEMPT = (
    "CHANGELOG.md",
    "docs/audit/",
    "docs/superpowers/",
)

SCANNED_SUFFIXES = {".py", ".md", ".json", ".toml", ".yml", ".yaml", ".sh"}
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}


def _scanned_files() -> list[Path]:
    """Alle Repo-Dateien, in denen eine Live-Referenz stehen koennte."""
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if any(part in SKIP_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        if rel.startswith(".claude/worktrees/"):
            continue
        if rel == Path(__file__).relative_to(REPO_ROOT).as_posix():
            continue
        if any(rel == exempt or rel.startswith(exempt) for exempt in HISTORY_EXEMPT):
            continue
        files.append(path)
    return files


def _backend_block(path: Path) -> str:
    """Den gemeinsamen Herkunfts-Textbaustein aus einer Command-Datei schneiden."""
    text = path.read_text(encoding="utf-8")
    assert BLOCK_START in text and BLOCK_END in text, (
        f"{path.name}: Herkunfts-Textbaustein ({BLOCK_START} … {BLOCK_END}) fehlt."
    )
    return text.split(BLOCK_START, 1)[1].split(BLOCK_END, 1)[0]


# --------------------------------------------------------------------------
# AC1 — skills/xlsx existiert nicht mehr, kein Verweis zeigt noch dorthin
# --------------------------------------------------------------------------


def test_skills_xlsx_directory_absent():
    """Die vendorierte Kopie ist aus dem Repository entfernt."""
    assert not (REPO_ROOT / "skills" / "xlsx").exists(), (
        f"{VENDOR_PATH}/ existiert noch — die proprietaere LICENSE.txt verbietet "
        "die Weitergabe in einem MIT-Plugin (Issue #445)."
    )


def test_no_live_reference_to_vendored_xlsx():
    """Kein aktiver Code/Doku-Pfad zeigt noch auf die entfernte Kopie."""
    offenders = []
    for path in _scanned_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if VENDOR_PATH in text:
            offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert not offenders, (
        f"Dateien referenzieren noch den entfernten Pfad {VENDOR_PATH}: {sorted(offenders)}"
    )


def test_no_unnamespaced_skill_permission():
    """``Skill(xlsx)`` ohne Namespace waere nach der Umstellung tot.

    Nach dem Entvendorieren heisst der Skill ``document-skills:xlsx``; eine
    ``allowed-tools``-Permission auf den nackten Namen greift nicht mehr und
    wuerde den Excel-Export stillschweigend blockieren.
    """
    pattern = re.compile(r"Skill\(\s*xlsx\s*\)")
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _scanned_files()
        if pattern.search(path.read_text(encoding="utf-8", errors="replace"))
    ]
    assert not offenders, f"Nicht-namespacierte Skill(xlsx)-Referenz in: {sorted(offenders)}"


# --------------------------------------------------------------------------
# AC2 — Dependency deklariert, frische Installation zieht sie mit
# --------------------------------------------------------------------------


def _dependencies() -> list:
    data = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
    assert "dependencies" in data, (
        ".claude-plugin/plugin.json deklariert kein 'dependencies'-Array — "
        "eine frische Installation zieht document-skills dann nicht mit."
    )
    return data["dependencies"]


def test_plugin_json_declares_document_skills_dependency():
    """AC2: document-skills steht als Cross-Marketplace-Dependency im Manifest."""
    entries = [
        d for d in _dependencies() if isinstance(d, dict) and d.get("name") == UPSTREAM_PLUGIN
    ]
    assert len(entries) == 1, (
        f"Genau ein '{UPSTREAM_PLUGIN}'-Eintrag erwartet, gefunden: {_dependencies()!r}"
    )
    assert entries[0].get("marketplace") == UPSTREAM_MARKETPLACE, (
        f"Dependency muss im Marketplace '{UPSTREAM_MARKETPLACE}' aufgeloest werden "
        f"(Upstream-Repo anthropics/skills), gefunden: {entries[0]!r}"
    )


def test_dependency_has_no_version_constraint():
    """Ein ``version``-Constraint wuerde das Plugin komplett deaktivieren.

    Versionsaufloesung laeuft laut Doku ausschliesslich ueber Git-Tags nach
    dem Muster ``{plugin-name}--v{version}``. ``anthropics/skills`` hat keine
    Tags (verifiziert via ``gh api repos/anthropics/skills/tags`` → ``[]``),
    also kann kein Constraint erfuellt werden → Fehler ``no-matching-tag``.
    """
    entry = next(
        d for d in _dependencies() if isinstance(d, dict) and d.get("name") == UPSTREAM_PLUGIN
    )
    assert "version" not in entry, (
        "Dependency darf keinen 'version'-Constraint tragen — Upstream hat keine "
        "Git-Tags, die Aufloesung liefe in 'no-matching-tag' und deaktivierte "
        "academic-research."
    )


def test_marketplace_allows_cross_marketplace_dependency():
    """Ohne Allowlist bricht die Installation mit ``cross-marketplace`` ab."""
    data = json.loads(MARKETPLACE_JSON.read_text(encoding="utf-8"))
    allowed = data.get("allowCrossMarketplaceDependenciesOn", [])
    assert UPSTREAM_MARKETPLACE in allowed, (
        "'allowCrossMarketplaceDependenciesOn' in .claude-plugin/marketplace.json "
        f"muss '{UPSTREAM_MARKETPLACE}' enthalten, sonst verweigert Claude Code die "
        f"Auto-Installation der Dependency. Gefunden: {allowed!r}"
    )


# --------------------------------------------------------------------------
# AC3 — /excel erzeugt weiterhin 4 Sheets inkl. Cluster-Farbcodierung
# --------------------------------------------------------------------------


def test_excel_command_sheet_spec_unchanged():
    """Die Sheet- und Farbspezifikation bleibt inhaltlich unangetastet."""
    text = EXCEL_CMD.read_text(encoding="utf-8")
    for sheet in ("Literaturübersicht", "Cluster-Analyse", "Kapitel-Zuordnung", "Datenblatt"):
        assert sheet in text, f"Sheet '{sheet}' fehlt in commands/excel.md."
    for mapping in ("Kern = grün", "Ergänzung = blau", "Hintergrund = grau", "Methoden = gelb"):
        assert mapping in text, f"Cluster-Farbcodierung '{mapping}' fehlt in commands/excel.md."


def test_commands_allow_namespaced_skill():
    """Ohne die Permission bricht die Excel-Generierung mit einem Tool-Fehler ab.

    Genau diesen rohen Fehler soll der Nutzer laut AC5 nicht sehen — die
    Permission muss also auf den namespacierten Skill zeigen (vgl. Issue #223).
    """
    for path in (EXCEL_CMD, PICKUP_CMD):
        text = path.read_text(encoding="utf-8")
        allowed_line = next(line for line in text.splitlines() if line.startswith("allowed-tools:"))
        assert f"Skill({UPSTREAM_PLUGIN}:xlsx)" in allowed_line, (
            f"{path.name}: allowed-tools muss 'Skill({UPSTREAM_PLUGIN}:xlsx)' "
            f"enthalten: {allowed_line!r}"
        )


# --------------------------------------------------------------------------
# AC4 — beide Commands beschreiben die Herkunft identisch und zutreffend
# --------------------------------------------------------------------------


def test_excel_and_pickup_describe_same_backend():
    """Der Herkunfts-Textbaustein ist in beiden Commands byte-gleich."""
    assert _backend_block(EXCEL_CMD) == _backend_block(PICKUP_CMD), (
        "commands/excel.md und commands/pickup.md beschreiben die Herkunft des "
        "Excel-Backends unterschiedlich."
    )


def test_backend_block_names_upstream_plugin_and_marketplace():
    """Die Beschreibung nennt Plugin UND Marketplace — sonst ist sie nicht handlungsfaehig."""
    block = _backend_block(EXCEL_CMD)
    assert f"{UPSTREAM_PLUGIN}:xlsx" in block
    assert UPSTREAM_MARKETPLACE in block
    assert "anthropics/skills" in block


def test_commands_do_not_claim_vendoring():
    """Nach dem Entvendorieren darf keine Datei mehr 'vendoriert' behaupten."""
    for path in (EXCEL_CMD, PICKUP_CMD):
        text = path.read_text(encoding="utf-8").lower()
        for claim in ("vendorier", "vendored"):
            assert claim not in text, (
                f"{path.name} behauptet weiterhin ('{claim}'), der xlsx-Skill sei "
                "im Plugin mitgeliefert."
            )


def test_pickup_no_longer_claims_openpyxl_free():
    """``/pickup`` kam nie ohne openpyxl aus — die Aussage war sachlich falsch.

    Das Upstream-Skill ``document-skills:xlsx`` fuehrt selbst Python mit
    ``openpyxl``/``pandas`` aus (SKILL.md: „pandas for data, openpyxl for
    formulas/formatting", ``from openpyxl import Workbook``). AC4 verlangt eine
    ZUTREFFENDE Beschreibung, deshalb faellt „kein openpyxl/pandas" weg.
    """
    text = PICKUP_CMD.read_text(encoding="utf-8")
    assert "kein openpyxl" not in text, (
        "commands/pickup.md behauptet weiterhin, das Excel-Backend komme ohne "
        "openpyxl aus — das Upstream-Skill nutzt openpyxl und pandas."
    )


# --------------------------------------------------------------------------
# AC5 — verstaendliche Meldung statt rohem Tool-Fehler
# --------------------------------------------------------------------------


def test_both_commands_document_recovery_path():
    """Beide Commands nennen die woertlichen Nachinstallations-Befehle."""
    for path in (EXCEL_CMD, PICKUP_CMD):
        block = _backend_block(path)
        assert "claude plugin marketplace add anthropics/skills" in block, (
            f"{path.name}: Marketplace-Befehl fehlt im Fehlerbehandlungs-Abschnitt."
        )
        assert f"claude plugin install {UPSTREAM_PLUGIN}@{UPSTREAM_MARKETPLACE}" in block, (
            f"{path.name}: Installations-Befehl fehlt im Fehlerbehandlungs-Abschnitt."
        )
        assert "keine Excel-Datei" in block, (
            f"{path.name}: Es fehlt der Hinweis, dass keine Excel-Datei erzeugt wird."
        )


def test_error_path_checks_availability_before_first_skill_call():
    """Die Pruefung steht VOR dem Skill-Aufruf — sonst sieht der Nutzer den Tool-Fehler."""
    for path in (EXCEL_CMD, PICKUP_CMD):
        block = _backend_block(path)
        assert "Vor dem ersten Skill-Aufruf" in block, (
            f"{path.name}: Der Abschnitt sagt nicht, dass die Verfuegbarkeit VOR dem "
            "ersten Skill-Aufruf geprueft wird."
        )
        assert f"Ist der Skill `{UPSTREAM_PLUGIN}:xlsx` aufrufbar?" in block, (
            f"{path.name}: Die konkrete Pruef-Frage fehlt."
        )
