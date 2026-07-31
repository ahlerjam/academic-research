# Hooks-Stack

[← Doku-Übersicht](../README.md)

Das Plugin verdrahtet 6 Claude-Code-Events in `hooks/hooks.json`. Maßgeblich ist immer
diese Datei — die Tabelle unten gibt ihren Inhalt wieder und wird von
`tests/test_readme_hook_stack_doc.py` dagegen geprüft.

| Event | Was läuft | Beschreibung |
|-------|-----------|--------------|
| `PreToolUse` (`Write\|Edit\|MultiEdit`) | `verbatim-guard.mjs` | Blockt Kapitel-Writes mit nicht-verifizierten Zitaten |
| `PreToolUse` (`Write\|Edit\|MultiEdit`) | `claim-drift-guard.mjs` | Warnt, wenn eine Überarbeitung die Aussage um ein belegtes Zitat ändert, ohne den Beleg anzupassen |
| `PostToolUse` (`Write\|Edit\|MultiEdit`) | `post-tool-use-decisions.mjs` | Decision-Log: jede `.md`-Änderung wird im Vault protokolliert |
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

> **Nicht verdrahtet:** `hooks/vault-bridge.mjs` ist **kein** Hook, sondern ein
> gemeinsames Modul, das die beiden Vault-Hooks importieren (DB-Pfad-Auflösung und
> Interpreter-Kaskade). Es liegt flach in `hooks/`, damit das CI-Syntax-Gate
> (`node --check hooks/*.mjs`) es miterfasst.

### Klammer-Zitat-Validierung

Klammer- und Paraphrase-Belege wie `(Müller 2021, S. 45)`,
`(Müller/Schmidt 2019)`, `(Müller u. a. 2021, S. 45–47)`, `(vgl. Müller 2021: 45)`
oder `vgl. Schmidt 2019` werden extrahiert und gegen den Vault geprüft:
Familienname und Jahr gegen `papers.csl_json` (Umlaut-Faltung und
Diakritika-Strip, `Müller`/`Mueller`/`Muller` treffen denselben Eintrag), die
Seitenzahl gegen `papers.page_first`/`page_last` bzw. `quotes.printed_page`.
Führende **Namenspartikel** werden dabei zusätzlich weggefaltet: im Text steht
`(von Neumann 1945)`, CSL-JSON führt das Partikel dagegen separat in
`non-dropping-particle` und `family` bleibt `Neumann` — ohne diese Variante
blockte der Guard Belege, deren Paper längst im Vault liegt.
Die beiden Seitenquellen wiegen unterschiedlich: nur der vollständige
Seitenumfang aus `page_first`/`page_last` kann eine Seite **widerlegen**.
`quotes.printed_page` ist eine punktuelle Stichprobe der bereits extrahierten
Stellen und kann eine Seite nur bestätigen — dass aus S. 47 noch nichts
extrahiert wurde, sagt nichts darüber aus, ob das Werk eine S. 47 hat.

**Nicht geprüft** (bewusst, gegen False Positives): Code-Fences und
Inline-Code, LaTeX-Makros (`\cite{…}`, `\ref{…}`), nackte Jahresklammern
(`(2021)`), Struktur-Verweise (`(siehe Kapitel 2)`, `(vgl. Abb. 3)`),
Datums- und Standangaben (`(Januar 2021)`, `(März 2020)`, `(Stand 2021)`,
`(Fassung 2019)`), `ebd.`/`a.a.O.` sowie alles ab der Überschrift des
Literaturverzeichnisses. Hat der Vault zu einem Paper **keinen vollständigen
Seitenumfang**, gilt die Seitenzahl als nicht widerlegbar (dokumentierter
Soft-Pass).

**Geprüft wird jede erkannte Form, und ein sauberes Negativ blockiert sie
auch.** Ob Vault und Kaskade nichts finden, hängt nicht daran, wie der Beleg
geschrieben ist — ein frei erfundenes `(Fantasius 2087)` ist genau der
Halluzinationsvektor, gegen den der Guard antritt.

