---
name: anchor-paper-survey
description: >
  Verwende diesen Skill, wenn der User statt eines Themas ein konkretes
  Ausgangspaper (arXiv-URL/-ID oder lokaler PDF-Pfad) als Einstiegspunkt für
  eine Recherche angeben möchte, der Skill dieses Anker-Paper im Vault
  anlegen und darauf aufbauend verwandte/zitierende Arbeiten suchen soll.
  Trigger-Phrasen: "Recherche von einem Paper aus starten",
  "Ausgangspaper für die Recherche / Ausgangspaper fuer die Recherche",
  "arXiv-Paper als Anker verwenden",
  "PDF als Ausgangspunkt für Themenfindung nutzen",
  "verwandte Arbeiten zu diesem Paper finden",
  "welche Arbeiten zitieren dieses Paper", "Anker-Paper anlegen",
  "Survey ausgehend von einem Paper / einem Papier".
  Extrahiert Titel/Autoren aus arXiv-Metadaten (arXiv-API) bzw. heuristisch
  aus einem lokalen PDF (`scripts/pdf.py`), legt genau einen Vault-Eintrag
  via `vault.add_paper(provenance="anchor-paper")` an und lädt danach
  verwandte Arbeiten nach: bei arXiv-Ankern und bei PDF-Ankern mit DOI
  (Vault oder `extract_doi_from_text()`) per echter Zitations-/Referenz-
  Abfrage (Semantic Scholar), sonst per Titelsuche via `search.py::run_search()`.
license: MIT
allowed-tools:
  - Bash
  - Read
security:
  - network_allowlist:
      - "export.arxiv.org"
      - "api.crossref.org"
      - "api.openalex.org"
      - "api.semanticscholar.org"
---

# Anchor-Paper-Survey Skill

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Zweck

