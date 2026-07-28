# Installation und Migration

[← zurück zur README](../../README.md)

Der Kurzweg steht in der README (Quickstart). Diese Seite erklärt die Voraussetzungen im
Detail, was das Setup genau tut, und wie eine Migration von v5 abläuft.

## Voraussetzungen

| Komponente | Warum | Installation |
|-----------|-------|--------------|
| **Claude Code** | CLI zum Ausführen | [Installations-Anleitung](https://code.claude.com/docs/en/quickstart) |
| **Python 3.11+** | Vault-MCP-Server, Suchskripte | `brew install python@3.11` (macOS) |
| **Git** | Plugin-Marketplace-Install | auf macOS/Linux meist vorinstalliert |
| **`uv` oder `pipx`** *(optional)* | Automatische `browser-use`-Installation | `brew install pipx` oder `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

`uv`/`pipx` sind optional: fehlen sie, überspringt das Setup die `browser-use`-CLI und
sagt das auch. Die 7 API-Suchmodule und der gesamte Vault-/Schreib-Workflow laufen
trotzdem — nur die 7 Browser-Module (`--mode deep`) stehen dann nicht bereit.

**Optionale Zusatzpakete:**

- `ocrmypdf` — OCR für Scan-PDFs ohne Text-Layer: `brew install ocrmypdf`
- **pyzotero** — für den `zotero-import`-Skill. Das Paket steht in
  `scripts/requirements.txt` und kommt daher über das Setup mit. Wer eine eigene
  Python-Umgebung nutzt, installiert es selbst: `pip install 'pyzotero>=1.5'`. Fehlt es,
  bricht der Skill mit genau dieser Aufforderung ab — er zieht nichts selbsttätig nach.
- **`hallucinator-cli`** *(optional, [gianlucasb/hallucinator](https://github.com/gianlucasb/hallucinator),
  **AGPL-3.0**)* — zusätzliche, kostenlose Offline-Absicherung gegen fabrizierte
  Referenzen (Titel/Autor/DOI), ergänzend zum `verbatim-guard`-Hook. Separat vom
  Nutzer installieren (z. B. `cargo install hallucinator` oder `pip install
  hallucinator`, je nach Upstream-Distribution) — bewusst **nicht** in
  `pyproject.toml`/`scripts/requirements.txt` gebundelt und nicht im Repo vendored,
  um die AGPL-Copyleft-Reichweite nicht auf dieses Plugin auszudehnen. `scripts/
  hallucinator_check.py` ruft das Binary rein als Subprozess auf und bricht bei
  fehlender Installation mit klarer Fehlermeldung ab (kein Crash).

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
   mcp, sqlite-vec, sentence-transformers u. a.) und macht danach einen Import-Smoke-Test.
4. Installiert die `browser-use`-CLI via `uv tool install` oder `pipx install` — sofern
   eines von beiden vorhanden ist.
5. Prüft, ob der globale `browser-use`-Claude-Skill unter `~/.claude/skills/browser-use/`
   liegt (wird separat von Anthropic bereitgestellt, nicht Teil dieses Plugins).
6. Trägt Claude-Code-Permissions in `~/.claude/settings.local.json` ein.
7. Fragt (bei leerem Ordner): *„Hier einen Facharbeit-Arbeitsordner initialisieren?"*
8. Fragt nach dem **SciHub-Tier** — Default ist *aus*.

Das Setup ist **idempotent**: mehrfach aufrufbar, ohne etwas zu zerstören.

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

# 3. Existierende Literatur migrieren (optional)
/academic-research:setup --migrate-v5
# → Fragt: "literature_state.md in Vault migrieren?" → y
```

**Von v4.x oder älter:** erst vollständig deinstallieren, dann neu installieren — v5.0 war
ein Breaking Release (Browser-Automation und Excel-Generierung wurden komplett
umgestellt).

Bestehende Vault-Datenbanken aus v6.5 brauchen für Volltext-Index und Vektor-Spiegel je
einen Backfill-Lauf; beide Befehle stehen in [vault.md](../reference/vault.md).