Die **Belegstärke** klassifiziert die Form und ist der Angriffspunkt der
einzigen Stellschraube, die es hier gibt. Eine Seitenangabe (`, S. 45`), ein
Signalwort (`vgl.`, `siehe`, `zit. nach`) oder ein Co-Autoren-Marker (`/`, `&`,
`u. a.`, `et al.`, jeweils mit tatsächlich folgendem zweiten Namen bzw. als
`u. a.`/`et al.`) machen die Zitierabsicht **eindeutig**. Die nackte Form
`(Wort Jahr)` ist dagegen von Fließtext lexikalisch nicht zu trennen
(`(Fukushima 2011)`, `(Corona 2020)`, `(Bologna 1999)`, `(Paris, 2015)`) und
heißt hier **mehrdeutig**.

`ACADEMIC_CITATION_AMBIGUOUS` entscheidet, was aus einem sauberen Negativ auf
der mehrdeutigen Form folgt:

| Wert | Mehrdeutige Form bei `no-match` | Für wen |
|---|---|---|
| `block` (Default) | **Block** (exit 2), die Meldung nennt diesen Schalter | Regelfall — AC2 aus #378 macht keine Ausnahme für die Form |
| `mark` | allow + `[UNVERIFIED]` | prosa-lastige Texte mit vielen Ort-/Ereignis-Klammern |

Die eindeutige Form blockiert in **beiden** Werten — der Schalter ist kein
Kill-Switch für die Prüfung. Und er greift nur beim *sauberen* Negativ:
`unavailable` (API-Ausfall) und „ungeprüft" (Kontingent erschöpft) bleiben
überall ein `[UNVERIFIED]`-Soft-Fail, denn fehlende Evidenz ist kein
Gegenbeweis.

Warum `block` der Default ist, obwohl die Form Prosa sein kann: der Hook greift
im Soft-Fail ohnehin in genau diesen Text ein — er schreibt
`(Fukushima 2011) [UNVERIFIED]` in die Datei. Wer diesen Eingriff akzeptiert,
kann ihn nicht als Grund gegen den Block anführen, der sichtbar ist, nichts
schreibt und sich in einem Zug auflösen lässt.

Der eigentliche Schutz vor Fehlalarmen in echter Prosa ist der **Treffer**,
nicht das Ausfiltern der Form: `Fukushima`, `Bologna` und `Paris` sind auch
reale Nachnamen, zu denen Vault oder Kaskade in aller Regel ein Paper finden —
dann schweigt der Hook vollständig. Bleibt doch etwas hängen, stehen drei Wege
offen: Quelle in den Vault, `ACADEMIC_CITATION_AMBIGUOUS=mark` für den
Schreibstil, `<!-- vault-guard: skip -->` für den Einzelfall. Der Marker hängt
hinter der Klammer und ändert sonst nichts am Satz (Invariante der Tests:
`updated.replace(' [UNVERIFIED]', '') == original`).

Ein Komma vor der Jahreszahl ist dabei **kein** Co-Autoren-Marker:
`(Paris, 2015)` hat exakt die Form von `(Müller, 2021)`, beide gelten als
mehrdeutig. Nur ein wirklich gelesener Zweitname (`(Müller/Schmidt 2019)`,
`(Müller, Schmidt 2019)`) oder ein `u. a.`/`et al.` macht die Kette eindeutig.

**Korroboration hebt die Mehrdeutigkeit auf.** Kommt derselbe Familienname im
selben Dokument mindestens einmal in einer eindeutigen Beleg-Form vor, weist
der Text ihn selbst als zitierten Autor aus — die nackte Form zählt dann als
eindeutig und blockiert auch unter `ACADEMIC_CITATION_AMBIGUOUS=mark`.
`(Müller 2021, S. 45)` im Kapitel macht ein danebenstehendes `(Müller 2099)`
zum Hard-Block; `(Fukushima 2011)` bleibt dort bei `[UNVERIFIED]`, weil
`Fukushima` nirgends als zitierter Autor auftritt.

