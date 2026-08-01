# Qualitäts-Review-Konfiguration

Nach der Generierung des Kapitel-Entwurfs (ggf. nach Humanizer-Audit-Pass)
triggert `SKILL.md` den `quality-reviewer`-Agent mit folgender Konfiguration.

## Agent-Aufruf

```
Agent(
  subagent_type="quality-reviewer",
  prompt={
    "content": "<Entwurfs-Text oder humanized_text>",
    "criteria": [
      {"name": "Satzlaenge Median", "threshold": "15-25 Woerter", "metric": "median"},
      {"name": "Passiv-Quote", "threshold": "< 30%", "metric": "percentage"},
      {"name": "Nominalstil", "threshold": "< 40%", "metric": "percentage"},
      {"name": "Quellen pro 1000 Woerter", "threshold": ">= 5", "metric": "count_per_1000"}
    ],
    "context": {
      "component": "chapter-writer",
      "iteration": <N>,
      "humanizer_de_pass": <true wenn Audit-Pass gelaufen, sonst false>
    }
  }
)
```

## Ergebnis-Handling

- **Bei PASS:** Output an User liefern.
- **Bei REVISE:** Empfehlungen anwenden, erneut generieren, iteration += 1.
- **Bei ESCALATE** (der Agent liefert es bei `iteration >= 2` **und**
  mindestens einem Kriterium mit FAIL, `BLOCKIERT_VON: iteration-limit`):
  nicht automatisch akzeptieren. Die verbleibenden Probleme aus `BEGRÜNDUNG`
  und `EMPFEHLUNGEN` auflisten und via `AskUserQuestion` genau drei Optionen
  anbieten:
  1. **Entwurf akzeptieren** — Output mit dokumentierten Restproblemen liefern.
  2. **Weitere Revision** — Empfehlungen anwenden und erneut generieren;
     das gewährt **genau eine zusätzliche Runde**. Bleiben danach Findings
     offen, liefert der Agent erneut ESCALATE und dieses Gate läuft erneut —
     nie ein stiller Auto-PASS und nie eine Endlos-Schleife.
  3. **Abbrechen** — Entwurf verwerfen, kein Output; offener Punkt in
     `./writing_state.md` vermerken.

  Steht kein `AskUserQuestion`-Kanal zur Verfügung (headless), gilt ESCALATE
  als Abbruch: kein Output als fertig ausweisen, sondern die Restprobleme
  melden.
