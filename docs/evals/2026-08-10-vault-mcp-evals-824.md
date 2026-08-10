# Test-Vault im CI an die Eval-Sitzung binden — Live-Nachweis (#824)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Laufs, nicht der
> aktuelle Stand. Rohdaten liegen daneben in
> [`2026-08-10-vault-mcp-evals-824-live-results.json`](2026-08-10-vault-mcp-evals-824-live-results.json).

[← Doku-Übersicht](../README.md) · [← Evals-Übersicht](README.md)

**Datum:** 2026-08-10
**Rohdaten:** [`2026-08-10-vault-mcp-evals-824-live-results.json`](2026-08-10-vault-mcp-evals-824-live-results.json)
**Reproduktion:** `uv run python scripts/eval/probe_vault_mcp_binding_824.py --out docs/evals/2026-08-10-vault-mcp-evals-824-live-results.json`

## Frage

Akzeptanzkriterium 1 von #824 verlangt einen Beleg **durch einen
tatsächlichen Lauf**, nicht durch Annahme: Lässt sich der
`academic-vault`-MCP-Server an die `claude --print`-Sitzung binden, die
`tests/evals/eval_runner.py` startet — ohne Netz, ohne Zugangsschlüssel,
gegen eine geseedete temporäre Datenbank?

Offen war dabei besonders die Flag-Frage aus dem Planungskommentar: Der
einzige Live-Präzedenzfall im Repo
(`scripts/eval/measure_context_enrichment_710.py`, siehe
[`2026-08-09-context-enrichment-710.md`](2026-08-09-context-enrichment-710.md))
setzt zusätzlich `--permission-mode bypassPermissions` und `--tools ""`. Ob
`--allowedTools mcp__academic-vault__*,Read` allein reicht — insbesondere
für den **Schreibpfad** `vault.add_quote` — war nicht verifiziert.

## Antwort: ja, mit den Profil-Flags allein

Ein Lauf, `claude-sonnet-4-6`, ohne `--permission-mode`, ohne `--tools`:

| Messgröße | Wert |
| --- | --- |
| Flags | `--allowedTools mcp__academic-vault__*,Read --setting-sources "" --mcp-config <tmp>/mcp_config.json --strict-mcp-config`, `cwd = <tmp>` |
| `--permission-mode` | **nicht gesetzt** |
| Exit-Code | 0 (`is_error: false`, `stop_reason: end_turn`) |
| `permission_denials` | `[]` — kein einziges Werkzeug wurde verweigert |
| Turns | 9 |
| Dauer | 103,3 s (Deckel `CLI_TIMEOUT_SECONDS = 300` reicht) |
| Kosten | 0,159 USD (OAuth-Kontingent, kein API-Schlüssel) |
| Quotes vom Agenten geschrieben | **2**, beide `extraction_method: "local-verbatim"` |

Der Beweis hängt bewusst **nicht am Antworttext**, sondern am Zustand der
Wegwerf-Datenbank nach dem Lauf. Ein Quote mit
`extraction_method="local-verbatim"` kann dort nur landen, wenn

1. der Agent `vault.get_paper` erreicht hat (sonst kennt er den `pdf_path`
   der temporären Kopie nicht),
