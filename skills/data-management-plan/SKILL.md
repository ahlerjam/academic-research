---
name: data-management-plan
description: >
  Verwende diesen Skill, wenn der User einen Datenmanagementplan (DMP) für
  seine Forschungsdaten erstellen oder aktualisieren möchte — also planen will,
  wie mit Rohdaten während und nach dem Projekt umgegangen wird: Speicherort,
  Sicherung, rechtliche Aspekte einschließlich personenbezogener Daten,
  Archivierung und Nachnutzung, Zuständigkeiten. Trigger-Phrasen:
  "Datenmanagementplan erstellen", "Datenmanagementplan aktualisieren", "DMP
  erstellen", "DMP schreiben", "Datenmanagementplan prüfen / pruefen", "Umgang
  mit Forschungsdaten planen", "datenmanagementplan.md generieren",
  "Forschungsdatenmanagement dokumentieren". Anders als `material-passport`
  (Reproduzierbarkeits-Manifest für die Abgabe, technische Metadaten wie
  Score-Versionen und PDF-Hashes) geht es hier um den organisatorischen und
  rechtlichen Umgang mit den Rohdaten selbst, insbesondere personenbezogenen
  Daten — nicht um ein Abgabe-Manifest. Nutzt
  `${CLAUDE_PLUGIN_ROOT}/skills/data-management-plan/scripts/build_dmp.py`,
  das den Vault-Bestand (Paper nach Herkunftsart, Transkriptsegmente,
  Kodierungen) als Ausgangslage liest und `datenmanagementplan.md` erzeugt
  bzw. aktualisiert; unentschiedene Punkte werden als `[OFFEN: ...]`
  markiert statt erfunden.
license: MIT
allowed-tools: [Bash, Read]
---

# Datenmanagementplan

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Zweck

Erstellt oder aktualisiert `datenmanagementplan.md`: ein lebendes Dokument,
das den Umgang mit Forschungsdaten über den Projektverlauf systematisch
plant, statt ihn am Ende improvisieren zu müssen. Der DFG-Kodex "Leitlinien
zur Sicherung guter wissenschaftlicher Praxis" ist von deutschen Hochschulen
und Forschungseinrichtungen rechtsverbindlich umzusetzen und macht den Umgang
mit Forschungsdaten zu einem seiner Gegenstände; ein DMP ist das übliche
Instrument dafür.

Der erzeugte Plan deckt sechs feste Abschnitte ab: Datenarten und -umfang,
Erhebung und Dokumentation, Speicherung und Sicherung während des Projekts,
rechtliche Aspekte (mit eigenem, hervorgehobenem Abschnitt zu
personenbezogenen Daten), Archivierung und Nachnutzung, Zuständigkeiten.
Bereits im Vault vorhandene Bestände (Paper nach Herkunftsart, Transkript-
segmente, Kodierungen) erscheinen als Ausgangslage-Abschnitt, nicht als
Rückfrage an den User. Projektspezifische Punkte, die weder im Vault noch
sonst bekannt sind (Speicherort, Repository-Wahl, zuständige Person, ...),
werden als `[OFFEN: ...]`-Marker geschrieben statt plausibel gefüllt — eine
offene Stelle ist ehrlicher als eine erfundene.

## Trigger-Erkennung

Aktiviert bei:
- "Datenmanagementplan erstellen" / "aktualisieren"
- "DMP erstellen" / "DMP schreiben"
- "Datenmanagementplan prüfen / pruefen"
- "Umgang mit Forschungsdaten planen"
- "datenmanagementplan.md generieren"

## Workflow

### Schritt 1: Kontext klären

Kläre bei Bedarf den Projekt-Slug (Standard: aus Vault-DB-Pfad oder
aktuelles Verzeichnis). Kein `AskUserQuestion`-Gate nötig — im Gegensatz zum
Repro-Lock in `material-passport` ist der DMP-Export jederzeit wiederholbar
und nicht irreversibel.

### Schritt 2: build_dmp.py ausführen

```bash
python ${CLAUDE_PLUGIN_ROOT}/skills/data-management-plan/scripts/build_dmp.py \
  --db vault.db \
  --slug <projekt-slug> \
  --output datenmanagementplan.md
```

Existiert `datenmanagementplan.md` bereits, aktualisiert das Script nur das
Datum ("Zuletzt aktualisiert") und den "## Ausgangslage im Vault"-Block —
alle übrigen Abschnitte, in denen der User zwischenzeitlich `[OFFEN: ...]`
durch echte Entscheidungen ersetzt haben kann, bleiben unverändert. Existiert
die Datei noch nicht, wird sie vollständig neu mit allen sechs Abschnitten
angelegt.

### Schritt 3: Ergebnis an User melden

```
Datenmanagementplan aktualisiert: ./datenmanagementplan.md

Ausgangslage aus dem Vault übernommen (Paper, Transkriptsegmente, Kodierungen).
Offene Punkte sind als [OFFEN: ...] markiert und warten auf projektspezifische
Entscheidungen — insbesondere im Abschnitt "Personenbezogene Daten".
```

Weise bei personenbezogenen Daten im Vault (Transkripte mit `source_kind:
primary`) explizit auf den Abschnitt "Personenbezogene Daten" hin: dort
liegen die Fehler, die sich später nicht mehr heilen lassen.

## Fehlerfälle

| Situation | Meldung | Maßnahme |
|-----------|---------|-----------|
| Vault-DB nicht gefunden | `FEHLER: ...` | Pfad prüfen oder `--db` korrigieren |
| Ausgabepfad nicht schreibbar | `FEHLER: ...` | Berechtigungen/Pfad prüfen |

## Abgrenzung

- Keine Rechtsberatung: Der Skill benennt die Fragen und die üblichen
  Antworten; die datenschutzrechtliche Prüfung leistet die zuständige Stelle
  der Einrichtung. Der erzeugte Plan spricht diese Grenze selbst aus.
- Keine Förderer-spezifischen Formulare: Vorgaben unterscheiden sich je
  Förderer und ändern sich; der Plan ist inhaltlich vollständig, aus ihm
  lässt sich ein Formular befüllen, er ersetzt es nicht.
- Kein tatsächliches Archivieren oder Hochladen der Daten — Repositorien
  werden nur als begründete Optionen genannt.
- Keine Einwilligungserklärungen für Interviewpartner:innen formulieren —
  verwandtes Thema, aber eigener Skill-Schnitt mit anderer rechtlicher Tiefe.
- Kein Reproduzierbarkeits-Manifest und kein Repro-Lock — dafür
  `material-passport` verwenden.
