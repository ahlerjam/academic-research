# Hooks-Stack

[← zurück zur README](../../README.md)

Das Plugin verdrahtet 7 Claude-Code-Events in `hooks/hooks.json`. Maßgeblich ist immer
diese Datei — die Tabelle unten gibt ihren Inhalt wieder und wird von
`tests/test_readme_hook_stack_doc.py` dagegen geprüft.

| Event | Was läuft | Beschreibung |
|-------|-----------|--------------|
| `PreToolUse` (`Write\|Edit\|MultiEdit`) | `verbatim-guard.mjs` | Blockt Kapitel-Writes mit nicht-verifizierten Zitaten |
| `PostToolUse` (`Write\|Edit\|MultiEdit`) | `post-tool-use-decisions.mjs` | Decision-Log: jede `.md`-Änderung wird protokolliert |
| `PreCompact` | `pre-compact.mjs` | Snapshot-Backup vor Claude-Compaction |
| `Notification` | `mid-session-reinforcement.mjs` | Erinnerung an Anti-Fabrikations-Regeln (nach ~20 Nachrichten) |
| `PostCompact` | `mid-session-reinforcement.mjs` | Erinnerung an Anti-Fabrikations-Regeln nach Compaction |
| `SessionStart` | *(Inline-Bash)* | Prüft, ob `~/.academic-research/venv` existiert und die Kernpakete importierbar sind |
| `Stop` | *(Inline-Bash)* | Hinweis bei ungesicherten `academic_context.md`-Änderungen |

Das sind **4 Skript-Dateien** (`verbatim-guard.mjs`, `post-tool-use-decisions.mjs`,
`pre-compact.mjs`, `mid-session-reinforcement.mjs`) plus **2 Inline-Bash-Kommandos**;
`mid-session-reinforcement.mjs` hängt an zwei Events.

> **Nicht verdrahtet:** `hooks/onboard-project-uni-prompt.sh` liegt zwar im Repo, ist aber
> **kein** Hook. Es ist ein eigenständiges Helferskript zur Profilauswahl, das manuell
> aufgerufen wird (`./hooks/onboard-project-uni-prompt.sh --profile tum`). Frühere
> Fassungen dieser Dokumentation führten es fälschlich als `SessionStart`-Hook.

## Privacy/Logs

Der `post-tool-use-decisions.mjs`-Hook protokolliert jede `.md`-Änderung im Projekt nach
`~/.academic-research/decisions.log` (Pfad überschreibbar via `ACADEMIC_DECISIONS_LOG`).
Datenschutz-Eigenschaften:

- **Kein Klartext-Inhalt.** Statt eines Content-Snippets steht in jeder Zeile nur der
  **SHA-256-Hash** des geschriebenen Inhalts (`… | Write | <pfad> | sha256=<hash>`). Damit
  bleibt der Idempotenz-/Änderungs-Check möglich, ohne PII (z. B. Zitat-Texte,
  Kapitelinhalte) zu leaken (CWE-532).
- **0600-Permissions.** Das Logfile wird mit `chmod 0600` (nur Owner liest/schreibt)
  erstellt; das Verzeichnis mit `0700`.
- **Rotation.** Überschreitet `decisions.log` 10 MB, wird es nach `decisions.log.1`
  rotiert und ein frisches Log begonnen.

Wer gar kein Decision-Log möchte, kann den Hook in `hooks/hooks.json` deaktivieren oder
`ACADEMIC_DECISIONS_LOG` auf einen verworfenen Pfad (z. B. unter `/tmp`) setzen.
