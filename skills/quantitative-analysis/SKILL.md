---
name: quantitative-analysis
description: >
  Verwende diesen Skill, wenn der User einen selbst erhobenen quantitativen
  Datensatz auswerten und die Ergebnisse berichtsfertig machen will:
  Deskription, Gruppenvergleich, Zusammenhangsmaß — jeweils mit
  Voraussetzungsprüfung, Effektstärke und Konfidenzintervall.
  Trigger-Phrasen: "quantitative Auswertung rechnen", "Datensatz auswerten",
  "t-Test rechnen", "Varianzanalyse rechnen", "Gruppenvergleich rechnen",
  "Effektstärke berechnen / Effektstaerke berechnen",
  "Voraussetzungsprüfung für den t-Test / Voraussetzungspruefung fuer den
  t-Test", "Ergebnisteil mit Effektstärken / Ergebnisteil mit Effektstaerken",
  "Analyseplan für die Erhebung / Analyseplan fuer die Erhebung",
  "Auswertung reproduzierbar dokumentieren". Rechnet über
  `${CLAUDE_PLUGIN_ROOT}/skills/quantitative-analysis/scripts/analyze.py`.
  Abgrenzung: `methodology-advisor` wählt das Design vor der Erhebung,
  `qualitative-coding` wertet Textmaterial aus, der `meta-analysis`-Agent
  rechnet über fremde Studien; hier geht es ausschließlich um eigene
  quantitative Rohdaten. Die Deutung der Ergebnisse bleibt beim Menschen.
license: MIT
allowed-tools: [Bash, Read, Write, AskUserQuestion]
---

# Quantitative Auswertung

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Zweck

Zwischen dem fertigen Instrument und dem Ergebniskapitel liegt die Auswertung.
Sie ist der Teil, der in der Begutachtung als Erstes auffällt, wenn er fehlt:
ein Ergebnisteil ohne Effektstärke, ein Verfahren ohne Voraussetzungsprüfung,
ein Rechenweg, den niemand ein zweites Mal gehen kann. Dieser Skill schließt
genau diese drei Lücken — und nur sie.

## Was diese Fassung abdeckt

| Fragestellung | Verfahren |
| --- | --- |
| Wie sieht die Verteilung aus? | `deskriptiv` (n, fehlende Werte, M, SD, Md, IQR, Min/Max, Häufigkeiten) |
| Unterscheiden sich zwei Gruppen? | `t_test_unabhaengig`, `welch_test`, `mann_whitney_u` |
| Unterscheiden sich zwei Messzeitpunkte? | `t_test_gepaart`, `wilcoxon` |
| Unterscheiden sich drei oder mehr Gruppen? | `anova_einfaktoriell`, `kruskal_wallis` |
| Hängen zwei Merkmale zusammen? | `chi_quadrat_unabhaengigkeit`, `pearson_r`, `spearman_rho` |

**Nicht abgedeckt, und zwar bewusst:** Regression jeder Art, mehrfaktorielle
Designs, Post-hoc-Vergleiche nach ANOVA, Poweranalyse, Faktorenanalyse,
Mediation. Wird eines davon gebraucht, sag das offen und verweise auf eine
Statistiksoftware — ein von Hand nachgeschobener Paarvergleich wäre
unkontrolliertes Mehrfachtesten.

Die Entscheidungstabelle Skalenniveau × Design, die Voraussetzungen je
Verfahren und die Berichtsvorlagen stehen in
`references/verfahren.md`. Lies sie, bevor du ein Verfahren vorschlägst.

## Schritt 1 — Daten sichten

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/quantitative-analysis/scripts/analyze.py \
  describe --data empirie/daten/erhebung.csv
```

Das zeigt Spalten, Fallzahl und fehlende Werte. Das Skalenniveau steht dort
absichtlich nicht — ob `note` metrisch oder ordinal gelesen wird, ist eine
inhaltliche Entscheidung und gehört in den Dialog.

## Schritt 2 — Verfahren wählen (Dialog, nicht Automatik)

Leg mit dem User fest und halte es wörtlich fest:

1. **Fragestellung je Analyse** — Unterschied, Zusammenhang oder Beschreibung.
2. **Skalenniveau je Variable** — metrisch, ordinal oder nominal.
3. **Designtyp** — unabhängige Stichproben oder Messwiederholung.

Aus diesen drei Angaben folgt das Verfahren (Tabelle in `references/`). Steht
mehr als eines zur Wahl — etwa Student- gegen Welch-Test —, leg die Optionen
per `AskUserQuestion` vor, statt still zu entscheiden. Ist das Design selbst
noch offen, ist `methodology-advisor` der richtige Ort, nicht dieser Skill.

Das Ergebnis ist ein Analyseplan als JSON (`empirie/analyseplan.json`) mit
`variablen`, `analysen`, `alpha`, `konfidenzniveau` und `bootstrap.seed`. Der
Plan ist das versionierbare Artefakt: Er wird **vor** dem ersten Lauf
geschrieben und mitcommittet. Ein nachträglich an das Ergebnis angepasster
Plan ist kein Plan mehr.

## Schritt 3 — Rechnen

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/quantitative-analysis/scripts/analyze.py \
  run --data empirie/daten/erhebung.csv \
      --plan empirie/analyseplan.json \
      --out empirie/auswertung/
```

