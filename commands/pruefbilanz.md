---
description: >
  Ruft die Pruefbilanz eines Kapitels ab: belegte Zitate aufgeteilt in
  "geprueft & unauffaellig", "Befund offen" und "nicht geprueft" (mit Grund
  je Eintrag), offene Befunde nach Schwere sortiert, plus Belegdichte ueber
  alle Aussagesaetze und die laengste unbelegte Strecke. Abgabe-Check, deckt
  das gesamte Kapitel ab, kein Nebenprodukt eines Schreibvorgangs. Belegt
  NICHT, dass geprueft eingestufte Zitate korrekt verwendet sind, und meldet/
  warnt/blockiert nichts auf Basis der Belegdichte.
disable-model-invocation: true
allowed-tools: Read, mcp__academic-vault__vault_chapter_quote_balance
argument-hint: <kapitel-datei.md>
---

# /academic-research:pruefbilanz

Prüfbilanz für ein Kapitel: wie viele belegte Zitate geprüft und unauffällig sind, bei wie
vielen ein Befund offen steht, wie viele noch nie geprüft wurden — mit Grund je Eintrag —
sowie die Belegdichte: welcher Anteil der Aussagesätze überhaupt einen Beleg trägt.

## Verwendung

```
/academic-research:pruefbilanz kapitel/03-methodik.md
```

## Umsetzung

1. `vault.chapter_quote_balance(chapter_path)` mit dem übergebenen Kapitelpfad aufrufen.
2. Die Rückgabe (`total_quotes`, `geprueft_unauffaellig`, `befund_offen`,
   `nicht_geprueft`, `not_audited`, `findings`) als Tabelle ausgeben:
   - Kopfzeile mit den drei Zählern und `total_quotes`.
   - `findings` schwerste zuerst (`kritisch` → `hoch` → `mittel`), je Eintrag
     Zitat, Paper und betroffene Kapitelstelle (`chapter_claim`).
   - `not_audited` mit dem jeweiligen `reason`-Feld je Zitat.
3. Ein Kapitel ohne belegte Zitate (`total_quotes == 0`) meldet das explizit als
   Ergebnis — kein Fehler, keine leere Ausgabe.
4. Belegdichte als eigene Zeile ausgeben, rein informativ, ohne Bewertung:
   `statement_sentences_covered` von `statement_sentences_total`
   Aussagesätzen (`citation_density` als Prozentzahl; bei `None` — 0
   Aussagesätze — statt eines Anteils explizit "keine Aussagesätze" melden).
   Ist `longest_uncovered_run` gesetzt, dessen `sentence_count`, `line` und
   `excerpt` als "längste unbelegte Strecke" mit ausgeben; ist es `None`,
   nichts dazu ausgeben (keine Strecke vorhanden).

## Was die Bilanz nicht belegt

Sie priorisiert die Prüfkette, sie beweist nicht, dass ein als "geprüft &
unauffällig" eingestuftes Zitat korrekt verwendet ist — dafür bleibt das
Urteil des `quote-fidelity-auditor`-Agenten die inhaltliche Quelle. Die
Bilanz stellt fest, sie handelt nicht: kein automatisches Nachprüfen, keine
Blockade auf Basis der Zahlen.

**Die Belegdichte ist kein Qualitätsmerkmal.** Eine hohe Zahl bedeutet nicht,
dass die Zitate korrekt verwendet sind, und eine niedrige Zahl ist keine
Aufforderung, mehr zu zitieren — ein Kapitel aus lauter Zitaten ist keine
eigene Leistung. Es gibt hierzu keine Meldung, keine Warnung, keinen
Schwellwert und keine Empfehlung, wo ein Beleg zu setzen wäre.
