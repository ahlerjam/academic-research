"""Zentrale Pfade der Dokumentations-Oberflaeche (Issue #402).

Mit dem README-Relaunch wandert die Langreferenz aus der README nach ``docs/``.
Die bestehenden Drift-Guards (Skills-Tabelle, MCP-Tools, Commands, Glossar,
Hooks, Uni-Profile) pruefen weiterhin dieselben Inhalte — nur eben an der neuen
Stelle. Damit diese Stelle genau EINMAL im Testbaum steht und ein spaeterer
Umzug nicht wieder ein Dutzend Dateien anfasst, sind die Pfade hier gebuendelt.

``DOC_SURFACE`` ist die Menge aller Nutzerdoku-Dateien (README + docs/). Sie
dient Guards, die nur "irgendwo dokumentiert" verlangen (z. B. keine
Title-Case-Skillnamen in Prosa).
"""

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
WALKTHROUGH_DOC = GUIDE_DIR / "walkthrough.md"
TROUBLESHOOTING_DOC = GUIDE_DIR / "troubleshooting.md"

DEVELOPMENT_DOC = DOCS_DIR / "development.md"
QUICKSTART_PROTOCOL_DOC = DOCS_DIR / "quickstart-protocol.md"

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
    WALKTHROUGH_DOC,
    TROUBLESHOOTING_DOC,
    DEVELOPMENT_DOC,
    QUICKSTART_PROTOCOL_DOC,
)


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
