# Doppel-Screening (#598)

Vollständiges Vorgehen für blindes Doppel-Screening: zwei unabhängige
`screening-judge`-Läufe je Treffer, ausgewiesenes Übereinstimmungsmaß
(Cohen's Kappa), gesammelte Dissensvorlage. Ergänzt `SKILL.md`, das die
Kurzfassung und den einrundigen (einfachen) Ablauf trägt.

## Warum Standard, nicht Ausnahme

PRISMA und Cochrane verlangen für systematische Übersichtsarbeiten doppeltes,
unabhängiges Screening mit ausgewiesener Übereinstimmung. Ein einzelner Judge
hat keine Fehlerkorrektur — wo zwei unabhängige Urteile auseinandergehen,
liegt fast immer ein Grenzfall vor, genau der Fall, den ein Mensch sehen
sollte. Darum ist Doppel-Screening der Default (`resolve_double_screening()`
→ `True`), nicht die Ausnahme. Für eine Seminararbeit mit wenigen Treffern ist
es Verschwendung — dafür der Schalter.

## Schalter

```python
resolve_double_screening(explicit=None, config_path=None) -> bool
```

Vorrang, absteigend:

1. Argument im Skill-Aufruf (`resolve_double_screening(explicit=…)`)
2. Umgebungsvariable `ACADEMIC_RESEARCH_DOUBLE_SCREENING` (`true`/`false`,
   `1`/`0`, `yes`/`no`, `on`/`off`, case-insensitiv)
3. `config/parallel_agents.json` → `double_screening`
4. Default `True`

Bei `False` verhält sich der Skill **exakt wie vor #598**: ein
`screening-judge`-Lauf je Treffer, `record_decision(round=1)` implizit,
`merge()`/`to_prisma_counters()` wie gehabt.

## Funktionen

Alle in `screening_ledger.py`, Import wie im Haupt-`SKILL.md` beschrieben.

| Funktion | Aufgabe |
|----------|---------|
| `resolve_double_screening()` | Schalter: Argument > Env > Config > Default `True` |
| `pending_round(ids, session_dir, stage, round)` | Resume für EINE Runde (1 oder 2) |
| `record_decision(..., round=1\|2)` | Ledger-Zeile je `(paper_id, stage, round)`, **ohne** `db_path` |
| `record_human_decision(session_dir, decision, stage=...)` | Dissens-Auflösung, `round="human"`, `decided_by="human"` |
| `compute_agreement(session_dir, stage)` | Cohen's Kappa + Fallzahl über vollständige Runde-1/2-Paare |
| `dissent_cases(session_dir, stage)` | Widersprüchliche Fälle ohne `human`-Auflösung, strukturiert |
| `dissent_report(session_dir, stage)` | Dieselben Fälle als Markdown-Vorlage |
| `merge_double(session_dir, stage)` | Buckets `include`/`exclude`/`unclear`/`dissent`, konsolidiert |
| `commit_double_screening(session_dir, stage, db_path)` | `merge_double` + Vault-Ausschlüsse — **einziger** Schreibpfad |
| `to_prisma_counters_double(session_dir, stage, ...)` | PRISMA-Zähler aus dem konsolidierten Doppel-Urteil |

CLI-Unterbefehle: `pending-round`, `agreement`, `dissent-cases`, `merge-double`
(analog zu den bestehenden, `--session-dir`/`--stage`/`--ids`/`--round`).

## Ablauf

### Schritt 1 — Offene Fälle je Runde bestimmen

```python
todo_r1 = pending_round(paper_ids, session_dir, round=1)
todo_r2 = pending_round(paper_ids, session_dir, round=2)
```

Anders als `pending()` (stufenweit, rundenblind) zählt hier nur eine
Ledger-Zeile für **genau diese Runde** als erledigt. Ein Lauf, der nach der
Runde-1-Welle abbricht, lässt Runde 2 damit garantiert offen — sonst gälte ein
Fall nach dem Resume fälschlich als vollständig doppelt geurteilt.

### Schritt 2 — Runde 1 abschließen, dann Runde 2 blind starten

Wie im einrundigen Ablauf: pro Welle ein `Task`-Aufruf je Fall an
`screening-judge`, dieselbe Kriterienliste wörtlich in jedem Aufruf.

**Blind-Regel (verbindlich, nicht im Code erzwingbar):** Runde 2 ist ein
eigener `Task`-Aufruf mit `round=2`. Sein Prompt darf **weder das Urteil noch
die Begründung von Runde 1** enthalten — kein `decision`, kein `reason`, kein
Hinweis auf ein bereits vorliegendes Ergebnis. Blindheit ist strukturell
gratis, solange diese Regel eingehalten wird: Runde 1 und Runde 2 sind zwei
komplett getrennte Agent-Kontexte, die einzige gemeinsame Eingabe sind
`paper_id`, Kriterienliste und Material (`agents/screening-judge.md` kennt
diese Isolation und geht selbst nicht davon aus, eine andere Runde zu sehen).
Runde 1 vollständig abschließen, bevor Runde 2 startet — nicht interleaven,
sonst lässt sich die Blindheit nicht mehr garantieren.

### Schritt 3 — Einzelurteile protokollieren, ohne Vault-Seiteneffekt

```python
record_decision(session_dir, judgement_r1, agent="screening-judge#3", wave=1, round=1)
record_decision(session_dir, judgement_r2, agent="screening-judge#7", wave=1, round=2)
```

**Kein `db_path`** in diesen Aufrufen, für beide Runden. Ein einzelner
Runden-Ausschluss vor Kenntnis der zweiten Runde wäre ein voreiliger
Vault-Schreibzugriff, den ein späterer Dissens nicht mehr zurücknehmen kann —
das würde AC3 verletzen ("Dissensfälle werden nicht automatisch
ausgeschlossen"). `record_decision` hängt genau eine Ledger-Zeile je
`(paper_id, stage, round)` an; Runde 1 und Runde 2 sind getrennte
Idempotenz-Slots, ein zweiter Aufruf für dieselbe Runde ändert nichts.

### Schritt 4 — Übereinstimmung ausweisen, Dissens vorlegen

Erst wenn für alle Fälle **beide** Runden vollständig sind:

```python
agreement = compute_agreement(session_dir)
# {"kappa": 0.81, "n": 22, "po": 0.91, "pe": 0.52}
print(dissent_report(session_dir))
```

`compute_agreement` zählt nur Fälle mit vollständigem Runde-1+Runde-2-Paar —
ein Fall, dessen Runde 2 (z. B. nach Abbruch) noch offen ist, verzerrt sonst
die Fallzahl. Perfekte Übereinstimmung (`po == pe == 1`) ergibt `kappa = 1.0`,
nicht eine Division durch 0.

Dissensfälle (Runde 1 ≠ Runde 2) werden **niemals automatisch** aufgelöst —
nicht per Mehrheit, nicht per drittem Agenten. Der Dissens ist das Signal;
ihn wegzurechnen zerstört den Zweck. `dissent_report` legt sie gesammelt vor:
Quelle, beide Urteile, beide Begründungen.

### Schritt 5 — Menschliche Entscheidung protokollieren

```python
record_human_decision(
    session_dir,
    {"paper_id": "smith2023", "decision": "exclude", "reason": "Nach Volltextsicht: kein RCT"},
)
```

Schreibt `round="human"` und `decided_by="human"` — ein eigenes Schema-Feld,
kein String-Präfix, damit die Entscheidung strukturell (nicht nur
konventionell) von einem Agenten-Urteil unterscheidbar bleibt (AC4).
Agenten-Zeilen aus `record_decision` tragen entsprechend `decided_by="agent"`.
Idempotent wie `record_decision`: eine zweite menschliche Entscheidung für
denselben Fall ändert nichts an der ersten.

### Schritt 6 — Konsolidieren und in den Vault schreiben

```python
buckets = commit_double_screening(session_dir, db_path=db_path)
# {"include": [...], "exclude": [...], "unclear": [...], "dissent": [...]}
```

`commit_double_screening` ist der **einzige** Ort, an dem Doppel-Screening-
Ausschlüsse den Vault erreichen. Konsolidierungsregel (`merge_double`):

- Runde 1 == Runde 2 (Konsens) → das gemeinsame Urteil.
- Runde 1 != Runde 2 und eine `human`-Zeile liegt vor → die menschliche
  Entscheidung gewinnt.
- Runde 1 != Runde 2 ohne `human`-Zeile → `dissent`.

`dissent` erreicht den Vault **nie** — weder als Ausschluss noch als
Einschluss. Papiere mit nur einer Runde (Runde 2 noch offen) tauchen in
keinem Bucket auf, sie sind schlicht noch nicht konsolidierbar.

### Schritt 7 — PRISMA-Zähler schreiben

```python
counters = to_prisma_counters_double(session_dir, n_identified=n_identified)
```

**Entscheidung (#598):** `dissent` bekommt im Flussdiagramm keinen eigenen
Knoten, sondern fließt in `n_unclear_screening` ein. Für den Leser des
Diagramms ist ein ungelöster Dissens dasselbe wie ein „noch nicht
entschieden" — beides wartet auf eine menschliche Entscheidung und ist weder
ein- noch ausgeschlossen. `render_flow.py` bleibt dadurch unverändert, der
bestehende „Unklar"-Knoten deckt beide Fälle ab. Eligibility-Ausschlüsse sind
in `to_prisma_counters_double` nicht abgebildet (Out-of-Scope für #598, das
sich auf Titel-/Abstract-Screening bezieht) und stehen fest auf `0`.

## Wichtige Regeln (Doppel-Screening-spezifisch)

- **Runde 2 ist blind.** Kein Runde-1-Urteil, keine Runde-1-Begründung im
  Runde-2-Prompt — sonst ist die zweite Meinung keine.
- **Kein `db_path` in `record_decision`.** Vault-Schreibzugriffe laufen
  ausschließlich über `commit_double_screening` — sonst schließt ein
  voreiliger Runde-1-Ausschluss einen Fall aus, den Runde 2 noch als Dissens
  markiert.
- **Dissens nie automatisch auflösen.** Nur `record_human_decision` löst
  einen Dissensfall auf; alles andere ist eine stille Auflösung durch die
  Hintertür.
- **`merge()`/`to_prisma_counters()` bleiben Runde-1-only.** Bei aktivem
  Doppel-Screening zählen sie ein Paper nicht doppelt, weil sie Runde-2- und
  `human`-Zeilen ignorieren — für den konsolidierten Blick immer
  `merge_double()`/`to_prisma_counters_double()` verwenden.