Ergänzt die themenbasierte Recherche um einen zweiten Einstiegspunkt:
"ich kenne bereits ein Schlüsselpaper". Statt mit einer Forschungsfrage zu
starten, gibt der User ein Ausgangspaper an — eine arXiv-URL/-ID oder den
Pfad zu einer lokalen PDF. Der Skill legt dieses Paper als Anker im Vault
an (`provenance="anchor-paper"`) und lädt darauf aufbauend verwandte Arbeiten
nach — analog zum Geschwister-Feature `github-repo-research` (Issue #401),
nur mit einem Paper statt einem Code-Repository als Anker.

Die Folge-Suche ist zweigleisig: arXiv-Anker und PDF-Anker mit DOI (Vault
oder per `extract_doi_from_text()` aus dem PDF-Volltext, Issue #599) bekommen
eine **echte** Zitations-/Referenz-Traversierung (`/paper/{id}/citations` +
`/paper/{id}/references`, Semantic Scholar) — kein Text-Match. Ohne DOI
(oder wenn S2 sie nicht kennt) fällt der Skill auf eine Titelsuche über die
bestehenden Fetcher (`scripts/search.py`) zurück, nie auf einen Abbruch. Das
Anker-Paper wird stets aus der Trefferliste gefiltert und die Rohtreffer
werden über `scripts/dedup.py` dedupliziert. `search.method`
(`"citation"`/`"keyword"`) und die Meldung machen den Unterschied explizit.

Konzept-Idee lose angelehnt an `JeanDiable/academic-research-plugin` (MIT) —
ausschließlich als Ideengeber zitiert; diese Implementierung teilt keinen
Code mit dem Originalrepo.

## Voraussetzungen

### 1. Abhängigkeiten

```bash
# requests, httpx, pypdf sind bereits Projekt-Dependencies (pyproject.toml)
uv sync --extra dev
```

### 2. Vault-Datenbank vorhanden

Der Vault muss initialisiert sein (z.B. via `vault.init_schema()`).

## Verwendung

### Automatisch (Skill-Trigger)

Claude erkennt Phrasen wie "Recherche von einem Paper aus starten" oder
"arXiv-Paper als Anker verwenden" und fragt nach der arXiv-URL bzw. dem
PDF-Pfad, falls nicht mitgeliefert.

### Manuell

```bash
python ${CLAUDE_PLUGIN_ROOT}/skills/anchor-paper-survey/scripts/anchor_paper.py \
  --input https://arxiv.org/abs/2005.14165 \
  --db ~/.academic-research/projects/meine-arbeit/vault.db

python ${CLAUDE_PLUGIN_ROOT}/skills/anchor-paper-survey/scripts/anchor_paper.py \
  --input /pfad/zu/ausgangspaper.pdf \
  --db ~/.academic-research/projects/meine-arbeit/vault.db
```

## Pipeline

```
Eingabe (arXiv-URL/-ID ODER lokaler PDF-Pfad)
    ↓
Input-Erkennung (detect_input)
    ↓                              ↘
arXiv-Fall                      PDF-Fall
    ↓                              ↓
arXiv-API (id_list=)      detect_needs_ocr()-Guard
    ↓                              ↓ (Textlayer fehlt -> sauberer Fehler, Stop)
CSL-JSON (Titel/Autoren/DOI)   extract_text_from_pdf() + Titel/Autoren-Heuristik
    ↓                              ↓
    ←──── genau EIN Anker-Paper ────→
    ↓
vault.add_paper(..., provenance="anchor-paper")
    ↓                              ↘
arXiv-Anker                     PDF-Anker: vault_get_paper() bzw.
    ↓                              extract_doi_from_text() -> DOI?
    ↓                              ↓ ja                  ↓ nein
s2_ref="ARXIV:<id>"        s2_ref="DOI:<doi>"       (kein s2_ref)
    ↘                              ↓                     ↓
     run_citation_search(s2_ref) → /citations+/references
       ↓ beide Relationen fehlgeschlagen (S2 kennt Ref nicht)? → run_search()
       ↓ sonst: method="citation"                            → method="keyword"
    ↓                              ↓                     ↓
    ←──────────── _filter_and_dedupe() ───────────────→
    ↓
Ergebnis: {status, paper_id, source, title, doi?,
           search: {hits, count, failed_modules, method}, message}
```

Kein Kandidat auflösbar (arXiv-ID unbekannt, PDF ohne Textlayer/Text)?
→ strukturierter Fehler, kein Vault-Eintrag, keine Fabrikation. Ungültige
Eingabe? → `ValueError` mit Klartextmeldung, ohne jede Vault-Mutation.

## Verhalten

1. Eingabe entgegennehmen (Argument oder via User-Frage): arXiv-URL/-ID
   oder lokaler PDF-Pfad
2. Eingabeart erkennen (`detect_input`) — ungültige Eingabe bricht sofort
   mit `ValueError` ab, **vor** jedem Vault-Zugriff
3. **arXiv-Fall**: ID aus URL/Bare-ID extrahieren, über die arXiv-API
   (`id_list=`) zu CSL-JSON auflösen
4. **PDF-Fall**: `detect_needs_ocr()` als Vorab-Guard (Scan-PDF ohne
   Textlayer → sauberer Fehler statt Rateversuch), dann
   `extract_text_from_pdf()` und Titel/Autoren-Heuristik (erste nicht-leere
   Zeile = Titel, zweite = Autoren — Best-Effort, siehe Einschränkungen)
5. Erfolgreich aufgelöstes Anker-Paper via `vault.add_paper()` ablegen
   (`provenance="anchor-paper"`) — **genau ein** Eintrag, kein Mehr, kein
   Weniger
6. **DOI-Auflösung für PDF-Anker** (Issue #599): `vault_get_paper()` hat
   Vorrang, sonst `extract_doi_from_text()` auf ein Zeichenfenster am Anfang
   des Volltexts (Best-Effort, siehe Einschränkungen)
7. Folge-Suche: **arXiv-/DOI-Anker** → `run_citation_search()`
   (`s2_ref="ARXIV:<id>"`/`"DOI:<doi>"`); scheitern beide Relationen, Rückfall
   auf Titelsuche statt Abbruch. **Ohne DOI** direkt `run_search()`. Danach
   `_filter_and_dedupe()` (Anker raus, `scripts/dedup.py`). Treffer nur
   angezeigt, nicht automatisch importiert
8. Ergebnis melden inkl. `search.method` (`"citation"`=nachgewiesene
   Zitationsbeziehung, `"keyword"`=Titel-Näherung), oder sauberer Fehlertext

## Abgrenzung

- **Kein neuer externer Dienst und keine Zitations-Graph-Datenbank** — nur
  die bereits im `network_allowlist` stehende Semantic-Scholar-API, kein
  eigener persistierter Zitations-Graph.
- **Folge-Treffer werden nicht automatisch importiert**: nur das Anker-Paper
  selbst landet im Vault, die Suchergebnisse sind Kandidaten zur Anzeige.
- Kein Cross-Skill-Import aus `github-repo-research`: eigenständige,
  analoge Implementierung ohne Code-Teilung.
- Findet die PDF-Heuristik keinen brauchbaren Titel, wird das offen
  gemeldet — es wird niemals ein Titel/Autor fabriziert.

## Sicherheitshinweise

- **Read-only Netz**: Nur lesende API-Zugriffe (arXiv; Semantic Scholar
  direkt für die Zitations-/Referenz-Abfrage; Crossref/OpenAlex/Semantic
  Scholar via `scripts/search.py` für die Titel-Stichwortsuche)
- **Kein Schreiben in externe Systeme**: nur der lokale Vault wird beschrieben
- **Keine Codeausführung**: kein Skript/Code aus PDF oder arXiv, nur
  Text-/Metadaten-Extraktion
- **Provenance-Tag**: jeder Eintrag trägt `provenance="anchor-paper"` (Audit,
  analog Issue #195)

## Bekannte Einschränkungen

- **Titel/Autoren-Heuristik aus PDF ist bewusst unscharf**: "erste
  nicht-leere Zeile = Titel, zweite = Autoren" ist ein Best-Effort-Ansatz
  ohne Genauigkeitsanspruch (kein Layout-Parsing, keine belegte
  Bibliographie-Extraktion) — deckt sich mit der bewusst weichen
  Issue-Formulierung "korrekt genug für eine Folge-Suche", nicht mit einer
  zitierfähigen Metadaten-Extraktion
- Scan-PDFs ohne Textlayer werden erkannt (`detect_needs_ocr`), aber nicht
  automatisch per OCR nachbearbeitet — das bleibt ein manueller,
  vorgelagerter Schritt (`scripts/ocr.py`)
- **PDF-Anker bekommen eine geprüfte Zitations-/Referenz-Beziehung, sobald
  sich eine DOI ermitteln lässt** (Issue #599, Vault oder
  `extract_doi_from_text()`). Das Suchfenster ist bewusst auf den
  Textanfang begrenzt (Titelseite/Header), damit keine zitierte Fremd-DOI
  aus der Bibliographie als eigene DOI gelesen wird — eine DOI weiter hinten
  im Text bleibt dadurch unentdeckt (bekannte Lücke, kein Bug). **Ohne
  auffindbare DOI** (oder wenn S2 sie nicht kennt) bleibt es bei der
  Titel-Stichwortsuche — thematisch ähnlich, aber KEINE nachgewiesene
  Zitationsbeziehung; `search.method` und die Meldung weisen das aus. Sehr
  generische/gekürzte Titel können dabei zu Streutreffern führen
- Netz-Ausfälle führen zu sauberem Fehlertext statt Crash/Fabrikation —
  "nicht gelesen" ist nicht "nicht vorhanden"
- **Nur arXiv-IDs im Format `YYMM.NNNNN`** (seit 2007) werden erkannt;
  alte IDs (z. B. `hep-th/9901001`) scheitern mit Fehlermeldung (bekannte
  Lücke, kein Bug)
