---
description: View past research sessions and their results; restore snapshots
allowed-tools: Read, Bash(cat ~/.academic-research/*), Bash(ls ~/.academic-research/*), Bash(~/.academic-research/venv/bin/python *), Bash(ls ~/.academic-research/snapshots/*), Bash(tar *)
argument-hint: [optional: search query, date, --restore <ts>, --restore-session <id>, --snapshots]
disable-model-invocation: true
---

# Recherche-Verlauf

Vergangene Recherche-Sessions ansehen und Snapshots verwalten.

## Verwendung

- `/academic-research:history` — Alle Sessions auflisten
- `/academic-research:history "DevOps"` — Sessions per Query durchsuchen
- `/academic-research:history 2026-03-17` — Details einer bestimmten Session anzeigen
- `/academic-research:history stats` — Aggregatstatistik anzeigen
- `/academic-research:history --snapshots` — Alle verfügbaren Snapshots auflisten
- `/academic-research:history --restore <ts>` — Snapshot wiederherstellen (z.B. `--restore 20260507-1430`)
- `/academic-research:history --restore-session <id>` — Frühere Recherche-Session als Arbeitsstand wiederherstellen (`<id>` ist der Session-Verzeichnisname bzw. -pfad aus der Auflistung, z.B. `2026-03-17T09-12-00Z`)

## Umsetzung

1. Argument prüfen:
   - `--restore <ts>` → **Snapshot-Wiederherstellung** (siehe unten)
   - `--restore-session <id>` → **Session-Wiederherstellung** (siehe unten)
   - `--snapshots` → Snapshot-Liste anzeigen (siehe unten)
   - Datum → Session von diesem Tag finden, Details anzeigen
   - `"stats"` → Aggregatstatistik anzeigen
   - Sonst → Sessions per Query-Text durchsuchen oder alle auflisten

2. Session-Index einlesen und um fehlende Ordner annotieren (statt rohem `cat`,
   damit ein zwischenzeitlich gelöschter/verschobener Sitzungsordner zu einer
   verständlichen Meldung statt zu einem Fehler führt):

```bash
~/.academic-research/venv/bin/python -c "
import json, sys
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from session_index import DEFAULT_INDEX_PATH, load_session_index, annotate_missing_sessions, search_session_index
entries = annotate_missing_sessions(load_session_index(DEFAULT_INDEX_PATH))
query = '<query>'  # nur gesetzt, wenn nach Query-Text gesucht wird ('' -> alle Sessions)
if query:
    entries = search_session_index(entries, query)
print(json.dumps(entries, ensure_ascii=False, indent=2))
"
```

Session-Einträge mit `missing: true` (Ordner nicht mehr vorhanden) in der
Auflistung als solche markieren statt sie kommentarlos wie eine normale
Session zu behandeln — deren `status`-Feld enthält den Klartext-Hinweis.

3. Ergebnisse als formatierte Tabelle ausgeben:

```
📚 Recherche-Verlauf

| # | Datum      | Query                  | Papers | PDFs  | Modus    |
|---|------------|------------------------|--------|-------|----------|
| 1 | 2026-03-17 | DevOps Governance      | 47     | 42/47 | standard |
| 2 | 2026-03-15 | AI Ethics              | 32     | 28/32 | deep     |
| 3 | 2026-03-10 | ML in Healthcare       | 25     | 20/25 | quick    |

Gesamt: 3 Sessions, 104 Papers, 90 PDFs
```

Für Einträge mit `missing: true` statt Papers/PDFs-Zahlen den Hinweis
`⚠️ Ordner fehlt` in der Zeile ausgeben.

Für die Detailansicht ausgeben: Paperliste, Zitat-Anzahl, Modul-Verteilung, Dateipfade.

## Snapshot-Liste (`--snapshots`)

```bash
ls ~/.academic-research/snapshots/
# Zeige pro Slug alle vorhandenen .tgz-Dateien
```

Ausgabe-Format:

```
📸 Snapshots

Projekt: my-project
  - 20260507-1430.tgz  (07.05.2026 14:30)
  - 20260506-0912.tgz  (06.05.2026 09:12)
```

## Snapshot-Wiederherstellung (`--restore <ts>`)

Ablauf:
1. Slug aus `ACADEMIC_PROJECT_SLUG` Umgebungsvariable oder Projekt-Verzeichnis ableiten.
2. Tarball lokalisieren: `~/.academic-research/snapshots/<slug>/<ts>.tgz`
3. Python-Script zur Wiederherstellung ausführen:

```bash
~/.academic-research/venv/bin/python -c "
import sys
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}')
from academic_vault.server import restore_snapshot
ok = restore_snapshot(
    slug='<slug>',
    ts='<ts>',
    target_dir='<CLAUDE_PROJECT_DIR>'
)
print('Wiederhergestellt.' if ok else 'Fehler: Snapshot nicht gefunden.')
"
```

4. Erfolg/Fehler ausgeben:
   - Erfolg: `✅ Snapshot <ts> wiederhergestellt in <CLAUDE_PROJECT_DIR>`
   - Fehler: `❌ Snapshot <ts> nicht gefunden unter ~/.academic-research/snapshots/<slug>/`

**Hinweis:** Vor der Wiederherstellung werden aktuelle Dateien überschrieben. Empfehlung: Neuen Snapshot erstellen bevor --restore ausgeführt wird.

## Session-Wiederherstellung (`--restore-session <id>`)

Anders als `--restore` (Snapshot-Tarball von Vault-/Projektdateien) macht
`--restore-session` eine frühere Recherche-Session wieder zum aktuellen
Arbeitsstand — im Sinne der bestehenden `ls -t`-Konvention, mit der
`score.md`/`excel.md` bereits die "neueste" Session per Verzeichnis-mtime
wählen. Die Sitzungsablage selbst wird dabei nicht umgebaut, nur die mtime
des Sitzungsordners aktualisiert.

Ablauf:
1. `<id>` aus dem Argument übernehmen — akzeptiert wird sowohl der reine
   Session-Verzeichnisname (z.B. `2026-03-17T09-12-00Z`) als auch der volle
   `session_path` aus der Auflistung.
2. Passenden Eintrag im Session-Index suchen und wiederherstellen:

```bash
~/.academic-research/venv/bin/python -c "
import json, sys
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from session_index import DEFAULT_INDEX_PATH, load_session_index, restore_session

session_id = '<id>'
entries = load_session_index(DEFAULT_INDEX_PATH)
match = next(
    (e for e in entries if e.get('session_path') == session_id or e.get('session_path', '').endswith('/' + session_id)),
    None,
)
if match is None:
    print(json.dumps({'ok': False, 'message': f'Keine Session mit ID {session_id!r} im Index gefunden.'}))
else:
    print(json.dumps(restore_session(match['session_path'])))
"
```

3. Ergebnis ausgeben:
   - Erfolg (`ok: true`): `✅ Sitzung <id> wiederhergestellt als Arbeitsstand — nachfolgende /score, /excel etc. verwenden sie automatisch als neueste Session.`
   - Ordner fehlt oder ID unbekannt (`ok: false`): die `message` aus dem
     JSON-Ergebnis 1:1 ausgeben (Klartext, kein Traceback), z.B.
     `❌ Sitzungsordner nicht gefunden: ~/.academic-research/sessions/2026-03-17T09-12-00Z`.