Das Prüfkontingent (`ACADEMIC_CITATION_MAX_PER_WRITE`) vergibt eindeutige
Belege zuerst — sonst genügte unter `mark` genug harmlose `(Wort Jahr)`-Prosa
vor einem erfundenen Beleg, um den Hard-Block zu verdrängen.

Ebenfalls **nicht** erfasst — bewusst, weil der Regex sonst zu viele
Falschtreffer produziert: die narrative Form ohne Signalwort
(`Müller (2021) zeigt …`, kollidiert mit `Die DSGVO (2016) trat in Kraft`)
und Körperschaftsautoren (`(Statistisches Bundesamt 2021)`). Bei Belegen mit
Seitenbereich (`S. 45–47`) wird die erste Seite geprüft. Ein Signalwort, das
über eine nicht geprüfte Region hinweg auf einen Namen zeigt
(`vgl. (Müller 2021, S. 45) Schmidt 2019`, `vgl. \cite{…} Schmidt 2019`),
zählt ebenfalls nicht: der Beleg hinter der Klammer bzw. dem Makro steht dort
nicht als Ziel des Signalworts, und die Klammer selbst hat der Klammer-Pass
bereits erfasst. False Positives blockieren den Schreibfluss und sind hier
teurer als False Negatives — der Guard ist die letzte, nicht die einzige
Verteidigungslinie.

**Externe Kaskade (Fallback).** Findet der Vault den Beleg nicht, laufen drei
Stufen mit Frühausstieg: arXiv (eine gebatchte Anfrage für alle offenen
Belege) → CrossRef → Semantic Scholar (Fuzzy, Gate: Autoren-Überlapp
≥ 0,6). Score-Modell pro Kandidat (0–100):

| Komponente | Punkte |
|---|---|
| Familienname trifft | 40 |
| Jahr exakt | 40 |
| Jahr um genau 1 daneben | 20 |
| Autoren-Überlapp (Jaccard) | 0–20 |

**Entscheidungsmatrix.**

| Ergebnis | Bedingung | Reaktion |
|---|---|---|
| `confirmed` | Vault-Treffer **oder** Score ≥ `ACADEMIC_CITATION_CONFIRMED_MIN` (80) | allow |
| `probable` | Score ≥ `ACADEMIC_CITATION_PROBABLE_MIN` (65) | allow + `[UNVERIFIED]` |
| `unavailable` | Timeout / `ECONNREFUSED` / abgebrochener Body / **jeder** Nicht-2xx-Status (5xx, 429, aber auch 403-Drosselung und 404) / HTTP 200 mit unlesbarem Body | allow + `[UNVERIFIED]` |
| `no-match`, eindeutige Form | alle Stufen haben sauber geantwortet (2xx + parsbarer Body im erwarteten Format), kein Treffer; Beleg trägt Seite, Signalwort, echten Co-Autor oder ist im Dokument korroboriert | **Block** (exit 2) |
| `no-match`, nackte Form | dasselbe, aber `(Wort Jahr)` ohne Korroboration | **Block** (exit 2) — mit `ACADEMIC_CITATION_AMBIGUOUS=mark`: allow + `[UNVERIFIED]` |
| `page-mismatch` | Autor/Jahr im Vault, Seite außerhalb des **vollständigen** Seitenumfangs | **Block** (exit 2) |
| ungeprüft (Kontingent) | mehr Belege als `ACADEMIC_CITATION_MAX_PER_WRITE` (eindeutige zuerst) | allow + `[UNVERIFIED]` (stderr-Warnung) |

Der Unterschied zwischen `no-match` und `unavailable` ist tragend: ein
Netzausfall darf nie wie ein Halluzinations-Nachweis wirken. Bei `probable`
und `unavailable` schreibt der Hook den Tool-Input per
`hookSpecificOutput.updatedInput` um und hängt ` [UNVERIFIED]` an den Beleg
(unterstützt `Write.content`, `Edit.new_string` und `MultiEdit.edits[]`).

