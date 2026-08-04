# Skills-Übersicht

[← Doku-Übersicht](../README.md)

Skills sind **selbstaktivierend**: Claude erkennt das passende Keyword und lädt die
Anleitung von selbst. Du musst nichts aufrufen — es reicht, in normalem Deutsch zu sagen,
was du brauchst.

Insgesamt **44 Skills** mit eigener `SKILL.md` (das ist der Claude-Code-Discovery-Count).
Das Verzeichnis `skills/_common/` enthält nur geteilte Markdown-Fragmente und zählt nicht
als Skill.

Die Spalte „Aktiviert bei" listet reale Trigger-Phrasen: jede davon steht auch in der
`description` der jeweiligen `SKILL.md` — `tests/test_skills_manifest.py` erzwingt das,
damit die Tabelle keine Aktivierung verspricht, die der Skill nicht leistet.

## Kern-Skills

| Skill | Aktiviert bei | Beschreibung |
|-------|--------------|-------------|
| `academic-context` | *„meine Arbeit"*, *„Thesis"*, *„Forschungsfrage"* | Bootet akademischen Kontext in `<projekt>/academic_context.md` (User-Output) |
| `research-question-refiner` | *„Forschungsfrage formulieren"*, *„präzisieren"* | Verfeinert auf Spezifität, Beantwortbarkeit, Falsifizierbarkeit |
| `advisor` | *„Gliederung"*, *„Exposé"*, *„Struktur"* | Baut Gliederungen und Exposés im Dialog (7-Kriterien-Check) |
| `methodology-advisor` | *„welche Methodik"*, *„Forschungsdesign"* | Berät bei Methodenwahl (4-Dimensionen-Scoring) |
| `topic-brainstorm` | *„welches Thema"*, *„Themenfindung"* | 3–5 Kandidaten mit Feasibility/Novelty/Career-Fit |

## Literatur-Skills

| Skill | Aktiviert bei | Beschreibung |
|-------|--------------|-------------|
| `literature-gap-analysis` | *„Literaturlücken"*, *„fehlende Quellen"* | Per-Kapitel-Coverage-Bericht |
| `source-quality-audit` | *„Quellenqualität"*, *„Peer-Review prüfen"* | 5-Dimensionen-Score 0–100 |
| `citation-extraction` | *„Zitate finden"*, *„Literaturverzeichnis erstellen"* | Citations-API, seitengenau, 8 Formate |
| `reading-notes` | *„Notiz zu einer Quelle anlegen"*, *„Kernbefund festhalten"* | Strukturiertes Exzerpt (Kernbefund/Methode/Verwendbarkeit) via `vault.add_note()` ([SKILL.md](../../skills/reading-notes/SKILL.md)) |
| `extraction-matrix` | *„Extraktionsmatrix erstellen"*, *„Studien vergleichen"* | Studienvergleich als Matrix (Zeilen = Quellen, Spalten aus Schlüsselkonzepten + Standardmerkmalen), Tabelle + Arbeitsblatt-Export ([SKILL.md](../../skills/extraction-matrix/SKILL.md)) |
| `zotero-import` | *„Zotero importieren"*, *„Bibliothek einlesen"* | pyzotero-Pull mit Vault-Dedup |
| `reading-list-import` | *„Literaturliste importieren"*, *„Quellenliste"* | PDF/Markdown/Text → Vault |
| `citation-style-import` | *„eigenen Zitierstil"*, *„CSL laden"* | CSL-Repository → Vault-Stilregeln |
| `book-handler` | *„Buch"*, *„Monografie"*, *„Sammelband"*, ISBN-/Springer-DOI-Muster | Löst ISBN/Titel/DOI via DNB + OpenLibrary + DOAB auf, legt CSL-JSON im Vault an ([SKILL.md](../../skills/book-handler/SKILL.md)) |
| `github-repo-research` | *„GitHub-Repo analysieren"*, *„Paper zu einem Repo finden"* | README/CITATION.cff → arXiv-/DOI-Kandidaten im Vault ([SKILL.md](../../skills/github-repo-research/SKILL.md)) |
| `anchor-paper-survey` | *„arXiv-Paper als Anker verwenden"*, *„verwandte Arbeiten zu diesem Paper finden"* | arXiv-URL/PDF als Ausgangspaper → Vault-Eintrag + Folge-Suche verwandter Arbeiten ([SKILL.md](../../skills/anchor-paper-survey/SKILL.md)) |
| `literature-excel` | *„Excel-Übersicht meiner Literatur"*, *„Excel aus meinen Papers"* | Router zu `/academic-research:excel`: leitet literaturbezogene NL-Anfragen zur 4-Sheet-Spezifikation statt zum generischen xlsx-Skill ([SKILL.md](../../skills/literature-excel/SKILL.md)) |

