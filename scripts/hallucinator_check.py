#!/usr/bin/env python3
"""Optionaler Wrapper fuer das externe CLI-Tool `hallucinator-cli` (Issue #398).

hallucinator (gianlucasb, AGPL-3.0, https://github.com/gianlucasb/hallucinator)
ist ein separates Kommandozeilen-Tool, das Literaturverzeichnisse offline gegen
seine eigenen Quellen prueft (Titel/Autor/DOI-Abgleich) und so fabrizierte
Referenzen aufspueren kann -- ergaenzend zum bestehenden verbatim-guard.

WICHTIG (AGPL-3.0-Reichweite): Dieses Modul ruft `hallucinator-cli` NUR als
externen Subprozess auf. Es importiert keinen Code aus dem hallucinator-Projekt
und vendort nichts davon in diesem Repo. Das Binary muss der Nutzer separat
installieren -- laut Upstream-README ausschliesslich per Installer-Skript
(`curl -sSf https://hallucinator.science/install-cli.sh | sh`).

Zwei naheliegende Wege liefern das Binary NACHWEISLICH NICHT und werden hier
deshalb bewusst nicht genannt: Auf crates.io existiert kein Crate
`hallucinator` (API-Abfrage -> HTTP 404), und das gleichnamige PyPI-Paket
enthaelt nur die PyO3-Python-Bindings (Modul `hallucinator`) -- seine Wheels
fuehren weder entry_points noch ein scripts/-Verzeichnis und legen damit kein
ausfuehrbares `hallucinator-cli` im PATH ab. Der shutil.which-Guard unten
wuerde nach so einer Installation unveraendert greifen.

hallucinator ist bewusst keine Dependency in pyproject.toml oder
scripts/requirements.txt, um das Plugin nicht versehentlich unter
AGPL-Copyleft zu stellen.

Analog zum bestehenden Wrapper-Muster in scripts/ocr.py: shutil.which-Guard,
subprocess.run(capture_output=True) ohne check=True, RuntimeError mit klarem
Installationshinweis statt Traceback.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Repo-Root, NICHT automatisch auf sys.path: bei direktem Skriptaufruf
# (`python scripts/hallucinator_check.py ...`, auch via `uv run`) setzt Python
# sys.path[0] auf das Skriptverzeichnis (scripts/), nicht auf das Repo-Root.
# `academic_vault` liegt eine Ebene hoeher und ist unter dieser Invokation ohne
# expliziten sys.path-Eintrag NICHT importierbar -- siehe record_vault_decision.
REPO_ROOT = Path(__file__).resolve().parents[1]

INSTALL_HINT = (
    "hallucinator-cli nicht gefunden. hallucinator ist ein optionales externes "
    "Tool (gianlucasb, AGPL-3.0, https://github.com/gianlucasb/hallucinator) "
    "und muss separat installiert werden -- laut Upstream-README ausschliesslich "
    "per Installer-Skript: "
    "'curl -sSf https://hallucinator.science/install-cli.sh | sh'. "
    "Nicht ausreichend: Das PyPI-Paket 'hallucinator' enthaelt nur die "
    "Python-Bindings und legt kein CLI-Binary im PATH ab; ein Crate "
    "'hallucinator' existiert auf crates.io nicht. "
    "Es wird bewusst nicht in pyproject.toml/scripts/requirements.txt "
    "gebundelt (AGPL-Copyleft)."
)

# Bekannte Status-Kategorien aus der hallucinator-cli-Textausgabe.
_STATUS_KEYS = {
    "Verified (Web Search)": "verified_web_search",
    "Author Mismatch": "author_mismatch",
    "Not Found": "not_found",
    "Verified": "verified",
}


def parse_hallucinator_output(stdout: str) -> dict:
    """Parst die zeilenbasierte Textausgabe von `hallucinator-cli check`.

    Es gibt kein dokumentiertes strukturiertes Ausgabeformat (kein --json),
    daher werden die vier bekannten Status-Kategorien defensiv gezaehlt und
    der Rohtext immer mitgefuehrt, damit bei Upstream-Formataenderungen
    nichts verloren geht.

    Args:
        stdout: Dekodierte Standardausgabe von hallucinator-cli.

    Returns:
        dict mit den Zaehlern `verified`, `author_mismatch`, `not_found`,
        `verified_web_search` sowie `raw_output` (unveraendeter Text).
    """
    counts = {
        "verified": 0,
        "author_mismatch": 0,
        "not_found": 0,
        "verified_web_search": 0,
    }
    for line in stdout.splitlines():
        # Reihenfolge wichtig: "Verified (Web Search)" enthaelt "Verified",
        # daher zuerst die spezifischeren Kategorien pruefen.
        for label, key in _STATUS_KEYS.items():
            if label in line:
                counts[key] += 1
                break
    return {**counts, "raw_output": stdout}


def run_hallucinator_check(pdf_path: str, extra_args: list[str] | None = None) -> dict:
    """Fuehrt `hallucinator-cli check <pdf_path>` als Subprozess aus.

    Prueft via shutil.which, ob das Binary im PATH vorhanden ist. Wertet den
    Exit-Code selbst aus (kein check=True), damit ein Nicht-Null-Exit nicht
    unnoetig zusaetzlich als CalledProcessError durchschlaegt.

    Args:
        pdf_path: Pfad zum zu pruefenden PDF (Literaturverzeichnis).
        extra_args: Optionale zusaetzliche CLI-Argumente.

    Returns:
        dict wie `parse_hallucinator_output`, ergaenzt um `returncode` und
        `stderr` (dekodierte Standardfehlerausgabe von hallucinator-cli).

    Raises:
        RuntimeError: Wenn hallucinator-cli nicht im PATH ist.
    """
    if shutil.which("hallucinator-cli") is None:
        raise RuntimeError(INSTALL_HINT)

    cmd = ["hallucinator-cli", "check", pdf_path, *(extra_args or [])]
    result = subprocess.run(cmd, capture_output=True)

    stdout = result.stdout.decode(errors="replace")
    stderr = result.stderr.decode(errors="replace")
    parsed = parse_hallucinator_output(stdout)
    parsed["returncode"] = result.returncode
    parsed["stderr"] = stderr
    return parsed


def record_vault_decision(db_path: str, result: dict, pdf_path: str) -> None:
    """Haelt das Check-Ergebnis optional als Vault-Decision fest.

    Fehlertolerant: Ein defekter/nicht existenter Vault-Pfad darf den
    eigentlichen Check-Exit-Code niemals beeinflussen, daher wird jede
    Exception hier abgefangen und nur als Warnung auf stderr ausgegeben
    (Best-Effort-Logging) -- nie stillschweigend verschluckt und nie an den
    aufrufenden Workflow durchgereicht.

    Args:
        db_path: Pfad zur Vault-SQLite-DB.
        result: Rueckgabe von `run_hallucinator_check`/`parse_hallucinator_output`.
        pdf_path: Gepruefter PDF-Pfad (fuer den Decision-Text).
    """
    try:
        # sys.path-Fix (siehe REPO_ROOT-Kommentar oben): ohne diesen Eintrag
        # scheitert der Import bei direktem Skriptaufruf mit ModuleNotFoundError,
        # weil sys.path[0] dann auf scripts/ zeigt, nicht auf das Repo-Root.
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from academic_vault.server import add_decision

        text = (
            f"hallucinator-check fuer {pdf_path}: "
            f"verified={result.get('verified', 0)}, "
            f"author_mismatch={result.get('author_mismatch', 0)}, "
            f"not_found={result.get('not_found', 0)}, "
            f"verified_web_search={result.get('verified_web_search', 0)}"
        )
        add_decision(
            db_path,
            category="hallucinator-check",
            text=text,
            rationale="Offline-Referenzcheck via externes hallucinator-cli-Tool.",
        )
    except Exception as exc:
        # Vault-Logging ist rein optional -- ein Fehler hier darf den
        # aufrufenden Workflow nicht stoeren, aber er darf auch nicht spurlos
        # verschwinden (sonst wirkt --db wirkungslos, ohne dass das auffaellt).
        print(
            f"[hallucinator-check] Vault-Decision konnte nicht angelegt werden "
            f"({type(exc).__name__}: {exc}). Check-Ergebnis bleibt davon unberuehrt.",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> None:
    """CLI-Entry: `python hallucinator_check.py <pdf_path> [--db <path>]`.

    Faengt RuntimeError (fehlendes Binary) ab und beendet sauber mit
    sys.exit(1) statt die Exception in den aufrufenden Workflow durchzureichen.

    Der Exit-Code von hallucinator-cli selbst wird durchgereicht (Nicht-Null
    Exit -> main() beendet ebenfalls nicht-null) und dessen stderr wird
    ausgegeben statt verworfen -- ein fehlgeschlagener hallucinator-cli-Lauf
    darf nicht wie ein erfolgreicher aussehen.
    """
    parser = argparse.ArgumentParser(
        description="Optionaler Offline-Referenzcheck via externes hallucinator-cli-Tool."
    )
    parser.add_argument("pdf_path", help="Pfad zum zu pruefenden PDF")
    parser.add_argument("--db", default=None, help="Optionaler Pfad zur Vault-SQLite-DB")
    args = parser.parse_args(argv)

    try:
        result = run_hallucinator_check(args.pdf_path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    print(result["raw_output"])
    stderr_text = result.get("stderr", "")
    if stderr_text:
        print(stderr_text, file=sys.stderr, end="" if stderr_text.endswith("\n") else "\n")
    if args.db:
        record_vault_decision(args.db, result, args.pdf_path)

    returncode = result.get("returncode", 0)
    if returncode != 0:
        sys.exit(returncode)


if __name__ == "__main__":
    main()
