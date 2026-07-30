# Modellwahl — welches Modell für welchen Arbeitsschritt

[← Doku-Übersicht](../README.md)

Das Plugin läuft mit jedem Claude-Code-Modell. Welches du wählst, entscheidet aber
spürbar über Qualität, Wartezeit und Kosten: Ein Kapitelentwurf mit einem kleinen Modell
liest sich flach, eine Literaturliste mit einem großen Modell ist Geldverbrennung. Diese
Seite ordnet die Aufgabentypen dieses Plugins den Modellen zu und zeigt, wie du
umschaltest.

Der Zusammenhang mit dem Verbrauch steht in [Token-Budget](token-budget.md); welcher
Schritt wann kommt, im [Walkthrough](walkthrough.md).

## Die Aliase

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

## Empfehlung je Aufgabentyp

| Aufgabentyp | Modell | Warum |
|---|---|---|
| Literatursuche und Query-Erweiterung | `haiku` | Formalisierbare Umformung einer Suchanfrage; die Trefferqualität hängt an den Quellen und am Scoring, nicht am Modell. Genau deshalb steht `haiku` im `query-generator`-Agent. |
| Screening, Scoring, Metadaten-Pflege | `sonnet` | Viele gleichförmige Urteile nach festen Kriterien. Braucht Sorgfalt, aber kein tiefes Reasoning — und läuft oft über hunderte Treffer, wo Geschwindigkeit zählt. |
| Kapitelentwürfe und Argumentation | `opus` oder `opusplan` | Hier entsteht der Text, der in der Arbeit landet: Argumentationsketten, Einordnung widersprüchlicher Befunde, saubere Übergänge. Der teuerste Schritt, aber der einzige, dessen Qualität die Note trifft. |
| Methodik- und Gliederungsberatung | `opus` | Der Nutzen liegt im Widerspruch, nicht in der Zustimmung. Schwächere Modelle bestätigen zu bereitwillig, was du ohnehin vorhattest — deshalb läuft auch der `sparring-partner`-Agent auf Opus. |
| Stilarbeit und Anti-KI-Pass | `opus` | Registerbrüche und Rhythmusfehler zu erkennen verlangt dieselbe Urteilstiefe wie der Entwurf selbst. Kleinere Modelle glätten zwar, ersetzen aber gern die auffällige Formulierung durch die nächstliegende — und genau daran erkennt man KI-Text. |
| Ein Durchlauf über die ganze Arbeit am Stück | `fable` | Die Doku ordnet Fable 5 den schwersten und längsten Aufgaben zu: lange autonome Läufe, Recherche vor dem Handeln, eigene Nachprüfung. Ein Stil- oder Konsistenzlauf über alle Kapitel ist genau so eine Aufgabe. Für einzelne Schritte ist es Verschwendung. |
| Sehr lange Sitzungen mit vielen Quellen | `sonnet[1m]` | Das große Kontextfenster hält Vault-Ausschnitte, Kapitelstand und Kontextdatei gleichzeitig — spart Wiederholungen, kostet aber pro Nachricht mehr. Vorher [Token-Budget](token-budget.md) lesen. |

## Umschalten

Innerhalb einer Session wechselst du mit dem `/model`-Command:

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

## Was die mitgelieferten Agents nutzen

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
`sparring-partner` auf `opus` (soll widersprechen, nicht bestätigen). Die vollständige
Liste steht in der [Agents-Referenz](../reference/agents.md).

Willst du das ändern, ohne die Plugin-Dateien anzufassen: Setz das Modell der
Hauptsitzung und entferne im Bedarfsfall lokal das `model:`-Feld — dann greift `inherit`.

## Faustregeln

- **Nicht dauerhaft auf dem größten Modell arbeiten.** Recherche, Import und Export sind
  Fleißarbeit; dort ist Opus reine Verschwendung.
- **Vor dem Kapitelentwurf hochschalten, danach zurück.** Ein `/model`-Wechsel kostet
  nichts und wirkt sofort.
- **Ein Modellwechsel repariert keinen fehlenden Kontext.** Steht die Forschungsfrage
  nicht in `academic_context.md` und liegen keine Zitate im Vault, liefert auch Opus
  Allgemeinplätze — siehe [Grenzen und bewährtes Vorgehen](best-practices.md).
