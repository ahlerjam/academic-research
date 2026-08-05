"""Zentrale Pfade der Dokumentations-Oberflaeche (Issue #402).

Mit dem README-Relaunch wandert die Langreferenz aus der README nach ``docs/``.
Die bestehenden Drift-Guards (Skills-Tabelle, MCP-Tools, Commands, Glossar,
Hooks, Uni-Profile) pruefen weiterhin dieselben Inhalte — nur eben an der neuen
Stelle. Damit diese Stelle genau EINMAL im Testbaum steht und ein spaeterer
Umzug nicht wieder ein Dutzend Dateien anfasst, sind die Pfade hier gebuendelt.

``DOC_SURFACE`` ist die Menge aller Nutzerdoku-Dateien (README + docs/). Sie
dient Guards, die nur "irgendwo dokumentiert" verlangen (z. B. keine
Title-Case-Skillnamen in Prosa).

Seit Issue #452 kommt die Navigationsschicht dazu: ``INDEX`` (die Einstiegsseite
``docs/README.md``), ``structured_pages()`` (Seiten mit einheitlicher
Grundstruktur) und ``historical_docs()`` (historische Dokumente und
Momentaufnahmen). Beide Listen werden aus ``git ls-files docs`` abgeleitet und
nicht gepflegt — eine neue Seite faellt automatisch in die passende Klasse.
"""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

README = REPO_ROOT / "README.md"
DOCS_DIR = REPO_ROOT / "docs"

# Referenz-Dokumente (ausgelagerte Langreferenz).
REFERENCE_DIR = DOCS_DIR / "reference"
SKILLS_DOC = REFERENCE_DIR / "skills.md"
AGENTS_DOC = REFERENCE_DIR / "agents.md"
COMMANDS_DOC = REFERENCE_DIR / "commands.md"
VAULT_DOC = REFERENCE_DIR / "vault.md"
HOOKS_DOC = REFERENCE_DIR / "hooks.md"
SEARCH_DOC = REFERENCE_DIR / "search.md"
UNI_PROFILES_DOC = REFERENCE_DIR / "uni-profiles.md"
GLOSSARY_DOC = REFERENCE_DIR / "glossary.md"

# Anleitungen.
GUIDE_DIR = DOCS_DIR / "guide"
INSTALLATION_DOC = GUIDE_DIR / "installation.md"
GETTING_STARTED_DOC = GUIDE_DIR / "getting-started.md"
WALKTHROUGH_DOC = GUIDE_DIR / "walkthrough.md"
MODEL_CHOICE_DOC = GUIDE_DIR / "model-choice.md"
TOKEN_BUDGET_DOC = GUIDE_DIR / "token-budget.md"
BEST_PRACTICES_DOC = GUIDE_DIR / "best-practices.md"
TROUBLESHOOTING_DOC = GUIDE_DIR / "troubleshooting.md"

#: Eigenstaendiges Grenzen-Dokument (Issue #637) — was das Plugin nicht kann,
#: nicht darf und nicht prueft, herausgeloest aus best-practices.md.
LIMITS_DOC = GUIDE_DIR / "limits.md"

#: Einstieg nach Vorhaben statt nach Komponenten (Issue #611).
PROJECT_PATHS_DOC = GUIDE_DIR / "project-paths.md"

#: Die Seiten des Praxis-Leitfadens (Issue #461) — untereinander verlinkt.
PRACTICE_GUIDE_DOCS = (
    GETTING_STARTED_DOC,
    WALKTHROUGH_DOC,
    MODEL_CHOICE_DOC,
    TOKEN_BUDGET_DOC,
    BEST_PRACTICES_DOC,
    LIMITS_DOC,
)

DEVELOPMENT_DOC = DOCS_DIR / "development.md"
QUICKSTART_PROTOCOL_DOC = DOCS_DIR / "quickstart-protocol.md"

#: Regeldokument fuer Ton und Glossar-Pflicht (Issue #634).
STYLE_GUIDE_DOC = DOCS_DIR / "style-guide.md"

