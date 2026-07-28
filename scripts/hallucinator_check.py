#!/usr/bin/env python3
"""Optionaler Wrapper fuer das externe CLI-Tool `hallucinator-cli` (Issue #398).

hallucinator (gianlucasb, AGPL-3.0, https://github.com/gianlucasb/hallucinator)
ist ein separates Kommandozeilen-Tool, das Literaturverzeichnisse offline gegen
seine eigenen Quellen prueft (Titel/Autor/DOI-Abgleich) und so fabrizierte
Referenzen aufspueren kann -- ergaenzend zum bestehenden verbatim-guard.

WICHTIG (AGPL-3.0-Reichweite): Dieses Modul ruft `hallucinator-cli` NUR als
externen Subprozess auf. Es importiert keinen Code aus dem hallucinator-Projekt
und vendort nichts davon in diesem Repo. Das Binary muss der Nutzer separat
installieren (z.B. `cargo install hallucinator` oder `pip install hallucinator`,
je nach Upstream-Distribution) -- es ist bewusst keine Dependency in
pyproject.toml oder scripts/requirements.txt, um das Plugin nicht versehentlich
unter AGPL-Copyleft zu stellen.

Analog zum bestehenden Wrapper-Muster in scripts/ocr.py: shutil.which-Guard,
subprocess.run(capture_output=True) ohne check=True, RuntimeError mit klarem
Installationshinweis statt Traceback.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

INSTALL_HINT = (
    "hallucinator-cli nicht gefunden. hallucinator ist ein optionales externes "
    "Tool (gianlucasb, AGPL-3.0, https://github.com/gianlucasb/hallucinator) "
    "und muss separat installiert werden, z.B. per cargo install hallucinator "
    "oder pip install hallucinator (siehe Upstream-Doku). Es wird bewusst nicht "
    "in pyproject.toml/scripts/requirements.txt gebundelt (AGPL-Copyleft)."
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
        dict wie `parse_hallucinator_output`, ergaenzt um `returncode`.

    Raises:
        RuntimeError: Wenn hallucinator-cli nicht im PATH ist.
    """
    if shutil.which("hallucinator-cli") is None:
        raise RuntimeError(INSTALL_HINT)

    cmd = ["hallucinator-cli", "check", pdf_path, *(extra_args or [])]
    result = subprocess.run(cmd, capture_output=True)

    stdout = result.stdout.decode(errors="replace")
    parsed = parse_hallucinator_output(stdout)
    parsed["returncode"] = result.returncode
    return parsed


def record_vault_decision(db_path: str, result: dict, pdf_path: str) -> None:
    """Haelt das Check-Ergebnis optional als Vault-Decision fest.

    Fehlertolerant: Ein defekter/nicht existenter Vault-Pfad darf den
    eigentlichen Check-Exit-Code niemals beeinflussen, daher wird jede
    Exception hier verschluckt (nur Best-Effort-Logging).

    Args:
        db_path: Pfad zur Vault-SQLite-DB.
        result: Rueckgabe von `run_hallucinator_check`/`parse_hallucinator_output`.
        pdf_path: Gepruefter PDF-Pfad (fuer den Decision-Text).
    """
    try:
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
    except Exception:
        # Vault-Logging ist rein optional -- ein Fehler hier darf den
        # aufrufenden Workflow nicht stoeren.
        pass


def main(argv: list[str] | None = None) -> None:
    """CLI-Entry: `python hallucinator_check.py <pdf_path> [--db <path>]`.

    Faengt RuntimeError (fehlendes Binary) ab und beendet sauber mit
    sys.exit(1) statt die Exception in den aufrufenden Workflow durchzureichen.
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
    if args.db:
        record_vault_decision(args.db, result, args.pdf_path)


if __name__ == "__main__":
    main()
