# Skills-Übersicht

[← Doku-Übersicht](../README.md)

Skills sind **selbstaktivierend**: Claude erkennt das passende Keyword und lädt die
Anleitung von selbst. Du musst nichts aufrufen — es reicht, in normalem Deutsch zu sagen,
was du brauchst.

Insgesamt **46 Skills** mit eigener `SKILL.md` (das ist der Claude-Code-Discovery-Count).
Das Verzeichnis `skills/_common/` enthält nur geteilte Markdown-Fragmente und zählt nicht
als Skill.

Die Spalte „Aktiviert bei" listet reale Trigger-Phrasen: jede davon steht auch in der
`description` der jeweiligen `SKILL.md` — `tests/test_skills_manifest.py` erzwingt das,
damit die Tabelle keine Aktivierung verspricht, die der Skill nicht leistet.

Jeder Eintrag führt dieselben drei Felder: **Voraussetzung** (was vorhanden sein muss,
bevor der Skill etwas leisten kann), **Rückgabe** (was am Ende vorliegt) und **Fehlschlag
erkennbar an** (woran du merkst, dass es nicht geklappt hat). Ohne das dritte Feld
lässt sich ein stiller Fehlschlag nicht von einem Erfolg unterscheiden.

## Kern-Skills

| Skill | Aktiviert bei | Beschreibung | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|-------|--------------|-------------|---------------|----------|-------------------------|
| `academic-context` | *„meine Arbeit"*, *„Thesis"*, *„Forschungsfrage"* | Bootet akademischen Kontext in `<projekt>/academic_context.md` (User-Output) | Projektverzeichnis mit Schreibrecht; kein Vault nötig | `academic_context.md` angelegt oder fortgeschrieben (Profil, Arbeit, Gliederung, Schlüsselkonzepte) | Die Datei fehlt danach, oder Profil- und Arbeitsblock bleiben leer |
| `research-question-refiner` | *„Forschungsfrage formulieren"*, *„präzisieren"* | Verfeinert auf Spezifität, Beantwortbarkeit, Falsifizierbarkeit | Themenidee oder Frageentwurf | Geschärfte Frage plus Bewertung je Kriterium (Spezifität, Beantwortbarkeit, Relevanz, Struktur) | Antwort ohne Bewertungsraster, oder die Frage kommt unverändert zurück |
| `advisor` | *„Gliederung"*, *„Exposé"*, *„Struktur"* | Baut Gliederungen und Exposés im Dialog (7-Kriterien-Check) | Gliederungs- oder Exposé-Entwurf, `academic_context.md` | Review mit PASS/FAIL je Kriterium, auf Wunsch Exposé-Text, Gliederung zurück in den Kontext geschrieben | Rückmeldung ohne PASS/FAIL-Urteil, oder es kommt Kapitelprosa statt Struktur |
| `methodology-advisor` | *„welche Methodik"*, *„Forschungsdesign"* | Berät bei Methodenwahl (4-Dimensionen-Scoring) | Formulierte Forschungsfrage | Methodenvergleich mit Score je Dimension und ausformulierter Begründung | Empfehlung ohne Scoring-Matrix oder ohne Bezug zur Fragestellung |
| `topic-brainstorm` | *„welches Thema"*, *„Themenfindung"* | 3–5 Kandidaten mit Feasibility/Novelty/Career-Fit | Fachgebiet und Interessen; kein Kontext nötig | 3–5 Themenkandidaten mit Score je Dimension, danach Übergabe an `research-question-refiner` | Weniger als drei Kandidaten, oder Kandidaten ohne Score |
| `workflow-status` | *„wo stehe ich"*, *„was ist der naechste Schritt"*, *„wie geht es weiter"*, *„Stand der Arbeit"* | Meldet aktuelle Phase, nächsten Schritt (mit Auslöser Claude/Operator) und Restkette bis Export gegen `config/workflow-phases.json` | `academic_context.md` im Projekt; kein Command nötig | Phase, nächster Schritt samt Auslöser, Restkette bis Export im Gespräch | Kein Kontext vorhanden → keine Ausgabe statt einer Phase (Issue #877) |

## Literatur-Skills

| Skill | Aktiviert bei | Beschreibung | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|-------|--------------|-------------|---------------|----------|-------------------------|
| `literature-gap-analysis` | *„Literaturlücken"*, *„fehlende Quellen"* | Per-Kapitel-Coverage-Bericht | Papers im Vault und eine Gliederung im Kontext | Coverage-Bericht je Kapitel mit Lücken-Klassifikation und Such-Empfehlungen | Bericht ohne Kapitelbezug, oder Coverage überall 0 (leerer Vault, fehlende Gliederung) |
| `source-quality-audit` | *„Quellenqualität"*, *„Peer-Review prüfen"* | 5-Dimensionen-Score 0–100 | Mindestens eine Quelle im Vault | Score 0–100 über die fünf gewichteten Dimensionen plus Score-Snapshot | Score ohne Dimensionsblock, oder kein neuer Eintrag in der Score-Historie |
| `citation-extraction` | *„Zitate finden"*, *„Literaturverzeichnis erstellen"* | Citations-API, seitengenau, 8 Formate | Paper im Vault mit lesbarem lokalem PDF-Pfad; Zitierstil in `academic_context.md` | Formatierte Bibliografie plus verifizierte Zitate im Vault | `vault.add_quote` weist mit `ValueError` ab (`no-match`/`no-textlayer`) — Wortlaut oder Textlayer fehlt |
| `reading-notes` | *„Notiz zu einer Quelle anlegen"*, *„Kernbefund festhalten"* | Strukturiertes Exzerpt (Kernbefund/Methode/Verwendbarkeit) via `vault.add_note()` ([SKILL.md](../../skills/reading-notes/SKILL.md)) | Paper-Eintrag im Vault | `note_id` aus `vault.add_note()`; die Notiz ist über `vault.search_notes()` auffindbar | `vault.find_notes()` gibt die Notiz nicht zurück |
| `extraction-matrix` | *„Extraktionsmatrix erstellen"*, *„Studien vergleichen"* | Studienvergleich als Matrix (Zeilen = Quellen, Spalten aus Schlüsselkonzepten + Standardmerkmalen), Tabelle + Arbeitsblatt-Export ([SKILL.md](../../skills/extraction-matrix/SKILL.md)) | Mehrere Papers im Vault; Zahlen-Spalten brauchen zusätzlich `vault.extract_tables()` | Matrix als Kapitel-Tabelle und als Arbeitsblatt | Zellen bleiben `— fehlend —`, weil kein Tabellenbeleg vorliegt |
| `zotero-import` | *„Zotero importieren"*, *„Bibliothek einlesen"* | pyzotero-Pull mit Vault-Dedup | `pyzotero` installiert, API-Key und Library-ID konfiguriert | Anzahl importierter und deduplizierter Items, Papers im Vault | Abbruch mit Authentifizierungsfehler, oder 0 Items trotz gefüllter Bibliothek |
| `reading-list-import` | *„Literaturliste importieren"*, *„Quellenliste"* | PDF/Markdown/Text → Vault | Datei mit Quellenliste und ein vorhandener Vault | Anzahl erkannter und übernommener Einträge; Mehrdeutigkeiten kommen als Rückfrage | Einträge bleiben als mehrdeutig stehen und landen nicht im Vault |
| `citation-style-import` | *„eigenen Zitierstil"*, *„CSL laden"* | CSL-Repository → Vault-Stilregeln | Netzzugang zum CSL-Repository oder eine lokale `.csl`-Datei | Stilregeln im Vault plus Beispiel für Inline-Zitat und Verzeichnis | Der Parser meldet unbekannte Elemente; der Stil fehlt danach in der Stil-Liste |
| `book-handler` | *„Buch"*, *„Monografie"*, *„Sammelband"*, ISBN-/Springer-DOI-Muster | Löst ISBN/Titel/DOI via DNB + OpenLibrary + DOAB auf, legt CSL-JSON im Vault an ([SKILL.md](../../skills/book-handler/SKILL.md)) | ISBN, Titel oder DOI; Netzzugang zu DNB, OpenLibrary und DOAB | CSL-JSON-Eintrag im Vault, auf Wunsch mit bestätigtem `page_offset` | Weder DNB noch OpenLibrary noch DOAB liefern einen Treffer — es entsteht kein Vault-Eintrag |
| `github-repo-research` | *„GitHub-Repo analysieren"*, *„Paper zu einem Repo finden"* | README/CITATION.cff → arXiv-/DOI-Kandidaten im Vault ([SKILL.md](../../skills/github-repo-research/SKILL.md)) | Repo-URL, ein vorhandener Vault (`requests` und `pyyaml` sind Projekt-Dependencies) | arXiv-/DOI-Kandidaten aus README und `CITATION.cff` im Vault | Repo ohne `CITATION.cff` und ohne DOI im README — null Kandidaten |
| `anchor-paper-survey` | *„arXiv-Paper als Anker verwenden"*, *„verwandte Arbeiten zu diesem Paper finden"* | arXiv-URL/PDF als Ausgangspaper → Vault-Eintrag + Folge-Suche verwandter Arbeiten ([SKILL.md](../../skills/anchor-paper-survey/SKILL.md)) | arXiv-URL/-ID oder lokaler PDF-Pfad, ein vorhandener Vault | Anker-Paper im Vault plus Trefferliste verwandter Arbeiten | Das Anker-Paper lässt sich nicht auflösen, die Folge-Suche startet gar nicht |
| `literature-excel` | *„Excel-Übersicht meiner Literatur"*, *„Excel aus meinen Papers"* | Router zu `/academic-research:excel`: leitet literaturbezogene NL-Anfragen zur 4-Sheet-Spezifikation statt zum generischen xlsx-Skill ([SKILL.md](../../skills/literature-excel/SKILL.md)) | Papers im Vault; Plugin `document-skills` installiert | Weiterleitung an `/academic-research:excel` mit der 4-Sheet-Spezifikation | Der generische xlsx-Skill übernimmt — die Datei hat nicht die vier Sheets |

## Schreib-Skills

| Skill | Aktiviert bei | Beschreibung | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|-------|--------------|-------------|---------------|----------|-------------------------|
| `chapter-writer` | *„Kapitel schreiben"*, *„Einleitung"*, *„Fazit"* | Kapitel-Entwürfe mit Vault-Zitaten | Gliederung in `academic_context.md` und verifizierte Zitate im Vault | Kapiteldatei unter `kapitel/`, Writing-State fortgeschrieben | Der `verbatim-guard`-Hook blockt den Write mit „Zitat nicht im Vault" |
| `style-evaluator` | *„Stil prüfen"*, *„Nominalstil"* | 9-Metriken-Analyse, KI-freie Stilqualität (KI-Detektion/-Prüfung → `humanizer-de`, #825) | Ein Textabschnitt oder eine Kapiteldatei | Score 0–100 mit Einzelwerten je Metrik | Score ohne Metrikliste — dann lief die Fallback-Rubrik ohne Skript |
| `plagiarism-check` | *„Plagiat prüfen"*, *„zu nah am Original"* | N-Gramm-Overlap gegen Vault-Quellen | Kapiteltext und Quelltexte der verglichenen Quellen im Vault | Geflaggte Passagen mit Severity und Umformulierungs-Vorschlägen | Bericht ohne Vergleichsbasis, weil kein Quelltext im Vault liegt |
| `peer-review` | *„Manuskript begutachten"*, *„Peer-Review-Gutachten verfassen"* | Strukturiertes Gutachten zu einem fremden Manuskript: 5 Bereiche, getrennte Blöcke Redaktion/Autor:innen, genau eine Empfehlung ([SKILL.md](../../skills/peer-review/SKILL.md)) | Fremdes Manuskript als Datei oder Text | Gutachten mit fünf Bereichen, getrennten Blöcken und genau einer Empfehlung | Mehr als eine Empfehlung, oder Redaktions- und Autorenblock sind vermischt |
| `humanizer-de` | *„humanisieren"*, *„menschlicher klingen"* | Anti-KI-Audit mit Severity-Ranking | Deutschsprachiger Entwurf | Überarbeiteter Text plus Diff, nach Severity gegliedert | Der Diff bleibt leer, obwohl der Audit Muster gemeldet hat |

## Methodik-Skills

| Skill | Aktiviert bei | Beschreibung | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|-------|--------------|-------------|---------------|----------|-------------------------|
| `preregistration` | *„Präregistrierung"*, *„PROSPERO-Anmeldung"*, *„OSF-Registrierung"* | Studienprotokoll vor der Erhebung: schlägt anhand des Vorhabens (Review/quantitativ/qualitativ/Sekundärdaten) eine Vorlage vor, erzwingt bei PROSPERO die dortigen Pflichtfelder, legt Suchstrategie/Kriterien für `parallel-screening` und `query-generator` in `./academic_context.md` ab ([SKILL.md](../../skills/preregistration/SKILL.md)) | Ein klassifizierbares Vorhaben (Review, quantitativ, qualitativ oder Sekundärdaten) | Protokoll plus Suchstrategie und Kriterien in `academic_context.md` | Ein PROSPERO-Pflichtfeld bleibt als `[OFFEN: ...]` stehen |
| `prisma-flow` | *„PRISMA"*, *„Systematic Review"*, *„Flussdiagramm"* | Mermaid-Flow + 27-Punkte-Checkliste | PRISMA-Zähler (`n_identified` und Folgezähler) aus Suche oder Screening | Mermaid-Diagramm in `kapitel/methodik.md` plus Checkliste | Das Diagramm steht auf Nullen, weil die Zähler fehlen |
| `parallel-screening` | *„viele Treffer screenen"*, *„Screening parallelisieren"*, *„Risk-of-Bias für mehrere Paper"*, *„Active Learning"* | Fächert Screening und Verzerrungsbewertung auf Subagents auf, Ledger + Resume + PRISMA-Zähler; optional Active Learning zur Umsortierung der Restliste ([SKILL.md](../../skills/parallel-screening/SKILL.md)) | Trefferliste oder Studienmenge im Vault, beschreibbare Ledger-Datei | Einzelurteile im Ledger, zusammengeführte Vorlage, geschriebene PRISMA-Zähler | Der Ledger führt nach dem Lauf noch offene Fälle — die Welle ist abgebrochen |
| `material-passport` | *„Material-Passport"*, *„Artefakt sichern"* | Unveränderlicher Repro-Passport | Projekt mit Vault-DB; Ausgabepfad beschreibbar | `material-passport.json` und auf Wunsch der Vault-Lock | `build_passport.py` meldet `FEHLER:` (Vault gesperrt oder DB nicht gefunden), die JSON-Datei fehlt |
| `instrument-design` | *„Interviewleitfaden erstellen"*, *„Fragebogen entwickeln"* | Erhebungsinstrument aus Forschungsfrage + Methodik, mit Rückverweis-Matrix je Frage ([SKILL.md](../../skills/instrument-design/SKILL.md)) | Forschungsfrage und bereits gewählte Methodik | Instrument (Leitfaden, Fragebogen oder Beobachtungsraster) plus Rückverweis-Matrix | Eine Frage steht ohne Zeile in der Rückverweis-Matrix |
| `qualitative-coding` | *„Transkript kodieren"*, *„Kategorien aus dem Material bilden"* | Transkript-Ingest mit belegfähiger Stellenangabe, induktive/deduktive Kategorienbildung, Kodier-Übersicht ([SKILL.md](../../skills/qualitative-coding/SKILL.md)) | Transkript als Text und ein Vault-Eintrag mit `source_kind='primary'` | Segmente und Kodierungen im Vault plus Kodier-Übersicht | `vault.add_coding` weist mit `ValueError` ab (leere Kategorie oder ungültige Herkunft) |
| `quantitative-analysis` | *„quantitative Auswertung rechnen"*, *„Datensatz auswerten"*, *„t-Test rechnen"* | Eigener Rohdatensatz vom Analyseplan bis zum Protokoll: Deskription, Gruppenvergleich, Zusammenhangsmaß — je mit Voraussetzungsprüfung, Effektstärke und Konfidenzintervall ([SKILL.md](../../skills/quantitative-analysis/SKILL.md)) | Eigener Rohdatensatz als Tabellendatei und ein abgestimmter Analyseplan | Protokoll mit Verfahren, Voraussetzungsprüfung, Effektstärke und Konfidenzintervall | Ergebnis ohne Voraussetzungsprüfung oder ohne Konfidenzintervall |
| `data-management-plan` | *„Datenmanagementplan erstellen"*, *„DMP erstellen"* | Plant Speicherung, Sicherung, rechtliche Aspekte inkl. personenbezogener Daten sowie Archivierung/Nachnutzung der Forschungsdaten; Vault-Bestand als Ausgangslage, offene Punkte als `[OFFEN: ...]` ([SKILL.md](../../skills/data-management-plan/SKILL.md)) | Projektkontext und erreichbare Vault-DB | DMP-Dokument; offene Punkte stehen als `[OFFEN: ...]` darin | `build_dmp.py` meldet `FEHLER:` (Vault-DB nicht gefunden oder Ausgabepfad nicht schreibbar) |

## Output-Skills (opt-in via `output_targets`)

Diese Skills sind per Default aus. Sie laufen erst, wenn im Projekt-State der passende
`output_targets`-Eintrag gesetzt ist — siehe [Glossar](glossary.md).

| Skill | Aktiviert bei | Beschreibung | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|-------|--------------|-------------|---------------|----------|-------------------------|
| `grant-proposal` | *„Förderantrag"*, *„DFG"*, *„BMBF"*, *„EU-Antrag"* | DFG/BMBF/EU-Antrag mit Vault-Quellen | `output_targets` enthält den Antrag; Quellen im Vault | Antragsskelett je Förderlinie plus Bibliografie-Block | Der Opt-in-Guard meldet das fehlende `output_targets` und erzeugt nichts |
| `conference-poster` | *„Poster"*, *„Konferenz-Poster"* | A0-Poster (LaTeX tikzposter / PowerPoint) | `output_targets` gesetzt, Kapitel und Figures im Vault | A0-Poster als tikzposter-`.tex` oder PowerPoint-Datei | Der Opt-in-Guard bricht ab; ohne Figures bleibt der Bildbereich leer |
| `reviewer-response` | *„Response-Letter"*, *„Reviewer-Kommentare"* | Point-by-point Response | `output_targets` gesetzt, Reviewer-Kommentare als Text | Point-by-point-Response plus abschließendes Dankschreiben | Ein Kommentar bleibt ohne zugeordneten Antwortpunkt |
| `latex-export` | *„Thesis als .tex"*, *„Kapitel exportieren"*, *„BibTeX aus Vault"* | Markdown-Kapitel → `.tex` (Pandoc/Custom) + `.bib` aus Vault (biblatex, DIN-1505) ([SKILL.md](../../skills/latex-export/SKILL.md)) | Kapitel unter `kapitel/`; für die `.bib` ein gefüllter Vault | `.tex`-Datei und auf Wunsch `.bib` | Der `verbatim-guard` blockt den `.tex`-Write; leerer Vault meldet „Vault leer" und liefert eine leere `.bib` |
| `word-export` | *„Kapitel als Word exportieren"*, *„Thesis als .docx"*, *„Abgabe als PDF"* | Markdown-Kapitel + Vault-Bibliografie → `.docx` mit echten Formatvorlagen (Titelblatt, Verzeichnisse, eidesstattliche Erklärung), optional PDF ([SKILL.md](../../skills/word-export/SKILL.md)) | Kapitel unter `kapitel/`, `python-docx` installiert; PDF zusätzlich `soffice` | `.docx` mit Formatvorlagen, optional zusätzlich PDF | `render_docx.py` meldet `FEHLER:` (fehlendes `python-docx`); ohne `soffice` bleibt es bei der `.docx` mit Hinweis |
| `slide-export` | *„Foliensatz erstellen"*, *„Kolloquium-Präsentation"*, *„Konferenz-Slides"* | Markdown-Kapitel → `.pptx` mit einer Kernaussage pro Folie ([SKILL.md](../../skills/slide-export/SKILL.md)) | Kapitel unter `kapitel/`, `python-pptx` installiert | `.pptx` mit einer Kernaussage je Folie | `ChapterResolutionError` bei unbekanntem `--kapitel`; leere `core_statement` löst eine Rückfrage aus |
| `notebook-bundle` | *„NotebookLM Bundle"*, *„PDF-Bundle exportieren"*, *„Riesen-PDF aufteilen"* | Konkateniertes PDF (Cover + TOC) der Paper für NotebookLM-Upload ([SKILL.md](../../skills/notebook-bundle/SKILL.md)) | Ausgewählte Paper mit lokalem PDF-Pfad | Konkateniertes PDF mit Cover und Inhaltsverzeichnis | Paper ohne PDF fehlen im Bundle; der Bericht weist sie aus |
| `cluster-visualizer` | *„zeige Cluster"*, *„visualisiere"*, *„Mindmap"*, *„Netzwerk der Quellen"* | Cluster-JSON → Mermaid-`graph-LR`-Diagramm, optional PNG via mmdc ([SKILL.md](../../skills/cluster-visualizer/SKILL.md)) | Cluster-JSON aus dem 5D-Scoring | Mermaid-Quelltext und, falls `mmdc` installiert ist, eine `.png` | Hinweis „PNG nicht erzeugt (mmdc nicht installiert)" — es bleibt beim Mermaid-Quelltext |

## Abschluss-Skills

| Skill | Aktiviert bei | Beschreibung | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|-------|--------------|-------------|---------------|----------|-------------------------|
| `abstract-generator` | *„Abstract schreiben"*, *„Zusammenfassung"* | IMRaD-konform, DE + EN | Fertige Kapitel oder zumindest Ergebnisse | Abstract auf Deutsch und Englisch, Management Summary, Keyword-Liste | Der Abstract lässt einen IMRaD-Teil aus (Methodik oder Ergebnisse fehlen) |
| `title-generator` | *„Titelvorschläge"*, *„Arbeitstitel"* | 5–7 Varianten mit Rationale | Thema oder Forschungsfrage | 5–7 Titel über vier Kategorien, je mit Begründung | Weniger als fünf Vorschläge, oder ein Titel ohne Begründung |
| `submission-checker` | *„abgabefertig"*, *„Formalia prüfen"* | Formalia-Check, Default: FH Leibniz -- beschränkt auf am Markdown-Material Prüfbares, Rest als „Nicht geprüft" ausgewiesen | Markdown-Material der Arbeit; Profil (Default FH Leibniz) | Checkliste je Dimension; nicht prüfbare Punkte stehen als „Nicht geprüft" | Ein Punkt gilt als bestanden, obwohl er am Markdown-Material gar nicht prüfbar ist |
| `ai-disclosure` | *„KI-Nutzung offenlegen"*, *„Offenlegungserklärung erstellen"* | Zweigeteilte Offenlegungserklärung (Danksagung + Methodenteil, DE/EN) nach ICMJE 01/2026; Vault-Spuren als Vorschlag statt Behauptung ([SKILL.md](../../skills/ai-disclosure/SKILL.md)) | Vault-Spuren der KI-Nutzung und deine Bestätigung je Kategorie | Danksagung und Methodenteil, je auf Deutsch und Englisch | Eine Kategorie steht im Text, ohne dass du sie bestätigt hast |
| `latex-layout-auditor` | *„LaTeX-Layout prüfen / pruefen"*, *„.tex auditieren"* | Read-only Prüfung eines `.tex`-Exports auf LaTeX-Layout-Fehler: Listen-Strukturen, Zitationskommandos, Kapitel-Nummerierung, Package-Konflikte ([SKILL.md](../../skills/latex-layout-auditor/SKILL.md)) | Eine `.tex`-Datei aus `latex-export` | Befundliste je Prüfdimension, ohne die Datei zu ändern | Die Datei ist nicht lesbar — es kommen keine Befunde, nur der „Nicht geprüft"-Block |
| `bibliography-auditor` | *„Literaturverzeichnis prüfen / pruefen"*, *„Zitate gegen Vault abgleichen"* | Read-only Gegenprobe zwischen `\cite{key}`-Zitaten in `kapitel/*.md` und der Vault-Paper-Menge: fehlende Verzeichniseinträge und verwaiste Vault-Einträge ([SKILL.md](../../skills/bibliography-auditor/SKILL.md)) | `kapitel/*.md` mit `\cite{key}`-Marken und ein gefüllter Vault | Zwei Listen: fehlende Verzeichniseinträge und verwaiste Vault-Einträge | Ein `\cite`-Key ohne Vault-Eintrag taucht in der Fehlliste auf |
| `defense-prep` | *„Verteidigung vorbereiten"*, *„Fragenkatalog Kolloquium"* | Vortragsgliederung mit Zeitrahmen + Kernaussage je Kapitel, Fragenkatalog zu Methodik/Limitationen ([SKILL.md](../../skills/defense-prep/SKILL.md)) | Fertige Kapitel und ein geklärter Zeitrahmen | Vortragsgliederung mit Zeitbudget je Block plus Fragenkatalog | Die Gliederung führt kein Zeitbudget je Block |

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

## Skill-Listing-Budget: wenn viele Plugins installiert sind

Claude Code lädt bei jeder Runde eine Liste aller installierten Skill-Namen und
-Beschreibungen ins Kontextfenster, damit das Modell weiß, was es aufrufen kann. Das
Budget dafür ist standardmäßig **1 % des Kontextfensters** (`skillListingBudgetFraction`,
Default `0.01`). Reicht das nicht, kürzt Claude Code zuerst die Beschreibungen der am
seltensten aufgerufenen Skills auf den bloßen Namen — die Skills bleiben aufrufbar, aber
ihr Trigger-Text fehlt. Das trifft am ehesten Einmal-pro-Projekt-Skills wie
`defense-prep`, `grant-proposal` oder `conference-poster`, bei denen die Trigger-Phrase
in der Beschreibung sitzen muss, damit der Skill überhaupt von selbst anspringt.

**Gemessen am 04./05.08.2026** auf einer Operator-Maschine mit mehreren installierten
Plugins:

| Größe | Wert |
|---|---|
| Aktives Listing über **alle** installierten Plugins | 91 Einträge, 43.343 Zeichen, ≈10.836 Token (Schätzung: Zeichen/4) |
| Anteil dieses Plugins daran | 28.253 Zeichen, ≈7.063 Token = 65,2 % des Gesamtlistings |
| Default-Budget bei 200k-Kontextfenster | ≈2.000 Token → Listing zu ≈542 % ausgelastet |
| Default-Budget bei 1M-Kontextfenster | ≈10.000 Token → Listing zu ≈108 % ausgelastet |

Bei 200k überschreitet allein dieses Plugin das Default-Budget um mehr als das Dreifache.
Bei 1M bleibt es für sich genommen darunter (≈7.063 von ≈10.000 Token), zusammen mit den
übrigen installierten Plugins wird das Budget aber auch dort überschritten.

**Gegenmittel — Einstellung, nicht Repo-Konfiguration.** Das Budget ist eine
Nutzerpräferenz, die für alle Projekte auf der jeweiligen Maschine gilt, nicht eine
Eigenschaft dieses Plugins. Sie gehört deshalb in die **globale** `settings.json` des
Nutzers (`~/.claude/settings.json`), nicht in eine Datei dieses Repos:

```json
{ "skillListingBudgetFraction": 0.02 }
```

`0.02` = 2 % statt 1 % des Kontextfensters. Alternativ setzt die Umgebungsvariable
`SLASH_COMMAND_TOOL_CHAR_BUDGET` eine feste Zeichenzahl statt eines Anteils.

Nachmessen lässt sich das über die Zeile „Skills" in `/context` — sie zeigt das Listing
**nach** Anwendung des Budgets, also das, was beim Modell wirklich ankommt. Die Änderung
greift erst in einer **neuen Sitzung**: das Listing wird beim Sitzungsstart gebaut.
(Ein Nachher-Wert ist für die oben genannte Messung bewusst nicht angegeben — er lag zum
Zeitpunkt der Dokumentation nicht vor.)

**`skillOverrides` hilft hier nicht.** Die Einstellung erlaubt zwar, einzelne Skills auf
`"name-only"` zu setzen und so Budget freizugeben — sie wirkt aber laut Doku
ausdrücklich nicht auf Plugin-Skills: „Plugin skills are not affected by
`skillOverrides`. Manage those through `/plugin` instead." Für Skills aus einem
installierten Plugin (wie diesem hier) bleibt also nur, das Budget selbst zu erhöhen
oder das Plugin über `/plugin` zu deaktivieren.

**Kein Nachher-Wert.** Die obige Messung ist der Zustand *vor* der Änderung. Ob und wie
stark `skillListingBudgetFraction: 0.02` die Kürzung tatsächlich behebt, ist nicht
gemessen — die Einstellung wirkt erst in einer neuen Sitzung, und ein Nachher-Lauf mit
denselben Kennzahlen steht noch aus.
