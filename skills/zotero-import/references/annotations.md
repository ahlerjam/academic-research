# Annotation-Import (Issue #395)

Detailreferenz zu Schritt 6 in `SKILL.md`. Wird nur bei Bedarf geladen —
`SKILL.md` bleibt dadurch innerhalb des Token-Budgets (Progressive Disclosure,
vgl. `skills/chapter-writer/references/`).

## Was importiert wird

Zotero legt Highlights und Notizen als eigene Items mit
`itemType == "annotation"` unterhalb des PDF-**Attachments** ab (nicht
unterhalb des bibliografischen Items). Der Import fragt deshalb nach der
Identifikation des PDF-Attachments zusätzlich `zot.children(att_key)` ab und
verarbeitet jedes Kind mit diesem Typ.

Jede so gefundene Annotation wird über `vault.add_quote()` mit
`extraction_method="manual"` angelegt.

## Textquelle

| Feld | Verwendung |
| --- | --- |
| `annotationText` | bevorzugt — der markierte Ausschnitt |
| `annotationComment` | Fallback für reine Notiz-Annotationen ohne markierten Text |

Sind beide leer, wird die Annotation übersprungen (kein leerer Quote).

## Seitenzahl

`annotationPageLabel` wird **ausschließlich exakt-numerisch** geparst.
`printed_page` ist eine INTEGER-Spalte; geraten wird nicht:

| Label | `printed_page` |
| --- | --- |
| `"42"` | `42` |
| `"iv"` (römisch) | `NULL` |
| `"12-13"` (Bereich) | `NULL` |
| `""` / fehlend | `NULL` |

## Idempotenz

Vor dem Einfügen liest der Import die vorhandenen Quotes des Papers und
vergleicht auf dem Schlüssel `(verbatim, printed_page)`. Bereits vorhandene
Markierungen werden übersprungen.

Das ist notwendig, weil `add_quote()` selbst nicht dedupliziert (jede Quote
bekommt eine frische `uuid4()`) und Items **ohne DOI/ISBN** vom
Paper-Dedup nicht erfasst werden: Sie durchlaufen bei jedem Lauf den vollen
Importpfad, während `paper_id` über den stabilen Zotero-Key konstant bleibt.
Ohne diesen Filter wüchse pro Lauf eine weitere Kopie jeder Markierung an
dasselbe Paper.

Derselbe Wortlaut auf **verschiedenen** Seiten bleibt bewusst als zwei
getrennte Quotes erhalten — das sind zwei echte Markierungen.

## Fehlerverhalten

Ein Fehler bei einer einzelnen Annotation bricht den Item-Import nicht ab,
sondern landet in `result.errors` (analog zum bestehenden
`ensure_file`-Pattern). Auch das Laden der Annotation-Kinder selbst ist
fehlertolerant.

Annotationen werden unabhängig vom Download-Erfolg des PDFs importiert —
sie stammen aus der Zotero-API, nicht aus der PDF-Datei.

## Bekannte Einschränkungen

- Nur das erste (erfolgreich geladene) PDF-Attachment pro Item wird
  betrachtet — Annotationen an weiteren Attachments desselben Items bleiben
  unerfasst.
- **Dedup-Kurzschluss:** Ist ein Paper bereits per DOI/ISBN im Vault, wird
  das Item vollständig übersprungen — inklusive Attachment- und
  Annotation-Verarbeitung. Neue Annotationen zu einem bereits importierten
  Paper werden bei einem Re-Import daher **nicht** nachgezogen.
- Eigenständige Zotero-Notiz-Items (`itemType == "note"`) und verschachtelte
  Attachments bleiben unberücksichtigt.

## Optionale Companion-Integration: 54yyyu/zotero-mcp

[54yyyu/zotero-mcp](https://github.com/54yyyu/zotero-mcp) ist ein separater,
eigenständiger MCP-Server für tiefere Zotero-Interaktion (Suche, Notizen,
Volltext) direkt aus einem MCP-Client heraus. Lizenz: MIT. Stand der
Verifikation (Issue #395): ~4,45k GitHub-Stars.

Dieser Skill bindet `54yyyu/zotero-mcp` **nicht** automatisch ein (keine
Einbindung in `.mcp.json`). Es ist eine optionale Ergänzung, die Nutzer bei
Bedarf selbst als zusätzlichen MCP-Server konfigurieren können, wenn sie über
den hier beschriebenen Batch-Import hinaus interaktiv mit Zotero arbeiten
möchten.
