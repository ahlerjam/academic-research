# Quickstart-Protokoll — realer Durchlauf

[← zurück zur README](../README.md)

Protokoll des Durchlaufs, mit dem der [Quickstart der README](../README.md#quickstart)
abgenommen wurde: frische Installation → Setup → erstes Paper im Vault → erstes
verifiziertes Zitat. Die Ausgaben unten sind mitgeschnitten, nicht nachgestellt.

## Umgebung

| | |
|---|---|
| **Datum** | 2026-07-27 |
| **Plattform** | macOS 26.5.2 (arm64) |
| **Python** | 3.14.4 (Homebrew) |
| **Commit** | `df22fd7` |
| **HOME** | frisches Sandbox-Verzeichnis — kein bestehendes `~/.academic-research` |
| **PATH** | `/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin` (bewusst **ohne** `uv` und `pipx`) |

**Was „frische Umgebung" hier heißt:** eigenes `HOME`, eigenes leeres Projektverzeichnis,
kein vorhandenes venv, kein Modell-Cache, keine `settings.local.json`. `uv` und `pipx`
wurden absichtlich aus dem `PATH` genommen, damit der Lauf keine global installierten
Tools der Maschine anfasst — das ist zugleich der interessantere Fall, weil er die
Degradations-Pfade des Setups zeigt (siehe Schritt 1).

**Was nicht ausgeführt wurde, und warum:**

- Die beiden `/plugin`-Befehle sind Claude-Code-interne Marketplace-Kommandos; sie
  installieren das Plugin, das hier bereits als Arbeitskopie vorlag. Getestet wurde
  stattdessen alles, was danach kommt.
- Die Slash-Commands rufen ihrerseits Skripte und MCP-Tools auf. Protokolliert ist die
  darunterliegende Ebene (`scripts/setup.sh`, `scripts/search.py`, die `vault.*`-Tools,
  `hooks/verbatim-guard.mjs`) — also der Code, der die Arbeit tatsächlich macht.
- Der Verbatim-Extraktor (`quote-extractor`, Claude-Citations-API) wurde **nicht** live
  aufgerufen: dafür braucht es einen `ANTHROPIC_API_KEY`, der hier nicht vorlag. Schritt 4
  legt das Zitat deshalb direkt über `vault.add_quote(..., extraction_method=
  "citations-api")` an und weist anschließend nach, dass der Halluzinationsschutz genau
  dieses Zitat akzeptiert und ein erfundenes ablehnt.

## 1. Setup

```
/plugin marketplace add ahlerjam/academic-research
/plugin install academic-research@academic-research
```

```bash
mkdir ~/meine-arbeit && cd ~/meine-arbeit
```

```
/academic-research:setup
```

Ausgeführt wurde `bash scripts/setup.sh` aus dem leeren Projektverzeichnis:

```console
✅ Python environment: ready
📦  browser-use CLI nicht gefunden — versuche Auto-Install…
⚠️  Weder 'uv' noch 'pipx' verfügbar — browser-use konnte nicht automatisch installiert werden.
   Install-Optionen (manuell):
     • brew install pipx && pipx install browser-use
     • curl -LsSf https://astral.sh/uv/install.sh | sh && uv tool install browser-use
⚠️  browser-use CLI nicht installiert — Browser-Suchmodule (Scholar, EBSCO, …) werden übersprungen.
⚠️  browser-use Claude-Skill unter ~/.claude/skills/browser-use/ fehlt.
   Der Skill wird separat von Anthropic bereitgestellt (nicht Teil dieses Plugins).
✅ Permissions updated (8 new rules added)
ℹ️  SciHub Opt-in: deaktiviert (Default) (scihub_optin: false in .../library-profiles/active.yaml)
Setup complete: .../.academic-research
```

Exit-Code 0. Das Setup meldet die fehlende `browser-use`-CLI klar und läuft weiter — die
Degradation ist gewollt und dokumentiert.

Angelegt wurde:

```console
$ ls ~/.academic-research
annotations.json  citations.bib  fulltext_index.json  library-profiles  pdfs  sessions  venv
```

**Befund 1 (eingearbeitet):** Das Projektverzeichnis blieb leer. Ursache ist kein Fehler,
sondern Absicht: `scripts/project_bootstrap.py` fragt *„Hier einen Facharbeit-Arbeitsordner
initialisieren?"* und wählt ohne Terminal den sicheren Default „nein". Der Lauf über eine
Pipe hatte kein TTY. Mit Terminal und Antwort `y`:

```console
$ python project_bootstrap.py     # interaktiv
Hier einen Facharbeit-Arbeitsordner initialisieren? [y/N] y
✅ Facharbeit-Arbeitsordner initialisiert: .../meine-arbeit
Git aktivieren? [y/N] n

$ ls -A
.gitignore  CLAUDE.md  academic_context.md  kapitel  literatur  pdfs
```

Damit ist die in [installation.md](guide/installation.md) beschriebene Ordnerstruktur
belegt. Der Hinweis auf die interaktive Frage steht jetzt dort und im
[Troubleshooting](guide/troubleshooting.md).

## 2. Erste Suche

```
/academic-research:search "DevOps Governance Mittelstand" --mode standard
```

Ausgeführt als `python search.py --query "DevOps Governance Mittelstand" --modules
crossref,openalex,arxiv --limit 5`:

```console
INFO:httpx:HTTP Request: GET https://api.crossref.org/works?query=DevOps+Governance+Mittelstand&rows=5 "HTTP/1.1 200 OK"
INFO:httpx:HTTP Request: GET https://export.arxiv.org/api/query?search_query=all%3ADevOps+Governance+Mittelstand&... "HTTP/1.1 200 OK"
INFO:httpx:HTTP Request: GET https://api.openalex.org/works?search=DevOps+Governance+Mittelstand&per-page=5 "HTTP/1.1 200 OK"
INFO:__main__:Found 15 papers (0 modules failed)
```

Drei API-Module, kein Fehlschlag, 15 deduplizierte Treffer. Die Browser-Module liefen
nicht mit — erwartbar, weil `browser-use` in dieser Umgebung fehlt.

## 3. Erstes Paper im Vault

Erster Treffer aus dem Suchlauf, in den Vault übernommen:

```console
$ erster Treffer:
   title   : Corporate Governance und Mittelstand
   year    : 2015
   doi     : 10.1007/978-3-658-09049-4_12

$ vault.add_paper('devops-gov-01', csl_json, doi=...)
-> ok

$ vault.stats()
-> {"paper_count": 2, "quote_count": 1, "cached_files": 0, "token_savings_estimate": 0}

$ vault.search('Corporate', k=3)
   - devops-gov-01  (score -0.0000)
```

Zusätzlich ein Paper mit angehängtem PDF, um Volltext- und Embedding-Ingest auszulösen:

```console
$ vault.add_paper('vaswani2017', csl_json, pdf_path='sample_book.pdf')
-> ok

$ vault.get_paper('vaswani2017')
-> title       : Attention Is All You Need
-> type        : article-journal
-> doi         : 10.48550/arXiv.1706.03762
-> pdf_path    : .../sample_book.pdf
```

Der erste `add_paper()`-Aufruf mit PDF lädt das Embedding-Modell
(`intfloat/multilingual-e5-small`, ~470 MB) nach `~/.academic-research/models` herunter.
Das dauert einmalig spürbar lange und braucht Netz — danach läuft alles lokal. Dieser
Hinweis steht jetzt im Quickstart, weil er sonst wie ein Hänger wirkt.

## 4. Erstes verifiziertes Zitat

```console
$ vault.add_quote('vaswani2017', verbatim, 'citations-api',
                  api_response_id='msg_01demo', printed_page=1)
-> quote_id: 7dfe57e3-27c9-4a03-adc2-e9f95972d1c5

$ vault.get_quote(quote_id)
-> paper_id         : vaswani2017
-> printed_page     : 1
-> extraction_method: citations-api
-> verbatim         : The dominant sequence transduction models are based on complex recurre...

$ vault.search_quote_text('dominant sequence transduction')
-> Treffer: 1

$ vault.find_quotes('vaswani2017')
-> Zitate am Paper: 1
```

Das Zitat liegt mit Seitenzahl und Extraktionsmethode im Vault — das ist der Zustand, den
`chapter-writer` und der Guard voraussetzen.

## 5. Halluzinationsschutz (verbatim-guard)

Der eigentliche Test: hält der Guard, was die README verspricht?

**5a — erfundenes Zitat, muss blockiert werden:**

```console
$ node hooks/verbatim-guard.mjs   # Write auf kapitel/01-einleitung.md
[Vault-Guard] BLOCKIERT: Zitat nicht im Vault verifiziert.
Zitat: "Transformer sind das Ende der Rekurrenz"
Bitte Zitat über vault.add_quote() oder den quote-extractor einpflegen.
-> exit 2 (blockiert)
```

**5b — das in Schritt 4 hinterlegte Zitat, muss durchgelassen werden:**

```console
$ node hooks/verbatim-guard.mjs   # Write mit dem verifizierten Verbatim
-> exit 0 (kein Einspruch)
```

Beide Richtungen greifen. Der Guard ist keine Attrappe.

## Befunde aus dem Durchlauf

Alles hier Aufgeführte ist in dieser Dokumentation eingearbeitet.

| # | Befund | Konsequenz |
|---|--------|------------|
| 1 | Ohne TTY legt das Setup den Arbeitsordner nicht an (sicherer Default, kein Bug) | Hinweis in [installation.md](guide/installation.md) und [troubleshooting.md](guide/troubleshooting.md) |
| 2 | Der erste `add_paper()`-Lauf lädt ~470 MB Modellgewichte — sieht wie ein Hänger aus | Erwartungsmanagement im README-Quickstart |
| 3 | Die alte README schrieb den `SessionStart`-Hook `onboard-project-uni-prompt.sh` zu; `hooks/hooks.json` verdrahtet dort ein Inline-Bash-Kommando | Korrigiert in [hooks.md](reference/hooks.md), Guard in `tests/test_issue_402_readme_relaunch.py` |
| 4 | Die alte README stellte pyzotero als selbsttätig nachinstallierte Abhängigkeit dar; der Code fordert nur zur Installation auf | Korrigiert in [installation.md](guide/installation.md), Guard im selben Test |
| 5 | Der alte Tests-Badge nannte „963 passing / 1111 collected", gemessen wurden 1809/148 | Zahlen-Badge entfernt, siehe [development.md](development.md) |
| 6 | Die alte README verlinkte die längst entfernte Datei MIGRATION-v5-to-v6.md unter `docs/` (#346) | Link entfernt, Guard prüft jetzt alle relativen Links |

## Die Demo im README

Das Terminal-Standbild oben in der README ist kein nachgestellter Screenshot, sondern
eine Wiedergabe der oben protokollierten Ausgaben.

- **Quelle:** [`docs/assets/quickstart.cast`](assets/quickstart.cast) — asciicast v2,
  abspielbar mit `asciinema play docs/assets/quickstart.cast`.
- **Inhalt:** die Befehle und Ausgaben der Schritte 1–5 dieses Protokolls, im Wortlaut
  übernommen. Lange Ausgabeblöcke sind auf die tragenden Zeilen gekürzt; kein Wort ist
  hinzuerfunden. Ein Test (`tests/test_issue_451_readme_showcase.py`) prüft, dass jede im
  Cast getippte Befehlszeile in diesem Protokoll steht.
- **Frame-Zeiten:** gleichmäßig gesetzt, damit der Cast lesbar abspielt. Sie sind
  **keine** Messwerte des Laufs — die realen Wartezeiten dominiert der Modell-Download.
- **Bild:** `uv run python scripts/dev/render_quickstart_svg.py` rendert daraus
  deterministisch [`docs/assets/quickstart.svg`](assets/quickstart.svg). Das Bild ist
  bewusst statisch: GitHub reicht eingebettete SVG durch einen Sanitizer, dessen Umgang
  mit SMIL-Animationen nicht zugesichert ist. Ein Test rendert neu und vergleicht
  byteweise, damit Bild und Mitschnitt nicht auseinanderlaufen.

## Wiederholen

Der Durchlauf ist reproduzierbar: frisches `HOME` setzen, `scripts/setup.sh` starten,
dann die `vault.*`-Aufrufe aus Schritt 3 und 4 sowie den Guard aus Schritt 5. Die
Prüfungen, die aus diesem Protokoll folgen, laufen automatisiert in
`tests/test_issue_402_readme_relaunch.py` mit.
