# Eval-Report — Erweitertes NLI-Goldset ins Repo aufgenommen (Issue #721)

> **Historisches Dokument.** Momentaufnahme einer einzelnen Aufnahme, nicht
> der aktuelle Stand. Der Sollzustand steht in [`STRATEGY.md`](STRATEGY.md).

[← Doku-Übersicht](../README.md)

**Datum:** 2026-08-06
**Komponente:** `evals/524-nli-prefilter/` (NLI-Batch-Vorfilter-Eval, Issue #524/#592/#720)
**Grundlage:** Issue #721 — 186 Fälle aus 30 echten Open-Access-Papern, geliefert
als Rohdaten in vier Issue-Kommentaren, hier ins Repo übernommen.

## Was neu dazukommt

Das bestehende Goldset deckte 92 Fälle ab: 32 konstruierte Paare (`cases.json`,
Issue #524) plus 60 reale Zitat-Paare aus 15 ML/NLP-Papern (`real-cases.json`,
Issue #592). `real-cases.json` benennt selbst die Lücke: „nur 15 Quell-Paper
aus einer einzigen Domäne". Issue #721 schließt diese Lücke mit **186
zusätzlichen Fällen aus 30 Papern über acht Fachrichtungen** (Medizin, Public
Health, Psychologie, Pädagogik, Soziologie, Wirtschaft, Umwelt, Informatik) —
zusammen 278 Fälle, die Grundlage der Modellentscheidung in Issue #720
(Wechsel auf `bge-m3-zeroshot-v2.0`, Schwelle 0,95).

## Konstruktionsregel statt Einzelurteil

Der methodisch entscheidende Punkt: Ein Goldset, dessen Labels aus einer
einzelnen Einschätzung stammen, misst am Ende nur die Übereinstimmung mit
dieser Einschätzung — nicht Verzerrungserkennung an sich. Die 186 neuen Fälle
vermeiden das, indem jede `verzerrend`-Variante durch eine **feste
Transformationsregel** aus der zugehörigen `faithful`-Wiedergabe entsteht,
nicht durch eine gesonderte Bewertung:

| Verzerrungstyp | Transformationsregel |
| --- | --- |
| `overgeneralization` | Quantor oder Geltungsbereich ausweiten |
| `condition-stripped` | Bedingung, Population oder Einschränkung weglassen |
| `causal-overreach` | Assoziation als Kausalität darstellen |
| `magnitude-inflation` | Effektgröße über den berichteten Wert hinaus steigern |
| `significance-flip` | nicht signifikanten Befund als Wirkung darstellen |

Prämissen sind unveränderte Abstract-Ausschnitte (samt Vor- und Nachsatz) aus
30 Open-Access-Papern, abgerufen über die OpenAlex-API
(`evals/524-nli-prefilter/fetch_abstracts.py`), Satzauswahl über ein
signalwortbasiertes Skript (`pick_sentences.py`). Jeder Fall trägt in
`source.doi` die DOI des Quellpapers — damit ist jede Behauptung auf ihr
Quellpaper rückführbar, unabhängig von der Konstruktion.

## Set-Aufbau

- **186 Fälle**, generiert aus `set_med.json` (94, Medizin + Public Health)
  und `set_soz.json` (92, Psychologie/Pädagogik/Soziologie/Wirtschaft/Umwelt/
  Informatik) über `build_extended_cases.py`, das `pick` (1-basiert) gegen
  die Quellsätze in `picks.json` auflöst.
- **Balance: 92 `faithful` / 94 `verzerrend`.**
- **Alle fünf Verzerrungstypen vertreten** (`overgeneralization`,
  `condition-stripped`, `causal-overreach`, `magnitude-inflation`,
  `significance-flip`) — geprüft in
  `tests/evals/test_nli_prefilter_evals.py::test_extended_cases_cover_all_five_verzerrend_types`.
- **Feldstruktur wie `real-cases.json`** (`id`, `claim_lang`, `context_lang`,
  `verzerrend_type`, `chapter_claim`, `context_before`, `verbatim`,
  `context_after`, `label`), ergänzt um `source` (hier: `doi`/`title`/`field`/
  `year` statt `arxiv_id`/`url` — DOI ist die naheliegende
  Rückführbarkeits-Kennung für nicht-arXiv-Quellen).
- Sprache wie im bestehenden Set: `claim_lang: "de"`, `context_lang: "en"` —
  deutsche Kapitelprosa zitiert englische Quellen, der reale Anwendungsfall.

## Reproduktion der #720-Schwellenkurve

Issue #720 dokumentiert einen A/B-Lauf über alle 278 Fälle (32 + 60 + 186)
zwischen `mDeBERTa-v3-XNLI` und `bge-m3-zeroshot-v2.0`. Bei Schwelle 0,95:

| Modell | Durchgerutschte Verzerrungen (FP) |
| --- | --- |
| `bge-m3-zeroshot-v2.0` | 1 |
| `mDeBERTa-v3-XNLI` | 10 |

`tests/evals/test_nli_prefilter_evals.py::test_live_threshold_curve_matches_720_report`
reproduziert diese beiden Zahlen gegen die 278 im Repo liegenden Fälle —
Opt-in per `RUN_LIVE_NLI_PREFILTER=1` (Modell-Download, Netz nötig), analog zu
den bestehenden Live-Tests aus #524/#592. **Im Build-Sandbox dieses PRs nicht
ausgeführt** (kein Netz verfügbar); der hermetische Teil der Suite (Feld-
struktur, DOI-Format, Label-Balance, Typ-Abdeckung, ID-Eindeutigkeit) läuft
immer, ohne Netz, und ist grün.

## Grenze: konstruierte Verzerrungen sind nicht dasselbe wie im Feld beobachtete

Die Transformationsregel macht das Set methodisch sauberer als ein
Einzelurteil — sie macht es nicht repräsentativ für reale Fehler. Alle 186
verzerrten Fälle entstehen durch eine von fünf festen, absichtlich
angewandten Transformationen an einer bekannten treuen Wiedergabe. Reale
Verzerrungen in tatsächlich verfassten Kapiteln können:

- mehrere Transformationstypen gleichzeitig kombinieren (nicht isoliert wie
  hier),
- subtiler ausfallen als eine regelbasierte Konstruktion (z. B. eine
  schleichende Bedeutungsverschiebung über mehrere Sätze hinweg, nicht ein
  einzelner isolierter Satz),
- Verzerrungstypen enthalten, die die fünf Regeln hier nicht abbilden.

Ein Precision/Recall-Wert auf diesem Set ist damit ein **Signal für die
Trennschärfe des Modells zwischen einer treuen Wiedergabe und ihrer geregelten
Transformation** — kein Beleg für die Fehlerrate auf im Feld beobachteten,
unregelmäßig entstandenen Verzerrungen. Dieselbe Einschränkung gilt bereits
für die 32 konstruierten Fälle aus #524 und in abgeschwächter Form für die 60
realen, aber händisch verzerrten Fälle aus #592 — das erweiterte Set
vergrößert die Stichprobe und die fachliche Streuung, ändert aber nichts an
dieser grundsätzlichen Grenze.

## Dateien

| Datei | Inhalt |
| --- | --- |
| `set_med.json` / `set_soz.json` | Rohdaten der 186 Fälle (unverändert aus den Issue-#721-Kommentaren übernommen) |
| `picks.json` | 30 Paper mit Quellsätzen, Kontext, Feld, DOI, Titel, Jahr — von `pick` (1-basiert, alle Paper nacheinander) referenziert |
| `fetch_abstracts.py` | Ruft Open-Access-Abstracts über die OpenAlex-API ab (rekonstruiert `abstract_inverted_index`) — Abrufweg für künftige Erweiterungen |
| `pick_sentences.py` | Wählt aus jedem Abstract die zitierfähigen Ergebnissätze (Signalwort-Heuristik) |
| `run_big.py` | 278-Fälle-A/B-Vergleich `mDeBERTa-v3-XNLI` vs. `bge-m3-zeroshot-v2.0` (Grundlage von #720) |
| `bidir.py` | Verworfener bidirektionaler NLI-Ansatz gegen `condition-stripped` (dokumentarisch aufbewahrt, siehe #720) |
| `build_extended_cases.py` | Baut `extended-cases.json` aus den drei Rohdateien |
| `extended-cases.json` | Generiertes Ergebnis: 186 Fälle im `real-cases.json`-Feldformat |

## Ausführen

```bash
# Struktur-Checks (immer, ohne Netz):
uv run pytest tests/evals/test_nli_prefilter_evals.py -q

# Erweitertes Set neu generieren:
python3 evals/524-nli-prefilter/build_extended_cases.py

# Live-Reproduktion der #720-Schwellenkurve (Netz + Modell-Download):
RUN_LIVE_NLI_PREFILTER=1 uv run pytest tests/evals/test_nli_prefilter_evals.py -q -k threshold_curve

# 278-Fälle-A/B-Vergleich direkt (Netz + Modell-Download, ~1-2 GB):
python3 evals/524-nli-prefilter/run_big.py
```