## Schreib-Skills

| Skill | Aktiviert bei | Beschreibung |
|-------|--------------|-------------|
| `chapter-writer` | *„Kapitel schreiben"*, *„Einleitung"*, *„Fazit"* | Kapitel-Entwürfe mit Vault-Zitaten |
| `style-evaluator` | *„Stil prüfen"*, *„KI-Erkennung"* | 9-Metriken-Analyse + Anti-KI-Detection |
| `plagiarism-check` | *„Plagiat prüfen"*, *„zu nah am Original"* | N-Gramm-Overlap gegen Vault-Quellen |
| `peer-review` | *„Manuskript begutachten"*, *„Peer-Review-Gutachten verfassen"* | Strukturiertes Gutachten zu einem fremden Manuskript: 5 Bereiche, getrennte Blöcke Redaktion/Autor:innen, genau eine Empfehlung ([SKILL.md](../../skills/peer-review/SKILL.md)) |
| `humanizer-de` | *„humanisieren"*, *„menschlicher klingen"* | Anti-KI-Audit mit Severity-Ranking |

## Methodik-Skills

| Skill | Aktiviert bei | Beschreibung |
|-------|--------------|-------------|
| `preregistration` | *„Präregistrierung"*, *„PROSPERO-Anmeldung"*, *„OSF-Registrierung"* | Studienprotokoll vor der Erhebung: schlägt anhand des Vorhabens (Review/quantitativ/qualitativ/Sekundärdaten) eine Vorlage vor, erzwingt bei PROSPERO die dortigen Pflichtfelder, legt Suchstrategie/Kriterien für `parallel-screening` und `query-generator` in `./academic_context.md` ab ([SKILL.md](../../skills/preregistration/SKILL.md)) |
| `prisma-flow` | *„PRISMA"*, *„Systematic Review"*, *„Flussdiagramm"* | Mermaid-Flow + 27-Punkte-Checkliste |
| `parallel-screening` | *„viele Treffer screenen"*, *„Screening parallelisieren"*, *„Risk-of-Bias für mehrere Paper"*, *„Active Learning"* | Fächert Screening und Verzerrungsbewertung auf Subagents auf, Ledger + Resume + PRISMA-Zähler; optional Active Learning zur Umsortierung der Restliste ([SKILL.md](../../skills/parallel-screening/SKILL.md)) |
| `material-passport` | *„Material-Passport"*, *„Artefakt sichern"* | Unveränderlicher Repro-Passport |
| `instrument-design` | *„Interviewleitfaden erstellen"*, *„Fragebogen entwickeln"* | Erhebungsinstrument aus Forschungsfrage + Methodik, mit Rückverweis-Matrix je Frage ([SKILL.md](../../skills/instrument-design/SKILL.md)) |
| `qualitative-coding` | *„Transkript kodieren"*, *„Kategorien aus dem Material bilden"* | Transkript-Ingest mit belegfähiger Stellenangabe, induktive/deduktive Kategorienbildung, Kodier-Übersicht ([SKILL.md](../../skills/qualitative-coding/SKILL.md)) |
| `quantitative-analysis` | *„quantitative Auswertung rechnen"*, *„Datensatz auswerten"*, *„t-Test rechnen"* | Eigener Rohdatensatz vom Analyseplan bis zum Protokoll: Deskription, Gruppenvergleich, Zusammenhangsmaß — je mit Voraussetzungsprüfung, Effektstärke und Konfidenzintervall ([SKILL.md](../../skills/quantitative-analysis/SKILL.md)) |

## Output-Skills (opt-in via `output_targets`)

Diese Skills sind per Default aus. Sie laufen erst, wenn im Projekt-State der passende
`output_targets`-Eintrag gesetzt ist — siehe [Glossar](glossary.md).

