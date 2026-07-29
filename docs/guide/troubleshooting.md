# Troubleshooting

[← zurück zur README](../../README.md)

## Setup und Umgebung

| Problem | Lösung |
|---------|--------|
| *„Python venv not found"* | `/academic-research:setup` ausführen |
| *„Python 3.11+ erforderlich"* | Neueres Python installieren (`brew install python@3.11`), dann Setup erneut |
| *„Vault not initialized"* | `/academic-research:setup` — initialisiert den MCP-Server |
| *„Missing dependencies"* | `~/.academic-research/venv/bin/pip install -r scripts/requirements.txt` |
| Setup legt den Arbeitsordner nicht an | Die Frage ist interaktiv und braucht ein Terminal; ohne TTY greift der sichere Default (nichts anlegen). In Claude Code mit `y` beantworten. |
| Kontext wird nicht geladen | `ls academic_context.md` — fehlt sie, `/academic-research:setup` in genau diesem Ordner ausführen |
| Plugin soll in Code-Projekten nicht laden | `.claude/settings.local.json`: `{"enabledPlugins": {"academic-research@academic-research": false}}` |

## Suche

| Problem | Lösung |
|---------|--------|
| Browser-Module funktionieren nicht | `uv tool install browser-use && browser-use doctor` |
| Browser-Module fehlen ganz | Ohne `uv`/`pipx` überspringt das Setup die CLI. Nachinstallieren, dann `--mode deep` erneut |
| Keine Ergebnisse bei der Suche | Breitere Query; `--no-expand` nutzt die Roh-Query ohne Expansion |
| Semantic Scholar 429-Fehler | `SS_API_KEY`-Umgebungsvariable setzen, siehe [Zugangsdaten](installation.md#zugangsdaten) |
| Excel leer | Zuerst `/academic-research:search` ausführen — ohne Session gibt es nichts zu exportieren |

## Vault und Zitate

| Problem | Lösung |
|---------|--------|
| Vault-Suche liefert keine Treffer | `vault.stats()` prüfen. `paper_count: 0` → noch nichts importiert; sonst evtl. `python academic_vault/migrate.py --state literature_state.md --db <vault.db>` nachholen ([installation.md](installation.md#update-und-migration-von-v5)) |
| Suche findet nur Titel, keinen Volltext | Volltext-Backfill laufen lassen (Befehl in [vault.md](../reference/vault.md#pdf-volltext-index)) |
| Vektor-Suche wirkt wirkungslos | Log prüfen: fehlt `sentence-transformers` oder scheitert der Modell-Download, fällt der Vault auf FTS5-only zurück |
| Verbatim-Guard blockt den Kapitel-Write | Das ist der Normalfall bei einem nicht belegten Zitat: Zitat via `quote-extractor` aus dem PDF holen, dann erneut schreiben |
| Zitat steht im Vault, wird trotzdem geblockt | Der Guard vergleicht wortwörtlich — Anführungszeichen, Auslassungen und Umbrüche müssen exakt passen |
| `book-fetcher` schlägt immer fehl | Per-Uni-Profil prüfen: `cat ~/.academic-research/library-profiles/active.yaml`, siehe [Zugangsdaten](installation.md#zugangsdaten) |

## Skills

| Problem | Lösung |
|---------|--------|
| Skill triggert nicht | Ein Keyword aus der Trigger-Liste verwenden ([skills.md](../reference/skills.md)) oder den Skill explizit ansprechen |
| Output-Skill (Poster, Antrag, Response) läuft nicht | Diese Skills sind Default-Off. `output_targets` im Projekt-State setzen — siehe [Glossar](../reference/glossary.md) |
