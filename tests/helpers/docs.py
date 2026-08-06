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
TROUBLESHOOTING_DOC = GUIDE_DIR / "troubleshooting.md"

#: Bedienung des Plugins an einer Stelle (Issue #638): Command/Skill/Agent,
#: Modellwahl, Sitzungsfuehrung, Kostenhebel, Umgang mit erfundenen Angaben.
#: Loest ``model-choice.md``, ``token-budget.md`` und ``best-practices.md`` ab —
#: deren Zusicherungen gelten unveraendert weiter, nur gegen diese Datei. Die
#: drei alten Namen bleiben als Alias bestehen, damit kein Guard, der eine
#: bestimmte Aussage gepachtet hat, beim Umzug still verschwindet.
WORKING_WITH_CLAUDE_CODE_DOC = GUIDE_DIR / "working-with-claude-code.md"
MODEL_CHOICE_DOC = WORKING_WITH_CLAUDE_CODE_DOC
TOKEN_BUDGET_DOC = WORKING_WITH_CLAUDE_CODE_DOC
BEST_PRACTICES_DOC = WORKING_WITH_CLAUDE_CODE_DOC

#: Eigenstaendiges Grenzen-Dokument (Issue #637) — was das Plugin nicht kann,
#: nicht darf und nicht prueft, herausgeloest aus best-practices.md.
LIMITS_DOC = GUIDE_DIR / "limits.md"

#: Einstieg nach Vorhaben statt nach Komponenten (Issue #611).
PROJECT_PATHS_DOC = GUIDE_DIR / "project-paths.md"

#: Die Seiten des Praxis-Leitfadens (Issue #461) — untereinander verlinkt.
#: Seit #638 sind es vier statt sechs: Modellwahl, Token-Budget und bewaehrtes
#: Vorgehen stehen zusammen in ``working-with-claude-code.md``.
PRACTICE_GUIDE_DOCS = (
    GETTING_STARTED_DOC,
    WALKTHROUGH_DOC,
    WORKING_WITH_CLAUDE_CODE_DOC,
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
    WORKING_WITH_CLAUDE_CODE_DOC,
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
    sich erst in CI. Ignorierte Pfade bleiben aussen vor: was ``.gitignore``
    ausschliesst, gehoert nicht zur ausgelieferten Doku.
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
    if top == "audit":
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
    """README + alle Markdown-Dateien unter docs/ (ohne historische Ordner).

    Quelle ist ``repo_docs()`` und damit ``git ls-files``, nicht ``rglob``: Was
    ``.gitignore`` ausschliesst, gehoert nicht zur ausgelieferten Doku und darf
    keinen Guard ueber die Doku-Oberflaeche ausloesen. Ein lokal liegender
    Ordner mit fremden Markdown-Dateien haette sonst die Zahlen- und
    Pfad-Guards rot gefaerbt, ohne dass eine ausgelieferte Seite falsch ist.
    """
    excluded = {"audit", "evals"}
    files = [README]
    for path in repo_docs():
        if path.suffix != ".md":
            continue
        rel = path.relative_to(DOCS_DIR)
        if rel.parts and rel.parts[0] in excluded:
            continue
        files.append(path)
    return files


def read_surface() -> str:
    """Gesamter Text der Doku-Oberflaeche, fuer 'irgendwo dokumentiert'-Guards."""
    return "\n".join(p.read_text(encoding="utf-8") for p in doc_surface() if p.exists())
