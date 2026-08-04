"""audit_bibliography.py — Vollstaendigkeits-/Konsistenz-Check Zitate <-> Vault (Issue #391).

Rein lesend (AC4, Plan-Risiko #3): importiert ausschliesslich lesende
Vault-Funktionen aus dem latex-export-Geschwisterskill --
`get_all_papers()` -- und den Kapitel-Resolver aus demselben Skill
(`resolve_chapters()`). Keine `add_*`/`update_*`/`lock_*`/`restore_*`/
`supersede_*`/`set_*`-Aufrufe, kein Schreibzugriff auf Vault oder
Kapiteldateien.

Zitierkonvention (Plan-Abweichung vom Issue-Wortlaut, siehe Plan-Kommentar
<!-- plan:v1 --> zu Issue #391): geprueft wird `\\cite{key}` (und Varianten
aus `LATEX_CITATION_COMMANDS`), NICHT freie "Autor/Jahr"-Prosa -- das ist die
tatsaechliche In-Text-Zitierkonvention dieses Repos (`kapitel/*.md`, Issue
#386), siehe `skills/word-export/scripts/collect_references.py`. Die
Kommandoliste wird importiert statt kopiert, damit sie nicht lautlos von
`render_tex.py`/`collect_references.py` auseinanderdriftet.

Prinzip-Katalog-Herkunft (Kategorie E3 "Bibliography Hygiene"):
https://github.com/andrehuang/academic-writing-agents (MIT-Lizenz).

Oeffentliche API:
  extract_cited_keys(chapters: list[Path]) -> set[str]
  audit_bibliography(kapitel_dir, selector, vault_db_path) -> dict
  main(argv) -> int
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Geschwister-Skill latex-export liefert Kapitel-Resolver + Vault-Query +
# die Zitationskommando-Allowlist. Import statt Kopie ist hartes Muss (siehe
# Modul-Docstring und das etablierte Muster in
# skills/word-export/scripts/collect_references.py).
_SKILLS_ROOT = Path(__file__).resolve().parent.parent.parent
_PLUGIN_ROOT = _SKILLS_ROOT.parent
_LATEX_EXPORT_SCRIPTS = _SKILLS_ROOT / "latex-export" / "scripts"
if str(_LATEX_EXPORT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LATEX_EXPORT_SCRIPTS))
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from build_bib import get_all_papers  # noqa: E402  (bewusster Re-Export, nur lesend)
from export_thesis import ChapterResolutionError, resolve_chapters  # noqa: E402
from render_tex import LATEX_CITATION_COMMANDS  # noqa: E402

DEFAULT_KAPITEL_DIR = "kapitel"

__all__ = [
    "extract_cited_keys",
    "audit_bibliography",
    "ChapterResolutionError",
]

# Gleiches Muster wie collect_references._CITE_MARKER_RE: die
# Kommando-Allowlist ist IMPORTIERT (LATEX_CITATION_COMMANDS), nur das
# Regex-Zusammensetzen selbst ist Glue-Code, kein zweiter Allowlist-Nachbau.
_CITE_MARKER_RE = re.compile(
    r"\\(?:" + "|".join(LATEX_CITATION_COMMANDS) + r")\*?(?:\[[^\[\]]*\])*\{([^{}]+)\}"
)


def extract_cited_keys(chapters: list[Path]) -> set[str]:
    """Sammelt alle `\\cite{key}`-Keys (und Mehrfachzitate) aus den Kapiteln.

    `\\cite{a,b}` liefert beide Keys einzeln -- gueltiges BibTeX/biblatex und
    real in kapitel/*.md vorhanden (Issue #386, siehe collect_references.py).
    """
    keys: set[str] = set()
    for chapter in chapters:
        text = chapter.read_text(encoding="utf-8")
        for match in _CITE_MARKER_RE.finditer(text):
            for raw_key in match.group(1).split(","):
                key = raw_key.strip()
                if key:
                    keys.add(key)
    return keys


def audit_bibliography(
    kapitel_dir: Path | str,
    selector: str,
    vault_db_path: str,
) -> dict:
    """Vergleicht In-Text-Zitate (Kapitel) gegen Vault-Paper-Menge.

    Liefert:
      missing_in_bibliography -- im Text zitierte Keys ohne Vault-Paper
                                  (sortierte Liste, AC2)
      orphaned_entries        -- Vault-Paper-IDs, die in keinem Kapitel
                                  zitiert werden (sortierte Liste, AC3)
      cited_count / paper_count -- Kennzahlen fuer den Klartext-Report
    """
    chapters = resolve_chapters(kapitel_dir, selector)
    cited_keys = extract_cited_keys(chapters)

    papers = get_all_papers(vault_db_path)
    paper_ids = {p.get("paper_id") for p in papers if p.get("paper_id")}

    missing = sorted(cited_keys - paper_ids)
    orphaned = sorted(paper_ids - cited_keys)

    return {
        "missing_in_bibliography": missing,
        "orphaned_entries": orphaned,
        "cited_count": len(cited_keys),
        "paper_count": len(paper_ids),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _resolve_vault_db_path(explicit: str | None) -> str:
    """Kanonischer Vault-Pfad -- identische Quelle wie latex-/word-export."""
    if explicit:
        return explicit
    from academic_vault.db import default_db_path

    return default_db_path()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prueft Literaturverzeichnis-Vollstaendigkeit/-Konsistenz zwischen "
            "kapitel/*.md-Zitaten und dem Vault (Issue #391). Rein lesend."
        ),
    )
    parser.add_argument("--kapitel", required=True, help="Kapitel-Nummer oder 'all'")
    parser.add_argument("--kapitel-dir", default=DEFAULT_KAPITEL_DIR)
    parser.add_argument(
        "--vault-db",
        default=None,
        help="Vault-Pfad (Default: academic_vault.db.default_db_path())",
    )
    parser.add_argument(
        "--json",
        default=None,
        help="Optional: Zieldatei fuer den JSON-Report (zusaetzlich zum Klartext-Report)",
    )
    return parser


def _format_report(result: dict) -> str:
    lines = [
        f"Geprueft: {result['cited_count']} zitierte Keys, {result['paper_count']} Vault-Paper.",
    ]
    if result["missing_in_bibliography"]:
        lines.append("Fehlend im Verzeichnis (zitiert, aber kein Vault-Paper):")
        lines += [f"  - {key}" for key in result["missing_in_bibliography"]]
    else:
        lines.append("Keine fehlenden Verzeichniseintraege.")

    if result["orphaned_entries"]:
        lines.append("Verwaiste Eintraege (im Vault, aber nirgends zitiert):")
        lines += [f"  - {key}" for key in result["orphaned_entries"]]
    else:
        lines.append("Keine verwaisten Eintraege.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    try:
        vault_db_path = _resolve_vault_db_path(args.vault_db)
        result = audit_bibliography(args.kapitel_dir, args.kapitel, vault_db_path)
    except ChapterResolutionError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    except ImportError as exc:
        print(
            f"FEHLER: Vault-Modul 'academic_vault' nicht ladbar ({exc}). "
            "Plugin-Installation pruefen (scripts/setup.sh).",
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    print(_format_report(result))

    if args.json:
        json_path = Path(args.json)
        if json_path.parent != Path(""):
            json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
