# Token-Budget — wo es teuer wird und wie du gegensteuerst

[← Doku-Übersicht](../README.md)

Eine Abschlussarbeit ist kein kurzer Chat: Recherche, Screening und Kapitelentwürfe
laufen über Wochen und viele Sitzungen. Wer dabei jede Suche auf voller Tiefe fährt und
jedes PDF erneut ins Fenster kippt, verbrennt Budget an Stellen, die keinen Erkenntniswert
haben. Diese Seite zeigt, welche Schritte teuer sind, mit welchem Befehl du sie eingrenzt
und wie du Zwischenstände sicherst, statt Arbeit zu wiederholen.

Welcher Schritt wann dran ist, steht im [Walkthrough](walkthrough.md); welches Modell
sich je Schritt lohnt, in [Modellwahl](model-choice.md).

## Die vier teuren Stellen

| Schritt | Warum teuer | Gegenmittel |
|---|---|---|
| Tiefensuche über Browser-Module | Jede Seite wird geladen, gerendert und gelesen; dazu Wartezeit pro Modul | Modus senken, Module gezielt wählen |
| Relevanz-Scoring großer Treffermengen | Ein Modellaufruf pro Paper | `--batch` oder kleinere Treffermenge |
| Volltext plus Embedding-Erstlauf | Erstes PDF zieht die Modellgewichte (~470 MB) und indexiert den ganzen Text | einmalig hinnehmen, danach offline |
| Kapitelentwürfe | Langer Output auf einem starken Modell, oft mehrfach überarbeitet | eigene Session pro Kapitel |

## Die Suche eingrenzen

Der häufigste Fehler: Alles auf `--mode deep` fahren, weil „gründlich" gut klingt. Für
die erste Orientierung reicht der schnelle Modus:

```
/academic-research:search "DevOps Governance Mittelstand" --mode quick
```

Willst du nur wissen, ob es überhaupt Literatur gibt, hol dir gar keine PDFs:

```
/academic-research:search "DevOps Governance Mittelstand" --mode metadata --limit 20
```

`--mode metadata` lädt keine Volltexte, `--limit` deckelt die Treffer pro Modul. Beides
zusammen macht aus einer Explorationssuche einen Vorgang von Sekunden.

Steht die Suchanfrage schon präzise, spar dir die Query-Erweiterung und die
Browser-Module:

```
/academic-research:search "DevOps Governance KMU" --no-expand --no-browser --limit 25
```

`--no-expand` überspringt den `query-generator`-Agent, `--no-browser` beschränkt den Lauf
auf die API-Quellen. Die vollständige Optionstabelle steht in der
[Commands-Referenz](../reference/commands.md).

## Große Treffermengen asynchron scoren

Ab etwa 50 Treffern lohnt sich der Batch-Weg: Das Relevanz-Scoring läuft dann über die
Anthropic-Message-Batches-API mit 50 % Rabatt, dafür mit rund einer Stunde Latenz.

```
/academic-research:search "IT Compliance KMU" --mode deep --batch
```

Das Ergebnis holst du dir später ab:

```
/academic-research:history --batch <id>
```

Das ist der einzige Hebel auf dieser Seite, der Geld spart, ohne Ergebnisqualität zu
kosten — er kostet nur Zeit.

## Wann sich ein eigener Kontext lohnt

Ein eigener Kontext heißt: eine frische Session oder ein Subagent, dessen Fenster nur das
enthält, was der Schritt wirklich braucht.

Lohnt sich, wenn:

- **Der Schritt lange Ausgaben erzeugt.** Ein Kapitelentwurf in einer Session, in der
  vorher 200 Suchtreffer diskutiert wurden, schleppt den gesamten Recherche-Verlauf mit.
  Neue Session, Kontextdatei und Vault sind da — mehr braucht das Kapitel nicht.
- **Der Schritt viele gleichförmige Urteile braucht.** Screening und Verzerrungsbewertung
  fächert das Plugin selbst auf Subagents auf; jeder bekommt nur seine Paper zu sehen:

  ```
  Ich muss viele Treffer screenen — bitte Screening parallelisieren.
  ```

- **Du das Thema wechselst.** Nach dem Sprung von der Methodik zur Diskussion ist der
  alte Verlauf Ballast, kein Kontext.

Lohnt sich **nicht**, wenn der Schritt auf dem unmittelbar vorher Gesagten aufbaut — dann
zahlst du den Aufbau des Kontexts doppelt.

## Zwischenstand sichern

Der teuerste Verlust ist nicht ein zu großes Fenster, sondern verlorene Arbeit.

**Automatisch vor jeder Compaction.** Der Hook `hooks/pre-compact.mjs` schreibt vor jedem
Verdichten des Verlaufs `academic_context.md`, `literature_state.md` und
`writing_state.md` weg und legt zusätzlich einen Vault-Tarball unter
`~/.academic-research/snapshots/<projekt>/` ab. Du musst dafür nichts tun; der Hook läuft
fail-open und blockiert nie.

**Manuell zurückholen.** Vorhandene Snapshots listest und stellst du so wieder her:

```
/academic-research:history --snapshots
/academic-research:history --restore 20260507-1430
```

Eine ganze frühere Recherche-Session machst du mit
`/academic-research:history --restore-session <id>` wieder zum Arbeitsstand.

**Der eigentliche Spar-Mechanismus ist der Vault.** Alles, was einmal drin ist — Paper,
Zitate, Notizen, Ausschlussentscheidungen — musst du nie wieder ins Fenster laden. Statt
ein PDF erneut anzuhängen, fragst du:

```
Welche Quellen im Vault behandeln IT-Governance?
```

Der Vault antwortet über `vault.search()` mit Snippet und Seitenzahl. Ein Treffer-Snippet
kostet einen Bruchteil eines PDF-Uploads, und der Beleg bleibt seitengenau.

## Was nichts bringt

- **„Fass dich kurz" als Dauerauftrag.** Das spart Output-Tokens und kostet Substanz.
  Begrenz lieber den Input.
- **Alles in eine einzige Riesensitzung packen**, um „den Kontext nicht zu verlieren".
  Der Kontext liegt in `academic_context.md` und im Vault, nicht im Verlauf.
- **Auf ein kleineres Modell ausweichen, wo es auf Qualität ankommt.** Welche Schritte das
  sind, steht in [Modellwahl](model-choice.md); welche Grenzen davon unabhängig gelten, in
  [Grenzen und bewährtes Vorgehen](best-practices.md).
