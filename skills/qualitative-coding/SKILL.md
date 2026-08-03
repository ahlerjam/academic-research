---
name: qualitative-coding
description: >
  Verwende diesen Skill, wenn der User eigenes Erhebungsmaterial auswerten will:
  ein Transkript in den Vault aufnehmen, Kategorien bilden und die Kodierungen
  zu einer Übersicht für das Ergebniskapitel verdichten. Trigger-Phrasen:
  "Transkript kodieren", "Interview auswerten",
  "Kategorien aus dem Material bilden",
  "Kodierleitfaden erstellen", "induktive und deduktive Kategorien",
  "qualitative Inhaltsanalyse durchführen / qualitative Inhaltsanalyse
  durchfuehren", "Transkript in den Vault aufnehmen",
  "Kodier-Übersicht für das Ergebniskapitel / Kodier-Uebersicht fuer das
  Ergebniskapitel". Nutzt `${CLAUDE_PLUGIN_ROOT}/skills/qualitative-coding/scripts/transcript_import.py`
  für Segmentierung, Vault-Schreiben und Rendering; die inhaltliche
  Kategorienbildung bleibt Dialog. Das Instrument selbst entsteht in
  `instrument-design`, Exzerpte aus fremder Literatur in `reading-notes`.
license: MIT
allowed-tools: [Bash, Read, Write]
---

# Qualitative Kodierung

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Zweck

Eigenes Erhebungsmaterial unterliegt derselben Nachweispflicht wie Literatur:
Ein Interviewzitat im Ergebniskapitel muss auf eine konkrete Stelle im
Transkript zurückführbar sein. Dieser Skill sorgt dafür, dass die Stelle
existiert, bevor das Zitat geschrieben wird.

## Datenmodell

| Vault-Objekt | Bedeutung |
| --- | --- |
| `papers` mit `source_kind='primary'` | Das Transkript als Ganzes (Interview, Protokoll) |
| `transcript_segments` | Ein Absatz = eine zitierfähige Stelle, `seq` = „Abs. n" |
| `quotes` | Wörtliches Zitat aus dem Material, `section="Abs. n"` |
| `codings` | Kategorie ↔ Stelle, mit `category_origin` (induktiv/deduktiv) |
| `decisions` mit `category="kodierung"` | Das methodische Vorgehen |

Warum das Transkript eine `papers`-Zeile ist: Nur so greift die bestehende
Belegkette. `hooks/verbatim-guard.mjs` prüft jedes Zitat in `kapitel/*.md`
gegen `quotes` — ein Interviewzitat wird damit genauso blockiert wie ein
erfundenes Literaturzitat, ohne Sonderweg. Unterschieden werden beide über
`source_kind`, nicht über den CSL-Typ; Literatur-Exporte
(`scripts/export-literature-state.mjs`) filtern Primärmaterial heraus.

## Schritt 1 — Transkript aufnehmen

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/qualitative-coding/scripts/transcript_import.py \
  --db "$VAULT_DB_PATH" import \
  --paper-id interview-01 --file empirie/interview-01.txt \
  --title "Interview 01 (Fachkraft, 12.03.)"
```

Erwartetes Format: ein Absatz je Redebeitrag, Leerzeile dazwischen. Optionaler
Timecode `[00:12:35]` und optionales Sprecherkürzel `B1:` am Absatzanfang
werden in eigene Felder gezogen, damit sie nicht im Zitattext landen.

Der Import ist idempotent: `seq` wird aus der Absatzreihenfolge abgeleitet, die
`segment_id` deterministisch aus `(paper_id, seq)`. Ein zweiter Lauf über
dieselbe Datei aktualisiert die Stellen, statt sie zu verdoppeln — eine
nachträglich korrigierte Transkriptzeile behält also ihre Stellenangabe.

Prüfe danach `vault.list_transcript_segments("interview-01")` und zeig dem User
die Zahl der Segmente. Weicht sie stark von seiner Erwartung ab, liegt es fast
immer am Absatzformat — nicht raten, sondern nachfragen.

## Schritt 2 — Kategorien bilden

Zwei Wege, beide zulässig, beide dokumentiert:

- **induktiv** — die Kategorie entsteht am Material. Vorgehen: Segmente
  durchgehen, Paraphrase bilden, auf das mit dem User vereinbarte
  Abstraktionsniveau verallgemeinern, ähnliche Paraphrasen bündeln.
- **deduktiv** — die Kategorie kommt aus der Theorie. Vorgehen: Kategorie und
  Definition aus der Literatur belegen (`vault.find_quotes()`), dann Stellen
  suchen, die darunterfallen.

Vor dem ersten Kodieren mit dem User festlegen und wörtlich notieren:

1. **Verfahrensreferenz** — nach welchem Verfahren gearbeitet wird.
2. **Abstraktionsniveau** — wie allgemein eine Kategorie sein soll.
3. **Selektionskriterium** — welches Material überhaupt kodiert wird.

Ohne diese drei Angaben startet der Kodierdurchgang nicht. Sie sind später der
Methodenteil; nachträglich rekonstruiert wären sie eine Erfindung.

Jede Zuordnung wird geschrieben als:

```
vault.add_coding(paper_id="interview-01", category="Teamabstimmung",
                 category_origin="induktiv", segment_id="interview-01#seg-5",
                 quote_id="q-interview-01-5",
                 memo="Kodierregel: Aussagen über Abstimmungsroutinen im Team")
