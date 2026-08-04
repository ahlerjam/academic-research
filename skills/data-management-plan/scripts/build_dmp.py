"""build_dmp.py — Datenmanagementplan Build-Script (Issue #609).

Liest den Vault-Bestand read-only aus (Paper nach Herkunftsart, Transkript-
segmente, Kodierungen) und erzeugt oder aktualisiert ein Datenmanagementplan-
Dokument mit fester Gliederung. Unentschiedene, projektspezifische Punkte
(Speicherort, Repository-Wahl, zustaendige Person, ...) werden nicht erfunden,
sondern als ``[OFFEN: ...]``-Marker geschrieben.

Idempotenz: Existiert die Ausgabedatei bereits, werden nur das
"Zuletzt aktualisiert"-Datum und der "## Ausgangslage im Vault"-Block ersetzt
-- alle anderen Abschnitte (in denen der User zwischenzeitlich [OFFEN: ...]
durch echte Entscheidungen ersetzt haben kann) bleiben unangetastet. Existiert
die Datei noch nicht, wird das vollstaendige Dokument neu erzeugt.

Aufruf:
    python skills/data-management-plan/scripts/build_dmp.py \\
        --db vault.db \\
        --slug mein-projekt \\
        --output datenmanagementplan.md
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from academic_vault import server as vault_server  # noqa: E402
from academic_vault.db import VaultDB  # noqa: E402

_AUSGANGSLAGE_HEADING = "## Ausgangslage im Vault"
_DATE_LABEL = "**Zuletzt aktualisiert:**"

_DATE_LINE_RE = re.compile(rf"^{re.escape(_DATE_LABEL)} .*$", re.M)
_AUSGANGSLAGE_BLOCK_RE = re.compile(rf"{re.escape(_AUSGANGSLAGE_HEADING)}\n.*?(?=\n## |\Z)", re.S)


def _offen(text: str) -> str:
    """Markiert einen unentschiedenen Punkt statt ihn plausibel zu erfinden."""
    return f"[OFFEN: {text}]"


def _aggregate_vault(db_path: str) -> dict:
    """Liest den Vault-Bestand read-only aus (kein Schreibzugriff).

    Prueft die DB-Existenz VOR ``_ensure_schema_for_read()``: dieser legt bei
    fehlender Datei sonst still eine leere DB an (``VaultDB._open()`` ->
    ``parent.mkdir()`` + ``sqlite3.connect``), und ein Tippfehler im
    ``--db``-Pfad wuerde als "0 Paper/Segmente/Kodierungen" gemeldet -- ein
    erfundener Bestand statt des dokumentierten FEHLER-Pfads (Issue #609,
    Code-Review-Fund P1).
    """
    if not Path(db_path).exists():
        raise FileNotFoundError(f"Vault-DB nicht gefunden: {db_path}")
    vault_server._ensure_schema_for_read(db_path)
    conn = VaultDB._open(db_path)
    try:
        total_papers = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        literature_papers = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE source_kind = 'literature'"
        ).fetchone()[0]
        primary_papers = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE source_kind = 'primary'"
        ).fetchone()[0]
        segment_count = conn.execute("SELECT COUNT(*) FROM transcript_segments").fetchone()[0]
        segment_paper_count = conn.execute(
            "SELECT COUNT(DISTINCT paper_id) FROM transcript_segments"
        ).fetchone()[0]
    finally:
        conn.close()
    coding_count = len(vault_server.list_codings(db_path, paper_id=None))
    return {
        "total_papers": total_papers,
        "literature_papers": literature_papers,
        "primary_papers": primary_papers,
        "segment_count": segment_count,
        "segment_paper_count": segment_paper_count,
        "coding_count": coding_count,
    }


def _render_ausgangslage(vault: dict) -> str:
    return (
        f"{_AUSGANGSLAGE_HEADING}\n\n"
        "Der Vault enthält zum Zeitpunkt dieser Aktualisierung:\n\n"
        f"- **{vault['total_papers']} Paper/Quellen** insgesamt, davon "
        f"**{vault['literature_papers']} Literatur** und "
        f"**{vault['primary_papers']} eigenes Erhebungsmaterial** "
        "(Transkripte, Beobachtungsprotokolle o. ä.)\n"
        f"- **{vault['segment_count']} Transkriptsegmente** über "
        f"**{vault['segment_paper_count']} Materialien**\n"
        f"- **{vault['coding_count']} Kodierungen** (Kategorienzuordnungen)\n\n"
        "Diese Zahlen sind die Ausgangslage für die folgenden Abschnitte, aber "
        "kein Ersatz für die dort zu treffenden Entscheidungen."
    )


def _render_full(slug: str, vault: dict, today: str) -> str:
    ausgangslage = _render_ausgangslage(vault)
    return f"""# Datenmanagementplan — {slug}

