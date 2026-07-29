# Hooks-Stack

[← Doku-Übersicht](../README.md)

Das Plugin verdrahtet 6 Claude-Code-Events in `hooks/hooks.json`. Maßgeblich ist immer
diese Datei — die Tabelle unten gibt ihren Inhalt wieder und wird von
`tests/test_readme_hook_stack_doc.py` dagegen geprüft.

| Event | Was läuft | Beschreibung |
|-------|-----------|--------------|
| `PreToolUse` (`Write\|Edit\|MultiEdit`) | `verbatim-guard.mjs` | Blockt Kapitel-Writes mit nicht-verifizierten Zitaten |
| `PreToolUse` (`Write\|Edit\|MultiEdit`) | `claim-drift-guard.mjs` | Warnt, wenn eine Überarbeitung die Aussage um ein belegtes Zitat ändert, ohne den Beleg anzupassen |
| `PostToolUse` (`Write\|Edit\|MultiEdit`) | `post-tool-use-decisions.mjs` | Decision-Log: jede `.md`-Änderung wird protokolliert |
| `PreCompact` | `pre-compact.mjs` | Snapshot-Backup vor Claude-Compaction |
| `UserPromptSubmit` | `mid-session-reinforcement.mjs` | Erinnerung an Anti-Fabrikations-Regeln (nach ~20 Nachrichten) |
| `SessionStart` (kein Matcher) | *(Inline-Bash)* | Prüft, ob `~/.academic-research/venv` existiert und die Kernpakete importierbar sind |
| `SessionStart` (`matcher: "compact"`) | `mid-session-reinforcement.mjs` | Erinnerung an Anti-Fabrikations-Regeln nach Compaction |
| `Stop` | *(Inline-Bash)* | Hinweis bei ungesicherten `academic_context.md`-Änderungen |

Das sind **5 Skript-Dateien** (`verbatim-guard.mjs`, `claim-drift-guard.mjs`,
`post-tool-use-decisions.mjs`, `pre-compact.mjs`, `mid-session-reinforcement.mjs`) plus
**2 Inline-Bash-Kommandos**; `mid-session-reinforcement.mjs` hängt an zwei
Event-Konfigurationen (`UserPromptSubmit` und `SessionStart`/`compact`), und
`PreToolUse` ruft zwei Skripte nacheinander auf.

### Claim-Drift-Warnung (`claim-drift-guard.mjs`, #397)

Der `verbatim-guard` prüft, ob ein Zitat **überhaupt** im Vault steht, und blockiert
sonst. Er sieht aber nicht, wenn eine spätere Überarbeitung die *Aussage um ein bereits
belegtes Zitat herum* verändert und die alte Quellenangabe stehen lässt — aus
„moderater Effekt" wird „starker Effekt", Zitat und Beleg bleiben unverändert. Genau
diese Lücke schließt der `claim-drift-guard` als **additiver Zusatzcheck**: er ersetzt
nichts an der bestehenden Kernlogik und **blockiert nie** (Exit 0, Warnung als
`systemMessage` + `hookSpecificOutput.additionalContext`, kein `permissionDecision`).

