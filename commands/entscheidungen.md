---
description: >
  Listet die im Lauf selbst getroffenen Abwägungen (Kategorie `judgment-call`)
  mit Grund und Zeitpunkt auf — aktive und abgelöste getrennt — und revidiert
  eine davon auf Wunsch per Nachfolge-Eintrag. Betrifft NICHT die automatisch
  protokollierten Datei-Änderungen oder Modellkennungs-Einträge; die bleiben
  aus dieser Übersicht ausgeschlossen.
disable-model-invocation: true
allowed-tools: mcp__academic-vault__vault_list_decisions, mcp__academic-vault__vault_add_decision, mcp__academic-vault__vault_supersede_decision
argument-hint: [--revidieren <decision_id> "<neue Entscheidung>" "<Grund>"]
---

# /academic-research:entscheidungen

Gibt aus, welche Abwägungen der Lauf selbst getroffen hat (Kategorie
`judgment-call`, siehe `skills/_common/preamble.md`, Abschnitt "Fehlende
Tatsache vs. offene Abwägung"), und erlaubt, eine davon zu revidieren.

## Verwendung

- `/academic-research:entscheidungen` — alle aktiven Abwägungen ausgeben
- `/academic-research:entscheidungen --revidieren <decision_id> "<neue Entscheidung>" "<Grund>"` —
  eine bestehende Abwägung durch eine neue ersetzen

## Umsetzung

### Ohne `--revidieren`: Übersicht

1. `vault.list_decisions(category="judgment-call", active_only=False)` aufrufen.
2. Nach `superseded_by` in zwei Gruppen aufteilen:
   - **Aktiv** (`superseded_by` ist `None`): Text, Grund (`rationale`) und
     Zeitpunkt (`created_at`) je Eintrag ausgeben.
   - **Abgelöst** (`superseded_by` gesetzt): dieselben Felder plus Verweis auf
     die ablösende `decision_id`, deutlich als "abgelöst" markiert — nicht
     einfach weglassen.
3. Keine aktiven Einträge vorhanden → das explizit melden ("Keine
   protokollierten Abwägungen in diesem Lauf"), kein Fehler.

### Mit `--revidieren <decision_id> "<neue Entscheidung>" "<Grund>"`

1. Existenz von `decision_id` unter den aktiven Einträgen aus Schritt 1 oben
   prüfen. Nicht gefunden oder bereits abgelöst → das melden, nichts
   ausführen.
2. `vault.add_decision(category="judgment-call", text="<neue Entscheidung>", rationale="<Grund>")`
   aufrufen, liefert die neue `decision_id`.
3. `vault.supersede_decision(decision_id=<alte decision_id>, superseded_by=<neue decision_id>)`
   aufrufen. Die alte Abwägung bleibt danach als abgelöst sichtbar (Schritt 3
   der Übersicht), nicht gelöscht.
4. Bestätigung mit alter und neuer `decision_id` ausgeben.

## Abgrenzung

Zeigt und revidiert ausschließlich `judgment-call`-Einträge. Automatisch vom
`post-tool-use-decisions.mjs`-Hook geschriebene Datei-Änderungen
(`file-change`) und Modellkennungs-Einträge (`model-version`) laufen über
eigene Pfade und erscheinen hier nicht — sie sind kein Ergebnis einer im Lauf
getroffenen Abwägung. Legt keine neuen Haltepunkte an und ändert nichts an
`outline_gate` oder anderen skill-eigenen Gates.
