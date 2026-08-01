---
name: reading-notes
description: >
  Verwende diesen Skill, wenn der User beim Lesen einer Quelle eine Notiz
  oder ein Exzerpt festhalten möchte. Trigger-Phrasen: "Notiz zu einer
  Quelle anlegen", "Exzerpt für eine Quelle erstellen / Exzerpt fuer eine
  Quelle erstellen", "Kernbefund festhalten", "diese Quelle zusammenfassen
  und einordnen", "meine Notizen zu diesem Paper durchsuchen", "was hatte
  ich zu dieser Studie notiert". Legt pro Quelle ein strukturiertes
  Exzerpt (Kernbefund/Methode/Verwendbarkeit) via `vault.add_note()` an,
  ohne dass der Nutzer die Struktur selbst vorgeben muss. Für
  Direktzitate mit Wortlaut aus dem PDF → `citation-extraction`. Für die
  Verarbeitung der Notizen in Kapitel-Prosa → `chapter-writer`.
license: MIT
allowed-tools: [Read]
---

# Lese-Notizen

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Übersicht

Legt beim Lesen einer Quelle ein strukturiertes Exzerpt im Vault an
(`vault.add_note()`). Anders als ein Direktzitat ist eine Notiz eine eigene
Verdichtung: Kernbefund, Methode und Verwendbarkeit für die eigene
Fragestellung — in eigenen Worten, mit optionaler Seitenangabe.

## Abgrenzung

Legt Exzerpte/Notizen zu einer Quelle an, findet und durchsucht sie wieder.
Wörtliche Zitate mit exaktem Wortlaut aus dem PDF → `citation-extraction`
(nutzt `vault.add_quote()`, nicht `vault.add_note()`). Die
Extraktionsmatrix (tabellarischer Studienvergleich über mehrere Quellen) ist
kein Teil dieses Skills.

## Kontext-Dateien

- Vault-Queries: `vault.find_notes(paper_id, query=None, k=10)` für Notizen
  zu einer bestimmten Quelle, `vault.search_notes(query, k=5)` für die
  themenbezogene Volltextsuche über alle Notizen hinweg
- Schreiben: `vault.add_note(paper_id, text, tags=None, page=None)`

## Core-Workflow

### 1. Quelle bestimmen

Kläre, zu welcher Quelle die Notiz gehört (`paper_id` aus `vault.search()`
oder direkt vom User genannt). Ist die Quelle noch nicht im Vault, zuerst
`vault.add_paper()` anlegen lassen (z. B. über `zotero-import` oder
`reading-list-import`) — eine Notiz ohne Quellenverknüpfung ist nicht
zulässig.

### 2. Struktur vorgeben, nicht abfragen

AC5: Die Struktur des Exzerpts kommt vom Skill, nicht vom User. Beim Lesen
der Quelle (PDF-Volltext via `vault.get_paper()`-`pdf_path` + `Read`-Tool
oder vom User eingefügter Auszug) leitest du selbstständig ab:

1. **Kernbefund** — die zentrale Aussage/das Ergebnis in 1-2 Sätzen
2. **Methode** — wie der Befund zustande kam (Design, Stichprobe, Verfahren)
3. **Verwendbarkeit** — wofür die Quelle in der eigenen Arbeit taugt (welche
   Forschungsfrage/welches Kapitel sie stützt, welche Einschränkung sie hat)

Frag den User nicht nach dieser Gliederung — sie ist der Zweck des Skills.
Nur bei echten inhaltlichen Lücken (z. B. Methode aus dem Text nicht
ableitbar) das explizit im Feld vermerken statt zu fabrizieren.

### 3. Seitenangabe (optional)

Ist die Textstelle einer konkreten Seite zuordenbar, `page` mitgeben
(gedruckte Seite, nicht PDF-Seite — siehe `vault.get_printed_page()` bei
Büchern mit Vorseiten). Ist der Kernbefund eine quellenübergreifende
Synthese ohne Einzelseite, bleibt `page` leer — keine Pflichtangabe.

### 4. Notiz persistieren

```
vault.add_note(
  paper_id="<paper_id>",
  text="Kernbefund: ...\nMethode: ...\nVerwendbarkeit: ...",
  page=<optional>
)
```

Dem User die gespeicherte Notiz kurz bestätigen (Quelle + die drei Felder),
nicht nur die rohe `note_id`.

### 5. Notizen wiederfinden

- Zu einer bestimmten Quelle: `vault.find_notes(paper_id, query=<optional Filter>)`
- Themenbezogen über alle Quellen: `vault.search_notes(query)` — das ist der
  Weg, den `chapter-writer` beim Quellen-Mapping nutzt, um passende Exzerpte
  zu einem Kapitelthema zu finden

## Wichtige Regeln

- **Nie den Kernbefund erfinden** — nur festhalten, was im gelesenen Text steht
- **Eigene Worte, keine Zitat-Verwechslung** — für Wortlaut-Zitate gilt `citation-extraction`
- **Struktur immer mitliefern** — Kernbefund/Methode/Verwendbarkeit auch ohne explizite Nachfrage des Users
- **Seitenangabe wenn möglich** — erleichtert spätere Prüfung am Original
- **Quellenverknüpfung ist Pflicht** — jede Notiz braucht eine `paper_id`
