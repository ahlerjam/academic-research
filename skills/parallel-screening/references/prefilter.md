# Mechanischer Vorfilter (#892)

Vor #892 kostete jeder Treffer einen Modellaufruf. Bei 1095 Treffern waren das
110 Agentenläufe für eine Frage, die ein Kriterienabgleich zum großen Teil
entscheidet — der Schritt war nicht langsam, er war unbenutzt. Der Vorfilter
entscheidet vorab, was die Ein-/Ausschlusskriterien **eindeutig** entscheiden,
und legt dem Modell die Grenzfälle vor.

Skript: `skills/parallel-screening/scripts/screening_prefilter.py`.
Er läuft **vor** Schritt 1 des Screening-Ablaufs.

## Der Filterblock

Der Vorfilter erfindet keine Grenzen. Er liest sie aus einem eingezäunten
`screening_filters`-Block in der Section `### Ein-/Ausschlusskriterien` von
`./academic_context.md` (dort geschrieben vom `preregistration`-Skill aus dem
Feld `screening_filters` des Vorhaben-Plans):

````markdown
### Ein-/Ausschlusskriterien

**Einschluss**
- Peer-reviewed Arbeiten ab 2015

**Ausschluss**
- Editorials und Rezensionen

```screening_filters
year_min: 2015
year_max: 2026
languages: [de, en]
publication_types: [journal-article, proceedings-article]
```
````

Die Prosa daneben bleibt die verbindliche Fassung für den Menschen; der Block
ist ihre maschinenlesbare Teilmenge. Alle vier Schlüssel sind optional, jeder
einzeln weglassbar. Ein Block außerhalb dieser Section zählt nicht — die
Kriterien haben genau eine Fundstelle.

| Schlüssel | Regel | Kriteriumsname im Grund |
|-----------|-------|-------------------------|
| `year_min` / `year_max` | Bereich auf `paper["year"]` | `Zeitraum` |
| `languages` | Allowlist auf `paper["language"]` (ISO-639-1) | `Sprache` |
| `publication_types` | Allowlist auf `paper["publication_type"]` | `Publikationstyp` |

Beide Metadaten liefert `scripts/search.py` seit #892 mit: CrossRef und
OpenAlex über `language`/`type`, Semantic Scholar über `publicationTypes[0]`,
arXiv fest als `preprint`. Module ohne diese Felder liefern `None` — und
`None` schließt nie aus.

## Fail-open, in beide Richtungen

1. **Kein Filterblock** → `apply_filters` gibt die Eingabe unverändert zurück,
   Reihenfolge inklusive. Der Lauf verhält sich exakt wie vor #892.
2. **Fehlendes Metadatum am Treffer** → **kein** Ausschluss. Unwissen ist kein
   Ausschlussgrund; der Fall geht ans Modell.

Damit kann der Vorfilter nur an Grenzen ausschließen, die ausdrücklich in den
Kriterien stehen, und nur an Metadaten, die tatsächlich vorliegen. Es gibt kein
Titel-Matching und keine Relevanzabschätzung — die Relevanz bleibt beim Modell.

## Aufruf

```bash
~/.academic-research/venv/bin/python \
  ${CLAUDE_PLUGIN_ROOT}/skills/parallel-screening/scripts/screening_prefilter.py \
  prefilter --session-dir "$SESSION_DIR" \
  --papers "$SESSION_DIR/ranked.json" \
  --context ./academic_context.md \
  --db-path "$VAULT_DB"
```

Oder als Python-API:

```python
from screening_prefilter import load_filters_from_file, prefilter

filters = load_filters_from_file("./academic_context.md")
report = prefilter(papers, filters, session_dir, db_path=db_path)
```

### Ausgaben

| Datei | Inhalt |
|-------|--------|
| `$SESSION_DIR/to_screen.json` | die Restmenge, absteigend nach `prescore` sortiert (Tie-Break `paper_id`) |
| `$SESSION_DIR/prefilter_report.json` | `n_input`, `n_to_screen`, `n_excluded_by_rule`, `batches_before`, `batches_after`, `by_criterion`, `filters_applied`, `excluded` |
| `$SESSION_DIR/screening_ledger.jsonl` | je Ausschluss eine Zeile mit `decided_by: "rule"` |
| `excluded_sources` im Vault | je Ausschluss `screening: <Kriterium>: <Detail>` |

