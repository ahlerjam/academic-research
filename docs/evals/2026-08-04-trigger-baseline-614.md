# Eval-Report — Trigger-Evals real gemessen, erste Baseline (Issue #614)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Laufs, nicht der
> aktuelle Stand. Der Sollzustand steht in [`STRATEGY.md`](STRATEGY.md).

[← Doku-Übersicht](../README.md)

**Datum:** 2026-08-04
**Komponente:** `tests/evals/test_triggers.py` (Klassifikationslogik
wiederverwendet, nicht dupliziert) über alle Skills mit `trigger_evals.json`
**Modell:** `claude-haiku-4-5-20251001`
**Aufrufpfad:** `claude`-CLI/OAuth-Session (Issue #631) — kein
`ANTHROPIC_API_KEY` verwendet (repo-weit verboten, Issue #632)
**Skript:** `scripts/dev/run_trigger_baseline.py` (neu, Issue #614)

## Vorgeschichte

Die 45 `trigger_evals.json`-Dateien unter `evals/` waren seit ihrer Anlage nie
real gelaufen: `tests/evals/test_triggers.py` skippt ohne `ANTHROPIC_API_KEY`
oder `claude`-CLI, und `eval-behavior.yml` hatte bis zu diesem Lauf null
Ausführungen. Die Frage „wie zuverlässig wählt Claude bei N Skills den
richtigen aus" war damit nicht *schlecht beantwortet*, sondern **unbeantwortet**.

**Zahlenkorrektur zum Issue-Text:** Issue #614 nennt „39 Skills, 765
Prüffälle". Live nachgezählt zum Zeitpunkt dieses Laufs: **45
Skills, 871 Fälle** (427 `should_trigger` +
442 `should_not_trigger`) — seither sind mehrere Skills mit
eigener `trigger_evals.json` dazugekommen (u. a. `bibliography-auditor` #676,
`preregistration` #607, `data-management-plan` #609, `peer-review` #608).

## Ergebnis je Skill

| Skill | Recall | Hits/Total | FPR | FalsePos/Total | CLI-Fehler |
|---|---|---|---|---|---|
| `abstract-generator` | 90% | 9/10 | 0% | 0/10 | 0 |
| `academic-context` | 64% | 7/11 | 0% | 0/10 | 0 |
| `advisor` | 90% | 9/10 | 0% | 0/10 | 0 |
| `ai-disclosure` | 88% | 7/8 | 0% | 0/10 | 0 |
| `anchor-paper-survey` | 75% | 6/8 | 0% | 0/10 | 0 |
| `bibliography-auditor` | 88% | 7/8 | 0% | 0/10 | 0 |
| `book-handler` | 90% | 9/10 | 0% | 0/10 | 0 |
| `chapter-writer` | 80% | 8/10 | 0% | 0/10 | 0 |
| `citation-extraction` | 50% | 5/10 | 0% | 0/10 | 0 |
| `citation-style-import` | 90% | 9/10 | 0% | 0/10 | 0 |
| `cluster-visualizer` | 100% | 10/10 | 0% | 0/10 | 0 |
| `conference-poster` | 80% | 8/10 | 0% | 0/10 | 0 |
| `data-management-plan` | 62% | 5/8 | 0% | 0/8 | 0 |
| `defense-prep` | 100% | 10/10 | 0% | 0/10 | 0 |
| `extraction-matrix` | 75% | 6/8 | 0% | 0/10 | 0 |
| `github-repo-research` | 38% | 3/8 | 0% | 0/10 | 0 |
| `grant-proposal` | 90% | 9/10 | 0% | 0/10 | 0 |
| `humanizer-de` | 60% | 6/10 | 0% | 0/10 | 0 |
| `instrument-design` | 62% | 5/8 | 0% | 0/10 | 0 |
| `latex-export` | 89% | 8/9 | 0% | 0/10 | 1 |
| `latex-layout-auditor` | 90% | 9/10 | 0% | 0/8 | 0 |
| `literature-excel` | 90% | 9/10 | 0% | 0/9 | 1 |
| `literature-gap-analysis` | 90% | 9/10 | 0% | 0/10 | 0 |
| `material-passport` | 80% | 8/10 | 0% | 0/10 | 0 |
| `methodology-advisor` | 90% | 9/10 | 0% | 0/10 | 0 |
| `notebook-bundle` | 80% | 8/10 | 0% | 0/10 | 0 |
| `parallel-screening` | 75% | 6/8 | 0% | 0/10 | 0 |
| `peer-review` | 90% | 9/10 | 0% | 0/10 | 0 |
| `plagiarism-check` | 90% | 9/10 | 0% | 0/10 | 0 |
| `preregistration` | 100% | 7/7 | 0% | 0/7 | 0 |
| `prisma-flow` | 40% | 4/10 | 0% | 0/10 | 0 |
| `qualitative-coding` | 88% | 7/8 | 0% | 0/10 | 0 |
| `quantitative-analysis` | 70% | 7/10 | 0% | 0/10 | 0 |
| `reading-list-import` | 90% | 9/10 | 0% | 0/10 | 0 |
| `reading-notes` | 75% | 6/8 | 0% | 0/10 | 0 |
| `research-question-refiner` | 80% | 8/10 | 0% | 0/10 | 0 |
| `reviewer-response` | 80% | 8/10 | 0% | 0/10 | 0 |
| `slide-export` | 100% | 10/10 | 0% | 0/10 | 0 |
| `source-quality-audit` | 70% | 7/10 | 0% | 0/10 | 0 |
| `style-evaluator` | 80% | 8/10 | 0% | 0/10 | 0 |
| `submission-checker` | 80% | 8/10 | 0% | 0/10 | 0 |
| `title-generator` | 80% | 8/10 | 0% | 0/10 | 0 |
| `topic-brainstorm` | 100% | 10/10 | 0% | 0/10 | 0 |
| `word-export` | 90% | 9/10 | 0% | 0/10 | 0 |
| `zotero-import` | 70% | 7/10 | 0% | 0/10 | 0 |

Rohdaten (alle Einzelantworten, Fehlklassifikationen, Tokens je Skill):
[`2026-08-04-trigger-baseline-614-live-results.json`](2026-08-04-trigger-baseline-614-live-results.json).

## Schwellenreißer

Schwelle laut `tests/evals/test_triggers.py` (unverändert, Issue-Scope
"Out"): Recall ≥ 85 %, FPR ≤ 10 %.

- **`academic-context`**: Recall 64% (7/11) < 85%
- **`anchor-paper-survey`**: Recall 75% (6/8) < 85%
- **`chapter-writer`**: Recall 80% (8/10) < 85%
- **`citation-extraction`**: Recall 50% (5/10) < 85%
- **`conference-poster`**: Recall 80% (8/10) < 85%
- **`data-management-plan`**: Recall 62% (5/8) < 85%
- **`extraction-matrix`**: Recall 75% (6/8) < 85%
- **`github-repo-research`**: Recall 38% (3/8) < 85%
- **`humanizer-de`**: Recall 60% (6/10) < 85%
- **`instrument-design`**: Recall 62% (5/8) < 85%
- **`material-passport`**: Recall 80% (8/10) < 85%
- **`notebook-bundle`**: Recall 80% (8/10) < 85%
- **`parallel-screening`**: Recall 75% (6/8) < 85%
- **`prisma-flow`**: Recall 40% (4/10) < 85%
- **`quantitative-analysis`**: Recall 70% (7/10) < 85%
- **`reading-notes`**: Recall 75% (6/8) < 85%
- **`research-question-refiner`**: Recall 80% (8/10) < 85%
- **`reviewer-response`**: Recall 80% (8/10) < 85%
- **`source-quality-audit`**: Recall 70% (7/10) < 85%
- **`style-evaluator`**: Recall 80% (8/10) < 85%
- **`submission-checker`**: Recall 80% (8/10) < 85%
- **`title-generator`**: Recall 80% (8/10) < 85%
- **`zotero-import`**: Recall 70% (7/10) < 85%

## Fehlklassifikationen

Fehlklassifikationen sind je Skill in der Rohdaten-JSON unter
`per_skill.<skill>.misclassified` einzeln aufgeführt (Prompt-Text + erhaltene
Klassifikation) — hier die vollständige Liste für jeden Skill unter 100 %
Recall oder über 0 % FPR:

### `abstract-generator`

- (sollte triggern) „Abstract 200 Woerter" -> klassifiziert als `ich`

### `academic-context`

- (sollte triggern) „Mein Abgabetermin ist in 3 Monaten" -> klassifiziert als `none`
- (sollte triggern) „Ich bin an der FH Leibniz, BWL, Bachelor" -> klassifiziert als `none`
- (sollte triggern) „Update mein academic profile" -> klassifiziert als `um`
- (sollte triggern) „Ich moechte spaeter ein Konferenz-Poster aus meiner Arbeit ableiten, trag das im Kontext ein" -> klassifiziert als `verstanden!`

### `advisor`

- (sollte triggern) „Ist meine Argumentation schluessig?" -> klassifiziert als `um`

### `ai-disclosure`

- (sollte triggern) „Ich brauche eine Offenlegungserklärung zur KI-Nutzung für meine Abgabe." -> klassifiziert als `der`

### `anchor-paper-survey`

- (sollte triggern) „Starte einen Survey ausgehend von diesem einen Papier." -> klassifiziert als `um`
- (sollte triggern) „Ich moechte meine Recherche von diesem Paper aus starten: https://arxiv.org/abs/2005.14165." -> klassifiziert als `der`

### `bibliography-auditor`

- (sollte triggern) „Prüf mal mein Literaturverzeichnis auf Vollständigkeit." -> klassifiziert als `es`

### `book-handler`

- (sollte triggern) „Importiere dieses Springer-Buch (DOI 10.1007/978-3-...)." -> klassifiziert als `ich`

### `chapter-writer`

- (sollte triggern) „Schreib die Zusammenfassung" -> klassifiziert als `abstract-generator`
- (sollte triggern) „200 Woerter zu Theorie Y schreiben" -> klassifiziert als `none`

### `citation-extraction`

- (sollte triggern) „Harvard-Zitation bitte" -> klassifiziert als `none`
- (sollte triggern) „DIN 1505-2 Format" -> klassifiziert als `none`
- (sollte triggern) „APA7 Eintrag fuer Smith 2023" -> klassifiziert als `none`
- (sollte triggern) „Chicago Author-Date fuer dieses Paper" -> klassifiziert als `none`
- (sollte triggern) „Bibliographic entry fuer dieses Buch" -> klassifiziert als `none`

### `citation-style-import`

- (sollte triggern) „Hol den Stil aus GitHub und mach eine Variante." -> klassifiziert als `perfect!`

### `conference-poster`

- (sollte triggern) „Mach mir ein tikzposter aus meinen Ergebnissen." -> klassifiziert als `es`
- (sollte triggern) „Poster fuer die Tagung erstellen bitte." -> klassifiziert als `der`

### `data-management-plan`

- (sollte triggern) „Aktualisiere den Datenmanagementplan." -> klassifiziert als `ich`
- (sollte triggern) „Schreib mir den DMP." -> klassifiziert als `es`
- (sollte triggern) „Generiere die datenmanagementplan.md." -> klassifiziert als `ich`

### `extraction-matrix`

- (sollte triggern) „Erstell mir eine Extraktionsmatrix aus meinen Vault-Quellen." -> klassifiziert als `der`
- (sollte triggern) „Stell mir eine Merkmalstabelle aus meinen Quellen zusammen." -> klassifiziert als `ich`

### `github-repo-research`

- (sollte triggern) „Kannst du dieses Repo analysieren und schauen ob es ein Paper dazu gibt?" -> klassifiziert als `ich`
- (sollte triggern) „Analysiere dieses GitHub-Repo: https://github.com/foo/bar." -> klassifiziert als `ich`
- (sollte triggern) „Welches Paper gehoert zu diesem Repository?" -> klassifiziert als `ich`
- (sollte triggern) „Ich will von diesem GitHub-Repository aus recherchieren -- welche Publikation steckt dahinter?" -> klassifiziert als `um`
- (sollte triggern) „Schau in der README nach einem arXiv-Link und lege das Paper im Vault an." -> klassifiziert als `ich`

### `grant-proposal`

- (sollte triggern) „Unterstuetze mich bei der Foerderantragstellung." -> klassifiziert als `leider`

### `humanizer-de`

- (sollte triggern) „Humanisiere diesen deutschen Text." -> klassifiziert als `ich`
- (sollte triggern) „Entferne KI-Floskeln aus diesem Absatz." -> klassifiziert als `ich`
- (sollte triggern) „Pruefe meinen Entwurf auf Anzeichen fuer KI-generierte Inhalte." -> klassifiziert als `style-evaluator`
- (sollte triggern) „Entferne aufgeblaehte Symbolik und Werbesprache aus dem Text." -> klassifiziert als `ich`

### `instrument-design`

- (sollte triggern) „Wie operationalisiere ich meine Forschungsfrage in konkrete Fragen?" -> klassifiziert als `research-question-refiner`
- (sollte triggern) „Woran erkenne ich, dass eine Leitfadenfrage zur Forschungsfrage gehoert?" -> klassifiziert als `das`
- (sollte triggern) „Bau mir ein Beobachtungsraster fuer die teilnehmende Beobachtung." -> klassifiziert als `um`

### `latex-export`

- (sollte triggern) „Baue mir die BibTeX aus den Quellen im Vault." -> klassifiziert als `perfect!`

### `latex-layout-auditor`

- (sollte triggern) „Meine Liste hat vermutlich einen tightlist Fehler, kannst du das checken?" -> klassifiziert als `gerne`

### `literature-excel`

- (sollte triggern) „Erstell mir eine Excel-Übersicht meiner Literatur" -> klassifiziert als `der`

### `literature-gap-analysis`

- (sollte triggern) „Welche Literaturluecken habe ich?" -> klassifiziert als `ich`

### `material-passport`

- (sollte triggern) „Generiere die material-passport.json." -> klassifiziert als `der`
- (sollte triggern) „Material-Passport fuer das Projekt erstellen." -> klassifiziert als `entschuldigung`

### `methodology-advisor`

- (sollte triggern) „Ist eine Fallstudie hier sinnvoll?" -> klassifiziert als `ich`

### `notebook-bundle`

- (sollte triggern) „Erstelle ein NotebookLM-Bundle." -> klassifiziert als `es`
- (sollte triggern) „Teile dieses Riesen-PDF fuer NotebookLM auf." -> klassifiziert als `ich`

### `parallel-screening`

- (sollte triggern) „Welche Treffer konntest du nicht entscheiden?" -> klassifiziert als `ich`
- (sollte triggern) „Wie viele Agents laufen beim Screening gleichzeitig?" -> klassifiziert als `basierend`

### `peer-review`

- (sollte triggern) „Schreibe mir einen Referee-Report zu diesem Paper." -> klassifiziert als `um`

### `plagiarism-check`

- (sollte triggern) „Overlap-Analyse" -> klassifiziert als `none`

### `prisma-flow`

- (sollte triggern) „Erstelle ein PRISMA-Flow-Diagramm." -> klassifiziert als `der`
- (sollte triggern) „Mach ein PRISMA-2020-Flussdiagramm." -> klassifiziert als `der`
- (sollte triggern) „Render das Flussdiagramm der Literatursuche." -> klassifiziert als `ich`
- (sollte triggern) „Erzeuge das PRISMA-Flowchart aus den Suchzaehlern." -> klassifiziert als `ich`
- (sollte triggern) „Zeige die Einschluesse als PRISMA-Flow." -> klassifiziert als `um`
- (sollte triggern) „PRISMA Flow mit n_identified und n_included rendern." -> klassifiziert als `ich`

### `qualitative-coding`

- (sollte triggern) „Wie zitiere ich eine Stelle aus meinem eigenen Interview belegfaehig?" -> klassifiziert als `ich`

### `quantitative-analysis`

- (sollte triggern) „Die Auswertung muss reproduzierbar dokumentiert sein — wie mache ich das?" -> klassifiziert als `material-passport`
- (sollte triggern) „Vergleiche die drei Standorte in meinem Datensatz statistisch." -> klassifiziert als `ich`
- (sollte triggern) „Schreib mir einen Analyseplan für meine Erhebung, damit die Auswertung nachvollziehbar ist." -> klassifiziert als `preregistration`

### `reading-list-import`

- (sollte triggern) „Lies meine Leseliste ein und resolve die DOIs." -> klassifiziert als `ich`

### `reading-notes`

- (sollte triggern) „Ich lese gerade diese Quelle -- leg mir dazu eine Notiz an." -> klassifiziert als `ich`
- (sollte triggern) „Schreib mir ein strukturiertes Exzerpt zu diesem Artikel." -> klassifiziert als `welchen`

### `research-question-refiner`

- (sollte triggern) „Bitte bewerte meine Hauptfrage" -> klassifiziert als `ich`
- (sollte triggern) „Wie formuliere ich eine nicht-falsifizierbare Frage um?" -> klassifiziert als `gerne`

### `reviewer-response`

- (sollte triggern) „Verfasse ein Response-Letter an die Gutachter." -> klassifiziert als `ich`
- (sollte triggern) „R&R-Antwortschreiben aufsetzen bitte." -> klassifiziert als `der`

### `source-quality-audit`

- (sollte triggern) „Ist das ein Predatory Journal?" -> klassifiziert als `um`
- (sollte triggern) „Welchen Impact hat dieses Paper?" -> klassifiziert als `ich`
- (sollte triggern) „Ist Elsevier Open Access hier seriös?" -> klassifiziert als `**none**`

### `style-evaluator`

- (sollte triggern) „Akademisch genug?" -> klassifiziert als `none`
- (sollte triggern) „Wortanzahl und Lesbarkeit" -> klassifiziert als `none`

### `submission-checker`

- (sollte triggern) „Zeilenabstand 1.5?" -> klassifiziert als `ich`
- (sollte triggern) „Ist die Gliederung konform?" -> klassifiziert als `ich`

### `title-generator`

- (sollte triggern) „Titelvorschlaege fuer meine Arbeit" -> klassifiziert als `es`
- (sollte triggern) „Arbeitstitel bitte" -> klassifiziert als `um`

### `word-export`

- (sollte triggern) „Exportiere alle Kapitel als eine Word-Datei mit Formatvorlagen." -> klassifiziert als `perfekt!`

### `zotero-import`

- (sollte triggern) „Zotero importieren bitte." -> klassifiziert als `es`
- (sollte triggern) „Importiere meine Zotero-Bibliothek." -> klassifiziert als `der`
- (sollte triggern) „Sync meine Zotero-Library, read-only." -> klassifiziert als `der`

## CLI-Fehler (getrennt von Fehlklassifikationen gezählt)

Issue #631 AC5: Auth-/Rate-Limit-/Timeout-Fehler des `claude`-CLI-Pfads
(`ClaudeCliError`) fließen nicht als "nicht getriggert" in Recall/FPR ein,
sondern werden separat gezählt.

- `latex-export` (should_trigger): „LaTeX-Export der gesamten Arbeit starten." -> claude --print Timeout nach 300s
- `literature-excel` (should_not_trigger): „Baue mir ein Excel-Sheet für die Inventarverwaltung" -> claude --print Timeout nach 300s

## Kosten / Aufwand

- Aufrufe gesamt: 871 (427 `should_trigger` + 442 `should_not_trigger`. 2 davon als CLI-Fehler separat gezaehlt)
- Tokens: 9.630 input + 474.211 output (inkl. Agenten-Scaffold-Cache-Erstellung je Subprozess-Aufruf. s. STRATEGY.md)
- Wanduhrzeit: 1030s (~17.2 min) bei 10 parallelen Workern. Modell `claude-haiku-4-5-20251001`
- Aufrufpfad: claude-CLI/OAuth (Issue #631)

Der OAuth-CLI-Pfad hat kein separat abgerechnetes USD-Budget — es ist
Abo-Kontingent (`CLAUDE_CODE_OAUTH_TOKEN` bzw. die lokal eingeloggte Session),
kein Pay-per-Call wie beim `ANTHROPIC_API_KEY`-Pfad. Die Bezifferung oben ist
daher Aufrufe/Tokens/Wanduhrzeit, keine USD-Schätzung (vgl. Issue-Plan-
Risiko 5).

## Einschränkung: kein deterministischer Lauf

Der CLI-Pfad kennt kein `--temperature`-Flag (dokumentierte Lücke aus Issue
#631, `docs/evals/STRATEGY.md` Abschnitt "Zwei Aufrufwege"). Der
Determinismus-Schutz aus Issue #231 (`temperature=0`) greift auf diesem Pfad
nicht — ein erneuter Lauf mit denselben Prompts kann leicht andere Recall-/
FPR-Werte liefern. Diese Baseline ist damit eine Momentaufnahme, kein exakt
reproduzierbarer Messwert.

## Was diese Baseline NICHT tut

- Keine Skill-Description wurde angepasst (Issue-Scope "Out": "hier wird
  gemessen, nicht verbessert").
- Keine Schwellen (`0.85`/`0.10` in `test_triggers.py`) wurden verändert,
  auch dort, wo ein Skill sie reißt.
- Keine neuen Trigger-Fälle wurden geschrieben.