**Konfiguration (Environment).**

| Variable | Default | Bedeutung |
|---|---|---|
| `ACADEMIC_CITATION_CASCADE` | `on` | `off` = Kill-Switch, Vault-only, kein Netzzugriff |
| `ACADEMIC_CITATION_AMBIGUOUS` | `block` | Reaktion auf ein **sauberes Negativ** bei der mehrdeutigen Form `(Wort Jahr)`; `mark` setzt sie auf `[UNVERIFIED]` herab. Eindeutige Formen blockieren in beiden Werten, `unavailable`/„ungeprüft" markieren in beiden |
| `ACADEMIC_CITATION_CONFIRMED_MIN` | `80` | Score-Schwelle für „bestätigt" (allow) |
| `ACADEMIC_CITATION_PROBABLE_MIN` | `65` | Score-Schwelle für „wahrscheinlich" (`[UNVERIFIED]`) |
| `ACADEMIC_CITATION_S2_MIN_OVERLAP` | `0.6` | Autoren-Überlapp-Gate für Semantic Scholar |
| `ACADEMIC_CITATION_TIMEOUT_MS` | `2000` | Timeout je HTTP-Request |
| `ACADEMIC_CITATION_BUDGET_MS` | `6000` | Gesamt-Wall-Clock-Budget der Kaskade |
| `ACADEMIC_CITATION_MAX_PER_WRITE` | `100` | Prüfkontingent je Write; darüber hinausgehende Belege gelten als **ungeprüft** und werden mit `[UNVERIFIED]` markiert, nie stillschweigend durchgewinkt |
| `ACADEMIC_CITATION_ARXIV_URL` | arXiv-API | Base-URL, überschreibbar (Tests/Proxy) |
| `ACADEMIC_CITATION_CROSSREF_URL` | CrossRef-API | Base-URL, überschreibbar (Tests/Proxy) |
| `ACADEMIC_CITATION_S2_URL` | Semantic-Scholar-API | Base-URL, überschreibbar (Tests/Proxy) |

Die Kaskade ist die einzige Stelle, an der ein Hook dieses Plugins ins Netz
geht. Wer das nicht möchte, setzt `ACADEMIC_CITATION_CASCADE=off` — dann
entscheidet allein der Vault.

**Markierung trifft die geprüfte Fundstelle.** `extractCitations()` liefert zu
jedem Beleg die Offsets `start`/`end` (Invariante: `content.slice(start, end)
=== raw`), und die Markierung spleißt `[UNVERIFIED]` an genau diesen Spans ein
— von hinten nach vorne, damit noch offene Offsets gültig bleiben. Eine
Textsuche wäre an drei Stellen falsch: sie träfe ein identisches Vorkommen in
einem maskierten Bereich (Code-Fence, `\cite{…}`, Literaturverzeichnis), sie
markierte bei mehrfach zitiertem Beleg nur das erste Vorkommen, und bei
`MultiEdit` landete ein Beleg aus `edits[1]` in `edits[0]`. Geprüft wird je
Beleg (dedupliziert, ein Lookup), markiert wird je Fundstelle. Passt ein Span
nicht zum erwarteten Text, wird die Markierung übersprungen und auf stderr
gewarnt — nie geraten: ein fehlender Marker ist harmlos, ein Marker an
falscher Stelle verändert den Text.

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

1. Pfad ist eine Kapitel-/LaTeX-Datei (`kapitel/**/*.md` inkl. Unterordner, `*.tex`)
   — wie beim `verbatim-guard`.
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

`mid-session-reinforcement.mjs` liest die Decisions über einen Python-Subprozess,
`post-tool-use-decisions.mjs` schreibt sie über denselben Weg; die Kaskade steht einmal in
`hooks/vault-bridge.mjs` (Node hat vor 22.5 kein `node:sqlite`, die CI pinnt Node 20 —
ein direkter DB-Zugriff aus dem Hook scheidet aus). Hooks
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

