---
name: peer-review
description: Use this skill when the user takes on the reviewer role and needs a structured peer-review report for someone else's manuscript. Triggers on "Gutachten für ein Manuskript schreiben / Gutachten fuer ein Manuskript schreiben", "Manuskript begutachten", "Peer-Review-Gutachten verfassen", "Referee-Report schreiben", "als Gutachter urteilen". Erzeugt ein Gutachten mit getrennten Blöcken für Redaktion (vertraulich) und Autor:innen, genau einer begründeten Empfehlung, nummerierten Anmerkungen mit Fundstelle. Für die Gegenrichtung (Antwort auf erhaltene Gutachten) → `reviewer-response`.
license: MIT
allowed-tools:
  - Read
---

# Peer-Review-Gutachten

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Keine Fabrikation, Aktivierung,
> Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt fortfährst.
> **Ausnahme:** Der Preamble-Block „Vorbedingungen" (`./academic_context.md`,
> `./literature_state.md`) greift hier nicht — Gegenstand dieses Skills ist
> ein **fremdes** Manuskript ohne Bezug zur eigenen Arbeit. Kein Trigger auf
> `academic-context` nötig; startet direkt mit dem eingefügten Manuskripttext.

## Übersicht

Verfasst ein strukturiertes Gutachten aus der Perspektive eines Gutachters,
der ein fremdes Manuskript **liest** — bewertet wird ausschließlich, was im
eingefügten Text steht. Deckt fünf Standardbereiche ab, trennt vertrauliche
Redaktionsanmerkungen von den Anmerkungen an die Autor:innen und mündet in
genau eine begründete Empfehlung.

## Abgrenzung

Erstellt das Gutachten selbst zu einem **fremden** Manuskript. Für die
Gegenrichtung — eine Antwort auf bereits erhaltene Gutachten zur **eigenen**
Arbeit verfassen → `reviewer-response`. Für die Bewertung von generiertem
Kapiteltext der eigenen Arbeit nach einem Qualitäts-Framework →
`quality-reviewer`-Agent. Für die Bias-Bewertung eines Vault-Papers nach
einem festen Bias-Framework → `risk-of-bias`-Agent. Für Textnähe-Prüfung
gegen Quellen → `plagiarism-check`. Kein Umschreiben des Manuskripts, keine
Textvorschläge — ein Gutachten sagt, was fehlt, nicht wie es zu schreiben
ist. Keine Plagiatsprüfung, keine Bewertung von Interessenkonflikten oder ob
das Gutachten angenommen werden sollte, kein automatisches Einreichen bei
einem Redaktionssystem, keine Doppelblind-/Anonymitätsprüfung.

## Workflow

### 1. Manuskript einlesen

Der Nutzer fügt den Manuskripttext ein (Copy-Paste oder Datei). Ohne
eingefügten Text kann kein Gutachten entstehen — danach fragen, nicht
annehmen.

### 2. Referenzstruktur laden

Lies `${CLAUDE_PLUGIN_ROOT}/skills/peer-review/references/gutachten-structure.md`
für Redaktions-/Autoren-Block, Empfehlungs-Skala und das nummerierte
Anmerkungsschema.

### 3. Fünf Bereiche durchgehen

Für jeden der folgenden Bereiche eine Einschätzung **ausschließlich anhand
des vorliegenden Manuskripttexts** formulieren:

1. **Fragestellung und Beitrag** — Ist die Forschungsfrage erkennbar, ist der
   Beitrag zum Feld benannt?
2. **Methodik** — Ist das Vorgehen nachvollziehbar und für die Fragestellung
   angemessen beschrieben?
3. **Ergebnisdarstellung** — Sind Ergebnisse vollständig und nachvollziehbar
   berichtet (Tabellen/Abbildungen konsistent zum Text)?
4. **Einordnung in die Literatur** — Verortet das Manuskript sich selbst
   erkennbar gegenüber der zitierten Literatur?
5. **Darstellung und Sprache** — Ist der Text klar strukturiert und
   verständlich geschrieben?

**Nicht-beurteilbar-Regel:** Lässt sich ein Bereich anhand des vorliegenden
Textausschnitts nicht beurteilen (z. B. Methodik-Kapitel fehlt im
eingefügten Auszug), wird das im Gutachten **explizit als „nicht
beurteilbar" ausgewiesen** — der Bereich wird nie stillschweigend
übergangen oder mit einer Vermutung gefüllt.

### 4. Anmerkungen sammeln

Jede Anmerkung bekommt eine fortlaufende Nummer und eine Fundstelle
(Abschnitt/Seite/Zeile oder Zitat aus dem Manuskript). Anmerkungen werden
konstruktiv formuliert: als konkrete Anforderung („Abschnitt 3 sollte die
Stichprobengröße begründen"), nie als Urteil über die Autor:innen
(„Die Autoren haben sich zu wenig Mühe gegeben" ist unzulässig).

### 5. Empfehlung bilden

Genau eine Empfehlung aus vier Optionen wählen — Annahme, kleinere
Überarbeitung, größere Überarbeitung, Ablehnung — mit Begründung, die sich
aus den Anmerkungen der fünf Bereiche ergibt. Keine zweite, konkurrierende
Empfehlung im selben Gutachten.

### 6. Gutachten ausgeben

Nach der Struktur aus `references/gutachten-structure.md`: zuerst der
vertrauliche Redaktionsblock, danach der Block für die Autor:innen. Beide
Blöcke sind durch eine eigene Überschrift getrennt und dürfen nicht
vermischt werden — vertrauliche Einschätzungen (z. B. Verdacht auf Redundanz
mit einer anderen Einreichung) gehören nie in den Autor:innen-Block.

## Wichtige Regeln

- **Keine erfundene „übersehene" Literatur:** Der Skill benennt niemals
  Literatur als vom Manuskript „übersehen", ohne dass diese Literatur belegt
  existiert (echter Titel/Autor/Jahr) und für die Fragestellung einschlägig
  ist. Ist keine solche Quelle bekannt, bleibt der Punkt offen statt erfunden
  zu werden.
- **Textbindung:** Jede Aussage über das Manuskript muss an einer konkreten
  Textstelle festmachbar sein. Keine Vermutungen über Absicht, Motivation
  oder fachliche Kompetenz der Autor:innen — nur Aussagen darüber, was der
  Text leistet oder nicht leistet.
- **Vertraulich vs. Autor:innen:** Der Redaktionsblock kann Verdachtsmomente
  und strategische Einschätzungen enthalten (z. B. Passung zur Zeitschrift),
  die Autor:innen sehen nur konstruktive, umsetzbare Anmerkungen.
- **Genau eine Empfehlung:** Nie zwei Empfehlungen nebeneinander stehen
  lassen — das Gutachten muss zu einem Urteil kommen.
- **Nummerierung + Fundstelle sind Pflicht:** Eine Anmerkung ohne Nummer oder
  ohne Fundstelle ist unvollständig und wird nicht ausgegeben.
