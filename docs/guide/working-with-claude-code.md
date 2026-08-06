# Claude Code richtig bedienen — Commands, Skills, Modelle, Sitzungen

[← Doku-Übersicht](../README.md)

Ob du mit diesem Plugin gut arbeitest, hängt weniger an den Skills als an der Bedienung.
Wer alles in eine Sitzung packt, verliert den Faden. Wer jeden Schritt einzeln startet,
verliert den Zusammenhang. Wer für Fleißarbeit das größte Modell nimmt, zahlt ein
Vielfaches ohne Gegenwert. Diese Seite beantwortet die Frage „wie arbeite ich damit gut"
an einer Stelle: wer die Arbeit macht, welches Modell wohin gehört, wie du eine lange
Sitzung führst und was du tust, wenn eine Angabe erfunden aussieht.

Welcher Schritt wann dran ist, steht im [Walkthrough](walkthrough.md); wo das Plugin an
seine Grenzen stößt, in [Grenzen](limits.md).

## Command, Skill, Agent — wer arbeitet hier eigentlich

Drei Arten von Bausteinen, ein Unterschied, der alles erklärt: **wer sie startet.**

**Ein Slash-Command rufst du.** Er tut nichts, solange du ihn nicht tippst. Er hat einen
Namen, feste Flags und einen klar umrissenen Auftrag:

```
/academic-research:search "DevOps Governance Mittelstand" --mode quick
```

**Ein Skill springt von selbst an.** Du beschreibst dein Vorhaben in normaler Sprache;
Claude Code erkennt am Wortlaut, welcher Skill zuständig ist, und lädt ihn nach. Du musst
seinen Namen nicht kennen:

```
Ich will eine Notiz zu einer Quelle anlegen.
```

Das aktiviert den `reading-notes`-Skill, ohne dass er im Satz vorkommt. Welche Formulierung
welchen Skill weckt, steht in der Spalte „Aktiviert bei" der
[Skills-Referenz](../reference/skills.md). Trifft keine Formulierung, nenn den Skill
einfach beim Namen — das funktioniert immer.

**Ein Agent arbeitet im Hintergrund.** Agents startest du nicht; sie werden von Commands
und Skills losgeschickt, wenn eine Teilaufgabe in ein eigenes Kontextfenster gehört. Der
`query-generator` erweitert deine Suchanfrage, der `relevance-scorer` bewertet Treffer in
Gruppen, der `sparring-partner` widerspricht deiner Argumentation. Du siehst ihr Ergebnis,
nicht ihren Verlauf — genau das ist ihr Zweck: Sie halten Zwischenschritte aus deinem
Fenster heraus. Die vollständige Liste steht in der [Agents-Referenz](../reference/agents.md).

Praktische Folge für dich: Bei einem Command bestimmst du die Flags. Bei einem Skill
bestimmt deine Formulierung, ob der richtige greift. Bei einem Agent bestimmst du gar
nichts — und musst es auch nicht.

## Die Modell-Aliase

Claude Code kennt Modell-Aliase statt fester Modell-IDs. Damit bleibt deine Konfiguration
gültig, wenn Anthropic ein neues Modell veröffentlicht:

| Alias | Bedeutung |
|---|---|
| `haiku` | das schnelle, sparsame Haiku-Modell für einfache Aufgaben |
| `sonnet` | das neueste Sonnet-Modell für die tägliche Arbeit |
| `opus` | das neueste Opus-Modell für komplexes Reasoning |
| `fable` | Fable 5 für die schwersten und längsten Aufgaben |
| `best` | Fable 5, wo deine Organisation Zugriff darauf hat, sonst das neueste Opus-Modell |
| `opusplan` | Opus im Plan-Modus, Sonnet in der Ausführung |
| `sonnet[1m]`, `opus[1m]` | dieselben Modelle mit 1-Million-Token-Kontextfenster |
| `default` | Override löschen, zurück zur Voreinstellung |