{_DATE_LABEL} {today}

> Dieses Dokument wurde durch den `data-management-plan`-Skill erzeugt bzw.
> aktualisiert. Es ist ein lebendes Dokument: Bei jedem Lauf werden nur das
> Datum und die Ausgangslage aus dem Vault aktualisiert, bereits ausgefüllte
> Abschnitte bleiben erhalten.

{ausgangslage}

## Datenarten und -umfang

- Welche Datenarten werden erhoben (z. B. Interviewtranskripte, Fragebogendaten,
  Beobachtungsprotokolle, Sekundärdaten)? {_offen("Datenarten konkret benennen")}
- Geschätzter Gesamtumfang (Anzahl Fälle, Dateigröße, Laufzeit): {_offen("Umfang schätzen")}
- Datenformate bei Erhebung: {_offen("Formate benennen, z. B. WAV/MP3, CSV, PDF")}

## Erhebung und Dokumentation

- Erhebungsmethode und -zeitraum: {_offen("Methode und Zeitraum eintragen")}
- Dokumentationsstandard (Codebook, Metadatenschema, Variablenbeschreibung):
  {_offen("Dokumentationsstandard festlegen")}
- Empfohlen: offene, dokumentierte Dateiformate (z. B. CSV, TXT/Markdown, JSON)
  statt proprietärer Formate, damit Daten ohne Speziallizenz nachnutzbar bleiben.

## Speicherung und Sicherung während des Projekts

- Speicherort während der Projektlaufzeit (z. B. Instituts-Server, verschlüsselter
  Cloud-Speicher der Einrichtung): {_offen("Speicherort eintragen")}
- Backup-Rhythmus und -Strategie (3-2-1-Regel als Orientierung: 3 Kopien, 2
  Medien, 1 externer Ort): {_offen("Backup-Strategie eintragen")}
- Zugriffsschutz (wer darf lesen/schreiben, Verschlüsselung ruhender Daten):
  {_offen("Zugriffsschutz beschreiben")}

## Rechtliche Aspekte

- Urheber- und Nutzungsrechte an den Daten (eigene Erhebung vs. Drittmaterial):
  {_offen("Rechtelage klären")}
- Lizenzierung des Vault-Materials selbst (unabhängig von der späteren
  Archiv-Lizenz, siehe Abschnitt Archivierung): {_offen("Lizenzierung klären")}

### Personenbezogene Daten

Dieser Abschnitt ist bewusst hervorgehoben: Fehler bei personenbezogenen Daten
lassen sich nach der Erhebung meist nicht mehr heilen.

- **Einwilligung:** Liegt von allen betroffenen Personen (z. B.
  Interviewpartner:innen) eine informierte Einwilligung zur Erhebung,
  Speicherung und ggf. Archivierung ihrer Daten vor?
  {_offen("Einwilligungsstatus eintragen")}
- **Pseudonymisierung:** Werden Namen und identifizierende Merkmale vor
  Weitergabe oder Archivierung pseudonymisiert oder anonymisiert, und nach
  welchem Verfahren? {_offen("Pseudonymisierungsverfahren eintragen")}
- **Aufbewahrung:** Wie lange werden personenbezogene Rohdaten aufbewahrt?
  Übliche Orientierung sind die Aufbewahrungsfristen aus dem DFG-Kodex sowie
  die Vorgaben der eigenen Einrichtung. {_offen("Aufbewahrungsfrist eintragen")}
- **Löschung:** Wann und wie werden personenbezogene Daten gelöscht (Löschkonzept,
  wer ist verantwortlich)? {_offen("Löschkonzept eintragen")}

> **Kein Ersatz für Rechtsberatung:** Dieser Plan ersetzt keine Rechtsberatung.
> Die datenschutzrechtliche Prüfung — insbesondere bei personenbezogenen Daten —
> leistet die zuständige Stelle der Einrichtung (z. B. Datenschutzbeauftragte/r,
> Forschungsdatenmanagement, Ethikkommission).
> Zuständige Stelle: {_offen("Kontakt der zuständigen Stelle eintragen")}

