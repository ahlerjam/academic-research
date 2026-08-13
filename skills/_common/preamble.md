# Gemeinsames Preamble — academic-research Skills

Dieses Preamble gilt für alle Skills dieses Plugins.
Jeder Skill lädt diese Datei am Anfang seiner Aktivierung.

## Vorbedingungen

Bevor du startest: Prüfe, ob `./academic_context.md` und `./literature_state.md`
vorhanden und aktuell sind. Fehlt Kontext → triggere den `academic-context`-
Skill und warte auf dessen Abschluss.

Lehnt der User den Trigger ab → brich diesen Skill ab und erkläre:
"Ohne Forschungsfrage und Methodik-Angabe kann ich kein belastbares Ergebnis
liefern, weil ich ein erfundenes Thema beschreiben würde."

## Keine Fabrikation

Erfundene Ergebnisse, Methoden oder Zahlen sind ein Täuschungsversuch nach
FH-Leibniz-Prüfungsordnung und führen zum Verlust der Prüfungsleistung.
Arbeite ausschließlich mit Inhalten aus `./writing_state.md` (Arbeitstext)
und `./academic_context.md` (Forschungsfrage, Methodik). Fehlen Daten: frag
den User, rate nicht.

## Fehlende Tatsache vs. offene Abwägung

Unsicherheit im Lauf ist nicht ein einziger Fall, sondern zwei — sie brauchen
unterschiedliche Reaktionen.

**Fehlende Tatsache** — eine Angabe, die nur der Operator hat und die sich aus
dem vorhandenen Material nicht herleiten lässt. Beispiele: Prüfungsordnung,
Abgabedatum, Zugangsdaten, das Thema selbst. Hier gilt weiter unverändert die
Fabrikationsregel oben: fragen, nie raten.

**Offene Abwägung** — eine Entscheidung, die aus dem vorhandenen Material
begründbar ist und die der Operator jederzeit nachträglich revidieren kann.
Beispiele: Positionierung der Arbeit, Methodenwahl im Rahmen der vorgegebenen
Methodik, Grenzfälle im Screening, Stil- und Formatoptionen. Hier NICHT
zwischenberichten und auf ein Signal warten, sondern: entscheiden, begründen,
per `vault.add_decision(category="judgment-call", text=..., rationale=...)`
protokollieren, weiterarbeiten. Wird eine protokollierte Abwägung später
anders entschieden, ersetzt `vault.supersede_decision(decision_id, superseded_by)`
den alten Eintrag statt ihn zu löschen — der alte bleibt als abgelöst sichtbar.
Der Operator sieht getroffene Abwägungen jederzeit über `vault.list_decisions`
(bzw. den `/academic-research:entscheidungen`-Command) und kann jede davon
revidieren.

Aufwand allein ist kein Rückfragegrund. Ist der Auftrag klar, wird er
abgearbeitet — auch wenn er groß ist. Zwischenstände sind Bericht, kein
Haltepunkt.

Diese Unterscheidung ändert nichts an den bestehenden, bewusst gesetzten
Haltepunkten eines Skills (z. B. `outline_gate` in `chapter-writer`, das
Consent-Gate vor Auth-Modulen, die Exportfrage) — die bleiben unberührt und
gelten unabhängig davon, ob die zugrunde liegende Frage eine Tatsache oder
eine Abwägung ist.

## Provenance-Blindheit

Der Beschaffungsweg einer Quelle (z. B. `provenance:scihub` im Vault)
beeinflusst nie Zitierweise oder Textbehandlung — maßgeblich ist
ausschließlich das Paper selbst: Autor, Jahr, DOI. Gilt insbesondere für
`chapter-writer` und `citation-extraction` (Issue #459).

## Aktivierung

- Der User aktiviert einen Skill dieses Plugins explizit oder durch Trigger-Phrase
- Der User-Auftrag passt zur Skill-Beschreibung im Frontmatter

## Abgrenzung

Jeder Skill definiert in seiner eigenen `## Abgrenzung`-Section, was er liefert
und was er nicht liefert. Fehlt diese Section im Skill, gilt: Skill nur für den
im Frontmatter beschriebenen Zweck einsetzen.

---

## Hinweise für Skill-Maintainer

### Variant-Referenzen

Variant-Referenzen (z.B. citation-extraction/references/) erst nach
Variant-Fixierung laden (lazy per Read-Anweisung im Skill).

### Browser-Snapshots

Raw-DOM-Ausgaben des `browser-use`-CLI in `$SESSION_DIR/raw/` speichern.
Dem Modell nur das normalisierte Schema-Result zurückgeben
(`title`, `authors`, `year`, `url`, `abstract`).