Belegt in der Claude-Code-Dokumentation unter
[Model configuration](https://code.claude.com/docs/en/model-config).

Zu `fable` sagt dieselbe Seite genauer, wofür das Modell gedacht ist: für Aufgaben, die
größer sind als eine Sitzung. Es hält lange autonome Läufe durch, recherchiert vor dem
Handeln und prüft sein Ergebnis häufiger selbst nach als kleinere Modelle. Das ist ein
Zuschnitt auf Umfang und Dauer — nicht auf Sprachqualität. Für einen einzelnen Absatz ist
es die falsche Wahl, für einen Durchlauf über die ganze Arbeit die richtige.

## Welches Modell für welchen Arbeitsschritt

Die Leitfrage ist nicht „wie schwer klingt das", sondern: **Steht das Ergebnis nach der
Anweisung schon fest?** Dann ist der Schritt mechanisch und ein kleines Modell reicht.
Musst du abwägen, verwerfen oder beurteilen, was nicht in der Anweisung steht, brauchst du
Urteilsvermögen — und dafür ein großes.

| Aufgabentyp | Modell | Warum |
|---|---|---|
| Literatursuche und Query-Erweiterung | `haiku` | Formalisierbare Umformung einer Suchanfrage; die Trefferqualität hängt an den Quellen und am Scoring, nicht am Modell. Genau deshalb steht `haiku` im `query-generator`-Agent. |
| Screening, Scoring, Metadaten-Pflege | `sonnet` | Viele gleichförmige Urteile nach festen Kriterien. Braucht Sorgfalt, aber kein tiefes Reasoning — und läuft oft über hunderte Treffer, wo Geschwindigkeit zählt. |
| Kapitelentwürfe und Argumentation | `opus` oder `opusplan` | Hier entsteht der Text, der in der Arbeit landet: Argumentationsketten, Einordnung widersprüchlicher Befunde, saubere Übergänge. Der teuerste Schritt, aber der einzige, dessen Qualität die Note trifft. |
| Methodik- und Gliederungsberatung | `opus` | Der Nutzen liegt im Widerspruch, nicht in der Zustimmung. Schwächere Modelle bestätigen zu bereitwillig, was du ohnehin vorhattest — deshalb läuft auch der `sparring-partner`-Agent auf Opus. |
| Stilarbeit und Anti-KI-Pass | `opus` | Registerbrüche und Rhythmusfehler zu erkennen verlangt dieselbe Urteilstiefe wie der Entwurf selbst. Kleinere Modelle glätten zwar, ersetzen aber gern die auffällige Formulierung durch die nächstliegende — und genau daran erkennt man KI-Text. |
| Ein Durchlauf über die ganze Arbeit am Stück | `fable` | Die Doku ordnet Fable 5 den schwersten und längsten Aufgaben zu: lange autonome Läufe, Recherche vor dem Handeln, eigene Nachprüfung. Ein Stil- oder Konsistenzlauf über alle Kapitel ist genau so eine Aufgabe. Für einzelne Schritte ist es Verschwendung. |
| Sehr lange Sitzungen mit vielen Quellen | `sonnet[1m]` | Das große Kontextfenster hält Vault-Ausschnitte, Kapitelstand und Kontextdatei gleichzeitig — spart Wiederholungen, kostet aber pro Nachricht mehr. Lies vorher den Abschnitt „Wo es teuer wird". |

### Umschalten

Innerhalb einer Sitzung wechselst du mit dem `/model`-Command:

```
/model opus
```

Dauerhaft pro Projekt setzt du das Feld `model` in der Projektkonfiguration
(`.claude/settings.json`):

```json
{
  "model": "opusplan"
}
```

Das ist die praktikabelste Einstellung für eine Abschlussarbeit: Planung und Struktur
laufen auf Opus, die Ausführung auf Sonnet.

### Was die mitgelieferten Agents nutzen

Subagents tragen ihre Modellwahl im Frontmatter. Das Feld `model:` akzeptiert einen Alias,
eine vollständige Modell-ID oder `inherit`; ohne Angabe gilt `inherit`, der Subagent läuft
also auf demselben Modell wie die Hauptsitzung.

```markdown
---
name: mein-agent
model: haiku
---
```

Ist-Stand dieses Plugins: Fast alle mitgelieferten Agents laufen auf `sonnet`. Zwei
weichen bewusst ab — `query-generator` auf `haiku` (mechanische Query-Umformung) und
`sparring-partner` auf `opus` (soll widersprechen, nicht bestätigen).

Willst du das ändern, ohne die Plugin-Dateien anzufassen: Setz das Modell der
Hauptsitzung und entferne im Bedarfsfall lokal das `model:`-Feld — dann greift `inherit`.

## Sitzungen führen

Eine Abschlussarbeit ist kein Chat. Sie läuft über Wochen, und die entscheidende Frage
lautet nicht „wie behalte ich alles in einer Sitzung", sondern: **Was trägt den
Zusammenhang, wenn die Sitzung endet?**

Die Antwort ist der Vault, nicht der Verlauf. Alles, was einmal im Vault liegt — Paper,
Zitate, Notizen, Ausschlussentscheidungen — ist in jeder künftigen Sitzung abrufbar, ohne
dass du es erneut ins Fenster lädst. Deine Forschungsfrage und deine Rahmendaten stehen in
`academic_context.md` und werden zu Beginn gelesen.

### Wann eine neue Sitzung sinnvoll ist

- **Vor einem Kapitelentwurf.** Ein Entwurf in derselben Sitzung, in der vorher 200
  Suchtreffer diskutiert wurden, schleppt den ganzen Recherche-Verlauf mit. Neue Sitzung,
  Kontextdatei und Vault — mehr braucht das Kapitel nicht.
- **Nach einem Themenwechsel.** Nach dem Sprung von der Methodik zur Diskussion ist der
  alte Verlauf Ballast, kein Kontext.
- **Wenn du dich wiederholst.** Musst du eine Festlegung zum zweiten Mal erklären, ist sie
  aus dem Fenster gefallen. Schreib sie in `academic_context.md` und fang neu an.

Nicht sinnvoll ist ein Schnitt mitten in einem Gedankengang, der auf dem unmittelbar
vorher Gesagten aufbaut — dann zahlst du den Aufbau des Kontexts doppelt.

### Was beim Verdichten verloren geht

Wird das Fenster voll, verdichtet Claude Code den Verlauf: Ältere Nachrichten werden zu
einer Zusammenfassung gerafft. Das hält die Sitzung am Leben, kostet aber Genauigkeit —
Wortlaute, Zwischenüberlegungen und die genaue Reihenfolge früherer Schritte überleben
das nicht zuverlässig.

Deshalb greift vorher der Hook `hooks/pre-compact.mjs`. Er schreibt vor jedem Verdichten
`academic_context.md`, `literature_state.md` und `writing_state.md` weg und legt
zusätzlich einen Vault-Tarball unter `~/.academic-research/snapshots/<projekt>/` ab. Du
musst dafür nichts tun; der Hook läuft fail-open und blockiert nie.

Was daraus folgt: Verlass dich auf das, was im Vault und in den Zustandsdateien steht,
nicht auf das, was „vorhin besprochen" wurde.

## Wo es teuer wird

Vier Stellen kosten spürbar mehr als der Rest:

| Schritt | Warum teuer | Gegenmittel |
|---|---|---|
| Tiefensuche über Browser-Module | Jede Seite wird geladen, gerendert und gelesen; dazu Wartezeit pro Modul | Modus senken, Module gezielt wählen |
| Relevanz-Scoring großer Treffermengen | Ein Modellaufruf pro Papergruppe | kleinere Treffermenge (`--limit`), Modus senken |
| Volltext plus Embedding-Erstlauf | Erstes PDF zieht die Modellgewichte (~470 MB) und indexiert den ganzen Text | einmalig hinnehmen, danach offline |
| Kapitelentwürfe | Langer Output auf einem starken Modell, oft mehrfach überarbeitet | eigene Sitzung pro Kapitel |

**Woran du es merkst, bevor es teuer geworden ist:** Der Verbrauch steigt mit der Menge an
Text, die durchs Fenster läuft — nicht mit der Zahl deiner Nachrichten. Die drei Signale,
die zuverlässig vor einem teuren Schritt stehen:

- Du startest eine Suche ohne `--limit` und ohne Modus-Angabe. Die Voreinstellung ist der
  gründliche Weg, nicht der billige.
- Du hängst ein PDF direkt an, statt es über den Vault zu holen.
- Die Sitzung läuft schon lange und du beginnst einen langen Output. Das ist der Moment
  für einen Schnitt, nicht danach.

### Die Suche eingrenzen

Der häufigste Fehler: Alles auf `--mode deep` fahren, weil „gründlich" gut klingt. Für die
erste Orientierung reicht der schnelle Modus:

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

Große Treffermengen kosten linear: Das Relevanz-Scoring läuft vollständig in der Sitzung,
der `relevance-scorer` bekommt die Treffer in Gruppen von 10 — bei 100 Papern sind das
zehn Läufe. Einen billigeren Zweitweg gibt es nicht mehr; der frühere `--batch`-Modus über
die Anthropic-Message-Batches-API ist mit #632 entfallen, weil er einen zweiten, selbst
bezahlten Modellzugang neben der Claude-Code-Sitzung vorausgesetzt hat. Der Hebel liegt
damit **vor** dem Scoring: Treffermenge klein halten, statt hinterher billiger zu bewerten.

### Wann sich ein eigener Kontext lohnt

Ein eigener Kontext heißt: eine frische Sitzung oder ein Subagent, dessen Fenster nur das
enthält, was der Schritt wirklich braucht. Das lohnt sich, wenn der Schritt viele
gleichförmige Urteile braucht. Screening und Verzerrungsbewertung fächert das Plugin
selbst auf Subagents auf; jeder bekommt nur seine Paper zu sehen:

```
Ich muss viele Treffer screenen — bitte Screening parallelisieren.
```

## Zwischenstand sichern

Der teuerste Verlust ist nicht ein zu großes Fenster, sondern verlorene Arbeit. Vorhandene
Snapshots listest und stellst du so wieder her:

```
/academic-research:history --snapshots
/academic-research:history --restore 20260507-1430
```

Eine ganze frühere Recherche-Sitzung machst du mit
`/academic-research:history --restore-session <id>` wieder zum Arbeitsstand.

Der eigentliche Spar-Mechanismus bleibt der Vault. Statt ein PDF erneut anzuhängen, fragst
du danach — `vault.search` antwortet mit Snippet und Seitenzahl, und ein Treffer-Snippet
kostet einen Bruchteil eines PDF-Uploads:

```
Welche Quellen im Vault behandeln IT-Governance?
```

## Wenn Claude etwas erfindet

Erfundene Angaben sind kein Ausnahmefall, den du wegdiskutieren kannst — sie sind der
Grund, warum dieses Plugin einen Vault hat. Ein Zitat, das in keiner Quelle steht, fällt
in der Prüfung auf dich zurück, nicht auf das Werkzeug. Der Ablauf dafür ist festgelegt:

**1. Der Guard greift automatisch.** Der Hook `hooks/verbatim-guard.mjs` prüft jeden
Schreibvorgang in dein Kapitelverzeichnis. Findet er ein Zitat, das nicht im Vault liegt,
blockiert er den Schreibvorgang und sagt, welches.

**2. Du prüfst gezielt nach.** Steht ein Zitat bereits im Text und du bist unsicher:

```
Bitte Zitate gegen Vault abgleichen.
```

Das ruft `vault.verify_verbatim` auf, das den Wortlaut zeichengenau gegen den
gespeicherten Volltext hält. Ergebnis ist eine Aussage über die Herkunft, keine Meinung.

**3. Was der Guard nicht leistet.** Er belegt, dass ein Zitat aus deinem Vault stammt —
nicht, dass Wortlaut, Seitenzahl, Autorenname und Jahr korrekt aus dem Original übernommen
wurden. Bei allem, was nicht aus dem Vault kommt — Jahreszahlen, Zuschreibungen,
Zusammenfassungen fremder Befunde — greift kein Mechanismus. Dort gilt: gegen die Quelle
prüfen, bevor es in die Arbeit geht. Die vollständige Aufstellung steht in
[Grenzen](limits.md).

## Was sich bewährt hat

- **Kontext zuerst, immer.** Ohne gefüllte `academic_context.md` raten alle folgenden
  Schritte. Fünf Minuten am Anfang sparen jede Nachfrage danach.
- **Erst belegen, dann schreiben.** Zieh die Zitate in den Vault, bevor du ein Kapitel
  anfängst. Umgekehrt schreibst du einen Entwurf, den der Guard anschließend zerlegt.
- **Pro Kapitel eine eigene Sitzung.** Der Vault trägt den Zusammenhang, nicht der Verlauf.
- **Notizen anlegen, während du liest.** Der `reading-notes`-Skill kostet pro Quelle eine
  Minute; die Rekonstruktion vier Wochen später kostet eine Stunde.
- **Ausschlüsse begründen und ablegen.** Wer eine Quelle verwirft, notiert warum — sonst
  taucht sie in der nächsten Suchrunde wieder auf und wird erneut geprüft.
- **Modell zum Schritt wählen.** Recherche klein, Kapitelentwurf groß, danach zurück.
- **Vor der Abgabe einfrieren.** Material-Passport und Repro-Lock machen den Stand
  nachvollziehbar; danach ändert niemand mehr versehentlich etwas.

## Typische Fehler

- **Das Thema zu spät schärfen.** Eine unscharfe Forschungsfrage produziert eine unscharfe
  Trefferliste, und die trägst du durch die ganze Arbeit. Lieber einen Durchgang mehr:

  ```
  Hilf mir, die Forschungsfrage zu präzisieren.
  ```

- **Jede Suche auf voller Tiefe.** Der teuerste Modus ist selten der nützlichste.
- **Zitate ungeprüft übernehmen.** Der Guard beweist Vault-Herkunft, nicht Korrektheit.
- **Kapitelentwürfe unverändert einreichen.** Ein Entwurf ist Rohmaterial. Die
  Argumentation musst du verantworten — inhaltlich und prüfungsrechtlich.
- **Den Vault als Ablage behandeln.** Er ist nur so gut wie das, was du hineinschreibst;
  ein Vault ohne Notizen und Zitate ist eine PDF-Halde.
- **„Fass dich kurz" als Dauerauftrag.** Das spart Output-Tokens und kostet Substanz.
  Begrenz lieber den Input.
- **Alles in eine einzige Riesensitzung packen**, um „den Kontext nicht zu verlieren".
  Der Kontext liegt in `academic_context.md` und im Vault, nicht im Verlauf.

Läuft etwas technisch schief, steht die Diagnose in
[Troubleshooting](troubleshooting.md) — hier stehen nur die Fehler, die kein Bug sind.
Wofür das Plugin grundsätzlich nicht taugt, steht mit Beleg in [Grenzen](limits.md); der
Einstieg in [Erste Schritte](getting-started.md).
