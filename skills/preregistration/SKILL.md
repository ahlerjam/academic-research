---
name: preregistration
description: >
  Verwende diesen Skill, wenn ein Studienprotokoll **vor** der Datenerhebung
  präregistriert werden soll: Fragestellung, Ein-/Ausschlusskriterien,
  Suchstrategie und Auswertungsplan öffentlich festhalten, bevor die
  Untersuchung läuft. Trigger-Phrasen: "Studie präregistrieren / Studie
  praeregistrieren", "Präregistrierung / Praeregistrierung", "PROSPERO-Eintrag
  vorbereiten", "PROSPERO-Anmeldung", "OSF-Registrierung", "OSF-Preregistration",
  "Studienprotokoll vor der Erhebung", "Analyseplan vor der Datenerhebung
  festhalten". Schlägt anhand des Vorhabens (systematischer Review /
  quantitativ / qualitativ / Sekundärdaten) eine passende Vorlage vor und
  begründet die Wahl; für systematische Reviews entsteht ein Protokoll mit
  den von PROSPERO verlangten Pflichtfeldern. Rechnet über
  `${CLAUDE_PLUGIN_ROOT}/skills/preregistration/scripts/render_protocol.py`.
  Abgrenzung: `methodology-advisor` wählt die Methode, dieser Skill
  registriert sie öffentlich, bevor erhoben wird; `prisma-flow` und
  `parallel-screening` setzen an, wenn die Suche schon läuft — deren
  Suchstrategie und Kriterien liegen danach in `./academic_context.md` bereit,
  und auch der `query-generator`-Agent liest sie von dort statt sie neu zu
  erfragen.
license: MIT
allowed-tools: [Bash, Read, Write, AskUserQuestion]
---

# Präregistrierung

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Zweck

Zwischen Methodenwahl und Datenerhebung liegt ein Schritt, der leicht
übersprungen wird: die öffentliche Festlegung von Fragestellung,
Ein-/Ausschlusskriterien, Suchstrategie und Auswertungsplan, **bevor** die
erste Quelle gesichtet oder der erste Datensatz erhoben wird. Präregistrierung
ist die wirksamste Absicherung gegen ein nachträglich an das Ergebnis
angepasstes Vorgehen — und bei systematischen Reviews faktisch Voraussetzung
für die Publikation in einschlägigen Zeitschriften (PROSPERO-Eintrag).

## Abgrenzung

- `methodology-advisor` wählt und begründet die Methode; dieser Skill
  registriert die gewählte Methode öffentlich, **bevor** erhoben wird.
- `prisma-flow` rendert das PRISMA-Flussdiagramm aus dem laufenden Screening;
  `parallel-screening` führt das Screening selbst aus. Beide setzen an, wenn
  die Suche schon läuft — die Suchstrategie und Kriterien, die dieser Skill
  hier festlegt, liegen für sie danach in `./academic_context.md` bereit
  (Sections `### Suchstrategie`, `### Ein-/Ausschlusskriterien`), ohne dass
  sie erneut erfragt werden müssen.
- Der `query-generator`-Agent generiert API-Suchqueries; er nutzt dieselbe
  Suchstrategie aus `./academic_context.md`, statt sie neu zu erfinden.
- Automatisches Einreichen bei OSF oder PROSPERO ist **out of scope**: dieser
  Skill erzeugt das Dokument, das Einreichen bleibt beim Menschen.
- Vollständige Vorlagentexte der Anbieter werden nicht mitgeliefert — sie
  ändern sich unabhängig von diesem Plugin. `references/` nennt Feldnamen,
  Quelle und Fundstelle, keine Formularvolltexte.
- Ob ein Vorhaben präregistrierungspflichtig ist, entscheidet dieser Skill
  nicht — das bleibt eine Einschätzung des Menschen bzw. der Prüfungsordnung.
- Registered Reports (Präregistrierung mit Zeitschriften-Begutachtung vor der
  Datenerhebung) sind ein eigenes Publikationsformat mit eigenem redaktionellem
  Prozess — hier out of scope, auch wenn das erzeugte Protokoll als Grundlage
  dienen kann.

## Schritt 1 — Vorhaben klassifizieren

Frag im Dialog (oder lies aus `./academic_context.md`, falls dort schon
vermerkt), welcher Vorhabenstyp vorliegt:

- **systematic-review** — systematischer Review/Meta-Analyse
- **qualitativ** — qualitatives oder Mixed-Methods-Design
- **sekundaerdaten** — Analyse an bereits vorhandenen Daten
- **quantitativ** — eigenes quantitatives Hypothesentest-Design ohne
  speziellere Passform

