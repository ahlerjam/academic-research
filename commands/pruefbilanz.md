---
description: >
  Ruft die Pruefbilanz eines Kapitels ab: belegte Zitate aufgeteilt in
  "geprueft & unauffaellig", "Befund offen" und "nicht geprueft" (mit Grund
  je Eintrag), offene Befunde nach Schwere sortiert. Abgabe-Check, deckt das
  gesamte Kapitel ab, kein Nebenprodukt eines Schreibvorgangs. Belegt NICHT,
  dass geprueft eingestufte Zitate korrekt verwendet sind.
disable-model-invocation: true
allowed-tools: Read, mcp__academic-vault__vault_chapter_quote_balance
argument-hint: <kapitel-datei.md>
---

# /academic-research:pruefbilanz

Prüfbilanz für ein Kapitel: wie viele belegte Zitate geprüft und unauffällig sind, bei wie
vielen ein Befund offen steht, und wie viele noch nie geprüft wurden — mit Grund je Eintrag.

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

## Was die Bilanz nicht belegt

Sie priorisiert die Prüfkette, sie beweist nicht, dass ein als "geprüft &
unauffällig" eingestuftes Zitat korrekt verwendet ist — dafür bleibt das
Urteil des `quote-fidelity-auditor`-Agenten die inhaltliche Quelle. Die
Bilanz stellt fest, sie handelt nicht: kein automatisches Nachprüfen, keine
Blockade auf Basis der Zahlen.
