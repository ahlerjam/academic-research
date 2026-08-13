---
description: >
  Laedt ein Buch als PDF herunter. Nimmt ISBN-10/ISBN-13, DOI (10...),
  HTTP/HTTPS-URL oder Freitext-Titel als Argument. Moegliche Ausgabe-Stati:
  success (PDF in Vault und literature_state.md aufgenommen),
  pickup_required (Fernleihe-Eintrag in ~/.academic-research/pickup_queue.json
  angelegt), captcha (Screenshot anzeigen, manuelle Entscheidung abwarten),
  no_match (kein Treffer -> ebenfalls pickup_required-Eintrag).
allowed-tools: Read, Write, Agent(book-fetcher), Agent(chunk-context-writer), mcp__academic-vault__vault_add_paper
argument-hint: <isbn|doi|url|titel>
---

# /academic-research:fetch

Laedt ein Buch als PDF herunter und integriert es in den Vault.

## Verwendung

```
/academic-research:fetch 978-3-16-148410-0
/academic-research:fetch 10.1007/978-3-662-54347-6
/academic-research:fetch https://link.springer.com/book/10.1007/978-3-662-54347-6
/academic-research:fetch "Advanced Machine Learning"
/academic-research:fetch isbn: 0-306-40615-2
```

## Ausgabe-Stati

| Status | Bedeutung | Aktion |
|---|---|---|
| `success` | PDF heruntergeladen | Vault + literature_state.md aktualisiert |
| `pickup_required` | Kein freier Download moeglich | Fernleihe-Eintrag in pickup_queue.json |
| `captcha` | CAPTCHA erkannt | Screenshot anzeigen, User entscheidet |
| `no_match` | Kein Treffer in allen Quellen | Wie pickup_required behandeln |

---

## Workflow

### Schritt 1: Input parsen

Erkenne den Typ des Arguments `$ARGUMENTS`:

```
Prioritaet:
  1. Beginnt mit "isbn:" (Gross/Kleinschreibung ignoriert) -> Typ: isbn, Wert: Rest nach ":"
  2. Beginnt mit "http://" oder "https://" -> Typ: url
  3. Matches ^10\.\d{4,}/ -> Typ: doi
  4. Nur Ziffern+Bindestriche, bereinigt = 978... oder 979... (13 Stellen) -> Typ: isbn (ISBN-13)
  5. Nur Ziffern+Bindestriche, bereinigt = 10 Stellen (letzte darf X) -> Typ: isbn (ISBN-10)
  6. Alles andere -> Typ: title
```

Speichere intern: `identifier_type` und `identifier_value`.

### Schritt 2: Output-Pfad bestimmen

```
output_dir = ~/.academic-research/books/
sanitized  = identifier_value, Nicht-Alphanum (ausser ._-) durch "_", max 80 Zeichen
output_path = output_dir / sanitized + ".pdf"
```

Erstelle `output_dir` mit Write-Tool falls nicht vorhanden.

### Schritt 3: book-fetcher aufrufen

Rufe `Agent(book-fetcher)` auf mit folgendem Payload:

```
<identifier_type>: <identifier_value>
output_path: <output_path>
```

Warte auf das Ergebnis. Das Ergebnis hat immer das Schema:
```json
{
  "status": "success | pickup_required | captcha | no_match",
  "source": "<subagent-name>",
  "file_path": "<absoluter PDF-Pfad, nur bei success>",
  "reason": "<optionale Beschreibung>",
  "tries": [...],
  "pickup_hint": { ... }
}
```

### Schritt 4: Status-Handling

#### Bei `success`

1. Lese `file_path` aus dem Ergebnis.
2. Trage den Fund im Vault ein — rufe `mcp__academic-vault__vault_add_paper`
   auf (Issue #450 AC4: die korrekte Ausgabe-/Jahresangabe des Digitalisats
   muss im Vault landen, nicht nur im Agent-Output des book-fetcher stehen
   bleiben):