`batches_before` / `batches_after` sind die Zahl der `relevance-scorer`-Läufe
zu zehn Arbeiten vor und nach dem Filter. Sie gehören in den Ergebnis-Digest —
das ist die Zahl, an der sich der Schritt messen lässt.

## Priorisierung

Die Restmenge kommt absteigend nach dem 4D-Vorranking `scoring.prescore()`
(Aktualität, Qualität, Autorität, Zugang; Gewichte auf 1.0 renormiert, ohne
Relevanz). Reicht das Budget nicht für die ganze Menge, ist damit das
Aussichtsreichste zuerst bewertet. Bei Gleichstand entscheidet die `paper_id` —
zwei Läufe liefern dieselbe Reihenfolge.

Active Learning (#602) bleibt davon unberührt: `reorder_pending` sortiert die
Restliste weiterhin nach den bereits gefällten Urteilen um und läuft, wenn
aktiviert, **nach** dem Vorfilter.

## Warum das Protokoll die Zähler trägt

`pending()` überspringt jede ID, die schon eine Ledger-Zeile hat — mechanisch
ausgeschlossene Treffer werden also nie einem Subagent vorgelegt. Genau
dieselbe Zeile trägt sie in `merge()` und damit in `to_prisma_counters()`. Der
PRISMA-Fluss ergibt sich vollständig aus dem Ledger; eine getrennt geführte
Zählung gibt es nicht mehr.

## Abgrenzung zum Doppel-Screening (#598)

Eine `rule`-Zeile liegt in `stage=screening`, `round=1` — nötig, damit
`merge()` und PRISMA sie sehen. Sie ist aber **kein Gutachterurteil**:

- `_double_screening_pairs()` lässt sie aus. Sie bildet also kein Runde-1/2-Paar
  und geht weder in Cohen's Kappa (`compute_agreement`) noch in die
  Dissensfälle (`dissent_cases`) ein. Ein Kriterienabgleich ist kein zweiter
  Gutachter; als solcher gezählt würde er die Übereinstimmungsmessung
  verfälschen.
- `merge_double()` übernimmt sie direkt in `exclude` — entschieden ist sie ja,
  nur eben nicht durch ein Urteil.
- `db_path` ist bei Regel-Zeilen auch mit aktivem Doppel-Screening korrekt: es
  gibt keine zweite Runde und damit keinen Dissens, der einen Vault-Eintrag
  zurücknehmen müsste. Die Sperre in `record_decision` gilt unverändert für
  Modellurteile.

## ID-Ableitung

`excluded_sources.paper_id` ist ein Primärschlüssel ohne Fremdschlüssel —
Session-IDs sind schreibbar, und eine abweichende ID macht das Protokoll
unzuordenbar. Darum gibt es genau eine Ableitung, `derive_paper_id()`:
ausdrückliche `paper_id` > DOI > URL > Titel, jeweils in der Schreibweise aus
`commands/fetch.md` (Nicht-Alphanumerisches außer `._-` durch `_`,
kleingeschrieben, max. 80 Zeichen). Ein Treffer ohne jedes dieser Felder ist
ein `ValueError` — er darf nicht still verschwinden.

## Schalter

Vorrang, absteigend: Argument (`--no-prefilter` bzw.
`resolve_prefilter(explicit=…)`) > `ACADEMIC_RESEARCH_SCREENING_PREFILTER` >
`config/parallel_agents.json` → `screening_prefilter` > Default `true`.

Der Default ist ohne Filterblock wirkungslos — er schaltet nichts ein, was
nicht in den Kriterien steht.

## Nicht in diesem Schritt

- **Sättigung / Abbruchkriterium.** Die Priorisierung sagt, *womit* angefangen
  wird, nicht *wann* aufgehört werden darf. Ab welcher Position keine neuen
  Einschlüsse mehr kamen, weist dieser Schritt nicht aus.
- **Autonomie des Screening-Laufs** → #880.
