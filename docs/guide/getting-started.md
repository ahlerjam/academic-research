# Erste Schritte — von der Installation zum ersten Beleg

[← Doku-Übersicht](../README.md)

Diese Seite bringt dich in einem Zug von „nichts installiert" bis zu einem wörtlichen
Zitat, das mit Quelle und Seitenzahl in deinem Vault liegt. Alles, was du dafür tippen
musst, steht hier — du musst keine andere Seite öffnen, um weiterzukommen. Rechne mit
rund 20 Minuten, davon das meiste Wartezeit beim einmaligen Modell-Download.

Am Ende jedes Schritts steht, woran du erkennst, dass er geklappt hat. Bricht etwas ab,
hilft [Troubleshooting](troubleshooting.md); wenn du wissen willst, wofür sich das Plugin
**nicht** eignet, lies vorher [Grenzen](limits.md) — das spart dir womöglich die ganze
Installation.

## Schritt 0 — was da sein muss

Vier Dinge sind Pflicht, alles andere erweitert nur:

| Pflicht | Prüfbefehl im Terminal | Erwartete Ausgabe |
|---|---|---|
| Claude Code | `claude --version` | eine Versionsnummer |
| Python 3.11+ | `python3 --version` | `Python 3.11` oder höher |
| Node.js | `node --version` | eine Versionsnummer (die Hooks sind `.mjs`) |
| Git | `git --version` | eine Versionsnummer |

Fehlt eines davon, installier es zuerst — ohne Node greift der Zitat-Guard nicht, ohne
Python startet der Vault nicht. Optional sind `uv` oder `pipx` (für die Browser-Module)
und `ocrmypdf` (für gescannte PDFs). Was genau daran hängt und wie du Zugangsdaten deiner
Hochschule hinterlegst, steht in der [Installationsanleitung](installation.md); für diese
Seite brauchst du davon nichts.

## Schritt 1 — Plugin installieren

In Claude Code, egal in welchem Ordner:

```
/plugin marketplace add ahlerjam/academic-research
/plugin install academic-research@academic-research
```

**Ergebnis:** Das Plugin liegt unter `~/.claude/plugins/cache/academic-research/` und ist
ab jetzt in *allen* Claude-Code-Sessions verfügbar. Tippst du `/academic-research:` in die
Eingabezeile, schlägt Claude Code die Commands vor.

## Schritt 2 — Arbeitsordner anlegen

Im Terminal, außerhalb von Claude Code:

```bash
mkdir ~/meine-arbeit && cd ~/meine-arbeit
claude
```

**Ergebnis:** Claude Code läuft in einem leeren Ordner. Das ist wichtig: Das Setup fragt
nur in einem leeren Ordner, ob es die Projektstruktur anlegen soll.

## Schritt 3 — Setup ausführen

```
/academic-research:setup
```

Beantworte *„Hier einen Facharbeit-Arbeitsordner initialisieren?"* mit `y`. Die Frage nach
dem SciHub-Tier kannst du mit `n` beantworten — der Tier ist rechtlich umstritten und für
den Einstieg unnötig.

**Ergebnis:** Im Ordner liegen jetzt `academic_context.md`, `CLAUDE.md`, `kapitel/`,
`literatur/` und `pdfs/`. Das Setup ist idempotent: Ein zweiter Aufruf zerstört nichts.

Melden `uv` und `pipx` als fehlend, überspringt das Setup die `browser-use`-CLI und sagt
es dir. Alles außer den Browser-Suchmodulen läuft trotzdem.

## Schritt 4 — Kontext setzen

Jetzt sagst du in normalem Deutsch, woran du arbeitest:

```
Richte den Kontext für meine Arbeit ein: Ich schreibe eine Bachelorarbeit über
DevOps-Governance im deutschen Mittelstand. Wirtschaftsinformatik, 60 Seiten.
```

Der `academic-context`-Skill springt selbst an — du rufst nichts auf. Er fragt nach, was
noch fehlt: Forschungsfrage, Arbeitstyp, Hochschule, Methodik.

**Ergebnis:** `academic_context.md` ist gefüllt. Ab hier lesen alle anderen Skills dieses
Profil, ohne dass du es wiederholen musst.

## Schritt 5 — erste Suche

```
/academic-research:search "DevOps Governance Mittelstand" --mode standard
```

**Ergebnis:** Der Lauf meldet am Ende die Trefferzahl. So sieht ein geglückter Lauf aus:

```console
INFO:__main__:Found 15 papers (0 modules failed, 0 modules skipped)
```

Beim ersten Paper mit PDF lädt das Plugin einmalig die Gewichte des Embedding-Modells
(~470 MB) nach `~/.academic-research/models`. Das sieht aus wie ein Hänger, ist aber
Fortschritt. Danach laufen Volltext- und Vektorsuche offline.

Ist dir das für den ersten Versuch zu viel, nimm `--mode quick` — weniger Module, weniger
Wartezeit, weniger Tokens. Welche Modi es gibt und was sie kosten, steht in
[Claude Code bedienen](working-with-claude-code.md).

## Schritt 6 — erstes verifiziertes Zitat

```
Zitate finden: Zieh mir aus dem wichtigsten Treffer drei wörtliche Belege zur
Forschungsfrage, jeweils mit Seitenzahl.
```

Der `quote-extractor`-Agent schreibt jedes Zitat mit Seitenzahl und Quelle in den Vault.

**Ergebnis:** Die Zitate liegen im Vault und lassen sich von dort abrufen. Ab jetzt darf
`chapter-writer` daraus zitieren — und der `verbatim-guard`-Hook blockt jeden
Kapitel-Write mit einem Zitat, das dort **nicht** steht. Das ist der eigentliche
Unterschied zum Chat-Fenster.

> **Trotzdem gegenprüfen.** Der Guard beweist, dass ein Zitat aus deinem Vault stammt —
> nicht, dass es korrekt aus dem Original übernommen wurde. Prüf Seitenzahl, Autorennamen
> und Jahr im Originaltext nach, bevor sie in die Arbeit wandern.

## Was jetzt

- **Die ganze Arbeit durchziehen:** [Walkthrough](walkthrough.md) — jeder Arbeitsschritt
  von der Themenfindung bis zur Abgabe, mit Beispielformulierung und erwartetem Ergebnis.
- **Gut damit arbeiten:** [Claude Code bedienen](working-with-claude-code.md) — wer welche
  Arbeit macht, welches Modell wohin gehört, wie du lange Sitzungen führst und was du
  tust, wenn eine Angabe erfunden aussieht.
- **Grenzen kennen:** [Grenzen](limits.md) — was das Plugin nicht kann, nicht darf und
  nicht prüft.

Wenn etwas hakt: [Troubleshooting](troubleshooting.md). Unbekannte Begriffe stehen im
[Glossar](../reference/glossary.md).