```json
{
  "paper_id": "<sanitized aus Schritt 2>",
  "csl_json": "<JSON-String: {\"type\": \"book\"} — bei vorhandenem result.edition die drei unten beschriebenen Felder issued/publisher/edition daraus ableiten und ergaenzen>",
  "pdf_path": "<file_path>",
  "isbn": "<identifier_value, falls identifier_type == isbn, sonst weglassen>",
  "doi": "<identifier_value, falls identifier_type == doi, sonst weglassen>"
}
```

   `result.edition` (von book-fetcher gemeldet, Freitext "Jahr/Ausgabe/Verlag
   DIESES Digitalisats" — siehe `agents/book-fetcher.md`, `agents/generic-fetcher.md`
   und `config/browser_guides/hathitrust.md` etc.) NICHT unveraendert als Freitext-Blob
   in ein einzelnes CSL-Feld kopieren — der `latex-export`-Skill
   (`skills/latex-export/scripts/build_bib.py`) liest das Jahr ausschliesslich
   aus `csl_json.issued["date-parts"]`, nicht aus `edition`. Stattdessen
   `result.edition` in `csl_json` zerlegen:

   - **Jahr:** die letzte 4-stellige Zahl (1000–2999) im String → nach
     `csl_json.issued = {"date-parts": [[<Jahr>]]}`.
   - **Verlag:** der Text zwischen einem fuehrenden Ort/Doppelpunkt und dem
     Jahr (z. B. "Printed for T. Egerton" aus
     "London : Printed for T. Egerton, 1813", oder "Verlag der
     Dieterichschen Buchhandlung" aus "Göttingen : Verlag der
     Dieterichschen Buchhandlung, 1864") → nach `csl_json.publisher`.
   - **Auflage:** nur eine tatsaechliche Ausgabebezeichnung (z. B. "3rd ed.",
     "2. Aufl.") → nach `csl_json.edition`. Bei HathiTrust/Internet
     Archive/MDZ fehlt eine solche Angabe im bisher beobachteten Format meist
     vollstaendig — dann `"edition"` ganz weglassen, NIE Jahr oder Verlag
     dort hineinschreiben.

   Laesst sich in `result.edition` keine 4-stellige Zahl finden, NICHT raten:
   den vollen String unveraendert nach `csl_json.edition` uebernehmen
   (Fallback) und `issued`/`publisher` weglassen. Fehlt `result.edition`
   komplett (z. B. bei einem Verlags-Treffer ohne dieses Feld), alle drei
   Schluessel weglassen — NIE einen Platzhalter oder eine aus
   `identifier_value` abgeleitete Angabe erfinden. Ein `title`-Feld fehlt
   hier bewusst noch: kein Subagent liefert bislang einen Titel aus der
   Quelle selbst — separater, vorbestehender Koordinationspunkt, nicht Teil
   von #450.
3. Erstelle oder appende folgenden Block an `./literature_state.md`
   (Write-Tool, append-Modus; erstelle Datei falls nicht vorhanden):

```markdown
## <title oder identifier_value> (<year oder "unbekannt">)

- **Typ:** book
- **ISBN/DOI:** <identifier_value>
- **PDF:** <file_path>
- **Hinzugefuegt:** <heutiges Datum ISO-8601>
```

**Kein `Quelle`-Feld im persistenten Block** (Issue #459): der Beschaffungsweg
(welcher Subagent das PDF geliefert hat) fliesst bewusst nicht in
`literature_state.md` ein, weil `chapter-writer` und `citation-extraction`
diese Datei als Kontext lesen duerfen — der Kanal darf Zitierweise und
Textbehandlung nicht beeinflussen. Die Provenienz bleibt vollstaendig im
Vault erhalten (`vault.get_paper()`, `vault.list_papers_by_provenance()`) —
ueber den `vault_add_paper`-Aufruf aus Schritt 2 tatsaechlich geschrieben.

4. Rufe `Agent(chunk-context-writer)` mit `{"paper_id": "<sanitized aus
   Schritt 2>"}` auf (Issue #710/#784) — schreibt inhaltliche Kontextsaetze
   fuer die soeben eingebetteten Chunks statt des deterministischen
   Metadaten-Satzes. **Bleibt der Aufruf aus oder scheitert er (Timeout,
   Tool-Fehler, `embedder-unavailable`): folgenlos fuer den restlichen
   Ablauf.** Kein Retry, keine Fehlermeldung an den User noetig — die Chunks
   behalten dann einfach ihren Metadaten-Kontextsatz und bleiben voll
   durchsuchbar. Dieser Schritt darf Schritt 5 (Ausgabe) nie blockieren.
5. Ausgabe an User:
```
PDF heruntergeladen: <file_path>
  Quelle: <source>
  Im Vault erfasst (paper_id: <sanitized>).
  In literature_state.md aufgenommen.
```

#### Bei `pickup_required` oder `no_match`

1. Lese `~/.academic-research/pickup_queue.json` (leeres Array `[]` falls nicht vorhanden).
2. Fuege folgenden Eintrag hinzu:

```json
{
  "identifier": "<identifier_value>",
  "identifier_type": "<identifier_type>",
  "bib_pickup_url": "<pickup_hint.bib_pickup_url oder leer>",
  "reason": "<result.reason oder 'Kein Download moeglich'>",
  "ts": "<ISO-8601 jetzt>",
  "source": "<result.source>"
}
```

3. Schreibe aktualisiertes Array zurueck mit Write-Tool.
4. Ausgabe an User:
```
Kein automatischer Download moeglich.
  Grund: <reason>
  Fernleihe-Eintrag angelegt in ~/.academic-research/pickup_queue.json
  Nutze /academic-research:pickup zur Weiterverarbeitung.
```

#### Bei `captcha`

1. Falls `result` einen Screenshot-Pfad enthaelt: Zeige ihn an.
2. Informiere User:
```
CAPTCHA erkannt bei <source>.
  [Screenshot: <screenshot_path>]
  Bitte manuell entscheiden:
  - "weiter" -> Pickup-Eintrag anlegen
  - "abbrechen" -> Abbruch ohne Eintrag
```
3. Warte auf User-Eingabe.
4. Bei "weiter": Behandle wie `pickup_required` (Schritt oben).
5. Bei "abbrechen": Abbruch mit Meldung.

---

## Hinweis: Inhaltliche Kontextsatz-Anreicherung (Issue #710/#784)

Der `vault_add_paper`-Aufruf aus Schritt 2 bettet Chunks zunaechst mit dem
deterministischen Metadaten-Kontextsatz ein (`context_source="metadata"`,
`chunking.default_context_sentence()`, kein Modellaufruf, #632-konform).
Schritt 4 (Bei `success`) ruft direkt danach `Agent(chunk-context-writer)`
fuer die geladene `paper_id` auf und schreibt dabei inhaltliche Saetze in
der Sprache jedes Chunks (`context_source="model"`) — automatisch, ohne
manuelles Zutun. Bleibt der Aufruf aus oder scheitert er, bleibt der
Metadaten-Satz stehen: die Chunks sind in jedem Fall voll durchsuchbar,
nur der Kontextsatz ist entweder metadatenbasiert oder inhaltlich.

Fuer einen **nachtraeglichen Bestandsvault-Nachtrag** (Papers, die vor #784
oder ausserhalb von `/academic-research:fetch` eingebettet wurden) denselben
Agenten manuell mit der jeweiligen `paper_id` aufrufen, oder mit
`paper_id: null` fuer einen vault-weiten Durchlauf (paperweise, kein
Ein-Klick-Automatismus — siehe `docs/reference/vault.md`).
