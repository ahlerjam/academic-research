---
name: parallel-screening
description: >
  Verwende diesen Skill, wenn gleichförmige Prüfungen über viele Quellen
  laufen sollen: Titel-/Abstract-Screening einer Trefferliste oder eine
  Verzerrungsbewertung über mehrere Studien. Trigger-Phrasen: "viele Treffer
  screenen", "Screening parallelisieren", "Ein- und Ausschluss für alle
  Treffer entscheiden", "Verzerrungsbewertung für viele Studien /
  Verzerrungsbewertung fuer viele Studien", "Risk-of-Bias für mehrere Paper",
  "Screening nach Abbruch fortsetzen", "Doppel-Screening",
  "Active Learning". Fächert die Fälle
  auf Subagents auf (`screening-judge` bzw. `risk-of-bias`), führt die
  Einzelurteile zusammen, schreibt Ausschlüsse nach `excluded_sources` und
  legt uneindeutige Fälle gesammelt zur menschlichen Entscheidung vor. Für
  das Rendern des Flussdiagramms → `prisma-flow`. Für die inhaltliche
  Relevanzsortierung einer Trefferliste → `relevance-scorer`-Agent.
license: MIT
allowed-tools: [Bash, Read, Task, Write]
---

# Paralleles Screening

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Übersicht

Screening und Verzerrungsbewertung sind mechanisch und gleichförmig: dieselbe
Prüfung, auf dreißig Treffer angewendet. Dieser Skill schickt sie wellenweise
an Subagents und führt Buch darüber, wer was entschieden hat.

Die Nebenläufigkeit kommt vom Harness (mehrere `Task`-Aufrufe je Nachricht);
das Limit ist **organisatorisch**, kein technischer Semaphor.

## Abgrenzung

Deckt die parallelisierbaren Prüfschritte ab. Das PRISMA-Flussdiagramm rendert
`prisma-flow` aus den hier erzeugten Zählern. Merkmalsextraktion über mehrere
Quellen ist **nicht** Teil dieses Skills. Fetcher-Agents (`book-fetcher` u.
Verwandte) haben ein eigenes Fan-out-Muster.

## Zielstrukturen (nicht neu erfinden)

| Ergebnis | Ablage |
|----------|--------|
| Ausschluss | `vault.add_excluded_source(paper_id, reason="screening: …")` |
| Einschluss | bleibt regulär in `papers` — kein Schreibvorgang nötig |
| Uneindeutig | nur Ledger, **nie** der Vault |
| Verzerrungsbewertung | `vault.add_risk_of_bias(...)` über den `risk-of-bias`-Agent |
| PRISMA-Zähler | `$SESSION_DIR/prisma_counters.json` |
| Protokoll + Resume | `$SESSION_DIR/screening_ledger.jsonl` |

## Buchführung

Die deterministischen Teile liegen in
`${CLAUDE_PLUGIN_ROOT}/skills/parallel-screening/scripts/screening_ledger.py`:

```python
import sys

sys.path.insert(0, "${CLAUDE_PLUGIN_ROOT}/skills/parallel-screening/scripts")
from screening_ledger import merge, open_cases_report, pending, plan_waves, record_decision
```

| Funktion | Aufgabe |
|----------|---------|
| `resolve_max_parallel()` | Obergrenze: Argument > Env > Config > Default |
| `plan_waves(ids, n)` | Fälle reihenfolgetreu in Wellen aufteilen |
| `pending(ids, session_dir)` | Resume: was ist noch offen? |
| `record_decision(...)` | Ledger-Zeile + Vault-Seiteneffekt, idempotent |
| `merge(session_dir)` | Buckets `include` / `exclude` / `unclear` |
| `open_cases_report(...)` | Markdown-Vorlage der uneindeutigen Fälle |
| `to_prisma_counters(...)` | PRISMA-Zähler direkt aus dem Ledger |
| `pending_rob(ids, dir, db)` | Resume für RoB (prüft zusätzlich den Vault) |

Dieselben Schritte gibt es als CLI:

```bash
~/.academic-research/venv/bin/python \
  ${CLAUDE_PLUGIN_ROOT}/skills/parallel-screening/scripts/screening_ledger.py \
  pending --session-dir "$SESSION_DIR" --ids "$IDS"
```

Unterkommandos: `pending`, `waves`, `merge`, `counters`, `open-cases`.

## Parallelitäts-Limit

Vorrang: `resolve_max_parallel(explicit=…)` > `ACADEMIC_RESEARCH_MAX_PARALLEL` >
`config/parallel_agents.json` → `max_parallel_agents` > Default `4`. Darüber ein
harter Deckel (`MAX_PARALLEL_HARD_CAP = 8`), damit eine verrutschte
Konfiguration nicht dreißig Agents gleichzeitig startet.

## Ablauf Screening

