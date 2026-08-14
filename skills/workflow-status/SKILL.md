---
name: workflow-status
description: Use this skill when the user asks where they stand in their thesis workflow or what to do next. Triggers on "wo stehe ich", "was ist der naechste Schritt", "wie geht es weiter", "Stand der Arbeit", "nächster Schritt / naechster Schritt", or similar phrasing (deutsch oder englisch) that asks for the current phase or next step of the academic-research workflow. Beantwortet die Frage ohne eigenen Slash-Command, direkt im Gespraech.
license: MIT
allowed-tools:
  - Bash
  - Read
---

# Phasenstand auf Zuruf

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

> **Override Vorbedingungen:** Dieser Skill setzt selbst keinen vorhandenen
> Kontext voraus — existiert `./academic_context.md` nicht, meldet er das
> ohne Fehler und verweist auf `academic-context`.

## Übersicht

Wertet `./academic_context.md` gegen `${CLAUDE_PLUGIN_ROOT}/config/workflow-phases.json`
aus und beantwortet "wo stehe ich" / "was ist der naechste Schritt" / "wie
geht es weiter" / "Stand der Arbeit" direkt im Gespräch — ohne eigenen
Slash-Command, damit die Frage auch mitten in einer anderen Unterhaltung
greift. Dieselbe Auswertungslogik nutzt der SessionStart-Hook (ungefragte
Kurzfassung) und der Compaction-Block von `mid-session-reinforcement.mjs`
(Issue #877).

## Ablauf

1. Führe `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_status.py" --project-dir . --plugin-root "${CLAUDE_PLUGIN_ROOT}" --full` aus.
2. Keine Ausgabe (leerer stdout)? Dann existiert entweder keine
   `./academic_context.md` oder sie ist beschädigt/unvollständig — beides
   ist kein Fehler. Antworte in diesem Fall, dass noch kein auswertbarer
   Kontext vorliegt, und biete den `academic-context`-Skill an. Erfinde
   **keine** Phase.
3. Liegt eine Ausgabe vor, fasse sie im Gespräch zusammen:
   - **Aktuelle Phase** (die `[flowkit] Phase: ...`-Zeile).
   - **Nächster Schritt** samt Auslöser (die `[flowkit] Naechster Schritt: ...`-Zeile
     nennt bereits, ob `Claude` (selbst-aktivierender Skill) oder `Operator`
     (expliziter Slash-Command bzw. direkter Vault-/MCP-Zugriff ohne eigenen
     Skill) den Schritt auslöst).
   - **Restkette bis Export** (der Block `[flowkit] Verbleibend bis Export:`) —
     jede verbleibende Phase in Reihenfolge, ebenfalls mit Auslöser
     (Claude/Operator) je Zeile.
4. Nenne bei jedem genannten Schritt explizit den Auslöser — das ist Teil der
   Antwort, nicht nur der Rohausgabe des Skripts.

## Abgrenzung

- Erzwingt keine Reihenfolge (kein Blocken vorzeitiger Schritte) — reine
  Auskunft, kein Gate. Durchsetzung ist ein eigener Schnitt.
- Ändert `config/workflow-phases.json` oder `academic_context.md` nicht.
- Kein neuer Slash-Command — reagiert ausschließlich auf die
  Trigger-Formulierungen im Gespräch.