#: Der "Einstiegspfad" (Issue #634): die Seiten unter "Ich fange gerade an" in
#: der Doku-Uebersicht, in genau der dort vorgegebenen Lesereihenfolge. Neue
#: Fachbegriffe muessen hier beim ersten Gebrauch erklaert sein oder im
#: Glossar stehen.
ENTRY_PATH_DOCS = (
    GETTING_STARTED_DOC,
    INSTALLATION_DOC,
    WALKTHROUGH_DOC,
    TROUBLESHOOTING_DOC,
    QUICKSTART_PROTOCOL_DOC,
)

#: Alle Referenz-/Guide-Dokumente, die die README verlinken muss.
LINKED_DOCS = (
    SKILLS_DOC,
    AGENTS_DOC,
    COMMANDS_DOC,
    VAULT_DOC,
    HOOKS_DOC,
    SEARCH_DOC,
    UNI_PROFILES_DOC,
    GLOSSARY_DOC,
    INSTALLATION_DOC,
    GETTING_STARTED_DOC,
    WALKTHROUGH_DOC,
    MODEL_CHOICE_DOC,
    TOKEN_BUDGET_DOC,
    BEST_PRACTICES_DOC,
    LIMITS_DOC,
    TROUBLESHOOTING_DOC,
    PROJECT_PATHS_DOC,
    DEVELOPMENT_DOC,
    QUICKSTART_PROTOCOL_DOC,
)


#: Einstiegsseite der Dokumentation (Issue #452).
INDEX = DOCS_DIR / "README.md"

#: Weitere Seiten, die die Einstiegsseite fuehrt, aber die README nicht verlinkt.
SKIP_REASONS_DOC = DOCS_DIR / "SKIP_REASONS.md"
LITERATURE_STATE_DOC = DOCS_DIR / "literature-state-schema.md"
NOTEBOOK_BUNDLE_DOC = DOCS_DIR / "skills" / "notebook-bundle.md"
EVALS_INDEX_DOC = DOCS_DIR / "evals" / "README.md"
EVAL_STRATEGY_DOC = DOCS_DIR / "evals" / "STRATEGY.md"
EVAL_TEMPLATE_DOC = DOCS_DIR / "evals" / "TEMPLATE.md"
SUPERPOWERS_INDEX_DOC = DOCS_DIR / "superpowers" / "README.md"

#: Linktext des Breadcrumbs, der jede Seite zur Einstiegsseite zurueckfuehrt.
BREADCRUMB_TEXT = "← Doku-Übersicht"

#: Kennzeichnung am Seitenanfang historischer Dokumente / Momentaufnahmen.
HISTORICAL_MARKER = "Historisches Dokument"

#: Ueberschrift, unter der die Einstiegsseite historische Dokumente sammelt.
HISTORICAL_SECTION = "Historisches und Momentaufnahmen"

#: Ueberschrift des `.claude/`-Abschnitts in docs/development.md.
CLAUDE_DIR_SECTION = "Versionierte `.claude/`-Dateien"

#: Dateien unter docs/evals/, die aktueller Sollzustand sind (keine Reports).
_CURRENT_EVAL_DOCS = {"README.md", "STRATEGY.md", "TEMPLATE.md"}

#: Dateien, die bewusst keiner Seitenstruktur folgen (Vorlage zum Kopieren).
_LAYOUT_EXEMPT = {EVAL_TEMPLATE_DOC}


