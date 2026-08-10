# humanizer-de vs. style-evaluator: Trigger-Grenze und Mess-Harness-Defekt (#825)

> **Historisches Dokument.** Momentaufnahme der Entscheidung und der
> Messwerte vom 2026-08-11. Der Sollzustand steht im Code: den Beschreibungen
> in `skills/humanizer-de/SKILL.md` / `skills/style-evaluator/SKILL.md` und
> im Harness `tests/evals/test_triggers.py`.

[← Doku-Übersicht](../README.md) · [← Evals-Übersicht](README.md)

**Stand:** 2026-08-11 · **Ausgangs-Issue:** #825 (Trigger-Recall
`humanizer-de`/`title-generator`) · **Vorgänger-Issues:** #177 (ursprüngliche
Abgrenzung humanizer-de/style-evaluator), #198 (Eval-Coverage-Guard, seit dem
das hier betroffene Goldset besteht), #837 (Zwischenstand, durch dieses
Dokument abgelöst) · **PR:** #834

## Zwei getrennte Ursachen, zwei getrennte Fixes

Issue #825 begann mit dem Symptom "`humanizer-de`-Recall unter der 85 %-Schwelle".
Ein Diagnoseskript (echte `claude`-CLI-Aufrufe, `claude-haiku-4-5-20251001`,
identische Logik wie `_classify`) hat für jeden fehlschlagenden
`should_trigger`-Prompt die **volle Rohausgabe** protokolliert, statt nur das
geparste erste Token. Ergebnis: die sechs beobachteten Misses (`humanizer-de`
7/10, `style-evaluator` 7/10) zerfielen in zwei völlig verschiedene Klassen.

### Ursache 1 (vier von sechs Missern): Mess-Harness, nicht Skill

Vier Misses waren gar keine Dispatch-Entscheidungen, sondern Rückfragen nach
dem zu bearbeitenden Text:

```
[MISS] 'Fuehre einen Anti-KI-Audit auf meinem Text durch.' -> 'gerne!'
  Gerne! Um einen Anti-KI-Audit mit dem **humanizer-de**-Skill durchzuführen,
  brauche ich den Text, den ich prüfen soll. Bitte stelle mir den Text zur
  Verfügung ...

[MISS] 'Klingt das nach ChatGPT? Bitte ueberarbeiten.' -> 'ich'
  Ich bräuchte den Text, um ihn zu prüfen und ggf. zu überarbeiten! Welcher
  Text ist gemeint? ...

[MISS] 'Akademisch genug?' -> 'ich'
  Ich brauche mehr Kontext, um dir zu helfen! Was genau soll ich prüfen? ...
```

Ursache: der zu klassifizierende Prompt ging bis dahin als gewöhnliche
User-Nachricht in `call_claude(system=..., user=user_prompt)` ein. Das Modell
beantwortete ihn folgerichtig **als Assistent an den Nutzer** statt ihn als
Dispatcher zu klassifizieren — der Skill-Name taucht in der Antwort teils auf
(erster Fall), teils gar nicht (zweiter/dritter Fall), aber nie als erstes
Token.

**Fix (in `tests/evals/test_triggers.py`, `TRIGGER_SYSTEM_TEMPLATE`):** der
zu klassifizierende Prompt wird jetzt in `<user_prompt>`-Tags gekapselt, mit
expliziter Anweisung, ihn nicht zu beantworten, keine Rückfrage zu stellen
und trotzdem — auch bei fehlenden Angaben wie dem zu bearbeitenden Text
selbst — anhand der Absicht zu klassifizieren.

Das ist eine Härtung, keine Aufweichung:

- Die Trefferbedingung ist wortgleich geblieben:
  `_classify(p, skill) == skill`, `output.strip().lower().split()[0]`. Kein
  Fallback, kein "Name kommt irgendwo in der Antwort vor"-Match.
- Die Änderung gilt für alle 45 Skills gleich, für `should_trigger` **und**
  `should_not_trigger`.
- **Gegenbeleg:** die False-Positive-Rate blieb über alle acht in #825
  nachgemessenen Skills bei 0/10 (0/7 bei `preregistration`) — vor und nach
  der Kapselung unverändert. Wäre die Kapselung eine Aufweichung, müsste sie
  dort anschlagen (mehr `should_not_trigger`-Prompts würden fälschlich als
  Treffer durchgehen).
- Eine Antwort, die trotz Kapselung nicht dispatcht, bleibt ein Miss (siehe
  `slide-export` in der Tabelle unten — ein Rückfrage-Ausreißer bleibt auch
  nach der Härtung bestehen).

Verifiziert an allen sechs ursprünglich beobachteten Missern: **alle sechs
klassifizieren nach der Kapselung korrekt** — einschließlich der beiden
`none`-Fälle unten (Ursache 2), **ohne** dass die `style-evaluator`-
Beschreibung um neue Trigger-Begriffe erweitert wurde. Die Kapselung allein
hat gereicht.

### Ursache 2 (zwei von sechs Missern): echte Beschreibungslücke — geprüft, nicht vorhanden

Zwei Misses waren wörtliche `none`-Antworten (`"Fuellwoerter-Analyse"`,
`"Wortanzahl und Lesbarkeit"`). Vor einer Beschreibungsänderung wurde geprüft,
ob `style-evaluator` diese Fähigkeiten tatsächlich hat (Skill-Body, nicht nur
Goldset) — sonst wäre eine Erweiterung der `description` um diese Begriffe
dieselbe Sorte Manipulation gewesen wie ein gelockerter Parser: eine
Beschreibung, geschrieben auf ein Goldset hin, ohne dass die Fähigkeit
dahintersteht.

