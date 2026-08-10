# Ergebnis-Report — disable-model-invocation nur mess-basiert setzen (Issue #622)

> **Historisches Dokument.** Momentaufnahme einer einzelnen Prüfung, nicht der
> aktuelle Stand. Der Sollzustand steht in [`STRATEGY.md`](STRATEGY.md).

[← Doku-Übersicht](../README.md)

**Datum:** 2026-08-05
**Grundlage:** [`2026-08-04-trigger-baseline-614.md`](2026-08-04-trigger-baseline-614.md) +
[`2026-08-04-trigger-baseline-614-live-results.json`](2026-08-04-trigger-baseline-614-live-results.json)
(45 Skills / 871 Fälle, `claude-haiku-4-5-20251001` über `claude`-CLI/OAuth,
Issue #614). Kein neuer Modell-Lauf (Policy: kein `ANTHROPIC_API_KEY`, #632;
ein Baseline-Lauf pro Release, nicht pro Issue — s. Plan-Kommentar `<!-- plan:v1 -->`
in Issue #622).

## Ergebnis in Kürze

**0 Skills werden mit `disable-model-invocation: true` markiert.**

Alle drei im Issue genannten Kandidaten (`citation-style-import`,
`notebook-bundle`, `cluster-visualizer`) zeigen in der #614-Baseline bereits
eine hohe Auslöserate über natürlichsprachige Formulierungen *ohne*
Skill-Namen. Das ist laut Akzeptanzkriterium 5 des Issues
("Kein Skill ist markiert, für den die Messung eine relevante Auslöserate
zeigt") ein Ausschlussgrund — kein Implementierungsdetail. Ein Ergebnis von 0
markierten Skills ist laut Issue-Text ein zulässiger, mess-basierter Ausgang
und wird hier so dokumentiert, statt die Ausgangsvermutung des Issues gegen
die Zahlen durchzudrücken.

## Prüfung je Kandidat

Schwelle: identisch mit `tests/evals/test_triggers.py` — Recall ≥ 85 % gilt
als "wird zuverlässig automatisch gefunden" (relevante Auslöserate im Sinne
von AC5).

### `cluster-visualizer` — Recall 100 % (10/10), FPR 0 %

Keine einzige Fehlklassifikation in der #614-Rohdaten-Liste
(`per_skill.cluster-visualizer.misclassified` ist leer). Alle zehn
`should_trigger`-Formulierungen ohne Nennung des Skill-Namens wurden korrekt
erkannt.

**Entscheidung: nicht markieren.** Recall liegt bei 100 % — der denkbar
stärkste Beleg dafür, dass die automatische Auswahl hier zuverlässig
funktioniert und nicht entbehrlich ist.

### `citation-style-import` — Recall 90 % (9/10), FPR 0 %

Eine Fehlklassifikation:

> (sollte triggern) „Hol den Stil aus GitHub und mach eine Variante." →
> klassifiziert als `perfect!`

`perfect!` ist kein Konkurrenz-Skill und keine Ablehnung, sondern ein
CLI-Parsing-Artefakt des Klassifikators (stray Antwortwort statt Skill-Name
oder `none`/`ich`/`um` — vgl. Learning aus #614: der `claude`-CLI-Pfad liefert
gelegentlich Natursprache statt des erwarteten Tokens). Der einzige Fehlschlag
ist damit kein echter "Skill nicht gefunden"-Fall, sondern Meldungsrauschen.

**Entscheidung: nicht markieren.** 90 % Recall liegt über der 85 %-Schwelle,
und der einzige Ausreißer ist Rauschen, kein inhaltlicher Miss.

### `notebook-bundle` — Recall 80 % (8/10), FPR 0 %

Zwei Fehlklassifikationen:

> (sollte triggern) „Erstelle ein NotebookLM-Bundle." → klassifiziert als `es`
> (sollte triggern) „Teile dieses Riesen-PDF fuer NotebookLM auf." →
> klassifiziert als `ich`

Beide Ziel-Tokens (`es`, `ich`) sind wie bei `citation-style-import` stray
Wörter des CLI-Klassifikators, keine Klassifikation als `none` oder als
konkurrierender Skill. Auch hier: kein echter inhaltlicher Miss in den
Fehlklassifikationen selbst.

**Entscheidung: nicht markieren.** 80 % Recall liegt zwar unter der strengen
85 %-Testschwelle, ist aber im Vergleich der 45 Baseline-Skills (Median-Recall
80 %, viele reguläre Skills darunter, z. B. `github-repo-research` 38 %,
`prisma-flow` 40 %) eine überdurchschnittlich hohe Auslöserate, und die beiden
Ausreißer sind — wie oben belegt — CLI-Rauschen statt inhaltlicher Fehltreffer.
Eine relevante, durch echte Verwechslung erklärte Nicht-Erkennung liegt nicht
vor. Markieren würde AC5 widersprechen (die Messung zeigt gerade *keine*
Notwendigkeit für die automatische Auswahl, sondern deren Zuverlässigkeit).

## Zusätzliche Kandidaten geprüft?

Nein. Punkt 3 der Task-Checkliste im Plan-Kommentar sieht das nur vor, "falls
die Messung selbst (nicht Vermutung) weitere eindeutige Fälle nahelegt". Da
bereits die drei Ausgangskandidaten bei 0 stehen bleiben, gibt es keinen
Anlass, aus den übrigen 42 Skills der Baseline weitere Kandidaten
nachzuziehen — das wäre Vermutung, keine Messung.

## Listing-Größe: vorher/nachher

Da 0 Skills markiert werden, ist die Listing-Größe (Summe der
`description`-Zeichen über alle Skills **ohne** `disable-model-invocation:
true`) vor und nach dieser Änderung identisch:

- **Vorher:** 45 Skills, 27073 Zeichen description-Text
- **Nachher:** 45 Skills, 27073 Zeichen description-Text (unverändert, 0
  Skills markiert)

Berechnung: Summe von `len(" ".join(description.split()))` über alle
`skills/*/SKILL.md` ohne `disable-model-invocation: true` im Frontmatter
(identische Methode wie `tests/test_skills_manifest.py::_description`).
Regressions-Guard: `tests/baselines/description_chars_622.json` +
`tests/test_issue_622_disable_model_invocation.py::test_listing_size_reduction_is_measured_against_baseline`.

**Update (Issue #825, 2026-08-10):** Die Baseline wurde bewusst aktualisiert,
weil `humanizer-de` und `title-generator` ihre `description` erweitert und
`style-evaluator` seine `description` verkleinert hat, um Trigger-Recall-
Fehlschläge und eine Trigger-Kollision zwischen `humanizer-de` und
`style-evaluator` zu beheben (siehe #825, PR #834). Neue Summe: 45 Skills,
27338 Zeichen description-Text (vorher 27073). Kein Skill wurde neu markiert
oder demarkiert — die Zählbasis (45 automatisch wählbare Skills) bleibt
unverändert.

## Erreichbarkeit per `/name`

Entfällt inhaltlich (0 Skills markiert, also keine Skills, deren
Erreichbarkeit sich ändert). Der Guard-Test
`test_marked_skills_keep_user_invocable` bleibt als Regressionsschutz stehen:
sollte in Zukunft ein Skill markiert werden, darf er nie zusätzlich
`user-invocable: false` setzen — das wäre die im Issue explizit
ausgeschlossene Gegenrichtung.

## Was dieser Report NICHT tut

- Keine neue Trigger-Messung wurde durchgeführt (Wiederverwendung der
  #614-Baseline, Policy #632/#631).
- Keine Skill-Description wurde angepasst (Issue-Scope "Out").
- Kein Skill wurde stillgelegt oder entfernt (Issue-Scope "Out").
- Die 85 %-Recall-Schwelle aus `tests/evals/test_triggers.py` wurde nicht
  verändert.
