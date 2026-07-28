# Skills-Übersicht

[← zurück zur README](../../README.md)

Skills sind **selbstaktivierend**: Claude erkennt das passende Keyword und lädt die
Anleitung von selbst. Du musst nichts aufrufen — es reicht, in normalem Deutsch zu sagen,
was du brauchst.

Insgesamt **29 Skills** mit eigener `SKILL.md` (das ist der Claude-Code-Discovery-Count,
inklusive dem vendorierten `xlsx/`). Das Verzeichnis `skills/_common/` enthält nur
geteilte Markdown-Fragmente und zählt nicht als Skill.

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
| `zotero-import` | *„Zotero importieren"*, *„Bibliothek einlesen"* | pyzotero-Pull mit Vault-Dedup |
| `reading-list-import` | *„Literaturliste importieren"*, *„Quellenliste"* | PDF/Markdown/Text → Vault |
| `citation-style-import` | *„eigenen Zitierstil"*, *„CSL laden"* | CSL-Repository → Vault-Stilregeln |
| `book-handler` | *„Buch"*, *„Monografie"*, *„Sammelband"*, ISBN-/Springer-DOI-Muster | Löst ISBN/Titel/DOI via DNB + OpenLibrary + DOAB auf, legt CSL-JSON im Vault an ([SKILL.md](../../skills/book-handler/SKILL.md)) |
| `github-repo-research` | *„GitHub-Repo analysieren"*, *„Paper zu einem Repo finden"* | README/CITATION.cff → arXiv-/DOI-Kandidaten im Vault ([SKILL.md](../../skills/github-repo-research/SKILL.md)) |

## Schreib-Skills

| Skill | Aktiviert bei | Beschreibung |
|-------|--------------|-------------|
| `chapter-writer` | *„Kapitel schreiben"*, *„Einleitung"*, *„Fazit"* | Kapitel-Entwürfe mit Vault-Zitaten |
| `style-evaluator` | *„Stil prüfen"*, *„KI-Erkennung"* | 9-Metriken-Analyse + Anti-KI-Detection |
| `plagiarism-check` | *„Plagiat prüfen"*, *„zu nah am Original"* | N-Gramm-Overlap gegen Vault-Quellen |
| `humanizer-de` | *„humanisieren"*, *„menschlicher klingen"* | Anti-KI-Audit mit Severity-Ranking |

## Methodik-Skills

| Skill | Aktiviert bei | Beschreibung |
|-------|--------------|-------------|
| `prisma-flow` | *„PRISMA"*, *„Systematic Review"*, *„Flussdiagramm"* | Mermaid-Flow + 27-Punkte-Checkliste |
| `material-passport` | *„Material-Passport"*, *„Artefakt sichern"* | Unveränderlicher Repro-Passport |

## Output-Skills (opt-in via `output_targets`)

Diese Skills sind per Default aus. Sie laufen erst, wenn im Projekt-State der passende
`output_targets`-Eintrag gesetzt ist — siehe [Glossar](glossary.md).

| Skill | Aktiviert bei | Beschreibung |
|-------|--------------|-------------|
| `grant-proposal` | *„Förderantrag"*, *„DFG"*, *„BMBF"*, *„EU-Antrag"* | DFG/BMBF/EU-Antrag mit Vault-Quellen |
| `conference-poster` | *„Poster"*, *„Konferenz-Poster"* | A0-Poster (LaTeX tikzposter / PowerPoint) |
| `reviewer-response` | *„Response-Letter"*, *„Reviewer-Kommentare"* | Point-by-point Response |
| `latex-export` | *„Thesis als .tex"*, *„Kapitel exportieren"*, *„BibTeX aus Vault"* | Markdown-Kapitel → `.tex` (Pandoc/Custom) + `.bib` aus Vault (biblatex, DIN-1505) ([SKILL.md](../../skills/latex-export/SKILL.md)) |
| `notebook-bundle` | *„NotebookLM Bundle"*, *„PDF-Bundle exportieren"*, *„Riesen-PDF aufteilen"* | Konkateniertes PDF (Cover + TOC) der Paper für NotebookLM-Upload ([SKILL.md](../../skills/notebook-bundle/SKILL.md)) |
| `cluster-visualizer` | *„zeige Cluster"*, *„visualisiere"*, *„Mindmap"*, *„Netzwerk der Quellen"* | Cluster-JSON → Mermaid-`graph-LR`-Diagramm, optional PNG via mmdc ([SKILL.md](../../skills/cluster-visualizer/SKILL.md)) |

## Abschluss-Skills

| Skill | Aktiviert bei | Beschreibung |
|-------|--------------|-------------|
| `abstract-generator` | *„Abstract schreiben"*, *„Zusammenfassung"* | IMRaD-konform, DE + EN |
| `title-generator` | *„Titelvorschläge"*, *„Arbeitstitel"* | 5–7 Varianten mit Rationale |
| `submission-checker` | *„abgabefertig"*, *„Formalia prüfen"* | Formalia-Check, Default: FH Leibniz |

## Vendorierte Skills

| Skill | Herkunft | Zweck |
|-------|----------|-------|
| `xlsx` | Claude-eigener document-skill, im Plugin mitgeliefert | Excel-Erzeugung für `/academic-research:excel` und `/academic-research:pickup` — kein externes Plugin nötig |
