# Installation und Migration

[← Doku-Übersicht](../README.md)

Der Kurzweg steht in der README (Quickstart). Diese Seite erklärt die Voraussetzungen im
Detail, was das Setup genau tut, und wie eine Migration von v5 abläuft.

## Voraussetzungen

| Komponente | Warum | Installation |
|-----------|-------|--------------|
| **Claude Code** | CLI zum Ausführen | [Installations-Anleitung](https://code.claude.com/docs/en/quickstart) |
| **Python 3.11+** | Vault-MCP-Server, Suchskripte | `brew install python@3.11` (macOS) |
| **Node.js** | Alle Hooks sind `.mjs` und werden in `hooks/hooks.json` als `node …` gestartet — ohne Node greifen `verbatim-guard`, `claim-drift-guard` und `context-fidelity-guard` nicht | `brew install node` (macOS); CI testet gegen Node 20 |
| **Git** | Plugin-Marketplace-Install | auf macOS/Linux meist vorinstalliert |
| **`uv` oder `pipx`** *(optional)* | Automatische `browser-use`-Installation | `brew install pipx` oder `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

**Modell-Download.** Das Plugin nutzt drei lokale Modelle: das Embedding-Modell
`BAAI/bge-m3` (~2,3 GB, seit #732; zuvor `intfloat/multilingual-e5-small`, ~470 MB) für die
Vektor-Suche, einen Reranker für die
Trefferreihenfolge und einen NLI-Vorfilter für den Zitatscan — alle drei landen nach
`~/.academic-research/models`. Schritt 9 des Setups (`model_prefetch.py`) fragt genau
einmal, ob alle drei jetzt vollständig geladen werden sollen, und nennt dabei die
Gesamtgröße. Bei Ablehnung
oder nicht-interaktivem stdin (z. B. CI) bleibt der bisherige Lazy-Load-Pfad unverändert:
jedes Modell lädt einzeln beim ersten Gebrauch nach, mit einer Meldung der jeweiligen
Downloadgröße direkt davor. Ohne die Modelle bleibt der Vektor-Index leer bzw. Reranking
und Zitatscan laufen degradiert — die Volltextsuche (FTS5) funktioniert in jedem Fall.

**Reranker seit #807 per Default aus.** Der lokale Reranker (`bge-reranker-v2-m3`,
Zeile unten) wird bei einer Suche ohne gesetzten Schalter nicht mehr geladen — die
#804-Nullmessung fand auf 60 Queries keinen von Null trennbaren Qualitätsbeitrag bei
3058 ms statt 17 ms Suchlatenz je Suche (Beschluss #806). Wird er über
`ACADEMIC_RESEARCH_RERANKER_ENABLED`/`reranker_enabled` in
`config/parallel_agents.json` manuell eingeschaltet, gelten Platzbedarf und
Peak-RSS aus der Tabelle unten unverändert.

**Nach einem Abbruch** setzt der nächste Lauf fort, statt neu zu beginnen: fertige
Modelle werden übersprungen, und innerhalb eines angefangenen Modells bleiben die bereits
vollständigen Dateien im Cache. Nur die eine Datei, die im Moment des Abbruchs übertragen
wurde, beginnt von vorn — `huggingface_hub` schreibt sie unter einem prozesseigenen
`.incomplete`-Namen und greift diesen später nicht wieder auf. Im ungünstigsten Fall,
Abbruch mitten in den Reranker-Gewichten, sind das erneut ~2,3 GB. Wird der Prozess hart
beendet (SIGKILL, Stromausfall), bleibt dieser angefangene Blob zudem unter
`~/.academic-research/models/models--*/blobs/*.incomplete` liegen; er wird nie
wiederverwendet und kann gelöscht werden. Geprüft an einem echten, hart abgebrochenen und
danach wiederholten Setup-Lauf (`tests/test_issue_718_model_prefetch.py::TestResume`).

### Hardware-Anforderungen

**Untergrenze:** 8 GB RAM, 7 GB freier Plattenplatz (~5,7 GB Modellgewichte plus Puffer für
den Abbruch-/Resume-Fall oben). **Keine GPU nötig** — alle drei
Modelle laufen auch auf reiner CPU, dabei aber spürbar langsamer als mit
Hardware-Beschleunigung (Apple-GPU/CUDA).

| Modell | Platte | Peak-RSS | CPU | Apple GPU |
|---|---|---|---|---|
| `BAAI/bge-m3` (Embedding) | 2,3 GB | 2,2 GB | 169 ms/Chunk | 63 ms |
| `bge-reranker-v2-m3` (Reranker) | 2,3 GB | 2,1 GB | 48 ms/Paar | 26 ms |
| `bge-m3-zeroshot-v2.0` (NLI-Zitatscan) | 1,1 GB | 1,5 GB | 570 ms/Paar | 38 ms |

Platte gemessen über den Content-Length-Header des jeweiligen Gewichts-Blobs je HF-Repo
(`model.safetensors` bei Reranker/NLI, `pytorch_model.bin` bei `bge-m3` — dessen Repo liefert
kein `safetensors`, siehe HF-Dateiliste; gemessen 2026-08-08 für die Embedding-Zeile,
2026-08-07 für die anderen beiden) — dieselbe Quelle, aus der der Setup-Prompt seine
Gesamtgröße bildet. Peak-RSS/Apple-GPU der Embedding-Zeile ebenfalls gemessen 2026-08-08 auf
Apple M4 Pro (12 Kerne, 12 CPU-Threads, MPS verfügbar): 3 Warmläufe verworfen, 30 Läufe über
`SentenceTransformer.encode` mit einem repräsentativen ~190-Wort-Chunk, Median, `ru_maxrss`
über beide Geräte hinweg (CPU zuerst, dann MPS, also der Prozess-Peak über beide Läufe). Die
CPU-Spalte der Embedding-Zeile übernimmt stattdessen den bereits gemessenen Wert aus
[`docs/evals/2026-08-08-embedding-candidates-731.md`](../evals/2026-08-08-embedding-candidates-731.md)
(Indexierung p50, Einzeltext-Encode über das Chunk-Goldset) statt einer zweiten, redundanten
Messung derselben Größe. Reranker/NLI gemessen am 2026-08-06 bzw. 2026-08-07 auf derselben
Maschinenklasse: 30 Läufe nach 3 Warmläufen über die jeweilige `predict`-Methode, Median,
Eingabe 210 Token (Quellenabsatz plus Behauptungssatz), Peak-RSS als `ru_maxrss` des
Messprozesses. Die CPU-Spalte ist überall der Produktionspfad — im Code steht kein
`.to("mps")`; die Apple-GPU-Spalte zeigt dieselbe Vorhersage nach manuellem Verschieben auf
`mps`, also die erreichbare Untergrenze, nicht das Standardverhalten. Die Millisekunden
hängen an der Eingabelänge und sind zwischen den Zeilen nur grob vergleichbar (Embedding je
Chunk, Reranker und NLI je Paar). `evals/524-nli-prefilter/README.md` zeigt weiterhin die
Werte des alten NLI-Modells (`mDeBERTa-v3-XNLI`, seit #720 kein Produktivmodell mehr).

Zusammen ~5,7 GB Plattenplatz für alle drei Modellgewichte. Ein anderes Embedding-Modell
lässt sich über `VAULT_EMBEDDING_MODEL` setzen, siehe [Vault-Referenz](../reference/vault.md).

`uv`/`pipx` sind optional: fehlen sie, überspringt das Setup die `browser-use`-CLI und
sagt das auch. Die 7 API-Suchmodule und der gesamte Vault-/Schreib-Workflow laufen
trotzdem — nur die 7 Browser-Module (`--mode deep`) stehen dann nicht bereit.

## Zugangsdaten

Drei getrennte Wege legen Zugangsdaten ab. Alle drei sind optional — ohne sie laufen
Vault, Schreib-Workflow und Open-Access-Quellen unverändert, nur die jeweils daran
hängenden Quellen fehlen bzw. Rate-Limits greifen strenger.

1. **Umgebungsvariablen pro Suchquelle** — `SS_API_KEY` (Semantic Scholar, verhindert
   429-Fehler bei viel Suchvolumen). Selbst in der Shell setzen (z. B.
   `export SS_API_KEY=…` in `~/.zshrc`). Zuständig: die 7 API-Suchmodule.
   Einen eigenen Modellzugang braucht keine Plugin-Funktion: alles, was ein
   Modell aufruft, läuft in deiner Claude-Code-Sitzung (#632).
2. **Per-Uni-Profil** — `~/.academic-research/library-profiles/active.yaml`, Feld
   `credentials_keys`. Der `auth-helper`-Subagent liest die dort genannten Feldnamen zur
   Laufzeit direkt aus derselben YAML-Datei aus. **Doku-Drift, noch nicht bereinigt:**
   `config/library-profiles/_schema.json` beschreibt `credentials_keys` als „Schlüssel
   für OS-Keychain“, an anderer Stelle kursiert „Namen von Umgebungsvariablen“ — beides
   trifft den tatsächlichen Code nicht. Zuständig: der `book-fetcher`-Workflow
   (Shibboleth/EZproxy/HAN der mitgelieferten Profile), siehe
   [Per-Uni-Profile](../reference/uni-profiles.md).
3. **HAN-Credential-Datei** — `~/.academic-research/`, Keys `han_user`/`han_password`
   (Dateiname siehe `config/browser_guides/han_login.md`). Institutionsspezifisch und
   komplett getrennt von Weg 2, obwohl beide denselben HAN-Login-Anwendungsfall
   abdecken. Zuständig: die Tiefensuche-Auth-Module `ebscohost`, `proquest` und `opac`
   (`--mode deep`), siehe [Suchquellen](../reference/search.md).

**Optionale Zusatzpakete:**

- `ocrmypdf` — OCR für Scan-PDFs ohne Text-Layer: `brew install ocrmypdf`
- **pyzotero** — für den `zotero-import`-Skill. Das Paket steht in
  `scripts/requirements.txt` und kommt daher über das Setup mit. Wer eine eigene
  Python-Umgebung nutzt, installiert es selbst: `pip install 'pyzotero>=1.5'`. Fehlt es,
  bricht der Skill mit genau dieser Aufforderung ab — er zieht nichts selbsttätig nach.
- **`hallucinator-cli`** *(optional, [gianlucasb/hallucinator](https://github.com/gianlucasb/hallucinator),
  **AGPL-3.0**)* — zusätzliche, kostenlose Offline-Absicherung gegen fabrizierte
  Referenzen (Titel/Autor/DOI), ergänzend zum `verbatim-guard`-Hook. Separat vom
  Nutzer installieren — das Upstream-README nennt dafür **ausschließlich** das
  Installer-Skript `curl -sSf https://hallucinator.science/install-cli.sh | sh`.
  **Nicht ausreichend:** Das gleichnamige PyPI-Paket liefert nur die
  Python-Bindings (Modul `hallucinator`, PyO3) und legt **kein**
  `hallucinator-cli` im PATH ab; ein Crate `hallucinator` existiert auf
  crates.io **nicht**. Bewusst **nicht** in
  `pyproject.toml`/`scripts/requirements.txt` gebundelt und nicht im Repo
  vendored, um die AGPL-Copyleft-Reichweite nicht auf dieses Plugin
  auszudehnen. `scripts/hallucinator_check.py` ruft das Binary rein als
  Subprozess auf und bricht bei fehlender Installation mit klarer
  Fehlermeldung ab (kein Crash).

## Schritt 1 — Plugin-Marketplace registrieren

```
/plugin marketplace add ahlerjam/academic-research
```

Einmalig pro System.

## Schritt 2 — Plugin installieren

```
/plugin install academic-research@academic-research
```

Das Plugin landet global unter `~/.claude/plugins/cache/academic-research/` und ist in
**allen** Claude-Code-Sessions verfügbar.

## Schritt 3 — Setup ausführen

```
/academic-research:setup
```

Der Command ruft `scripts/setup.sh`. Was dabei passiert (in dieser Reihenfolge):

1. Legt `~/.academic-research/` als Daten-Verzeichnis an (`sessions/`, `pdfs/`).
2. Prüft Python ≥ 3.11 und erzeugt ein isoliertes venv unter `~/.academic-research/venv/`.
3. Installiert die Pakete aus `scripts/requirements.txt` (httpx, pypdf, pyyaml, anthropic,
   mcp, sqlite-vec, sentence-transformers, pdfplumber u. a.) und macht danach einen
   Import-Smoke-Test. `pdfplumber` ist seit Issue #723 Pflicht-Dependency — die
   strukturerhaltende Tabellenextraktion (`vault.extract_tables`) läuft dadurch ohne
   Zusatzschritt mit.
4. Installiert die `browser-use`-CLI via `uv tool install` oder `pipx install` — sofern
   eines von beiden vorhanden ist.
5. Prüft, ob der globale `browser-use`-Claude-Skill unter `~/.claude/skills/browser-use/`
   liegt (wird separat von Anthropic bereitgestellt, nicht Teil dieses Plugins).
6. Zeigt die neu zu setzenden Claude-Code-Permissions an und trägt sie erst
   nach Bestätigung in `~/.claude/settings.local.json` ein (siehe Hinweis
   unten).
7. Fragt (bei leerem Ordner): *„Hier einen Facharbeit-Arbeitsordner initialisieren?"*
8. Fragt nach dem **SciHub-Tier** — Default ist *aus*.

Das Setup ist **idempotent**: mehrfach aufrufbar, ohne etwas zu zerstören.

> **Schritt 6 ist benutzerweit, nicht projektbezogen:** `~/.claude/settings.local.json`
> gilt für **alle** Claude-Code-Projekte auf diesem Rechner, nicht nur für
> academic-research. Das Setup zeigt deshalb die einzelnen neuen Regeln vor
> dem Schreiben an (`scripts/configure_permissions.py`) und schreibt erst nach
> expliziter Bestätigung — läuft `setup.sh` ohne Terminal (Pipe, CI, u. a. der
> primäre `/academic-research:setup`-Aufruf durch Claude Code selbst), greift
> der sichere Default: **kein** automatisches Schreiben, sichtbar gemeldet
> samt Nachhol-Befehl (`configure_permissions.py --yes`). Läuft `/setup` über
> Claude Code, holt Claude die Bestätigung in diesem Fall selbst per
> `AskUserQuestion` ein, bevor `configure_permissions.py --yes` schreibt
> (siehe `commands/setup.md`). Keine der gesetzten Regeln erlaubt pauschale
> Codeausführung (z. B. kein `Bash(python3 *)` mehr, nur eng gescopte Muster
> wie `Bash(~/.academic-research/venv/bin/python *)`).
> **Rücknahme:** Die betreffenden Zeilen aus dem `permissions.allow`-Array in
> `~/.claude/settings.local.json` manuell entfernen (oder — falls dort keine
> anderen Projekt-Berechtigungen stehen — die ganze Datei löschen).

> **Stolperstelle:** Schritt 7 und 8 sind interaktive Fragen. Läuft `setup.sh` ohne
> Terminal (Pipe, CI), greift jeweils der sichere Default — der Arbeitsordner wird dann
> **nicht** angelegt und SciHub bleibt aus. In Claude Code ist das kein Thema; wer das
> Skript direkt aus einem Skript heraus aufruft, sollte es wissen. Belegt im
> [Quickstart-Protokoll](../quickstart-protocol.md).

### Was der Arbeitsordner enthält

Nach `y` auf die Frage aus Schritt 7 liegt im **User-Projektordner** (nicht im
Plugin-Repo):

```
<projekt>/                  # z.B. meine-arbeit/
├── academic_context.md     # Thesis-Profil (leere Stubs) — User-Output
├── CLAUDE.md               # Plugin-Anleitung für Claude (generiert)
├── .gitignore              # sinnvolle Defaults
├── kapitel/                # Kapitel-Markdown — User-Output
├── literatur/
└── pdfs/
```

## Schritt 4 — Per-Uni-Profil auswählen (optional)

```
/academic-research:setup
# → "Hochschul-Profil auswählen?" → Hochschule wählen oder eigenes Profil anlegen
```

Details und die Liste der mitgelieferten Profile:
[Per-Uni-Profile](../reference/uni-profiles.md).

## Update und Migration von v5

Der ausführliche Migrations-Guide (die frühere Datei MIGRATION-v5-to-v6.md unter `docs/`)
wurde mit #346 als versionsgebundenes Altdokument entfernt. Bei Bedarf ist er über die
Git-Historie abrufbar.

**Kurzversion (von v5.x):**

```bash
# 1. Plugin updaten
/plugin update academic-research

# 2. Vault einrichten (MCP-Server-Init)
/academic-research:setup

# 3. Existierende Literatur migrieren (optional) — eigenständiges Skript,
#    kein setup-Flag: liest literature_state.md, schreibt in den Vault.
python academic_vault/migrate.py --state literature_state.md --db <vault.db>
```

**Von v4.x oder älter:** erst vollständig deinstallieren, dann neu installieren — v5.0 war
ein Breaking Release (Browser-Automation und Excel-Generierung wurden komplett
umgestellt).

Bestehende Vault-Datenbanken aus v6.5 brauchen für Volltext-Index und Vektor-Spiegel je
einen Backfill-Lauf; beide Befehle stehen in [vault.md](../reference/vault.md).
