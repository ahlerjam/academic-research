# Hooks-Stack

[← Doku-Übersicht](../README.md)

Das Plugin verdrahtet 6 Claude-Code-Events in `hooks/hooks.json`. Maßgeblich ist immer
diese Datei — die Tabelle unten gibt ihren Inhalt wieder und wird von
`tests/test_readme_hook_stack_doc.py` dagegen geprüft.

| Event | Was läuft | Beschreibung |
|-------|-----------|--------------|
| `PreToolUse` (`Write\|Edit\|MultiEdit`) | `verbatim-guard.mjs` | Blockt Kapitel-Writes mit nicht-verifizierten Zitaten |
| `PreToolUse` (`Write\|Edit\|MultiEdit`) | `claim-drift-guard.mjs` | Warnt, wenn eine Überarbeitung die Aussage um ein belegtes Zitat ändert, ohne den Beleg anzupassen |
| `PreToolUse` (`Write\|Edit\|MultiEdit`) | `context-fidelity-guard.mjs` | Markiert Zitate, deren echter Quellkontext der Kapitelverwendung widerspricht (Quote-Mining) |
| `PostToolUse` (`Write\|Edit\|MultiEdit`) | `post-tool-use-decisions.mjs` | Decision-Log: jede `.md`-Änderung wird im Vault protokolliert |
| `PostToolUse` (`Write\|Edit\|MultiEdit`) | `nli-quote-scan.mjs` | NLI-Zitatscan: stößt nach einem Kapitel-Write den Scan aller belegten Zitate an und meldet Fundstellen |
| `PreCompact` | `pre-compact.mjs` | Snapshot-Backup vor Claude-Compaction (State-Dateien + `vault.db`) |
| `UserPromptSubmit` | `mid-session-reinforcement.mjs` | Erinnerung an Anti-Fabrikations-Regeln (nach ~20 Nachrichten) |
| `UserPromptSubmit` | `nli-quote-scan.mjs` | Nachreichen offener Zitatscan-Befunde (nur Abholung, kein neuer Scan) |
| `SessionStart` (kein Matcher) | *(Inline-Bash)* | Prüft, ob `~/.academic-research/venv` existiert und die Kernpakete importierbar sind |
| `SessionStart` (kein Matcher) | `bypass-log-report.mjs` | Meldet neue Nutzungen des `vault-guard`-Bypass-Markers seit der letzten Session |
| `SessionStart` (`matcher: "compact"`) | `mid-session-reinforcement.mjs` | Erinnerung an Anti-Fabrikations-Regeln nach Compaction |
| `Stop` | *(Inline-Bash)* | Hinweis bei ungesicherten `academic_context.md`-Änderungen |
| `Stop` | `session-snapshot.mjs` | Vault-Snapshot pro Sitzung (#625, PR #650) — zusätzlich zum `PreCompact`-Snapshot, unabhängig davon; pro Sitzung maximal einmal exportiert (Drosselung nach session_id) |

Das sind **9 Skript-Dateien** (`verbatim-guard.mjs`, `claim-drift-guard.mjs`,
`context-fidelity-guard.mjs`, `post-tool-use-decisions.mjs`, `nli-quote-scan.mjs`,
`pre-compact.mjs`, `mid-session-reinforcement.mjs`, `bypass-log-report.mjs`,
`session-snapshot.mjs`) plus **2 Inline-Bash-Kommandos**;
`mid-session-reinforcement.mjs` hängt an zwei Event-Konfigurationen
(`UserPromptSubmit` und `SessionStart`/`compact`), `nli-quote-scan.mjs` ebenfalls
(`PostToolUse` und `UserPromptSubmit`), und `PreToolUse` ruft drei Skripte
nacheinander auf.

### Session-Ende-Snapshot (`session-snapshot.mjs`, #625, PR #650)

Läuft zusätzlich zum bestehenden `PreCompact`-Snapshot unter `Stop` — er
ersetzt ihn nicht, sondern deckt die Fälle ab, in denen eine Sitzung nie
verdichtet wird (kurze Sitzungen erzeugten bis #625 über Wochen keinen
einzigen Snapshot). Der `Stop`-Event feuert nach jedem Assistenten-Turn, nicht
nur einmal am Sitzungsende; um Perf-Regression und unnötige Exporte zu
vermeiden, drosselt der Hook pro Sitzung: die `session_id` aus dem Stop-Payload
wird im Marker gespeichert, und pro Sitzung wird maximal einmal exportiert
(Audit P1, PR #650). Nachfolgende Turns in derselben Sitzung überspringen den
Export; eine neue Sitzung triggert einen erneuten Export.

**Fingerprint-Vergleich:** Ein billiger Fingerprint der Vault-DB (Dateigröße +
`mtimeMs`) wird gegen die Marker-Datei
`<ACADEMIC_SNAPSHOTS_DIR>/<slug>/.last-session-snapshot.json` aus dem letzten
Lauf verglichen: unverändert (und gleiche session_id, falls vorhanden) → kein
neuer Snapshot, aber eine Stderr-Zeile mit dem Zeitpunkt der letzten Sicherung;
verändert (oder Marker fehlt/kaputt, oder neue Sitzung) → Export über dieselbe
Python-Funktion wie `pre-compact.mjs` (`academic_vault.server.export_snapshot()`),
aufgerufen über die Interpreter-Kaskade aus `hooks/lib/vault-bridge.mjs` (#382).

**Retention:** je Slug-Verzeichnis werden maximal `ACADEMIC_SNAPSHOTS_KEEP`
(Default **20**, env-überschreibbar) eigene `.tgz`-Dateien aufbewahrt — ältere
werden nach jedem erfolgreichen Export gelöscht (Sortierung über den
`YYYYMMDD-HHMM`-Dateinamen). Das Slug-Verzeichnis wird mit dem
`PreCompact`-Snapshot geteilt; damit das Pruning dessen `.tgz`-Dateien nicht
versehentlich mitzählt oder löscht, kennzeichnet `session-snapshot.mjs` seine
eigenen Exporte mit dem Suffix `.session.tgz` und prunt ausschließlich danach
(Audit-Finding, PR #650 — blindes Pruning aller `.tgz` unabhängig von der
Herkunft konnte fremde, potenziell vault-haltige Snapshots vorzeitig
verdrängen). Die Marker-Datei selbst ist vom Pruning ausgenommen.

`pre-compact.mjs` folgt seit #857 derselben Konvention mit dem Suffix
`.precompact.tgz` und prunt ebenfalls nur die eigenen Dateien (gleiches
`ACADEMIC_SNAPSHOTS_KEEP`). Nötig wurde das, weil der PreCompact-Snapshot seit
demselben Change tatsächlich die vollständige `vault.db` enthält (der Export
war zuvor toter Code): ohne Kennzeichnung wuchs das Snapshot-Verzeichnis bei
jeder Auto-Compaction um eine komplette DB-Kopie, die kein Pruning-Filter je
erfasst hätte. Kollidieren zwei Läufe in derselben Minute, weicht der Hook auf
`<ts>-1.precompact.tgz`, `<ts>-2…` aus, statt den vorhandenen — potenziell
vault-haltigen — Tarball zu kürzen; dasselbe Schema nutzt
`academic_vault.server.export_snapshot()`. `restore_snapshot` löst einen
Zeitstempel entsprechend auf alle gültigen Namensformen auf (`<ts>.tgz`,
`<ts>-<n>.tgz`, `.precompact`/`.session`-gekennzeichnete), sonst wären genau
die vault-haltigen Snapshots über `/history --restore` unerreichbar. Ein
Fehlschlag beim Export (z. B. kein funktionierender
Python-Interpreter erreichbar) bricht die Sitzung nicht ab: `exit 0`, aber
eine sichtbare `⚠️`-Meldung auf stderr, und der Marker bleibt unverändert
stehen, damit der nächste Lauf erneut einen Export versucht.

**Grenzen (bewusst akzeptiert für Umfang size/S):** Der Fingerprint ist kein
Volltext-Hash — ein False-Negative bei einer Änderung exakt gleicher
Dateigröße innerhalb derselben Millisekunde ist theoretisch möglich, aber für
die Größenordnung „Vault über zwei Jahre" vernachlässigbar. Die Pro-Sitzungs-
Drosselung basiert auf der `session_id` des Stop-Payload: Wenn Claude Code
diese nicht mitteilt (oder `null` ist), fällt die Drosselung weg und der Hook
exportiert wie gewohnt nach Fingerprint. Zwei parallele Sitzungen auf
demselben Projekt können sich beim Marker-Update oder Pruning überschneiden
— es gibt kein Locking.

> **Nicht verdrahtet:** `hooks/lib/vault-bridge.mjs` ist **kein** Hook, sondern ein
> gemeinsames Modul, das die Vault-Hooks importieren (DB-Pfad-Auflösung und
> Interpreter-Kaskade). Es liegt bei den übrigen importierten Modulen in
> `hooks/lib/` (#542); flach in `hooks/` liegen ausschließlich die in
> `hooks/hooks.json` registrierten Hooks. Der CI-Syntax-Gate erfasst `hooks/lib/`
> mit: er läuft seit #542 über alle getrackten `*.mjs`
> (`bash scripts/dev/check-mjs-syntax.sh`) statt über den nicht-rekursiven Glob
> `hooks/*.mjs`.

### Geschützter Pfad: welche Dateien geprüft werden (`hooks/lib/protected-path.mjs`, #615)

Alle drei Kapitel-Guards (`verbatim-guard.mjs`, `claim-drift-guard.mjs`,
`context-fidelity-guard.mjs`) teilen sich **eine** Pfadprüfung in
`hooks/lib/protected-path.mjs`: geschützt ist jede `*.tex`-Datei
(ordnerunabhängig, überall im Projekt) und jede `*.md`-Datei unterhalb des
Kapitelverzeichnisses (beliebig tief verschachtelt). Die Prüfung ist
**case-insensitiv** — sowohl für den Ordnernamen als auch für die
Dateiendung. `Kapitel/03.md`, `KAPITEL/03.md` und `kapitel/03.MD` sind alle
geschützt, nicht nur die kleingeschriebene Form. Das schließt die Lücke, die
auf macOS' case-insensitivem Standard-Dateisystem sonst lautlos blieb: die
Datei landete am richtigen Ort, aber ohne Zitatprüfung, wenn der
Kapitelordner `Kapitel/` statt `kapitel/` hieß.

Das Kapitelverzeichnis selbst ist über `ACADEMIC_CHAPTER_DIR` konfigurierbar
(Default weiterhin `"kapitel"`, unverändertes Verhalten ohne die Variable) —
für Projekte, die ihren Ordner `chapters/`, `manuskript/` oder `text/`
nennen. `academic_vault.server.check_retractions()` (Issue #604) honoriert
denselben Override über die gleiche Trim-Semantik (`_chapter_dirname()`) —
sonst schützten Guards und Retraction-Prüfung unterschiedliche Verzeichnisse.

**Sichtbare Meldung statt stillem Durchlass:** Schreibt `Write`/`Edit`/
`MultiEdit` eine `.md`- oder `.tex`-Datei außerhalb der geschützten Menge, gibt
`verbatim-guard.mjs` eine Hinweiszeile auf stderr aus (`[Vault-Guard] Hinweis:
… liegt außerhalb des geschützten Kapitelverzeichnisses …`). Der Write bleibt
erlaubt — es ist kein Block, nur ein Signal, damit ein falsch benannter oder
vergessener Kapitelordner nicht unbemerkt bleibt. Andere Dateitypen (`.py`,
`.json`, …) lösen keine Meldung aus.

**Bash-Schreibvorgänge sind nicht erfasst.** `hooks/hooks.json` registriert
`PreToolUse` für die drei Guards ausschließlich auf `Write|Edit|MultiEdit`
(siehe Tabelle oben) — ein `cat > kapitel/03.md`, `tee`, `sed -i` oder
`python -c "...write..."` über das `Bash`-Tool erreicht keinen der drei
Guards. Das ist eine bewusste Auslassung, keine übersehene Lücke: ein
zuverlässiger Parser für Schreibabsicht in beliebigen Shell-Kommandos
(Quoting, Heredocs, Pipes, `dd`, interpretierte Sprachen) ist praktisch nicht
erreichbar und würde eher falsche Sicherheit vortäuschen als echten Schutz
bieten. Wer Kapiteltexte über Bash statt über `Write`/`Edit`/`MultiEdit`
verändert, bekommt aktuell **keine** Zitat-, Claim-Drift- oder
Kontexttreue-Prüfung.

### Wortlaut-Prüfung wörtlicher Zitate (#846)

Anführungszeichen-Spans (`"…"`, `„…"`, `«…»`, ` ``…'' `) ab zehn Zeichen werden
gegen die Vault-Tabelle `quotes` geprüft. Bis #846 war das ein Boolean
(`verbatim LIKE '%kandidat%'`): jede typografische Abweichung galt als „nicht im
Vault" (Falschalarm), und ein *verändertes* Wort war vom *fehlenden* Zitat nicht
zu unterscheiden. Seit #846 liefert
`academic_vault.server.match_quote_wording()` je Span einen Status:

| Status | Bedeutung | Reaktion |
|---|---|---|
| `exact` | zeichengleich im Vault | still durch |
| `normalized` | gleich bis auf Anführungszeichen/Apostroph, Whitespace, NFKC/Ligaturen, Trennstrich am Zeilenumbruch — oder nur Groß-/Kleinschreibung | still durch (bei reinem Case-Unterschied ein Hinweis auf stderr) |
| `ellipsis` | Auslassungszitat: alle Fragmente zwischen `[…]`/`[...]` kommen in dieser Reihenfolge vor | still durch |
| `deviation` | eindeutig zugeordnet, Wortlaut weicht ab | **Block** mit Fundstelle (`Datei:Zeile:Spalte`), beiden Wortlauten und den abweichenden Wörtern |
| `absent` | kein Vault-Zitat zuordenbar | **Block** mit der bisherigen Meldung „Zitat nicht im Vault verifiziert" |

Die Zuordnung läuft zweistufig: zuerst der billige Substring-Abgleich über die
Normalisierungsstufen aus `academic_vault/verbatim.py`, dann — erst ab **40
normalisierten Zeichen** — eine rapidfuzz-Zuordnung (`partial_ratio`, Schwelle
82) über einen **einmal je Write** gelesenen Quotes-Snapshot
(`VaultDB.quotes_snapshot_for_wording()`, Längenband-Vorfilter + Limit 5000).
Die Mindestlänge ist Absicht: kurze Fragmente erzielen in langem Text zufällig
hohe Ähnlichkeitswerte (#520). Liegen die zwei besten Treffer näher als zwei
Punkte beieinander und unterscheiden sich ihre Wortlaute, gilt der Span als
`absent` — ein Wortlaut-Vorwurf gegen das falsche Vault-Zitat wäre schlimmer als
der unspezifische Bestandsbefund.

**Prüfkontingent:** Es gilt dieselbe Obergrenze wie für die Klammer-Belege
(`ACADEMIC_CITATION_MAX_PER_WRITE`, Default 100). Überzählige Spans verlieren
nur die teure Zuordnung, nicht die Prüfung: sie bleiben im Zweifel `absent` und
blockieren weiterhin, die Meldung nennt die Kappung. Ein stiller Durchlass wäre
ein Loch im Guard.

**Strenge-Schalter:** `ACADEMIC_VERBATIM_WORDING=report` meldet eine
Wortlaut-Abweichung nur auf stderr, statt zu blockieren (Default `block`). Der
Schalter ist guard-schwächend und wird deshalb wie die vier
`ACADEMIC_CITATION_*`-Schalter protokolliert (siehe Env-Switch-Report unten).

**Fail-open bleibt unverändert:** fehlende Vault-DB, kaputter Interpreter,
Exception im Lookup → kein Block, mit den beiden getrennten Wortlauten aus #381.
`search_quote_text()` ist unangetastet — `claim-drift-guard.mjs`,
`context-fidelity-guard.mjs` und das MCP-Tool `vault.search_quote_text` hängen an
seiner Boolean-Semantik.

### Klammer-Zitat-Validierung

Klammer- und Paraphrase-Belege wie `(Müller 2021, S. 45)`,
`(Müller/Schmidt 2019)`, `(Müller u. a. 2021, S. 45–47)`, `(vgl. Müller 2021: 45)`,
`vgl. Schmidt 2019` — seit Issue #740 auch die **narrative Form außerhalb von
Klammern**, bei der nur die Jahreszahl geklammert ist: `Müller (2021, S. 45)
zeigt …`, `Müller und Schmidt (2019) belegen …`, `Müller et al. (2021)
belegen …`, `Wie Müller (2021, S. 45) zeigt …`, `Müller (2021, S. 45)
schreibt: „…"` — werden extrahiert und gegen den Vault geprüft:
Familienname und Jahr gegen `papers.csl_json` (Umlaut-Faltung und
Diakritika-Strip, `Müller`/`Mueller`/`Muller` treffen denselben Eintrag), die
Seitenzahl gegen `papers.page_first`/`page_last` bzw. `quotes.printed_page`.
Führende **Namenspartikel** werden dabei zusätzlich weggefaltet: im Text steht
`(von Neumann 1945)`, CSL-JSON führt das Partikel dagegen separat in
`non-dropping-particle` und `family` bleibt `Neumann` — ohne diese Variante
blockte der Guard Belege, deren Paper längst im Vault liegt.
Die beiden Seitenquellen wiegen unterschiedlich, seit Issue #724 aber nicht
mehr so, dass eine der beiden nie widerlegen könnte: der vollständige
Seitenumfang aus `page_first`/`page_last` ist immer autoritativ. Liegt er
NICHT vor, wird `quotes.printed_page` — die punktuelle Stichprobe der bereits
extrahierten Stellen — selbst zum widerlegenden Signal: deckt keine bekannte
Stichprobe die Beleg-Seite (bzw. bei einem Seitenbereich keine davon eine
Seite im Bereich), gilt die Seite als `page-mismatch`. Nur wenn zum Paper
**gar keine** Seitendaten hinterlegt sind (weder Umfang noch Stichprobe),
bleibt der dokumentierte Soft-Pass (`unknown`). Ein Seitenbereich im Beleg
(`S. 45–47`) gilt als gedeckt, sobald irgendeine bekannte Seite darin liegt —
`page_offset` (`vault.set_page_offset`) wirkt bereits auf `printed_page`
selbst, verglichen wird also stets die gedruckte, nie die PDF-Seite.

**Nicht geprüft** (bewusst, gegen False Positives): Code-Fences und
Inline-Code, LaTeX-Makros (`\cite{…}`, `\ref{…}`), nackte Jahresklammern
(`(2021)`), Struktur-Verweise (`(siehe Kapitel 2)`, `(vgl. Abb. 3)`),
Datums- und Standangaben (`(Januar 2021)`, `(März 2020)`, `(Stand 2021)`,
`(Fassung 2019)`), `ebd.`/`a.a.O.` sowie alles ab der Überschrift des
Literaturverzeichnisses.

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

**Die narrative Form ohne Seitenangabe** (`Müller (2021) belegt …`,
`Müller et al. (2021) belegen …`) ist von reiner Prosa mit Jahresklammer wie
`Die DSGVO (2016) trat in Kraft` oder `Deutschland und Frankreich (2016)
unterzeichneten das Abkommen` lexikalisch nicht zu trennen — das gilt AUCH
dann, wenn ein Co-Autoren-Muster wie „und Frankreich" matcht, denn dieselbe
Struktur trifft auf gewöhnliche Aufzählungen zu. Ohne Seite zählt die Form
deshalb ausnahmslos nur, wenn direkt hinter der Klammer eines von einer
festen Liste einwortiger Berichtsverben steht (`REPORTING_VERBS` in
`citation-parse.mjs`: `zeigt`, `belegt`, `schreibt`, `argumentiert`, `betont`,
`konstatiert`, `erklärt`, `folgert`, `meint`, `kritisiert`, `resümiert`,
`sieht`, `beschreibt`, `analysiert`, `untersucht`, `formuliert` — jeweils
inkl. Pluralform) — sonst bleibt sie unerkannt und damit auch ungeprüft,
exakt wie eine nackte Jahresklammer. Mehrwortige Wendungen wie „stellt fest"
oder „weist hin" erkennt der Detektor bewusst nicht (nur ein Wort nach der
Klammer wird geprüft). Ein vorangestelltes `vgl.`/`siehe` allein ersetzt das
Berichtsverb nicht (`NARRATIVE_CITATION`, Pass 2a, verlangt das Jahr direkt
nach dem Signalwort, ohne Klammer). Eine feste Liste gängiger
Rechts-/Institutionsbegriffe (`Gesetz`, `Verordnung`, `Bericht`, `Studie` u. a.
in `NON_AUTHOR_TOKENS`) schließt zusätzlich die häufigsten Substantive aus,
die zufällig auf ein Berichtsverb treffen — nicht erschöpfend, dieselbe
Grenze wie bei den übrigen Ausschlusslisten.

**Sekundärbelege** (`(Schmidt, 2015, zitiert nach Müller, 2021, S. 45)`)
werden als **zwei** Belege erfasst: das nicht gelesene Original (`Schmidt
2015`) und das tatsächlich vorliegende Werk (`Müller 2021, S. 45`, intern mit
`viaSecondary: true` markiert). Beide werden unabhängig voneinander gegen den
Vault geprüft.

Ebenfalls **nicht** erfasst — bewusst, weil der Regex sonst zu viele
Falschtreffer produziert: Körperschaftsautoren (`(Statistisches Bundesamt
2021)`). Ein Signalwort, das über eine nicht geprüfte Region hinweg auf einen
Namen zeigt (`vgl. (Müller 2021, S. 45) Schmidt 2019`, `vgl. \cite{…} Schmidt
2019`), zählt ebenfalls nicht: der Beleg hinter der Klammer bzw. dem Makro
steht dort nicht als Ziel des Signalworts, und die Klammer selbst hat der
Klammer-Pass bereits erfasst. False Positives blockieren den Schreibfluss und sind hier
teurer als False Negatives — der Guard ist die letzte, nicht die einzige
Verteidigungslinie.

**Externe Kaskade (Fallback).** Findet der Vault den Beleg nicht, laufen drei
Stufen mit Frühausstieg: arXiv (eine gebatchte Anfrage für alle offenen
Belege) → CrossRef → Semantic Scholar (Fuzzy, Gate: Autoren-Überlapp
≥ 0,6). Score-Modell pro Kandidat (0–100):

| Komponente | Punkte |
|---|---|
| Familienname trifft | 40 |
| Jahr exakt | 30 |
| Jahr um genau 1 daneben | 15 |
| Autoren-Überlapp (Jaccard), nur jenseits des bereits über `familyHit` gematchten Namens | 0–30 |

Issue #740 (AC5): Familienname + Jahr **allein** erreichen ohne echte
Zusatz-Evidenz höchstens 70 Punkte — das liegt im `probable`-Band
(`[UNVERIFIED]`), nicht mehr in `confirmed` (Default 80). Vorher genügten
40+40=80 Punkte, sobald irgendein Paper mit passendem Nachnamen und Jahr
gefunden wurde, unabhängig davon, ob es das zitierte Werk war. Die
Überlapp-Komponente zählt deshalb **nicht** den Autor, der bereits
`familyHit` ausgelöst hat — sonst bestätigt sich ein Einzelautoren-Beleg wie
`(Müller, 2021)` über den Überlapp-Umweg selbst (Jaccard 1.0 gegen sich
selbst). Erst ein wirklich gelesener Co-Autor liefert hier Punkte.

**Entscheidungsmatrix.**

| Ergebnis | Bedingung | Reaktion |
|---|---|---|
| `confirmed` | Vault-Treffer **oder** Score ≥ `ACADEMIC_CITATION_CONFIRMED_MIN` (80) | allow |
| `probable` | Score ≥ `ACADEMIC_CITATION_PROBABLE_MIN` (65) | allow + `[UNVERIFIED]` |
| `unavailable` | Timeout / `ECONNREFUSED` / abgebrochener Body / **jeder** Nicht-2xx-Status (5xx, 429, aber auch 403-Drosselung und 404) / HTTP 200 mit unlesbarem Body | allow + `[UNVERIFIED]` |
| `no-match`, eindeutige Form | alle Stufen haben sauber geantwortet (2xx + parsbarer Body im erwarteten Format), kein Treffer; Beleg trägt Seite, Signalwort, echten Co-Autor oder ist im Dokument korroboriert | **Block** (exit 2) |
| `no-match`, nackte Form | dasselbe, aber `(Wort Jahr)` ohne Korroboration | **Block** (exit 2) — mit `ACADEMIC_CITATION_AMBIGUOUS=mark`: allow + `[UNVERIFIED]` |
| `page-mismatch` | Autor/Jahr im Vault, Seite außerhalb des vollständigen Seitenumfangs bzw. — mangels Umfang — außerhalb aller bekannten `printed_page`-Stichproben | **Block** (exit 2) |
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
| `ACADEMIC_CITATION_UNAVAILABLE_RATE_THRESHOLD` | `0.5` | Anteil `unavailable`/Gesamtanfragen, ab dem eine Warnung ausgegeben wird (Issue #601) |
| `ACADEMIC_CITATION_UNAVAILABLE_RATE_MIN_REQUESTS` | `5` | Mindestzahl Kaskaden-Anfragen im Lauf, unterhalb derer keine Warnung ausgelöst wird (Issue #601) |
| `ACADEMIC_CITATION_UNCHECKED_NOTICE` | `on` | `off` unterdrückt den Ungeprüft-Hinweis (siehe unten, Issue #740) |

**Ungeprüfte Belegformen (Hinweis, kein Block).** `detectUncheckedCitationForms()`
(`hooks/lib/citation-parse.mjs`) erkennt — grob, ohne Vault-Prüfung — drei
Formen, die oben **nicht** geprüft werden: LaTeX-Fußnoten mit Autor/Jahr-Payload
(`\footnote{Vgl. Müller 2021, S. 45.}`), Markdown-Fußnotenmarker/-Definitionen
(`[^1]`, `[^1]: Vgl. Müller 2021.`) und numerische Klammerverweise im
IEEE-Stil (`[12]`). Wer in einer dieser Formen zitiert, bekam bisher **keine**
Rückmeldung und hielt den Schutz für aktiv, obwohl er für diese Form nie
gegriffen hat. `verbatim-guard.mjs` meldet daher — unabhängig davon, ob
`extractCitations()` überhaupt etwas findet — höchstens einmal je Write auf
stderr, dass ungeprüfte Formen im Content stehen; der Write bleibt erlaubt
(exit 0), es ist kein Block. Abschaltbar über
`ACADEMIC_CITATION_UNCHECKED_NOTICE=off`.

**Beobachtung: dauerhaft blockierter Egress.** Eine einzelne `unavailable`-
Antwort ist Betriebsrauschen (Drosselung, kurzer Ausfall). Läuft der Egress
über einen ganzen Lauf dauerhaft ins Leere — falsch gesetzter Proxy,
abgelaufener API-Key, verlegter Endpunkt —, meldet jede Einzelanfrage brav
`unavailable` und niemand zieht die Summe. `resolveCitations()` zählt daher
je Lauf Gesamtanfragen und `unavailable`-Fälle; überschreitet der Anteil
`ACADEMIC_CITATION_UNAVAILABLE_RATE_THRESHOLD` bei mindestens
`ACADEMIC_CITATION_UNAVAILABLE_RATE_MIN_REQUESTS` Anfragen, schreibt der Hook
eine Warnung auf stderr mit beiden Zahlen, dem Prozentsatz und dem häufigsten
Grund (Statuscode oder Fehlerart). Die Bewertung einzelner HTTP-Antworten
(jeder Nicht-2xx bleibt `unavailable`) ändert sich dadurch nicht — es wird
nur mitgezählt, nicht umklassifiziert.

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

### Kontexttreue-Markierung (`context-fidelity-guard.mjs`, #522)

Der `verbatim-guard` prüft, **ob** ein Zitat im Vault steht, der `claim-drift-guard`
prüft die **Kapitel**-Umgebung eines Zitats. Beide sehen nicht, ob der **Quellkontext**
die Verwendung noch trägt: Das Original schränkt unmittelbar nach dem zitierten Satz
ein („Allerdings gilt das nur für …"), das Kapitel übernimmt nur den ersten Teil. Genau
dieses Quote-Mining-Muster macht der `context-fidelity-guard` sichtbar.

Er **blockiert nie** (Exit 0, `systemMessage` + `hookSpecificOutput.additionalContext`,
kein `permissionDecision`) — die Signale sind lexikalisch bzw. probabilistisch und
werden bewusst nicht zur harten Linie gemacht. Die harte Linie bleibt der
deterministische `verbatim-guard`.

**Prüfbar** ist ein Zitat nur mit `quotes.context_source = 'fulltext'` (#520). Ein
nichtleeres `context_before`/`context_after` genügt nicht: der No-Op-Pfad von
`resolve_quote_context` lässt modellgenerierte Kontextfelder stehen. Der Hook meldet
deshalb bei jedem Kapitel-Write mit Zitaten eine Abdeckungszeile
(`[KONTEXT-PRÜFEN] Abdeckung: x von y Zitaten prüfbar`) und begründet jedes nicht
prüfbare Zitat namentlich — kein Eintrag im Vault, kein aufgelöster Quellkontext oder
Vault nicht erreichbar. Stilles Überspringen wäre ein lautloses Loch.

Drei Signale im `PreToolUse`-Pfad (lexikalisch), alle bewusst konservativ:

| # | Signal | Quelle | Auslöser |
|---|--------|--------|----------|
| 1 | Kontrastmarker am **Anfang** von `context_after` | Vault | `however`, `nevertheless`, `allerdings`, `jedoch`, `dennoch`, … im ersten Satz (max. 80 Zeichen) |
| 2 | Rahmen-Marker am **Ende** von `context_before` | Vault | `critics argue`, `kritiker behaupten`, `vielfach wird behauptet`, … — das Zitat referiert im Original eine fremde Position |
| 3 | Hedge-Verlust Quelle → Kapitel | Vault + Kapitel | Relativierung in der Quelle (`deutet darauf hin`, `könnte`, `suggests`, …), **keine** Relativierung im Kapitelfenster **und** ein Absolutheitsmarker dort (`beweist`, `durchweg`, `ausnahmslos`, …) |
| 4 | Semantische Distanz | **[Nicht aktiv im PreToolUse-Pfad]** ~~`quote_embeddings` (#521)~~ | ~~`cos(embed_query(Kapitelfenster), gespeichertes Quote-Embedding) < CONTEXT_FIDELITY_SIM_MIN`~~ — Signal 4 deaktiviert um Embedding-Modell-Loads und torch-Importe im Vault-Lookup zu vermeiden (#522) |

**Unterdrückung (kein False Positive bei bewusst kontrastiver Zitation):** Trägt das
Kapitelfenster um das Zitat selbst ein Kontrast-/Relativierungssignal, ist die
Kontrastivität offengelegt — Signal 1 und 2 sind dann gegenstandslos. Signal 3 bleibt
aktiv: ein offengelegter Kontrast heilt nicht einen Hedge-Verlust. (Signal 4 ist im
PreToolUse-Pfad nicht aktiv, siehe Tabelle.)

> **Schwelle 0.35 ist nicht aktiv.** Signal 4 (semantische Distanz via Kosinus-Ähnlichkeit)
> läuft nicht im `PreToolUse`-Pfad (#522); `CONTEXT_FIDELITY_SIM_MIN` ist wirkungslos.
> e5-Ähnlichkeiten liegen eng beieinander; der Wert wäre eine begründete, defensiv niedrige
> Vermutung gewesen. Die Variable bleibt konfigurierbar für zukünftige Nutzung.

Der Lookup läuft — wie beim `claim-drift-guard` — in **einem** Python-Subprozess für
alle Kandidaten über `hooks/lib/vault-bridge.mjs`. Der Subprozess wird auf
`HF_HUB_OFFLINE=1` gezwungen, um Modell-Downloads im `PreToolUse`-Pfad zu vermeiden (#522).
Die semantische Distanz (Signal 4) wird im Lookup nicht berechnet, um torch/sentence-transformers-
Importe und Modellgewichts-Loads zu sparen.

Konfiguration: `CONTEXT_FIDELITY_WINDOW` (Kapitelfenster, Default 300),
`CONTEXT_FIDELITY_MAX_QUOTES` (Kontingent je Write, Default 20),
`CONTEXT_FIDELITY_SIM_MIN` (Default 0.35, **nicht aktiv im PreToolUse-Pfad**),
`CONTEXT_FIDELITY_DEBUG=1`. Der Bypass-Marker `<!-- vault-guard: skip -->` schaltet auch
diesen Hook stumm; die Nutzung wird wie beim `verbatim-guard` protokolliert, mit dem
eigenen Label `context-fidelity-guard: skip`.

> **Bypass-Report-Dedupe (#517/#522):** Zwei Guards am selben `PreToolUse`-Event loggen
> denselben Bypass. `bypass-log-report.mjs` faltet deshalb Zeilen mit gleichem Pfad
> innerhalb derselben Sekunde zu **einer** Nutzung zusammen — sonst meldete der Report
> „2 neue Nutzung(en)" für einen einzigen Write.

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
`hooks/lib/vault-bridge.mjs`. Ein Wechsel auf `node:sqlite` wurde geprüft (#600, CI läuft
seit dort auf Node 22): ein Mikrobenchmark bestätigt zwar den erwarteten Geschwindigkeits­
vorteil des reinen Zugriffswegs (Median über 20 Wiederholungen: Python-Subprozess ~22,7 ms
gegen `node:sqlite` in-process ~0,9 ms), aber die drei Aufrufer rufen keine rohen SELECTs
auf, sondern Geschäftslogik, die ausschließlich in `academic_vault` (Python) existiert —
eine Migration müsste diese Logik in JavaScript duplizieren statt nur den Treiber zu
tauschen. Details und Zahlen: Modulkopf von `vault-bridge.mjs`. Hooks
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

### NLI-Zitatscan (`nli-quote-scan.mjs`, #717)

Nach jedem Kapitel-Write werden **alle im Vault belegten Zitate des Kapitels**
gegen ihre Quelle geprüft: trägt der Quellkontext die Behauptung, die das
Kapitel an dieser Stelle aufstellt? Bewertet wird lokal mit
`MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` (MIT-Lizenz, kein
API-Key, kein Netz nach dem ersten Download).

Damit schließt sich die Lücke, die die drei `PreToolUse`-Guards offen lassen:
`verbatim-guard` prüft, ob ein Zitat *existiert*, `claim-drift-guard` und
`context-fidelity-guard` reagieren auf *Änderungen*. Ein Zitat, das von Anfang
an falsch verwendet und danach nie wieder angerührt wurde, fiel durch alle drei
Raster.

**Detektor, kein Filter.** Der Scan entfernt **kein** Zitat aus dem
Prüfpfad. Als „treu" eingestufte Zitate werden lediglich nicht gemeldet — sie
bleiben für jede spätere Prüfung (`quote-fidelity-auditor`) vollständig
verfügbar. Ein Fehlurteil des Modells kostet damit höchstens eine ausgebliebene
Meldung und stellt nie den Zustand her, in dem ein verzerrtes Zitat als
„geprüft" gilt. Genau deshalb ist der Scan **per Default an**: Im früheren
Filter-Modus (#592) hätte ein Fehlurteil ein Zitat dauerhaft aus der Prüfung
genommen, was den Default-aus rechtfertigte.

**Zweiphasig, damit der Write nicht wartet.** Der Hook lädt selbst nie ein
Modell:

1. **Anstoß** (`PostToolUse`, nur Kapitelpfade): startet den Python-Worker
   `academic_vault.nli_scan_worker` **abgekoppelt** (`detached` + `unref`) und
   kehrt sofort zurück. Der Write wird weder verzögert noch blockiert; der Hook
   setzt bewusst kein `permissionDecision`.
2. **Abholung** (jeder Aufruf): liest das Spool-Verzeichnis des Workers leer und
   meldet die Fundstellen als `systemMessage` + `additionalContext`.

Weil die Abholung erst beim *nächsten* Hook-Aufruf greift, ist derselbe Hook
zusätzlich unter `UserPromptSubmit` verdrahtet — dort ausschließlich als
Abholung. Ohne diese zweite Stelle bliebe ein Befund des letzten Kapitel-Writes
einer Sitzung bis zum nächsten Write liegen.

**Was eine Meldung enthält** (nachvollziehbar ohne Nachschlagen im Vault): das
wörtliche Zitat, den Kurzbeleg (`Nachname (Jahr): Titel` plus `paper_id` und
`quote_id`), den betroffenen Kapitelsatz und den Entailment-Score. Pro Meldung
werden höchstens 10 Fundstellen ausgeschrieben, der Rest gezählt.

**Spool:** `~/.academic-research/nli-scan-spool/` (Verzeichnis `0700`, Dateien
`0600`, Override `ACADEMIC_NLI_SCAN_SPOOL`) — eine JSON-Datei je Kapitelpfad,
der letzte Lauf überschreibt den vorherigen. Geschrieben wird nur, wenn es etwas
zu melden gibt: ein Kapitel ohne Auffälligkeiten hinterlässt keine Datei.

**Fehlerfall (fehlendes oder kaputtes Modell):** Der Worker schreibt einen
`error`-Datensatz statt zu crashen, der Hook meldet ihn **einmal** (Dedup über
den Fehler-Hash in `<spool>/.reported-errors.json`) und die Sitzung läuft
normal weiter. Kein Retry-Sturm, kein Traceback, kein Block.

**Gemessene Laufzeit** (Apple M-Serie, CPU, warmer Modell-Cache):
**50 Zitate in 6,3 s** bei 0,127 s je Zitat, zuzüglich 1,6 s einmaligem
Modell-Laden je Worker-Start. Beim allerersten Lauf kommt der Download der Modellgewichte
(~1,1 GB nach `~/.academic-research/models`, Override
`NLI_PREFILTER_MODEL_CACHE`) hinzu — er läuft im abgekoppelten Worker und
berührt die Sitzung nicht.

**Schalter** (Vorrang: Env > Configdatei > Default **an**):

| Weg | Wirkung |
|-----|---------|
| `ACADEMIC_RESEARCH_NLI_PREFILTER=0` | Hook tut nichts — weder Anstoß noch Abholung |
| `"nli_prefilter_enabled": false` in `config/parallel_agents.json` | dasselbe, dauerhaft für das Projekt |
| `<!-- vault-guard: skip -->` im geschriebenen Inhalt | nur dieser eine Write wird nicht gescannt (identisch zu den drei Kapitel-Guards) |

**Grenzen (bewusst akzeptiert):**

- Ein Befund erscheint frühestens beim nächsten Hook-Aufruf (nächster Write oder
  nächster Prompt) — der Scan läuft asynchron, das ist der Preis dafür, dass der
  Write nicht wartet.
- Der Hook startet den Worker nur, wenn eine Vault-DB existiert. Er legt selbst
  keine an.
- Erkannt werden Zitate in typografischen Anführungszeichen (`"…"`, `„…"`,
  `«…»`) ab 20 Zeichen, die per Volltextsuche im Vault wiederzufinden sind. Ein
  paraphrasierter Beleg ohne wörtliche Spanne ist für diesen Scan unsichtbar.
- `verzerrend` ist ein **Verdacht, kein Urteil**. Die Eval (#524, #720) misst
  auf konstruierten Fällen Precision 1.00 / Recall 0.812 bei einer
  Rule-of-Three-Obergrenze von ~10 % für unentdeckte Fehlerraten — die
  abschließende inhaltliche Prüfung bleibt beim `quote-fidelity-auditor`.

**Kalibrierung: Zuschreibungssätze, Satzzuordnung, Sprachenpaar (#899).** Ein
Kapitelsatz der Form „X berichtet, dass ‚…'" ist eine Zuschreibung, keine
logische Folgerung — NLI misst aber genau Satzfolgerung. Enthält der
Kapitelsatz das Zitat selbst (praktisch immer der Fall, weil der Kapitelsatz
der Satz UM die gefundene Zitat-Spanne ist), gilt er nur dann als
verdächtig, wenn er einen lexikalischen Widerspruchs-/Negationsmarker trägt
(kuratierte Liste, Deutsch und Englisch, `NEGATION_MARKERS` in
`nli_prefilter.py`) — sonst wird die NLI-Prüfung für dieses Item ohne
Scorer-Aufruf übersprungen. Die Satzzuordnung (`claim_sentence_for_span`)
liefert nur noch den Satz, der die **gesamte** Zitat-Spanne umschließt, und
behandelt Markdown-Strukturzeilen (Überschriften, Listenpunkte, Leerzeilen)
als harte Blockgrenzen; findet sich keine eindeutig umschließende
Satzgrenze, liefert die Funktion `None` statt eines Zeichenfenster-
Rateversuchs — das betroffene Item bleibt im Prüfpfad, wird aber nicht per
NLI bewertet. Gemessen am lokalen Referenzkapitel (12.08.2026): 20 von 21
Zitaten vorher als verdächtig gemeldet, 0 von 21 danach (echter
`BgeM3ZeroshotScorer`). Die Schwelle `DEFAULT_THRESHOLD = 0.95` bleibt
unverändert — die gemessenen Fehlalarme gingen auf die
Attributions-/Satzzuordnungslogik zurück, nicht auf eine für das Sprachenpaar
(deutscher Kapitelsatz, meist englischer Quellkontext) falsch kalibrierte
Schwelle; eine gezielte Schwellenmessung am Sprachenpaar war mangels
negationsmarkierter Fälle im lokalen Referenzkapitel nicht möglich (siehe
Issue-#899-Kommentar).

**Regression-Harness:** `bash scripts/dev/test-nli-quote-scan-hook.sh` (fährt
den Hook als echten Prozess mit Stub-Interpreter; CI-blockierend, analog
`test-pretooluse-blocker.sh`).

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
  `hooks/lib/vault-bridge.mjs` auf, damit sie nicht erneut auseinanderlaufen können.

### Bypass-Report: sichtbare Bypass-Nutzung (`bypass-log-report.mjs`, #517)

Der Bypass-Marker `<!-- vault-guard: skip -->` schaltet `verbatim-guard.mjs` für
eine Datei ab — legitim für Ausnahmefälle, aber jede Nutzung landet seit #381 in
`~/.academic-research/vault-guard-bypass.log` (Env-Override
`VAULT_GUARD_BYPASS_LOG`). Bis #517 las nichts dieses Log; Umgehungen blieben
dauerhaft unsichtbar. `bypass-log-report.mjs` schließt die Lücke als rein
**lesender** SessionStart-Hook (kein Matcher, läuft also bei jedem Start):

- Liest das Bypass-Log ab einem persistierten Byte-Offset und meldet neue
  Zeilen seit dem letzten SessionStart mit Zähler und den betroffenen Dateien
  (dedupliziert, gedeckelt auf 5) auf stdout.
- Der Offset liegt in `~/.academic-research/vault-guard-bypass-report-state.json`
  (Env-Override `VAULT_GUARD_BYPASS_REPORT_STATE`, 0600/0700 wie
  `reinforcement-state.json`) — Merkposten „zuletzt gemeldet“, keine Kopie des
  Logs.
- **Kein Rauschen ohne neue Einträge:** Wurde der Bypass seit dem letzten
  Report nicht erneut genutzt, gibt der Hook nichts aus.
- **Fail-open in jede Richtung** (blockiert den SessionStart nie): fehlt das
  Log (Normalfall ohne je genutzten Bypass), gibt es keinen Report und kein
  stderr-Rauschen; ist die Logdatei kürzer als der gespeicherte Offset
  (externe Rotation/Löschung), wird der Offset auf 0 zurückgesetzt statt eine
  Exception zu werfen; eine korrupte State-Datei führt zu einer
  stderr-Warnung und behandelt den Lauf wie ohne State.
- Ändert nichts an der Schreibseite: Blockieren des Bypass bleibt weiterhin
  möglich und unverändert Aufgabe von `verbatim-guard.mjs`.

### Env-Switch-Report: guard-schwächende Schalter sichtbar (#519, Audit R7)

Mehrere Env-Schalter schwächen `verbatim-guard.mjs` gezielt ab, ohne ihn
abzuschalten: `ACADEMIC_CITATION_AMBIGUOUS=mark` (mehrdeutige Klammerform wird
markiert statt blockiert), `ACADEMIC_CITATION_CASCADE=off` (externe Kaskade
deaktiviert), `ACADEMIC_CITATION_MAX_PER_WRITE` (Prüfkontingent pro Write),
`ACADEMIC_CITATION_UNCHECKED_NOTICE=off` (Hinweis auf ungeprüfte Belegformen
aus, #740) und `ACADEMIC_VERBATIM_WORDING=report` (Wortlaut-Abweichung wird
gemeldet statt blockiert, #846). Legitime Konfiguration — aber ihre Nutzung
blieb bislang unbemerkt. Bei einem Guard-Lauf auf einer geschützten Datei
protokolliert `verbatim-guard.mjs` jetzt für **jeden gesetzten** (nicht-leeren)
dieser Schalter je eine Zeile nach
`~/.academic-research/vault-guard-env-switch.log` (Env-Override
`VAULT_GUARD_ENV_SWITCH_LOG`, 0600/0700, fail-open — identisches Muster wie das
Bypass-Log aus #381).

**Dedupliziert über die Schalter-Kombination:** Anders als der Bypass-Marker
ist ein Env-Schalter eine dauerhaft gesetzte Konfiguration. Geschrieben wird
deshalb nur, wenn sich die Kombination aus gesetzten Schaltern, Werten und
Zieldatei vom zuletzt protokollierten Block unterscheidet — sonst hinge an
jedem geschützten Write derselbe Block erneut, und der SessionStart-Report
meldete dutzende „neue Nutzungen" für eine einzige Einstellung. Verglichen
wird der ganze Block, nicht die einzelne Zeile: Bei mehreren gesetzten
Schaltern stammt die jeweils letzte Zeile von einem anderen Schalter. „Gesetzt" bedeutet: der Schalter steht in der Umgebung,
unabhängig davon, ob er im konkreten Content-Check überhaupt greift — sichtbar
gemacht wird die Nutzung, nicht ihre Wirkung.

`bypass-log-report.mjs` liest zusätzlich dieses Log (eigener
Offset-Merkposten `~/.academic-research/vault-guard-env-switch-report-state.json`,
Env-Override `VAULT_GUARD_ENV_SWITCH_REPORT_STATE`) und hängt bei neuen
Einträgen einen zweiten Report-Abschnitt mit Schalter-Name, Wert und
betroffener Datei an — kein neuer Hooks.json-Eintrag, weiterhin **6
Skript-Dateien**. Gleiches Fail-open- und Kein-Rauschen-Verhalten wie beim
Bypass-Abschnitt.

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