**Doppel-Screening (#598) ist Standard** (Schalter
`resolve_double_screening()`, Default `True`): zwei blinde
`screening-judge`-Läufe je Treffer, Runde 2 ohne Runde-1-Urteil. `False` →
exakt der Ablauf unten. Details (Kappa, Dissens, Vault-Commit) →
`references/double-screening.md`.

**Active Learning (#602) ist Opt-in** (Schalter `resolve_active_learning()`,
Default `False`): ein lokal trainierter Klassifikator sortiert die Restliste
um, sodass wahrscheinlich relevante Treffer zuerst kommen. Er sortiert nur —
kein Ausschluss, keine Kürzung, kein automatischer Abbruch. `reorder_pending`
und `progress_report` kommen aus `scripts/active_learning.py` (gleicher
`sys.path`-Eintrag wie oben). Details → `references/active-learning.md`.

### Schritt 0: Vorfilter (#892)

`screening_prefilter.py` schließt mechanisch aus → `references/prefilter.md`.

### Schritt 1: Offene Fälle bestimmen

```python
todo = pending(paper_ids, session_dir)
todo = reorder_pending(todo, papers, session_dir)  # nur bei Active Learning
waves = plan_waves(todo, max_parallel)
```

Ein abgebrochener Lauf setzt hier automatisch auf: bereits entschiedene Quellen
stehen im Ledger und tauchen nicht erneut auf.

### Schritt 2: Welle starten

Pro Welle **einen `Task`-Aufruf je Fall** in derselben Nachricht, Subagent
`screening-judge`. Jeder Aufruf bekommt genau einen `paper_id`, die
Kriterienliste und das verfügbare Material (Titel/Abstract oder Volltext).

Die Kriterienliste ist über alle Fälle identisch — sie gehört wörtlich in jeden
Aufruf, damit die Urteile vergleichbar bleiben. Steht in `./academic_context.md`
bereits eine Section `### Ein-/Ausschlusskriterien` (aus `preregistration`),
diese als Kriterienliste übernehmen statt erneut zu erfragen.

### Schritt 3: Einzelurteile protokollieren

Jeder Agent liefert das Ein-Fall-JSON aus `agents/screening-judge.md`:

```json
{"paper_id": "smith2023", "decision": "include", "reason": "…",
 "criterion": "study_design", "confidence": 0.85, "evidence": "title_abstract"}
```

Danach je Fall:

```python
record_decision(session_dir, judgement, agent="screening-judge#3", wave=1, db_path=db_path)
```

`record_decision` validiert den Vertrag (leere Begründung oder unbekannte
Entscheidung → `ValueError`), schreibt bei `exclude` nach `excluded_sources` und
hängt genau eine Ledger-Zeile an. Ein zweiter Aufruf für denselben Fall ändert
nichts.

### Schritt 4: Zusammenführen und vorlegen

```python
buckets = merge(session_dir)
print(open_cases_report(session_dir))
```

Die uneindeutigen Fälle werden **gesammelt** vorgelegt — mit Quelle, Grund und
fehlender Angabe. Entschieden wird darüber nur im Dialog, nie durch den Skill.

### Schritt 5: PRISMA-Zähler schreiben

```bash
~/.academic-research/venv/bin/python \
  ${CLAUDE_PLUGIN_ROOT}/skills/parallel-screening/scripts/screening_ledger.py \
  counters --session-dir "$SESSION_DIR" --n-identified "$N_IDENTIFIED" \
  > "$SESSION_DIR/prisma_counters.json"
```

Summenregel: `n_after_dedup = n_excluded_screening + n_included +
n_unclear_screening`. `prisma-flow` liest die Datei anschließend ohne
Zwischenschritt; uneindeutige Fälle bekommen dort einen eigenen Knoten und
zählen nicht als Volltextkandidaten.

## Ablauf Verzerrungsbewertung

Gleiches Muster, anderer Agent — `agents/risk-of-bias.md` bleibt unverändert:

```python
todo = pending_rob(paper_ids, session_dir, db_path)
for wave_no, wave in enumerate(plan_waves(todo, max_parallel), start=1):
    ...  # je Fall ein Task-Aufruf an risk-of-bias
```

`pending_rob` prüft zusätzlich `vault.list_risk_of_bias(paper_id)` —
`add_risk_of_bias` ist reines INSERT, sonst legte ein zweiter Lauf ein
zweites Assessment an.

Ist nur eine Domain unklar, ist das kein `unclear`-Fall des Ganzen — Score
`some concerns`/`can't tell`, Begründung „Nicht berichtet". Erst ein insgesamt
nicht bewertbares Paper (kein Volltext, falscher Studientyp) wird `unclear`.

## Wichtige Regeln

- **Nie selbst entscheiden**, was der Agent als `unclear` gemeldet hat.
- **Ein Agent, ein Fall** — keine Sammelaufträge, sonst ist das Protokoll wertlos.
- **Ledger ist append-only.** Nicht editieren, nicht neu schreiben; ein Resume
  verlässt sich darauf.
- **Zähler nie von Hand nachbessern** — sie kommen aus dem Ledger.