Verglichen werden immer **ganze Dateistände**, nicht die Tool-Strings: Ein realistischer
`Edit` trägt in `old_string`/`new_string` nur die geänderte Stelle („moderaten Effekt" →
„starken Effekt"), während Zitat und Quellenangabe ausschließlich in der Datei stehen.
Der Hook liest deshalb den Stand von Platte und rekonstruiert daraus den neuen Stand
(`MultiEdit`: kumulativ, ein Vergleichspaar je Teil-Edit). Ohne lesbaren Vorgängerstand
fällt er auf den reinen String-Vergleich zurück; bei `Write` auf eine neue Datei gibt es
keinen Vergleichsstand und er schweigt. Passt `old_string` nicht auf den Dateistand,
würde auch das echte Tool scheitern — der Teil-Edit wird übersprungen.

Er warnt nur, wenn alle Bedingungen zugleich gelten:

1. Pfad ist eine Kapitel-/LaTeX-Datei (`kapitel/*.md`, `*.tex`) — wie beim `verbatim-guard`.
2. Alt und Neu unterscheiden sich nach Normalisierung (Markdown-Emphase raus,
   Whitespace kollabiert) — reine Formatierungsänderungen zählen nicht.
3. Im Fenster um die Änderung (Default 300 Zeichen, `CLAIM_DRIFT_WINDOW`) liegt ein
   Zitat-Span, der in Alt **und** Neu wörtlich identisch vorkommt.
4. Die Beleg-Marker im Fenster **um dieses Zitat** (`(Autor Jahr, S. x)`, `\cite{…}`,
   `[^fussnote]`, `[@citekey]`) sind unverändert — wurde die Quelle mitgeändert, war es
   eine bewusste Anpassung und der Hook schweigt. Maßgeblich ist der Stand nach dem
   *kompletten* Tool-Aufruf: bei einem `MultiEdit`, das die Aussage im einen und die
   Quelle im anderen Teil-Edit anfasst, zählt das als mitgeändert.
5. Dieser Zitat-Span ist im Vault belegt (`search_quote_text` → `get_quote`).

Der Vault-Lookup ist **tri-state**: gefunden / nicht gefunden / nicht erreichbar. Anders
als beim `verbatim-guard` ist „nicht erreichbar" hier kein fail-open-Bypass, sondern
Schweigen — ohne Datenbasis wird nicht geraten, sonst wäre jede Änderung eine Warnung.
Die Warnung zitiert `context_before`/`context_after` des Vault-Zitats mit, damit direkt
prüfbar ist, ob der Beleg die neue Aussage noch trägt. Der Lookup läuft in **einem**
Python-Subprozess für alle Kandidaten (Budget `CLAIM_DRIFT_MAX_LOOKUPS`, Default 10) und
nutzt dieselbe Interpreter-Kaskade wie `mid-session-reinforcement.mjs`. Diagnose-Ausgaben
auf stderr gibt es nur mit `CLAIM_DRIFT_DEBUG=1`; der Bypass-Marker
`<!-- vault-guard: skip -->` schaltet auch diesen Hook stumm.

> Die Idee eines Revisions-Claim-Drift-Schutzes stammt aus dem Repo
> `academic-research-skills` von Imbad0202 (CC-BY-NC-4.0). Übernommen wurde
> ausschließlich das **Konzept**; die Implementierung hier ist eigenständig, es wurde
> kein Code von dort gelesen oder kopiert.

> **Warum nicht `Notification`/`PostCompact` (Stand vor #382)?** Laut offizieller
> Claude-Code-Doku ([code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks))
> wirkt stdout nur bei den Events `UserPromptSubmit`, `UserPromptExpansion` und
> `SessionStart` tatsächlich als Modell-Kontext ("the exceptions are..."). Die
> Anti-Fabrikations-Erinnerung lief auf `Notification`/`PostCompact` daher vollständig
> ins Leere — sie ist jetzt auf `UserPromptSubmit` (Intervall) und `SessionStart` mit
> `matcher: "compact"` (nach Compaction) verdrahtet.

### Nachweis, dass die Erinnerung wirklich beim Modell ankommt

Dass ein Hook an einem Context-Injection-Event hängt, beweist noch nicht, dass beim
Modell etwas ankommt. Den Round-Trip prüft:

```bash
uv run python scripts/dev/verify_reinforcement_context.py
```

Das Skript legt einen temporären Vault mit einer Decision an, deren Text einen frisch
gewürfelten Nonce-Marker enthält, leitet die `settings.json` aus der **deployten**
`hooks/hooks.json` ab (kein handgeschriebenes Duplikat) und fragt eine headless
`claude -p`-Session, welchen Marker sie im Kontext sieht. Nennt das Modell ihn, kann
er nur über die Hook-Injection dorthin gelangt sein. Zusätzlich wird das
Session-Transcript auf den `hook_success`-Eintrag geprüft.

Der Lauf kostet einen kurzen API-Aufruf und braucht Netz + Anmeldung, läuft daher
**nicht** in der Default-Suite. Als pytest-Variante:
`ACADEMIC_LIVE_CONTEXT_TEST=1 uv run pytest tests/test_hook_midsession_live_context.py`
(Gate analog zu `VAULT_E5_LIVE_TEST`). Die Verdrahtungs-Tests derselben Datei laufen
ohne Gate immer mit.

### Python-Interpreter für den Vault-Lookup

`mid-session-reinforcement.mjs` liest die Decisions über einen Python-Subprozess. Hooks
erben in einer echten Session die `PATH` des Nutzers — dort steht meist das System-Python
(macOS: `/usr/bin/python3` == 3.9), das `academic_vault` mangels PEP-604-Syntax nicht
importieren kann. Der Hook probiert daher in dieser Reihenfolge:

1. `$ACADEMIC_PYTHON` (expliziter Override, z. B. conda/pyenv)
2. `$VIRTUAL_ENV/bin/python` (aktives venv, z. B. `uv run`)
3. `~/.academic-research/venv/bin/python` (Setup-venv aus `/academic-research:setup`)
4. `python3` aus der `PATH`

Scheitert jeder Kandidat, bleibt der Hook fail-open (Exit 0) und injiziert den Hinweis
ohne Decision-Liste.

### Intervall-Zähler und Hook-Timeout

Der `UserPromptSubmit`-Payload enthält kein `message_count`; der Hook zählt seine eigenen
Aufrufe in `~/.academic-research/reinforcement-state.json` (`prompt_count`, Pfad
überschreibbar via `ACADEMIC_REINFORCEMENT_STATE`). Der erhöhte Zähler wird **vor** dem
Vault-Lookup geschrieben — auch auf dem Trigger-Pfad. Grund: der Lookup blockiert pro
Interpreter-Kandidat bis zu 10 s, das Hook-Timeout in `hooks.json` beträgt 15 s. Würde
erst nach dem Lookup gespeichert, bliebe bei einem abgeschossenen Trigger-Aufruf
dauerhaft `TRIGGER_N-1` in der Datei stehen und jeder folgende Prompt liefe erneut in
denselben hängenden Lookup. Preis dieser Reihenfolge: Stirbt der Hook während des
Lookups, entfällt die Erinnerung dieser Runde — die nächste kommt regulär nach
`ACADEMIC_REINFORCEMENT_N` weiteren Nachrichten.

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
