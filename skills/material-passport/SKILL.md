---
name: material-passport
description: >
  Verwende diesen Skill wenn der User ein Reproduzierbarkeits-Manifest erstellen
  oder das Projekt für die Abgabe finalisieren möchte.
  Trigger-Phrasen: "Reproduzierbarkeits-Manifest / Material-Passport erstellen",
  "Artefakt sichern", "Manifest prüfen / pruefen", "Abgabe vorbereiten",
  "Vault sperren", "Repro-Lock", "material-passport.json",
  "Reproduzierbarkeit dokumentieren".
  Exporttyp: "Prüfung / Validation" via JSON-Schema.
  Exportiert alle relevanten Metadaten (paper_ids, DOIs, Scores, Algo-Version,
  Modellversionen, PDF-Hashes, Decision-Snapshot) als material-passport.json
  und ergänzt kapitel/methodik.md automatisch um einen Reproduzierbarkeits-Block.
license: MIT
allowed-tools:
  - Bash
  - AskUserQuestion
---

# Material-Passport Skill

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

---

## Zweck

Erstellt einen vollständigen Material-Passport für das Forschungsprojekt:

- **material-passport.json** — maschinenlesbares Manifest mit allen Metadaten
- **kapitel/methodik.md** — erhält automatisch einen `## Reproduzierbarkeit`-Block
- **Repro-Lock** (optional) — sperrt den Vault nach Abgabe read-only

Der Passport macht nachvollziehbar, welche Paper, Scores, Algorithmus- und
Modellversionen verwendet wurden.

---

## Trigger-Erkennung

Aktiviert bei:
- "Reproduzierbarkeits-Manifest erstellen"
- "Material-Passport"
- "Abgabe vorbereiten"
- "Vault für Abgabe sperren" / "Repro-Lock"
- "material-passport.json generieren"
- "Reproduzierbarkeit dokumentieren"

---

## Systemanforderungen

1. **Vault-DB** vorhanden (Standard: `vault.db` im CWD oder via `VAULT_DB_PATH`)
2. **Paper im Vault** eingetragen (via `vault.add_paper`)
3. **kapitel/methodik.md** existiert (wird ggf. angelegt)
4. Python-Abhängigkeiten installiert: `pip install -r scripts/requirements.txt`

---

## Workflow

### Schritt 1: User-Anfrage verstehen

Kläre bei Bedarf:
- Projekt-Slug (Standard: aus Vault-DB oder aktuelles Verzeichnis)

**Repro-Lock-Gate:** Bevor `build_passport.py` jemals mit `--lock` aufgerufen
wird, MUSS `AskUserQuestion` gestellt werden — eine Prosa-Rückfrage genügt
nicht. Optionen:

- **"Mit Repro-Lock exportieren — `--lock`, irreversibel: Vault wird danach
  dauerhaft read-only"** → weiter mit Schritt 2 "Mit Repro-Lock"
- **"Ohne Repro-Lock exportieren"** (Default) → weiter mit Schritt 2 "Ohne
  Repro-Lock"

Bricht der User ab oder wählt "Ohne Repro-Lock": normaler Export ohne
`--lock` (Schritt 2, "Ohne Repro-Lock") — kein Fehler, kein Abbruch des
Skills.

### Schritt 2: build_passport.py ausführen

**Ohne Repro-Lock** (normaler Export):
```bash
python ${CLAUDE_PLUGIN_ROOT}/skills/material-passport/scripts/build_passport.py \
  --db vault.db \
  --slug <projekt-slug> \
  --output-dir . \
  --methodik kapitel/methodik.md
```

**Mit Repro-Lock** (Vault nach Export sperren):
```bash
python ${CLAUDE_PLUGIN_ROOT}/skills/material-passport/scripts/build_passport.py \
  --db vault.db \
  --slug <projekt-slug> \
  --output-dir . \
  --methodik kapitel/methodik.md \
  --lock
```

> **Achtung:** Der Repro-Lock ist **irreversibel**. Sobald `--lock` gesetzt wurde,
> können keine weiteren Paper oder Decisions in den Vault geschrieben werden.
> `--lock` nur nach positiver Antwort auf das `AskUserQuestion`-Gate aus
> Schritt 1 aufrufen — keine eigenständige Bestätigung an dieser Stelle.

### Schritt 3: Ergebnis an User melden

Ausgabe nach erfolgreichem Export:
```
Material-Passport exportiert: ./material-passport.json
methodik.md aktualisiert: kapitel/methodik.md
```

Vollständige Meldung an User:
```
Material-Passport erstellt:
  Datei:   ./material-passport.json
  Slug:    <projekt-slug>
  Paper:   <N> eingetragen
  DOIs:    <M> mit DOI
  Decisions: <K> aktive Entscheidungen

kapitel/methodik.md wurde um '## Reproduzierbarkeit' ergänzt.
```

Bei aktivem Repro-Lock zusätzlich:
```
Vault gesperrt (Repro-Lock aktiv).
Keine weiteren Aenderungen am Vault möglich.
```

---

## Fehlerfälle

| Situation | Meldung | Maßnahme |
|-----------|---------|-----------|
| Vault bereits gesperrt | `FEHLER: Vault für Slug '...' ist gesperrt` | Kein erneuter Export — Vault ist read-only |
| Vault-DB nicht gefunden | `FEHLER: ...` | Pfad prüfen oder `VAULT_DB_PATH` setzen |
| methodik.md nicht schreibbar | `WARNUNG: methodik.md konnte nicht aktualisiert werden` | Berechtigungen prüfen; Passport wurde trotzdem erstellt |

---

## material-passport.json — Inhalt

Das JSON-Dokument enthält:

| Feld | Beschreibung |
|------|-------------|
| `slug` | Projekt-Slug |
| `paper_ids` | Liste aller Paper-IDs im Vault |
| `dois` | Liste aller vorhandenen DOIs |
| `download_tier` | `full` (PDFs vorhanden) oder `metadata-only` |
| `scores_5d` | Aktuelle 5D-Scores je Paper |
| `score_algo_version` | Version des Scoring-Algorithmus |
| `plugin_version` | Version des academic-research Plugins |
| `model_versions` | KI-Modellversionen je Arbeitsschritt (`<schritt>: <modell>`) — leer heisst *nicht erfasst*, nicht *kein Modell*; Erfassung lueckenhaft (#617) |
| `per_uni_profile_hash` | Hash des Uni-Bewertungsprofils (optional) |
| `decisions_snapshot` | Snapshot aktiver methodischer Decisions (ohne `file-change`-Auto-Einträge) |
| `pdf_sha256_hashes` | SHA-256-Hashes aller vorhandenen PDFs |
| `quote_extraction_methods`/`manual_quotes_count`/`manual_quotes_ratio` | Herkunft je Zitat + Anzahl/Anteil `manual` (#595) |
| `created_at` | Unix-Timestamp des Exports |
| `passport_hash` | SHA-256 über alle übrigen Felder |

Das Dokument wird gegen das JSON-Schema in
`academic_vault/material-passport.schema.json` validiert.

---

## Abgrenzung

- Kein automatisches Backup oder Archivierung — nur Export
- Kein Hochladen in externe Systeme
- Repro-Lock nur mit expliziter User-Bestätigung
- Kein Löschen vorhandener Vault-Daten
- JSON-Schema-Validierung erfolgt intern; bei Validierungsfehler wird kein File geschrieben
