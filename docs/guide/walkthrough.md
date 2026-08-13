# Walkthrough — jeder Arbeitsschritt in der realen Reihenfolge

[← Doku-Übersicht](../README.md)

Diese Seite ist der vollständige Durchlauf durch eine Arbeit, in der Reihenfolge, in der
die Schritte tatsächlich anfallen. Zu jedem Schritt steht eine Formulierung, die du so
übernehmen kannst, und darunter, was dabei herauskommt — damit du merkst, wenn etwas
anderes passiert als erwartet.

Du musst nicht bei 1 anfangen: Spring dahin, wo du gerade stehst. Voraussetzung ist nur,
dass Setup und Kontext stehen — das erledigt [Erste Schritte](getting-started.md).
Welches Modell sich je Schritt lohnt und wo die teuren Stellen liegen, steht in
[Claude Code bedienen](working-with-claude-code.md).

Skills aktivieren sich selbst, sobald die passende Formulierung fällt — die Beispiele
unten enthalten deshalb bewusst die realen Trigger-Phrasen aus der
[Skills-Übersicht](../reference/skills.md). Commands rufst du dagegen explizit auf.

## 1. Kontext einrichten

```
Richte den Kontext für meine Arbeit ein: Bachelorarbeit über DevOps-Governance im
deutschen Mittelstand, Leibniz FH, Wirtschaftsinformatik, 60 Seiten.
```

Der `academic-context`-Skill fragt durch, was noch fehlt: Forschungsfrage, Arbeitstyp,
Hochschule, Disziplin, Methodik, Gliederung.

**Ergebnis:** `<projekt>/academic_context.md` ist gefüllt und wird ab jetzt von allen
anderen Skills gelesen. Ohne diesen Schritt raten alle folgenden Schritte.

## 2. Thema finden

Nur nötig, wenn das Thema noch offen ist:

```
Welches Thema passt zu mir? Wirtschaftsinformatik, 5. Semester, Interesse an
Governance und Automatisierung.
```

**Ergebnis:** 3–5 Themenkandidaten mit Feasibility-, Novelty- und Career-Fit-Score und je
zwei bis drei möglichen Forschungsfragen.

## 3. Forschungsfrage schärfen

```
Hilf mir, die Forschungsfrage zu formulieren: „Wie wirkt sich DevOps auf KMU aus?"
```

**Ergebnis:** Eine Bewertung auf Spezifität, Beantwortbarkeit und Falsifizierbarkeit plus
eine geschärfte Fassung. Erwarte Widerspruch — eine Frage, die alles offenlässt, kommt
umformuliert zurück.

## 4. Gliederung und Exposé

```
Bau mir eine Gliederung für die Arbeit und daraus ein Exposé.
```

**Ergebnis:** Ein Kapitelgerüst, gegen sieben Kriterien geprüft (Logik, Gewichtung,
Abdeckung der Forschungsfrage), und ein Exposé-Entwurf im Dialog.

## 5. Methodik wählen

```
Welche Methodik passt zu dieser Forschungsfrage — qualitativ, quantitativ, Mixed?
```

**Ergebnis:** Ein Methodenvorschlag mit Scoring über vier Dimensionen und der Begründung,
warum die Alternativen schlechter passen.

## 6. Literatur suchen

```
/academic-research:search "DevOps Governance Mittelstand KMU" --mode standard
```

**Ergebnis:** Parallele Suche über die API-Quellen, Deduplizierung, Scoring, Ablage im
Vault. Der Lauf meldet am Ende `Found N papers (0 modules failed, 0 modules skipped)`.
Jeder Lauf bekommt ein eigenes Sitzungsverzeichnis
`~/.academic-research/sessions/<zeitstempel>/`; die beschafften Volltexte liegen darin
unter `~/.academic-research/sessions/<zeitstempel>/pdfs/`, nicht in einem gemeinsamen
Sammelordner. Den zuletzt angelegten Ordner findest du mit
`ls -t ~/.academic-research/sessions/ | head -1`.