> **Nicht verdrahtet:** `hooks/lib/onboard-project-uni-prompt.sh` liegt zwar im Repo, ist aber
> **kein** Hook. Es ist ein eigenständiges Helferskript zur Profilauswahl, das manuell
> aufgerufen wird (`./hooks/lib/onboard-project-uni-prompt.sh --profile tum`). Frühere
> Fassungen dieser Dokumentation führten es fälschlich als `SessionStart`-Hook.

### Decision-Log: eine Senke, zwei Hooks

`post-tool-use-decisions.mjs` protokolliert jede `.md`-Änderung im Projekt in der
**Vault-Tabelle `decisions`** — genau der Tabelle, die `mid-session-reinforcement.mjs`
in der nächsten Session vorliest. Bis Issue #527 schrieb der Hook stattdessen in die
Textdatei `~/.academic-research/decisions.log`, während das Reinforcement SQLite las:
zwei Speicherorte, die nie zusammenfanden, und ein Feature, das faktisch tot war.

Eigenschaften der Auto-Einträge:

- **Feste Kategorie `file-change`.** Datei-Änderungen sind keine Entscheidungen. Das
  Reinforcement gibt sie deshalb in einem eigenen Block aus (bis zu 3), getrennt von den
  manuell über `vault.add_decision` gepflegten Decisions (bis zu 5) — sonst würden die
  letzten Writes jede echte Entscheidung aus dem Fenster drängen.
- **Höchstens ein aktiver Eintrag pro Datei.** Gleicher Inhalts-Hash ⇒ kein neuer Eintrag;
  geänderter Hash ⇒ neuer Eintrag, der den bisherigen per `superseded_by` ablöst.
  Begrenzt ist damit die Menge der *aktiven* Einträge — abgelöste bleiben als Historie
  in der Tabelle stehen und werden nicht gelöscht.
- **Kein Bestandteil des Material-Passports.** `vault.export_material_passport` nimmt
  nur die methodischen Decisions in `decisions_snapshot` auf und filtert `file-change`
  heraus. Sonst würde der `passport_hash` bei jeder Kapitel-Änderung wandern, obwohl
  sich am Material nichts geändert hat (#380).
- **Fail-open.** Existiert keine Vault-DB, ist der Vault gesperrt
  (Material-Passport-Lock) oder findet sich kein brauchbarer Python-Interpreter, bleibt
  es bei einer Meldung auf stderr; der Hook beendet sich immer mit Exit 0 und legt nie
  selbst eine DB an. Schreib- und Lesepfad lösen den DB-Pfad über dasselbe Modul
  `hooks/vault-bridge.mjs` auf, damit sie nicht erneut auseinanderlaufen können.

## Privacy/Logs

In der Vault-Tabelle landen ausschließlich **relativer Pfad, Tool-Name und der
SHA-256-Hash** des geschriebenen Inhalts — kein Klartext (CWE-532, Issue #191).

`~/.academic-research/decisions.log` ist seit #527 ein reines **Opt-in-Debug-Log**: Es
entsteht nur noch, wenn `ACADEMIC_DECISIONS_LOG` auf einen Pfad zeigt; ohne die Variable
schreibt der Hook keine Datei. Bestehende `decisions.log`-Dateien aus früheren Versionen
sind ein reines Pfad/Hash-Journal ohne semantischen Wert und können gelöscht werden.
Ist das Debug-Log aktiviert, gelten unverändert:

- **Kein Klartext-Inhalt.** Statt eines Content-Snippets steht in jeder Zeile nur der
  **SHA-256-Hash** des geschriebenen Inhalts (`… | Write | <pfad> | sha256=<hash>`).
- **0600-Permissions.** Das Logfile wird mit `chmod 0600` (nur Owner liest/schreibt)
  erstellt; das Verzeichnis mit `0700`.
- **Rotation.** Überschreitet `decisions.log` 10 MB, wird es nach `decisions.log.1`
  rotiert und ein frisches Log begonnen.

Wer gar kein Decision-Log möchte, kann den Hook in `hooks/hooks.json` deaktivieren.
