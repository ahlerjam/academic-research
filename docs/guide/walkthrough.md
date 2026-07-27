# Walkthrough — von der Themenfindung bis zur Abgabe

[← zurück zur README](../../README.md)

Der [Quickstart in der README](../../README.md#quickstart) bringt dich bis zum ersten
verifizierten Zitat. Diese Seite zeigt den vollständigen Weg durch eine Arbeit. Du musst
die Schritte nicht der Reihe nach abarbeiten — spring dahin, wo du gerade stehst.

Voraussetzung: Setup ist gelaufen, du bist in deinem Projektordner
(siehe [Installation](installation.md)).

## 1. Kontext einrichten

```
Ich schreibe eine Bachelorarbeit über DevOps-Governance
im deutschen Mittelstand. Leibniz FH, Wirtschaftsinformatik, 60 Seiten.
```

Der `academic-context`-Skill fragt durch: Forschungsfrage, Arbeitstyp, Hochschule,
Disziplin, Methodik, Gliederung. Das Ergebnis landet in `<projekt>/academic_context.md`
und wird ab da von allen anderen Skills gelesen.

## 2. Thema finden

Noch kein Thema? Der `topic-brainstorm`-Skill hilft:

```
Ich studiere Wirtschaftsinformatik im 5. Semester — welches Thema könnte passen?
```

Liefert 3–5 Kandidaten mit Feasibility/Novelty/Career-Fit-Scores und je 2–3
Forschungsfragen.

## 3. Forschungsfrage schärfen

```
Ist meine Forschungsfrage gut? „Wie wirkt sich DevOps auf KMU aus?"
```

`research-question-refiner` prüft Spezifität, Beantwortbarkeit, Falsifizierbarkeit.

## 4. Literatur suchen

```
/academic-research:search "DevOps Governance Mittelstand KMU" --mode standard
```

Sucht parallel in 7 APIs, dedupliziert, scort auf 5 Dimensionen. PDFs landen in
`~/.academic-research/pdfs/`.

Für die systematische Suche mit Browser-Modulen (Google Scholar, Springer, TIB usw.):

```
/academic-research:search "IT Compliance KMU" --mode deep
```

Details zu Modi und Quellen: [Suchquellen und Scoring](../reference/search.md).

## 5. Buch beschaffen

```
/academic-research:fetch "IT-Governance im Mittelstand" --isbn 978-3-658-12345-6
```

Der `book-fetcher`-Agent probiert TIB, Springer, OAPEN, KVK und weitere Quellen gemäß
deinem Per-Uni-Profil.

## 6. Literaturliste aus einem Handout importieren

```
/academic-research:search --import-list literaturliste.pdf
```

Oder über den `reading-list-import`-Skill: *„Importiere diese Quellenliste ins Vault."*

## 7. Vault abfragen

```
Welche Quellen im Vault behandeln IT-Governance?
```

Der Vault antwortet mit Snippet und Seite, ohne dass PDFs erneut hochgeladen werden.

## 8. Papers bewerten und Excel exportieren

```
/academic-research:score
/academic-research:excel
```

## 9. Kapitel schreiben

```
Schreib mir einen Entwurf für das Methodik-Kapitel.
```

`chapter-writer` nutzt Vault-Zitate via `vault.find_quotes()` — seitengenau und gegen den
Vault geprüft. Der `verbatim-guard`-Hook blockt jeden Kapitel-Write mit einem Zitat, das
nicht im Vault steht.

## 10. Anti-KI-Audit mit humanizer-de

```
/academic-research:humanize kapitel/03-methodik.md --mode deep
```

Erzeugt `kapitel/03-methodik.humanized.md` und `kapitel/03-methodik.diff.md` mit
Severity-Ranking der KI-Muster.

## 11. PRISMA-Flow (für Systematic Reviews)

```
Erstelle den PRISMA-Flow für meine Literaturrecherche.
```

Der `prisma-flow`-Skill rendert das Mermaid-Diagramm und die 27-Punkte-Checkliste.

## 12. Abstract, Titel, Formalia-Check

```
Schreib ein IMRaD-Abstract (DE + EN).
Ich brauche 5 Titelvorschläge.
Ist die Arbeit abgabefertig? FH-Leibniz-Formalia prüfen.
```

## 13. LaTeX-Export

```
/academic-research:latex --kapitel all --output thesis.tex
```

Erzeugt `thesis.tex` und `thesis.bib` (biblatex, DIN-1505-Stil).

## 14. Abgabe reproduzierbar einfrieren

```
Erstelle einen Material-Passport und sperre den Vault.
```

Der `material-passport`-Skill schreibt `material-passport.json` und setzt den Vault-Lock
(Repro-Lock). Danach sind keine Schreibzugriffe mehr möglich — der Stand bleibt exakt
nachvollziehbar.