Für die systematische Recherche mit Browser-Modulen (Google Scholar, Springer, TIB):

```
/academic-research:search "IT Compliance KMU" --mode deep
```

Das ist der teuerste Suchmodus — Details zu Modi und Quellen stehen in
[Suchquellen und Scoring](../reference/search.md). Unbeaufsichtigt läuft
`--mode deep` nur, wenn `/academic-research:setup` (Schritt 4) den
Chrome-Verbindungsweg bereits eingerichtet hat — sonst bricht der
Browser-Teil kontrolliert mit einer Handlungsanweisung ab, siehe
[troubleshooting.md](troubleshooting.md).

## 7. Literaturliste aus einem Handout übernehmen

```
Literaturliste importieren: Übernimm literaturliste.pdf ins Vault.
```

**Ergebnis:** Die Einträge aus PDF, Markdown oder Text landen als Paper-Datensätze im
Vault, dedupliziert gegen den vorhandenen Bestand. Hast du eine Zotero-Bibliothek, sag
stattdessen *„Zotero importieren"*.

## 8. Bücher beschaffen

```
/academic-research:fetch 978-3-658-12345-6
```

Der `book-fetcher`-Agent probiert TIB, Springer, OAPEN, DOAB, KVK und weitere Quellen
gemäß deinem Per-Uni-Profil. Statt der ISBN gehen auch DOI, URL oder Freitext-Titel.

**Ergebnis:** Status `success` (PDF im Vault), `pickup_required` (Fernleihe-Eintrag in
`~/.academic-research/pickup_queue.json`), `captcha` oder `no_match`. Bei
`pickup_required` baust du dir mit `/academic-research:pickup` die Bibliotheksliste.

## 9. Treffermenge screenen

Bei großen Treffermengen (systematisches Review):

```
Ich muss viele Treffer screenen — bitte Screening parallelisieren nach meinen
Ein- und Ausschlusskriterien.
```

**Ergebnis:** Der `screening-judge`-Agent bewertet die Treffer aufgefächert auf Subagents,
schreibt ein Ledger mit Ein-/Ausschluss samt Begründung und aktualisiert die
PRISMA-Zähler. Der Lauf ist wiederaufnehmbar — ein Abbruch kostet dich das Ledger nicht.

## 10. Quellenqualität prüfen

```
Prüf die Quellenqualität der Top-20-Treffer.
```

**Ergebnis:** Ein Score von 0–100 über fünf Dimensionen je Quelle, mit Begründung. Damit
sortierst du aus, bevor du Lesezeit investierst.

## 11. Lesenotizen anlegen

```
Notiz zu einer Quelle anlegen: Kernbefund, Methode und Verwendbarkeit für
mein Kapitel 3.
```

**Ergebnis:** Ein strukturiertes Exzerpt im Vault (`vault.add_note()`), auffindbar über
`vault.search_notes()`. Das ist der Schritt, den man am ehesten überspringt und später am
meisten vermisst.

## 12. Vault abfragen

```
Welche Quellen im Vault behandeln IT-Governance im Mittelstand?
```

**Ergebnis:** Der Vault antwortet über `vault.search()` mit Snippet, Quelle und Seite —
ohne dass PDFs erneut hochgeladen werden. Das ist der Kern des Token-Sparens: Du arbeitest
mit Ausschnitten statt mit ganzen Dokumenten.

## 13. Studien vergleichen

```
Extraktionsmatrix erstellen: Studien vergleichen über die eingeschlossenen Quellen.
```

**Ergebnis:** Eine Matrix mit Quellen als Zeilen und den Schlüsselkonzepten als Spalten,
als Tabelle und als Arbeitsblatt exportierbar.

## 14. Bewerten und als Excel exportieren

```
/academic-research:score
/academic-research:excel --output literatur.xlsx
```

**Ergebnis:** Erst das Relevanz-Scoring über den `relevance-scorer`-Agent, dann eine
Excel-Übersicht deiner Literatur. Der Excel-Teil braucht das externe Plugin
`document-skills` — fehlt es, nennt der Command den Nachinstallations-Befehl.

