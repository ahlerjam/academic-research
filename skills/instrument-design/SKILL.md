---
name: instrument-design
description: >
  Verwende diesen Skill, wenn der User für seine eigene Erhebung ein
  Erhebungsinstrument braucht — also einen Interviewleitfaden, einen Fragebogen
  oder ein Beobachtungsraster —, das sich aus der Forschungsfrage und der
  bereits gewählten Methodik ableitet. Trigger-Phrasen:
  "Interviewleitfaden erstellen", "Fragebogen entwickeln",
  "Erhebungsinstrument für meine Arbeit / Erhebungsinstrument fuer meine
  Arbeit", "Leitfaden für die Experteninterviews / Leitfaden fuer die
  Experteninterviews", "Beobachtungsraster bauen",
  "welche Fragen soll ich stellen", "Operationalisierung meiner
  Forschungsfrage". Liest Forschungsfrage, Unterfragen und Methodik aus
  `academic_context.md` und gibt zu jedem Instrument eine Rückverweis-Matrix
  aus, die jede Frage genau einer Unterfrage bzw. der Forschungsfrage zuordnet.
  Die Methodenwahl selbst trifft `methodology-advisor`, die Auswertung des
  erhobenen Materials übernimmt `qualitative-coding`.
license: MIT
allowed-tools: [Read, Write]
---

# Erhebungsinstrument entwerfen

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Zweck

Zwischen „ich nehme qualitative Interviews" und dem ersten geführten Interview
liegt ein Artefakt, das die Forschungsfrage in beantwortbare Fragen übersetzt.
Dieser Skill baut es — und macht die Übersetzung nachprüfbar, statt eine Liste
plausibel klingender Fragen zu liefern.

## Eingaben

Gelesen wird ausschließlich `academic_context.md`:

| Feld | Verwendung | Fehlt es? |
| --- | --- | --- |
| Forschungsfrage | Wurzel der Rückverweis-Matrix | **Abbruch** (siehe unten) |
| Unterfragen | Gliederungsebene des Instruments | Instrument bleibt einstufig, Hinweis an den User |
| Methodik/Forschungsdesign | Bestimmt den Instrumententyp | Rückfrage an den User, keine Annahme |
| Zielgruppe/Sample | Ansprache, Vorwissen, Sprachniveau | Neutrale Ansprache, als offene Stelle markiert |

**Ohne Forschungsfrage kein Instrument.** Steht in `academic_context.md` keine
Forschungsfrage (oder nur ein Themenfeld), brich ab und verweise auf
`academic-context` (Kontext anlegen) bzw. `research-question-refiner`
(Formulierung schärfen). Ein Instrument ohne Forschungsfrage ist nicht
verbesserungsfähig — es ist gegenstandslos.

## Instrumententypen

| Methodik im Kontext | Instrument | Kernmerkmal |
| --- | --- | --- |
| Leitfadeninterview, Experteninterview | Interviewleitfaden | Erzählgenerierende Einstiegsfrage, Nachfragen als Optionen |
| Standardisierte Befragung | Fragebogen | Geschlossene Items mit expliziter Skala, je Item ein Konstrukt |
| Teilnehmende Beobachtung | Beobachtungsraster | Beobachtbare Ereignisse, keine Deutungen in der Spalte |
| Gruppendiskussion | Diskussionsleitfaden | Impulse statt Fragen, Reihenfolge dramaturgisch |

Passt die Methodik zu keinem Typ, frag nach, statt den nächstähnlichen zu wählen.

## Ablauf

1. `academic_context.md` lesen; fehlende Pflichtfelder wie oben behandeln.
2. Je Unterfrage 2–4 Fragen formulieren. Eine Frage, die sich keiner Unterfrage
   zuordnen lässt, kommt nicht ins Instrument — sie zeigt entweder eine fehlende
   Unterfrage oder überflüssige Neugier.
3. Sprachlich prüfen: keine Suggestivfragen, keine doppelten Verneinungen, keine
   zwei Konstrukte in einer Frage, keine Fachbegriffe ohne Erklärung.
4. Dramaturgie festlegen: Einstieg (niedrigschwellig) → Hauptteil (je Unterfrage
   ein Block) → Abschluss (offene Ergänzung, Rückgabe an die Befragten).
5. Rückverweis-Matrix erzeugen (Pflicht, siehe unten).
6. Instrument nach `empirie/<instrument>.md` schreiben, Matrix im selben Dokument.
7. Die Entscheidung über Instrumententyp und Fragenzuschnitt via
   `vault.add_decision(category="erhebung", …)` festhalten.

## Rückverweis-Matrix

**Pflichtausgabe.** Kein Instrument wird ohne diese Matrix ausgeliefert — sie
ist der Beleg dafür, dass die Fragen aus der Forschungsfrage stammen und nicht
aus dem Sprachmodell.

| Frage | Unterfrage/FF | Begründung |
| --- | --- | --- |
| 1. Wie sieht ein typischer Arbeitstag bei Ihnen aus? | UF1 | Erzählgenerierender Einstieg, liefert Kontext für UF1 |
| 2. Woran merken Sie, dass eine Abstimmung gelungen ist? | UF2 | Operationalisiert „gelungene Abstimmung" aus UF2 |
| 3. Was würden Sie ändern, wenn Sie könnten? | FF | Deckt den normativen Teil der Forschungsfrage ab |

Regeln zur Matrix:

- Jede Frage steht genau einmal in der Spalte „Frage".
- Die Spalte „Unterfrage/FF" enthält eine konkrete Kennung (UF1, UF2 … oder FF),
  nie „allgemein" oder „Hintergrund".
- Bleibt eine Unterfrage ohne Frage, wird das unter der Matrix als Lücke
  benannt — nicht stillschweigend hingenommen.

## Abgrenzung

- `methodology-advisor` wählt die **Methode** („welches Design passt?"). Dieser
  Skill setzt eine bereits gewählte Methodik voraus und baut das Werkzeug dazu.
- `qualitative-coding` übernimmt **nach** der Erhebung: Transkripte aufnehmen,
  Kategorien bilden, Kodierungen auswerten.
- `research-question-refiner` schärft die Forschungsfrage selbst; hier wird sie
  nur noch übersetzt.
- Die Erhebung **durchführen** (Rekrutierung, Termine, Aufnahme) ist nicht Teil
  dieses Skills.

## Personenbezogene Daten

Instrumente enthalten regelmäßig Fragen, deren Antworten personenbezogen sind.
Verwende in Beispielen und Vorlagen Sprecherkürzel (`B1`, `IP2`) statt
Klarnamen und weise den User einmalig darauf hin, dass Einwilligung,
Aufbewahrung und Anonymisierung vor der ersten Erhebung geklärt sein müssen.
Das ist ein Hinweis, **keine Datenschutz-Beratung** und ersetzt keine
Rechtsauskunft — die Prüfung durch die zuständige Stelle (Ethikkommission,
Datenschutzbeauftragte) bleibt Sache des Users.