| Skill | Aktiviert bei | Beschreibung |
|-------|--------------|-------------|
| `grant-proposal` | *„Förderantrag"*, *„DFG"*, *„BMBF"*, *„EU-Antrag"* | DFG/BMBF/EU-Antrag mit Vault-Quellen |
| `conference-poster` | *„Poster"*, *„Konferenz-Poster"* | A0-Poster (LaTeX tikzposter / PowerPoint) |
| `reviewer-response` | *„Response-Letter"*, *„Reviewer-Kommentare"* | Point-by-point Response |
| `latex-export` | *„Thesis als .tex"*, *„Kapitel exportieren"*, *„BibTeX aus Vault"* | Markdown-Kapitel → `.tex` (Pandoc/Custom) + `.bib` aus Vault (biblatex, DIN-1505) ([SKILL.md](../../skills/latex-export/SKILL.md)) |
| `word-export` | *„Kapitel als Word exportieren"*, *„Thesis als .docx"*, *„Abgabe als PDF"* | Markdown-Kapitel + Vault-Bibliografie → `.docx` mit echten Formatvorlagen (Titelblatt, Verzeichnisse, eidesstattliche Erklärung), optional PDF ([SKILL.md](../../skills/word-export/SKILL.md)) |
| `slide-export` | *„Foliensatz erstellen"*, *„Kolloquium-Präsentation"*, *„Konferenz-Slides"* | Markdown-Kapitel → `.pptx` mit einer Kernaussage pro Folie ([SKILL.md](../../skills/slide-export/SKILL.md)) |
| `notebook-bundle` | *„NotebookLM Bundle"*, *„PDF-Bundle exportieren"*, *„Riesen-PDF aufteilen"* | Konkateniertes PDF (Cover + TOC) der Paper für NotebookLM-Upload ([SKILL.md](../../skills/notebook-bundle/SKILL.md)) |
| `cluster-visualizer` | *„zeige Cluster"*, *„visualisiere"*, *„Mindmap"*, *„Netzwerk der Quellen"* | Cluster-JSON → Mermaid-`graph-LR`-Diagramm, optional PNG via mmdc ([SKILL.md](../../skills/cluster-visualizer/SKILL.md)) |

## Abschluss-Skills

| Skill | Aktiviert bei | Beschreibung |
|-------|--------------|-------------|
| `abstract-generator` | *„Abstract schreiben"*, *„Zusammenfassung"* | IMRaD-konform, DE + EN |
| `title-generator` | *„Titelvorschläge"*, *„Arbeitstitel"* | 5–7 Varianten mit Rationale |
| `submission-checker` | *„abgabefertig"*, *„Formalia prüfen"* | Formalia-Check, Default: FH Leibniz -- beschränkt auf am Markdown-Material Prüfbares, Rest als „Nicht geprüft" ausgewiesen |
| `ai-disclosure` | *„KI-Nutzung offenlegen"*, *„Offenlegungserklärung erstellen"* | Zweigeteilte Offenlegungserklärung (Danksagung + Methodenteil, DE/EN) nach ICMJE 01/2026; Vault-Spuren als Vorschlag statt Behauptung ([SKILL.md](../../skills/ai-disclosure/SKILL.md)) |
| `latex-layout-auditor` | *„LaTeX-Layout prüfen / pruefen"*, *„.tex auditieren"* | Read-only Prüfung eines `.tex`-Exports auf LaTeX-Layout-Fehler: Listen-Strukturen, Zitationskommandos, Kapitel-Nummerierung, Package-Konflikte ([SKILL.md](../../skills/latex-layout-auditor/SKILL.md)) |
| `bibliography-auditor` | *„Literaturverzeichnis prüfen / pruefen"*, *„Zitate gegen Vault abgleichen"* | Read-only Gegenprobe zwischen `\cite{key}`-Zitaten in `kapitel/*.md` und der Vault-Paper-Menge: fehlende Verzeichniseinträge und verwaiste Vault-Einträge ([SKILL.md](../../skills/bibliography-auditor/SKILL.md)) |
| `defense-prep` | *„Verteidigung vorbereiten"*, *„Fragenkatalog Kolloquium"* | Vortragsgliederung mit Zeitrahmen + Kernaussage je Kapitel, Fragenkatalog zu Methodik/Limitationen ([SKILL.md](../../skills/defense-prep/SKILL.md)) |

## Externe Skills (Plugin-Dependencies)

Diese Skills liegen nicht im Repository, sondern werden bei der Installation als
Plugin-Abhängigkeit mitgezogen (`dependencies` in `.claude-plugin/plugin.json`).

| Skill | Herkunft | Zweck |
|-------|----------|-------|
| `document-skills:xlsx` | Plugin `document-skills` aus dem Marketplace `anthropic-agent-skills` (`anthropics/skills`) | Excel-Erzeugung für `/academic-research:excel` und `/academic-research:pickup` |
| `document-skills:docx` | Plugin `document-skills` aus dem Marketplace `anthropic-agent-skills` (`anthropics/skills`) | Optionale Layout-Verfeinerung für `/academic-research:word`; die `.docx` selbst erzeugt `skills/word-export/scripts/render_docx.py` |
| `document-skills:pptx` | Plugin `document-skills` aus dem Marketplace `anthropic-agent-skills` (`anthropics/skills`) | Optionale Designvorlagen für `/academic-research:slides`; das `.pptx` selbst erzeugt `skills/slide-export/scripts/render_pptx.py` |

Fehlt die Abhängigkeit, melden die jeweiligen Commands den Nachinstallations-Weg,
statt einen Tool-Fehler durchzureichen:

```bash
claude plugin marketplace add anthropics/skills
claude plugin install document-skills@anthropic-agent-skills
```