**Ergebnis:** nicht nötig. Nach der Harness-Härtung (Ursache 1) klassifizierten
beide Prompts ebenfalls korrekt — es waren keine echten Fähigkeitslücken,
sondern derselbe Rückfrage-Mechanismus wie oben (kurze, kontextarme Prompts
lösten eine "was genau meinst du"-Antwort statt einer Dispatch-Entscheidung
aus). `skills/style-evaluator/SKILL.md` wurde entsprechend **nicht** um
„Füllwörter"/„Wortanzahl"/„Lesbarkeit" erweitert.

## Die Abgrenzung selbst (Issue #177 revidiert)

Unabhängig von den beiden Harness-Ursachen bestand ein zweiter, echter
Widerspruch: ein Zwischenstand von PR #834 hatte versucht, KI-Detektions-
Prompts ("Prüfe … auf KI-typische Muster") aus `humanizer-de`s Goldset in
`style-evaluator`s Goldset zu verschieben — Live-Messung zeigte, dass diese
Prompts beim Dispatcher-Modell durchgängig `humanizer-de` zuordnen, nicht
`style-evaluator` (Details und die verworfene Verschiebung: #837).

Issue #177 (die ursprüngliche Abgrenzung) zog textuell "Detektion →
style-evaluator, Korrektur → humanizer-de". Das seit #198 bestehende Goldset
(`evals/humanizer-de/trigger_evals.json`) ordnet KI-Detektions-Prompts aber
schon immer `humanizer-de` zu — im Widerspruch zu #177s Text, aber konsistent
mit der tatsächlichen Dispatcher-Realität. Entscheidung: die Grenze wird
bewusst neu gezogen, nicht nur um Tests grün zu bekommen, sondern weil die
Messung sie stützt:

- **`humanizer-de`** deckt jede KI-bezogene Prüfung/Audit ab — auch ohne
  anschließende Überarbeitung ("KI-typisch", "KI-generiert",
  "ChatGPT-artig").
- **`style-evaluator`** bleibt Detektion-only, aber nur für KI-freie
  Stilqualitätsmetriken (Satzlänge, Passiv-Quote, Nominalstil, Duktus,
  Score) — der vorherige Trigger "KI-Erkennung" ist entfernt.

`tests/test_issue_177_ki_trigger_disambiguation.py` ist mit begründendem
Docstring-Update auf diese revidierte Abgrenzung angepasst; die vier
Assertions selbst sind unverändert.

Nebenbefund beim Beschreibungs-Umbau: `_load_all_descriptions` (der
Dispatcher-Klassifikator-Prompt) kürzt jede Skill-Beschreibung hart auf 500
Rohzeichen (inklusive YAML-`>`-Präfix und Einrückung). Der neue
Abgrenzungssatz in `humanizer-de` musste deshalb an den Anfang der
Beschreibung gezogen werden — sonst hätte der Dispatcher ihn nie gesehen,
unabhängig davon, ob er inhaltlich richtig war.

## Ergebnis: vollständige Nachmessung

Ein Lauf, kein Wiederholen bis grün. `humanizer-de`, `style-evaluator`,
`title-generator` und die fünf Skills, die vor #825 bereits bestanden
(`literature-excel`, `notebook-bundle`, `preregistration`,
`reading-list-import`, `slide-export`) — damit der Recall-Gewinn nicht durch
eine neue Verdrängung an anderer Stelle erkauft ist:

| Skill | Recall | FPR |
|---|---|---|
| `humanizer-de` | 9/10 (90 %) | 0/10 (0 %) |
| `style-evaluator` | 9/10 (90 %) | 0/10 (0 %) |
| `title-generator` | 10/10 (100 %) | 0/10 (0 %) |
| `literature-excel` | 10/10 (100 %) | 0/10 (0 %) |
| `notebook-bundle` | 10/10 (100 %) | 0/10 (0 %) |
| `preregistration` | 7/7 (100 %) | 0/7 (0 %) |
| `reading-list-import` | 10/10 (100 %) | 0/10 (0 %) |
| `slide-export` | 9/10 (90 %) | 0/10 (0 %) |

Alle acht über der 85 %-Recall- bzw. unter der 10 %-FPR-Schwelle. Kein Skill
bei 100 % Recall außer den vieren, die es zufällig trafen — die verbliebenen
90 %-Werte sind einzelne Rückfrage-Ausreißer, die auch die Kapselung nicht
vollständig eliminiert (z. B. `slide-export`: `"Erzeuge ein .pptx aus meiner
Thesis."` → `'ich'`). Das ist inhärente Nichtdeterminiertheit eines
Live-Modells, kein Regress und keine offene Ursache mehr — die Schwelle von
85 % ist genau dafür gesetzt.

Befehl (fünf gebündelt je Skill, drei Batch-Läufe wegen CLI-Laufzeit):

```
uv run pytest \
  "tests/evals/test_triggers.py::test_should_trigger_recall[<skill>]" \
  "tests/evals/test_triggers.py::test_should_not_trigger_fpr[<skill>]" \
  -p no:randomly
```

## Bezug zu Issue #837

#837 dokumentierte den Zwischenstand (verworfene Goldset-Verschiebung,
`style-evaluator` 9/10 mit dem damaligen, noch ungehärteten Harness). Dieses
Dokument ersetzt #837 als permanenten Datensatz: dieselbe Boundary-
Entscheidung, jetzt ergänzt um die eigentliche Ursache (Mess-Harness) und die
vollständige Achter-Skill-Nachmessung. #837 ist geschlossen, mit Verweis
hierher.
