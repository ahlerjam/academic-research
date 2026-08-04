---
name: bibliography-auditor
description: >
  Verwende diesen Skill, um das Literaturverzeichnis eines Kapitels oder der
  gesamten Thesis auf Vollständigkeit und Konsistenz gegen den Vault zu
  prüfen: jede im Text per `\cite{key}` zitierte Quelle muss einen
  Vault-Eintrag haben, und jeder Vault-Eintrag sollte mindestens einmal
  zitiert sein. Trigger-Phrasen: "Literaturverzeichnis prüfen / pruefen",
  "Zitate gegen Vault abgleichen", "Bibliographie auditieren",
  "fehlende Quellen im Literaturverzeichnis finden", "verwaiste
  Literatureinträge / Literatureintraege finden", "Zitat-Vollständigkeit /
  Zitat-Vollstaendigkeit prüfen". Read-only: liest Kapitel und Vault, ändert
  nichts.
license: MIT
allowed-tools:
  - Read
  - Bash
---

# Bibliographie-Auditor

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Zweck

Gegenprobe zwischen den `\cite{key}`-Zitaten in `kapitel/*.md` und der
Paper-Menge im Vault, bevor Inkonsistenzen erst bei der Abgabe auffallen:

- **Fehlende Verzeichniseinträge** — im Text zitiert, aber kein passendes
  Vault-Paper (`missing_in_bibliography`).
- **Verwaiste Einträge** — im Vault vorhanden, aber in keinem Kapitel
  zitiert (`orphaned_entries`).

Reiner Prüfbericht — keine automatische Korrektur des Literaturverzeichnisses
oder der Kapiteldateien.

## Quelle

Die Prüfdimension orientiert sich an Kategorie E3 „Bibliography Hygiene“ des
30-Prinzipien-Katalogs aus
[andrehuang/academic-writing-agents](https://github.com/andrehuang/academic-writing-agents)
(MIT-Lizenz; Wortlaut-Übernahme mit Quellenhinweis, analog zu
`latex-layout-auditor`, Issue #392).

## Abgrenzung

- **`submission-checker`** prüft Hochschul-Formalia (Seitenränder,
  Zeilenabstand, Pflichtabschnitte) — nicht Zitat-Vollständigkeit.
  **`bibliography-auditor`** prüft ausschließlich die Zitat-↔-Vault-
  Konsistenz. Beide ergänzen sich; keiner ersetzt den anderen.
- Geprüft wird die tatsächliche In-Text-Zitierkonvention dieses Repos
  (`\cite{key}` in `kapitel/*.md`, Issue #386) — nicht freie Autor/Jahr-Prosa.
- Kein Schreibzugriff: weder auf den Vault (keine `add_*`/`update_*`/
  `lock_*`/`restore_*`/`supersede_*`/`set_*`-Aufrufe) noch auf Kapiteldateien.
  `allowed-tools` enthält bewusst kein `Write`/`Edit`/`NotebookEdit`.

## Workflow

`${CLAUDE_PLUGIN_ROOT}/skills/bibliography-auditor/scripts/audit_bibliography.py --kapitel <n>|all`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/bibliography-auditor/scripts/audit_bibliography.py" \
  --kapitel "$KAPITEL"
```

1. Kapitel über `export_thesis.resolve_chapters()` auflösen (dieselbe
   `--kapitel <n>|all`-Semantik wie `latex-export`/`word-export`, kein
   zweiter Nachbau).
2. `\cite{key}`-Marker (und Mehrfachzitate `\cite{a,b}`) aus allen aufgelösten
   Kapiteln extrahieren.
3. Vault-Paper-Menge über `build_bib.get_all_papers()` laden (Re-Export,
   identischer Vault-Pfad-Auflöser wie `latex-export`/`word-export`:
   `academic_vault.db.default_db_path()`, außer `--vault-db` überschreibt).
4. Differenzmengen bilden: `missing_in_bibliography` (zitiert, kein Paper),
   `orphaned_entries` (Paper, nirgends zitiert).
5. Klartext-Report ausgeben; optional `--json <datei>` für die maschinen-
   lesbare Fassung.

Exit-Code ≠ 0 → `FEHLER: ...`-Meldung des Skripts unverändert an den User
weitergeben (kein Stacktrace).

## Fehlerfälle

| Situation | Meldung | Maßnahme |
|-----------|---------|-----------|
| `kapitel/`-Verzeichnis fehlt oder Selektor passt auf keine Datei | `FEHLER: ...` (von `resolve_chapters()`) | Pfad/Selektor prüfen |
| Vault-Modul nicht ladbar | `FEHLER: Vault-Modul 'academic_vault' nicht ladbar ...` | Plugin-Installation prüfen (`scripts/setup.sh`) |
| Vault leer (0 Paper) | `paper_count: 0` im Report, alle zitierten Keys als `missing_in_bibliography` | Paper via `add` in den Vault eintragen |

## Nicht geprüft

Format-Konsistenz einzelner Literatureinträge (Feldvollständigkeit, Stil-
konformität) — dafür `citation-extraction`/`word-export`/`latex-export`.
Freie Autor/Jahr-Zitate außerhalb der `\cite{}`-Konvention werden nicht
erkannt (siehe Abgrenzung oben) — bei Verdacht auf solche Stellen manuell
gegenlesen, dieser Skill weist das nicht als geprüft aus.
