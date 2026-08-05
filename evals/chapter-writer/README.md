# chapter-writer — Offline-Qualitaetsmetrik (Issue #606)

**Status in `docs/evals/STRATEGY.md`: `metric`.**

## Was hier gemessen wird

**Zitatintegritaet am fertigen Kapitelentwurf** — nicht Stil, nicht Argumentation.
Der Grund fuer diese Auswahl: Ein Formulierungsfehler faellt beim Lesen auf, ein
erfundener Beleg nicht. Genau dieser Defekt landet in der abgegebenen Arbeit.

Drei Pruefpfade je Entwurf, alle gegen einen aus `corpus.json` aufgebauten
temporaeren Vault:

| Pfad | Produktionsfunktion | Was ein Fehlschlag bedeutet |
| --- | --- | --- |
| Beleg loest auf | `academic_vault.server.verify_citations()` | erfundene Quelle |
| Direktzitat ist woertlich | `academic_vault.server.search_quote_text()` | verfaelschter Wortlaut |
| Zitatdichte >= 5/1000 Woerter | Schwelle aus `skills/chapter-writer/references/quality-review-config.md` | zu wenig belegt |

Erkannt werden beide im Deutschen ueblichen Belegformen: narrativ `Bauer (2021)`
und klammernd `(Weiss, 2018)`. Nur die klammernde zu kennen haette in einem
realen Entwurf die Mehrzahl der Belege uebersehen.

## Zaehlregel fuer Woerter (nachrechenbar)

Ueberschriften und Klammern mit Jahreszahl werden entfernt, danach werden
Whitespace-getrennte Tokens mit mindestens einem Buchstaben oder einer Ziffer
gezaehlt. Beispiel `drafts/cw-02-datenschutz.md`: 159 Tokens im Rohtext, minus 4
Tokens Ueberschrift, minus 3 Klammerbelege = **152** — der committete Sollwert.

## Gegenprobe

`counter_examples.json` haelt drei Entwuerfe mit je **genau einem** Defekt. Dass
es genau einer ist, prueft `test_each_defect_path_is_covered_exactly_once`:
sonst waere nicht belegt, welcher Pruefpfad ausschlaegt.

| Fall | Defekt | Befund |
| --- | --- | --- |
| `ce-cw-01` | `(Lindner, 2017)` liegt nicht im Vault | nicht aufloesbarer Beleg |
| `ce-cw-02` | ein Wort im Direktzitat getauscht (`Nachteile` -> `Vorteile`) | nicht woertliches Direktzitat |
| `ce-cw-03` | 263 Woerter, ein Beleg | Zitatdichte 3,9/1000 < 5,0 |

## Grenzen dieser Zahl

Die Entwuerfe sind **hand-autoriert und synthetisch**, nicht aus Live-Laeufen des
Skills. Gemessen wird die Trennschaerfe gegen bekannte Defekte, nicht die
Qualitaet dessen, was das Modell heute schreibt. Und gemessen wird
Zitat*integritaet*, nicht Kapitel*qualitaet*: ob ein Kapitel gut argumentiert,
bleibt ein Modellurteil und ist hier ausdruecklich nicht abgedeckt.

## Ausfuehren

```
python3 evals/chapter-writer/runner.py
uv run pytest tests/evals/test_chapter_writer_metrics.py
```
