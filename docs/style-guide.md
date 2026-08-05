# Schreibregeln und Glossar-Pflicht

[← Doku-Übersicht](README.md)

Diese Seite legt fest, wie neue Nutzer-Doku in diesem Repo klingt — bevor du sie
schreibst, nicht danach. Fünf Regeln, je ein Beispielpaar aus echtem Bestand: ein
Vorher, das die Regel bricht, ein Nachher, das sie einhält. Beide Zitate sind
wörtlich, mit Fundstelle. Unbekannte Begriffe klärst du im
[Glossar](reference/glossary.md).

## Zielgruppe

Die Regeln gelten für Texte, die **Studierende und Promovierende** lesen, die mit
dem Plugin ihre Arbeit schreiben — von der ersten Suche bis zur Abgabe. Diese
Zielgruppe bringt ihr Fachgebiet und ihre Forschungsfrage mit, keine
Programmiererfahrung.

Was sie **nicht mitbringen**: Vorwissen über Retrieval-Verfahren (BM25, Vektor-Suche,
RRF), die Claude-Code-Plugin-Architektur oder Python. Jeder Fachbegriff, den eine
Seite braucht, steht dort erklärt oder im Glossar — nie einfach vorausgesetzt.

## Regel 1 — Ansprache: durchgehend „du“

Sprich die Leserin direkt an. Kein unpersönliches Passiv, wenn eigentlich sie
gemeint ist.

**Vorher** (`docs/reference/vault.md:16-18`): „Der `verbatim-guard`-Hook prüft
jeden `Write`-Aufruf auf `kapitel/**/*.md` (Unterordner eingeschlossen) und
`*.tex`: enthaltene Zitate werden gegen den Vault geprüft.“

**Nachher** (`docs/guide/getting-started.md:10`): „Am Ende jedes Schritts steht,
woran du erkennst, dass er geklappt hat.“

## Regel 2 — Satzlänge: ein Gedanke, ein Satz

Trenn lange Schachtelsätze. Ein Nebensatz pro Satz ist die Grenze, keine Richtung
zum Ausreizen.

**Vorher** (`CHANGELOG.md:1322`, 56 Wörter in einem Satz): „`run_search()` in
`scripts/search.py` wartete bisher unbegrenzt über
`concurrent.futures.as_completed()`, bis alle 7 Modul-Futures fertig waren —
insbesondere der EconStor-OAI-PMH-Fallback aus #236 (bis zu `OAI_MAX_PAGES=5` ×
`TIMEOUT=30s` ≈ 150s Worst-Case, laut #456 aktuell der Live-Normalfall, da
`econstor.eu`'s REST-Endpunkt durchgehend HTTP 405 liefert) konnte den gesamten
Lauf um Minuten verzögern, ohne dass die übrigen, längst fertigen Treffer
ausgeliefert wurden.“

**Nachher** (`docs/guide/getting-started.md:68`): „Das Setup ist idempotent: Ein
zweiter Aufruf zerstört nichts.“

## Regel 3 — Fachbegriffe: erklärt vor dem ersten Gebrauch

Ein neuer Begriff bekommt beim ersten Auftreten eine Erklärung im Fließtext oder
einen Link ins Glossar. Das gilt besonders für den **Einstiegspfad** — die fünf
Seiten unter „Ich fange gerade an“ in der Doku-Übersicht, wo Erstleser ohne
Vorwissen ankommen.

**Vorher** (`docs/evals/recall-at-k-model-ab-375.md:25`): „FTS5 + vec0-KNN via
RRF fusioniert“ — drei Fachbegriffe hintereinander, keiner erklärt.

**Nachher** (`docs/reference/vault.md:29-30`): „... führt die KNN-Treffer per
Reciprocal-Rank-Fusion mit dem BM25-Ranking zusammen.“ — der volle Name steht vor
der Abkürzung, `RRF` folgt erst später im selben Dokument.

## Regel 4 — Zahlen und Versprechen: nur mit Beleg

Jede Zahl braucht eine Quelle, die sich nachzählen lässt: Code, Test oder Messung.
Ein Versprechen ohne Mechanismus dahinter ist Werbung, keine Doku.

**Vorher** (`CHANGELOG.md:1362`, seit #453 korrigiert): *„Universal Book Fetcher
(8-Tier-Pipeline)"* — der Begriff „Tier" kam im Code nirgends vor.

**Nachher** (`CHANGELOG.md:1362`): *„10 Fetcher-Subagenten mit Fallback-Kette"*
— Zählbasis: die `Agent(...)`-Tools im `book-fetcher`-Frontmatter.

## Regel 5 — keine Werbesprache, keine leeren Steigerungen

Steigerungswörter aus einer kleinen Verbotsliste beschreiben nichts Prüfbares.
Schreib, was gemessen wurde, und was die Zahl nicht bedeutet.

**Vorher** (`docs/evals/recall-at-k-model-ab-375.md:45-46`): „perfekten
Recall@10 = 1.0“ — klingt nach Werbung, wenn es allein steht.

**Nachher** (`docs/evals/recall-at-k-model-ab-375.md:51-52`): „Das ist ein
Deckeneffekt (ceiling effect), kein Qualitaetsunterschied zwischen den
Modellen“ — derselbe Befund, sofort eingeordnet.