```

`category_origin` ist Pflicht (`induktiv` oder `deduktiv`) — ein dritter Wert
wird abgewiesen. Das Ankerbeispiel (`quote_id`) verweist auf ein echtes Zitat
aus `vault.add_quote()`; solange keines ausgewählt ist, bleibt das Feld leer.
**Ein Ankerzitat wird nie formuliert, sondern immer aus dem Material zitiert.**

## Schritt 3 — Kodierleitfaden und Übersicht

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/qualitative-coding/scripts/transcript_import.py \
  --db "$VAULT_DB_PATH" codebook \
  --paper-id interview-01 --output empirie/kodierleitfaden.md \
  --verfahren "Qualitative Inhaltsanalyse nach Mayring (zusammenfassend)" \
  --abstraktionsniveau "Handlungsroutinen im Arbeitsalltag" \
  --selektionskriterium "Aussagen zur Zusammenarbeit im Team"

python3 ${CLAUDE_PLUGIN_ROOT}/skills/qualitative-coding/scripts/transcript_import.py \
  --db "$VAULT_DB_PATH" overview --paper-id interview-01
```

`codebook` schreibt Definition, Ankerbeispiel, Kodierregel und Herkunft je
Kategorie und legt zusätzlich einen `decisions`-Eintrag mit
`category="kodierung"` an — das dokumentierte Vorgehen. `overview` rendert die
Tabelle für das Ergebniskapitel: Kategorie, Herkunft, Häufigkeit, Ankerzitat.

Beide Ausgaben markieren Fehlendes ausdrücklich („kein Ankerzitat hinterlegt",
„Kodierregel noch nicht festgehalten"), statt es zu füllen. Diese Marker sind
die Arbeitsliste — arbeite sie mit dem User ab, statt sie wegzuschreiben.

## Häufigkeiten richtig lesen

Die Übersicht zählt Kodierungen, nicht Personen und nicht Zustimmung. Formuliere
im Ergebniskapitel entsprechend („in 7 Stellen bei 3 Befragten"), nie als
Prozentangabe über eine qualitative Stichprobe. Für eine statistische Auswertung
quantitativer Daten ist dieser Skill der falsche Ort.

## Abgrenzung

- `instrument-design` baut das Erhebungsinstrument **vor** der Erhebung.
- `methodology-advisor` wählt die Methode; hier wird sie ausgeführt.
- `reading-notes` und `extraction-matrix` arbeiten mit **fremder Literatur**;
  dieser Skill ausschließlich mit eigenem Erhebungsmaterial (`source_kind='primary'`).
- `citation-extraction` zieht Zitate aus PDFs; Transkriptzitate entstehen hier.
- Die statistische Auswertung eigener quantitativer Erhebungsdaten gehört zu
  `quantitative-analysis` — dort mit Voraussetzungsprüfung, Effektstärke und
  Konfidenzintervall.

## Personenbezogene Daten

Transkripte landen im Klartext in der Vault-DB. Verwende Sprecherkürzel
(`B1`, `IP2`) statt Klarnamen und weise den User darauf hin, bereits die
importierte Datei anonymisiert zu halten. Das ist ein Hinweis, **keine
Datenschutz-Beratung** und ersetzt keine Rechtsauskunft.