## Archivierung und Nachnutzung

Repositorien und Lizenzen sind als begründete Optionen zu verstehen — welche am
Ende passt, hängt von Fachkultur und Einrichtung ab, nicht von einer Vorgabe
dieses Plans.

**Repositorien (Auswahl, keine Vorgabe):**

- Zenodo — generalistisch, CERN-betrieben, kostenlos, vergibt DOI; passend,
  wenn kein Fach- oder Instituts-Repositorium vorgeschrieben ist.
- OSF (Open Science Framework) — verbreitet in Sozial- und
  Verhaltenswissenschaften, unterstützt Präregistrierung und Versionierung.
- Institutionelles Repositorium der eigenen Hochschule — bei Abschlussarbeiten
  oft die naheliegende erste Anlaufstelle, lokale Policy zuerst prüfen.
- Fachspezifisches Repositorium über re3data.org suchen, falls die Disziplin
  ein etabliertes Standard-Repositorium hat.

**Lizenzen (Auswahl, keine Vorgabe):**

- CC0 — Verzicht auf Rechte, maximale Nachnutzbarkeit; passend bei vollständig
  anonymisierten Daten ohne Drittrechte.
- CC-BY — Namensnennung erforderlich, gängiger Standard für offene Forschungsdaten.
- CC-BY-NC — schließt kommerzielle Nachnutzung aus; kann bei sensiblen oder
  teilweise personenbezogenen Daten passender sein.
- Eingeschränkter Zugang statt offener Lizenz, wenn Teile der Daten aus
  rechtlichen Gründen nicht frei zugänglich gemacht werden dürfen.

Gewählte Option: {_offen("Repositorium und Lizenz projektbezogen festlegen")}

## Zuständigkeiten

| Rolle | Verantwortlich für | Person/Stelle |
|---|---|---|
| Projektverantwortliche/r | Gesamtverantwortung für den Plan | {_offen("eintragen")} |
| Datenerhebung | Durchführung, Dokumentation | {_offen("eintragen")} |
| Speicherung und Sicherung | Backups, Zugriffsschutz | {_offen("eintragen")} |
| Archivierung und Nachnutzung | Repository-Upload, Lizenzvergabe | {_offen("eintragen")} |
| Datenschutz / Personenbezogene Daten | zuständige Stelle der Einrichtung | {_offen("eintragen")} |
"""


def _apply_idempotent_update(content: str, vault: dict, today: str) -> str:
    """Ersetzt nur Datum und Ausgangslage-Block, laesst den Rest unangetastet."""
    new_date_line = f"{_DATE_LABEL} {today}"
    if _DATE_LINE_RE.search(content):
        content = _DATE_LINE_RE.sub(new_date_line, content, count=1)
    else:
        content = content.rstrip() + "\n\n" + new_date_line + "\n"

    new_ausgangslage = _render_ausgangslage(vault)
    if _AUSGANGSLAGE_BLOCK_RE.search(content):
        content = _AUSGANGSLAGE_BLOCK_RE.sub(new_ausgangslage, content, count=1)
    else:
        content = content.rstrip() + "\n\n" + new_ausgangslage + "\n"

    return content


def build(db_path: str, slug: str, output_path: Path) -> None:
    vault = _aggregate_vault(db_path)
    today = datetime.now(UTC).date().isoformat()

    if output_path.exists():
        content = output_path.read_text(encoding="utf-8")
        content = _apply_idempotent_update(content, vault, today)
    else:
        content = _render_full(slug, vault, today)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Datenmanagementplan aus Vault-Bestand erzeugen/aktualisieren."
    )
    parser.add_argument("--db", required=True, help="Pfad zur Vault-DB")
    parser.add_argument("--slug", required=True, help="Projekt-Slug")
    parser.add_argument(
        "--output",
        default="datenmanagementplan.md",
        help="Pfad zur Ausgabedatei (Standard: datenmanagementplan.md)",
    )
    args = parser.parse_args(argv)

    try:
        build(args.db, args.slug, Path(args.output))
    except Exception as exc:
        print(f"FEHLER beim Erzeugen des Datenmanagementplans: {exc}", file=sys.stderr)
        return 1

    print(f"Datenmanagementplan aktualisiert: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