## 15. Literaturlücken finden

```
Zeig mir die Literaturlücken pro Kapitel.
```

**Ergebnis:** Ein Coverage-Bericht je Kapitel: wo die Belege dünn sind, welche Konzepte
gar nicht gedeckt sind. Daraus wird die nächste Suchrunde.

## 16. Zitate extrahieren

```
Zitate finden zur Forschungsfrage: drei wörtliche Belege aus den drei
wichtigsten Quellen, mit Seitenzahl.
```

**Ergebnis:** Seitengenaue Belege im Vault. Ohne diesen Schritt bleibt der nächste
blockiert — der `verbatim-guard`-Hook lässt keinen Kapitel-Write mit einem Zitat durch,
das nicht im Vault steht.

## 17. Kapitel schreiben

```
Kapitel schreiben: Entwurf für das Methodik-Kapitel, gestützt auf die Quellen im Vault.
```

**Ergebnis:** Ein Entwurf, dessen Zitate über `vault.find_quotes()` belegt sind. Der
Entwurf landet in `<projekt>/kapitel/`. Das ist der teuerste Einzelschritt im ganzen
Durchlauf — pro Kapitel eine eigene Session lohnt sich.

## 18. Anti-KI-Audit

```
/academic-research:humanize kapitel/03-methodik.md --mode deep
```

**Ergebnis:** `kapitel/03-methodik.humanized.md` und `kapitel/03-methodik.diff.md` mit
einem Severity-Ranking der gefundenen KI-Muster. `--mode deep` ist gründlicher und
teurer; für einen ersten Blick reicht der Standardmodus.

## 19. Plagiatsnähe prüfen

```
Plagiat prüfen: Ist Kapitel 3 zu nah am Original meiner Hauptquelle?
```

**Ergebnis:** Ein N-Gramm-Overlap gegen die Vault-Quellen mit den kritischen Stellen.
Das ersetzt keinen Plagiatsdienst deiner Hochschule — siehe
[Grenzen](limits.md#was-das-plugin-nicht-darf).

## 20. PRISMA-Flow (nur systematische Reviews)

```
Erstelle den PRISMA-Flow für meine Literaturrecherche.
```

**Ergebnis:** Das Mermaid-Flussdiagramm mit den realen Zählern aus dem Screening plus die
27-Punkte-Checkliste.

## 21. Abstract, Titel, Formalia

```
Abstract schreiben (IMRaD, DE und EN).
Ich brauche Titelvorschläge.
Ist die Arbeit abgabefertig? Formalia prüfen nach FH-Leibniz-Vorgaben.
```

**Ergebnis:** Ein IMRaD-Abstract in beiden Sprachen, fünf bis sieben Titelvarianten mit
Begründung und ein Formalia-Bericht mit den konkreten Verstößen.

## 22. Exportieren

```
/academic-research:latex --kapitel all --output thesis.tex
/academic-research:word --kapitel all --output thesis.docx --format pdf
/academic-research:slides --kapitel all --output kolloquium.pptx --kolloquium
```

**Ergebnis:** `thesis.tex` plus `thesis.bib` (biblatex, DIN-1505), eine `.docx` mit echten
Formatvorlagen inklusive Titelblatt und eidesstattlicher Erklärung, und ein Foliensatz mit
einer Kernaussage pro Folie.

## 23. Abgabe reproduzierbar einfrieren

```
Erstelle einen Material-Passport und sperre den Vault.
```

**Ergebnis:** `material-passport.json` und ein gesetzter Repro-Lock. Danach sind keine
Schreibzugriffe mehr möglich, und der Stand bleibt exakt nachvollziehbar. Willst du danach
weiterarbeiten, brauchst du eine neue Vault-Kopie.

## Wenn du unterbrichst

Eine frühere Recherche-Session holst du dir mit
`/academic-research:history --restore-session <id>` zurück; Snapshots listet
`/academic-research:history --snapshots`. Wie du Zwischenstände gezielt sicherst, steht in
[Claude Code bedienen](working-with-claude-code.md).