def _git_ls_files(*patterns: str) -> list[Path]:
    """Repo-Pfade zu den Patterns: bereits getrackt oder neu und nicht ignoriert.

    ``--others --exclude-standard`` nimmt neue, noch nicht committete Dateien mit
    — sonst pruefte kein Guard eine gerade angelegte Seite, und der Fehler faende
    sich erst in CI. Ignorierte Pfade bleiben aussen vor: ``docs/superpowers/plans/``
    und ``docs/superpowers/specs/`` liegen lokal, gehoeren aber nicht zur
    ausgelieferten Doku.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", *patterns],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted({REPO_ROOT / rel for rel in out.split("\0") if rel})


def repo_docs() -> list[Path]:
    """Alle zum Repo gehoerenden Dateien unter docs/ (inkl. assets/)."""
    return _git_ls_files("docs")


def repo_markdown() -> list[Path]:
    """Alle Markdown-Dateien des Repos — Quelle eingehender Links."""
    return _git_ls_files("*.md")


def committed_paths(*patterns: str) -> list[str]:
    """Nur bereits committete Pfade — fuer Aussagen ueber den Versionsstand."""
    out = subprocess.run(
        ["git", "ls-files", "-z", *patterns],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(rel for rel in out.split("\0") if rel)


def is_historical(path: Path) -> bool:
    """True fuer historische Planungsdokumente und Eval-Momentaufnahmen."""
    rel = path.relative_to(DOCS_DIR)
    if not rel.parts:
        return False
    top = rel.parts[0]
    if top in {"superpowers", "audit"}:
        return True
    return top == "evals" and rel.name not in _CURRENT_EVAL_DOCS


def historical_docs() -> list[Path]:
    """Dokumente, die eine Kennzeichnung am Seitenanfang brauchen."""
    return [p for p in repo_docs() if p.suffix == ".md" and is_historical(p)]


def structured_pages() -> list[Path]:
    """Seiten, die der einheitlichen Grundstruktur folgen muessen.

    Ausgenommen sind die Einstiegsseite selbst, historische Dokumente (sie
    tragen stattdessen den Marker) und die Eval-Report-Vorlage.
    """
    return [
        p
        for p in repo_docs()
        if p.suffix == ".md" and p != INDEX and not is_historical(p) and p not in _LAYOUT_EXEMPT
    ]


def doc_surface() -> list[Path]:
    """README + alle Markdown-Dateien unter docs/ (ohne historische Ordner)."""
    excluded = {"superpowers", "audit", "evals"}
    files = [README]
    for path in sorted(DOCS_DIR.rglob("*.md")):
        rel = path.relative_to(DOCS_DIR)
        if rel.parts and rel.parts[0] in excluded:
            continue
        files.append(path)
    return files


def read_surface() -> str:
    """Gesamter Text der Doku-Oberflaeche, fuer 'irgendwo dokumentiert'-Guards."""
    return "\n".join(p.read_text(encoding="utf-8") for p in doc_surface() if p.exists())


# ---------------------------------------------------------------------------
# Komponenten-Inventar (Issue #640)
# ---------------------------------------------------------------------------

SKILLS_DIR = REPO_ROOT / "skills"
AGENTS_DIR = REPO_ROOT / "agents"
COMMANDS_DIR = REPO_ROOT / "commands"
VAULT_PACKAGE = REPO_ROOT / "academic_vault"

#: Kein eigenstaendiger Skill, nur geteilte Markdown-Fragmente.
_NON_SKILL_DIRS = {"_common"}

#: Registrierte MCP-Tools erkennt man am Dekorator, nicht an einer Liste.
_MCP_TOOL_RE = re.compile(r'@mcp\.tool\(name="(vault\.[a-z_]+)"\)')


def component_inventory() -> dict[str, set[str]]:
    """Die vier Komponentenmengen des Plugins — aus dem Code, nicht aus Doku.

    Genau eine Stelle im Testbaum zaehlt Skills, Agents, Commands und
    MCP-Tools aus. Jeder Guard, der Vollstaendigkeit oder eine Zahlenangabe
    prueft, fragt hier — sonst pruefte eine Doku-Stelle gegen die naechste
    und beide drifteten gemeinsam ab (Issue #640).
    """
    tool_source = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(VAULT_PACKAGE.glob("*.py"))
    )
    return {
        "skills": {
            p.parent.name
            for p in SKILLS_DIR.glob("*/SKILL.md")
            if p.parent.name not in _NON_SKILL_DIRS
        },
        "agents": {p.stem for p in AGENTS_DIR.glob("*.md")},
        "commands": {p.stem for p in COMMANDS_DIR.glob("*.md")},
        "mcp_tools": set(_MCP_TOOL_RE.findall(tool_source)),
    }