Ist der Typ nicht eindeutig aus dem Gespräch ableitbar, frag per
`AskUserQuestion` nach — rate nicht. Die Zuordnung übernimmt
`klassifiziere_vorhaben()`:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/preregistration/scripts/render_protocol.py \
  classify --methodik-typ qualitativ
```

Liefert `{"template": "qualitative", "begruendung": "..."}`. **Ein
qualitatives Vorhaben bekommt nie das quantitative Raster** — die Begründung
gehört unverändert ins spätere Protokoll.

Vier Vorlagen stehen zur Wahl, referenziert in `references/`:

| Vorhabenstyp | Vorlage | Referenzdatei |
| --- | --- | --- |
| systematic-review | PROSPERO-Registrierungsformular | `references/prospero-fields.md` |
| quantitativ | OSF Preregistration (general) | `references/osf-templates.md` |
| sekundaerdaten | OSF Secondary Data Preregistration | `references/osf-templates.md` |
| qualitativ | OSF Qualitative Preregistration | `references/osf-templates.md` |

## Schritt 2 — Felder im Dialog erheben

Frag die Felder der gewählten Vorlage im Gespräch ab (Feldnamen stehen in der
jeweiligen Referenzdatei). **Was der User nicht festlegt, bleibt offen** —
der Renderer füllt unbeantwortete Felder mit dem festen Platzhalter `[OFFEN]`,
nie mit Plausiblem. Bei PROSPERO sind alle Pflichtfelder aus
`references/prospero-fields.md` im Protokoll sichtbar, auch wenn sie offen
bleiben — inhaltlich offen ist erlaubt, weggelassen nicht.

Halte die Antworten als Plan-JSON fest (`preregistration_plan.json`, analog
zum Analyseplan-Muster aus `quantitative-analysis`):

```json
{
  "template": "prospero",
  "titel": "Wirksamkeit von X bei Y",
  "begruendung": "<Begründungstext aus Schritt 1>",
  "felder": {
    "Review question(s)": "...",
    "Searches": "..."
  },
  "suchstrategie": "...",
  "einschlusskriterien": ["...", "..."],
  "ausschlusskriterien": ["...", "..."]
}
```

## Schritt 3 — Protokoll rendern

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/preregistration/scripts/render_protocol.py \
  render --plan preregistration_plan.json --out preregistration.md
```

Das Protokoll enthält je Feld ein Label (Wert oder `[OFFEN]`), den Abschnitt
`## Abweichungen vom Protokoll` (dort werden spätere Abweichungen mit Datum
und Begründung nachgetragen — nicht durch Löschen des Protokolls, sondern
durch Ergänzung) und einen `## Quelle`-Block mit Vorlagenname, URL und
Fundstelle. Derselbe Plan erzeugt bei jedem Lauf denselben Text — kein
Zeitstempel im Dokument selbst.

## Schritt 4 — Suchstrategie und Kriterien für `parallel-screening` bereitstellen

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/preregistration/scripts/render_protocol.py \
  update-context --plan preregistration_plan.json --context ./academic_context.md
```

Schreibt `suchstrategie`, `einschlusskriterien`, `ausschlusskriterien` und —
falls im Plan vorhanden — den `screening_filters`-Block (Quelle des
Vorfilters, #892) aus dem Plan strukturiert in die Sections
`### Suchstrategie` und
`### Ein-/Ausschlusskriterien` von `./academic_context.md` — alle anderen
Sections bleiben unverändert. Existiert `./academic_context.md` noch nicht,
bricht der Schritt ab: erst den `academic-context`-Skill laufen lassen. Ab
hier lesen `parallel-screening` (Schritt 2) und der `query-generator`-Agent
diese Sections, statt Suchstrategie oder Kriterien erneut zu erfragen.

## Schritt 5 — Decision-Log

Die Vorlagenwahl und der Begründungstext aus Schritt 1 gehören zusätzlich ins
Decision-Log des Vaults, analog zum Muster in `academic-context`:

```python
vault.add_decision(
    category="praeregistrierung",
    decision="Vorlage: OSF Qualitative Preregistration",
    rationale="<Begründungstext aus klassifiziere_vorhaben()>",
)
```

## Referenzen

- `references/prospero-fields.md` — PROSPERO-Pflichtfelder, Quelle + Fundstelle.
- `references/osf-templates.md` — Feldlisten der drei OSF-Vorlagen (general,
  secondary-data, qualitative), Quelle + Fundstelle je Vorlage.