Es entstehen drei Dateien: `ergebnisse.json` (der Payload — enthält keinen
Zeitstempel und ist deshalb zwischen zwei Läufen byte-identisch),
`lauf_meta.json` (Zeitpunkt, Pfade, Python-/numpy-/scipy-Version) und
`protokoll.md` (der Bericht mit Wiederhol-Kommandozeile und SHA-256 der
Rohdatei).

Jedes inferenzstatistische Ergebnis trägt Teststatistik, p-Wert, Effektstärke,
Konfidenzintervall und einen Voraussetzungsblock. Fehlt eines davon, bricht der
Renderer mit einem Fehler ab, statt einen unvollständigen Bericht zu schreiben.

## Schritt 4 — Verletzte Voraussetzungen behandeln

Der Bericht weist jede Prüfung mit Kennwert, p-Wert und Verdikt aus — auch die
erfüllten. Ist eine Voraussetzung verletzt, steht das im Klartext im Protokoll,
zusammen mit der naheliegenden Alternative.

**Das Skript wechselt das Verfahren nie von selbst.** Es rechnet, was geplant
war, und benennt die Verletzung. Ob stattdessen der Welch- oder der
Mann-Whitney-U-Test gerechnet wird, entscheidet der User; die Entscheidung
gehört anschließend in den Analyseplan und ins Decision-Log. Eine stille
Verfahrensänderung wäre genau die Sorte Freiheitsgrad, die Ergebnisse
unbrauchbar macht.

## Schritt 5 — In den Vault

Die Rohdaten bleiben **außerhalb** des Vaults: Ein Datensatz mit tausend Fällen
gehört nicht in eine Literatur-Datenbank, und personenbezogene Falldaten schon
gar nicht. In den Vault gehen nur der Anker und die Ergebnisse.

```
vault.is_locked()                  # zuerst — nach dem Repro-Lock wird nicht mehr geschrieben
vault.add_paper(paper_id="erhebung-2026", source_kind="primary", ...)
vault.add_figure(paper_id="erhebung-2026", figure_id="t1",
                 caption="Gruppenvergleich Score (t-Test)",
                 data_extracted_json="<Ergebnis-Objekt aus ergebnisse.json>")
vault.add_decision(category="auswertung",
                   decision="Welch-Test statt Student-t (Levene p = 0.01)",
                   rationale="Varianzhomogenität verletzt, Entscheidung des Autors")
```

Meldet `vault.is_locked()` einen gesperrten Vault, sag das und schreib nichts —
die Auswertung selbst bleibt davon unberührt, die Dateien unter `empirie/`
liegen ja vor. Die Verbindung zwischen Bericht und Rohdatei ist der SHA-256 im
Protokoll, nicht eine Kopie der Falldaten.

## Deutung

Du formulierst **keine inhaltliche Deutung**. Kein „das bekräftigt die
Annahme", kein „der Unterschied spricht für". Das Protokoll endet an jeder
Stelle mit `Deutung: [vom Autor zu ergänzen]`, und dabei bleibt es. Was ein
Effekt von g = 0.62 für die Fragestellung heißt, entscheidet die Autorin — und
schreibt es im `chapter-writer` selbst.

Zulässig und erwünscht ist dagegen die Testentscheidung („H₀ wird bei α = 0.05
verworfen"): Das ist eine Rechenregel, keine Aussage über die Welt.

## Abgrenzung

- `methodology-advisor` wählt Design und Methode **vor** der Erhebung; hier
  wird die gewählte Methode ausgeführt.
- `instrument-design` baut das Erhebungsinstrument, ebenfalls davor.
- `qualitative-coding` wertet eigenes **Textmaterial** aus (Transkripte,
  Kategorien); dieser Skill ausschließlich Zahlen aus eigener Erhebung.
- Der `meta-analysis`-Agent rechnet über Effektstärken **fremder** Studien
  (DerSimonian-Laird, I², τ²); hier geht es um den eigenen Rohdatensatz.
- `chapter-writer` schreibt das Ergebniskapitel aus diesem Protokoll — dort
  entsteht die Deutung, nicht hier.