2. er das PDF mit `Read` gelesen hat,
3. `vault.add_quote` durchgelaufen ist — und dessen serverseitige,
   fail-closed Verbatim-Prüfung (pypdf + rapidfuzz gegen den lokalen
   Volltext, Issue #512) den Wortlaut im PDF gefunden hat.

Ein halluzinierter Antworttext kann keinen Datenbankzeilenzustand erzeugen.
Geschriebene Zitate (aus den Rohdaten):

```
"Governance frameworks ensure DevOps compliance across distributed teams."   (Seite 1)
"Audit trails make DevOps governance decisions reviewable after each release." (Seite 1)
```

Der Agent lieferte zusätzlich das erwartete JSON mit gefüllten
`vault_quote_id`-Feldern — genau die Erwartung von `qe-01`
(`$.quotes[0].vault_quote_id`, `non_empty`), die im Lauf vom 2026-08-10
(Run 31369626618) noch daran scheiterte, dass die Sitzung gar keine
Vault-Werkzeuge hatte.

## Konsequenz für die Verdrahtung

- `--permission-mode bypassPermissions` ist **nicht** nötig. Es wird
  bewusst nicht gesetzt: eine fünfte Achse nur für dieses Profil wäre eine
  breitere Freigabe als der Zweck verlangt, und `permission_denials: []`
  belegt, dass die Werkzeugliste ausreicht.
- `--tools ""` ist ebenfalls nicht nötig; `--allowedTools` genügt.
- Damit bleibt `eval_runner.py` unverändert: die vier Achsen aus #830
  (`cwd`, `allowed_tools`, `mcp_config`, `env`) reichen aus. #824 liefert
  nur die Fixture-Seite (`tests/evals/vault_fixture.py`).
- `env=` bleibt `None`. `VAULT_DB_PATH` steht ausschließlich im `env`-Block
  der MCP-Config, den der Serverprozess beim Start erbt — ein
  `subprocess.run(env={...})` hätte `PATH`/`HOME`/`CLAUDE_CODE_OAUTH_TOKEN`
  aus der Sitzung entfernt.

## Rahmenbedingungen des Nachweises

- **Kein Netz-Egress** außer dem Modellaufruf selbst: freigegeben sind nur
  `mcp__academic-vault__*` und `Read`; `WebFetch`/`WebSearch`/`Bash` sind
  nicht in der Werkzeugliste (Guard:
  `tests/evals/test_vault_mcp_binding_824.py::test_mcp_config_has_exactly_one_server_and_no_network_tools`).
- **Kein Zugangsschlüssel**: OAuth-Sitzung der CLI, kein `ANTHROPIC_API_KEY`
  (#632).
- **Kein Zugriff auf die Operator-Vault**: Datenbank, MCP-Config und
  Fixture-PDFs liegen in einem `TemporaryDirectory`, das zugleich das `cwd`
  der Sitzung ist. `VAULT_DB_PATH` hat in `academic_vault/db.py`
  (`default_db_path()`) Vorrang — ohne die Variable läge die DB unter
  `~/.academic-research/…`, also in echten Forschungsdaten.
- **Ein Serverprozess = eine Datenbank**: `academic_vault/server.py` friert
  `_DEFAULT_DB` beim Import ein. Deshalb baut die pytest-Fixture
  `vault_session` je Testfunktion ein eigenes Wegwerf-Verzeichnis.

## Kostenabschätzung für den geplanten Lauf

103 s und 0,16 USD je vault-gebundenem Fall. Betroffen sind im Kern-Set
zehn Fälle (`qe-01`, `qe-02`, `qe-03`, `qe-05` sowie `cw-01`…`cw-05`,
`cw-vault-01`, jeweils in den Modi, für die sie definiert sind) — also grob
15–20 Minuten und rund 1,5 USD zusätzlich gegenüber der werkzeuglosen
Variante. Der Job-Deckel des geplanten Laufs (120 Minuten) trägt das.
`qe-04` bleibt übersprungen (siehe unten).

## `qe-04`: entschieden, nicht vergessen

`qe-04` scheiterte im Lauf 31369626618 **nicht** am Vault, sondern an
fehlenden Web-Werkzeugen. Netz-Egress in Evals wäre nichtdeterministisch
und ist in `STRATEGY.md` bereits als `net-excluded` dokumentiert. Der Fall
bleibt deshalb übersprungen — aber mit maschinell lesbarer Begründung
(`eval-skip:net-excluded …`) und namentlich im Inventar
(`tests/evals/skip_inventory.py`). Ein Guard hält die tatsächliche
Skip-Menge des Laufs dagegen; verschwindet oder erscheint ein Skip, wird
der Lauf rot (`scripts/dev/check_eval_skip_inventory.py`, verdrahtet in
`.github/workflows/eval-behavior.yml`).
