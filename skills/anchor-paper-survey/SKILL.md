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
  verwandte Arbeiten nach: bei arXiv-Ankern per echter Zitations-/
  Referenz-Abfrage (Semantic Scholar), bei PDF-Ankern per Titelsuche über
  `scripts/search.py::run_search()`.
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

Die Folge-Suche ist bewusst zweigleisig: arXiv-Anker besitzen mit ihrer ID
einen stabilen Semantic-Scholar-Identifier (`ARXIV:<id>`) und bekommen damit
eine **echte** Zitations-/Referenz-Traversierung (`/paper/{id}/citations` +
`/paper/{id}/references`) — Arbeiten, die den Anker tatsächlich zitieren
bzw. die er zitiert, kein Text-Match. PDF-Anker haben keinen solchen
externen Identifier und fallen auf eine Titelsuche über die bereits
vorhandenen Fetcher (`scripts/search.py`) zurück. In beiden Fällen wird das
Anker-Paper selbst aus der Trefferliste gefiltert und die Rohtreffer werden
über die kanonische Repo-Pipeline (`scripts/dedup.py`) dedupliziert, bevor
gezählt/gemeldet wird.

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
arXiv-Anker                     PDF-Anker
    ↓                              ↓
run_citation_search(              run_search(query=Titel,
  "ARXIV:<id>")                     modules=[arxiv, semantic_scholar,
  → /citations + /references         openalex, crossref])
    ↓                              ↓
    ←── _filter_and_dedupe() ───→   (Anker raus, scripts/dedup.py)
    ↓
Ergebnis: {status: "ok"|"error", paper_id, source, title,
           search: {hits, count, failed_modules}, message}
```

Kein Kandidat auflösbar (arXiv-ID unbekannt, PDF ohne Textlayer/Text)?
→ strukturierter Fehler (`status: "error"`), kein Vault-Eintrag, keine
Fabrikation. Ungültige Eingabe (weder arXiv-URL/-ID noch existierender
Pfad)? → `ValueError` mit Klartextmeldung, ebenfalls ohne jede Vault-Mutation.

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
6. Folge-Suche anstoßen — **arXiv-Anker**: `run_citation_search()` fragt
   die Semantic-Scholar-Graph-API nach Arbeiten, die den Anker zitieren
   (`/citations`) bzw. die er zitiert (`/references`); **PDF-Anker**:
   `scripts/search.py::run_search()` mit dem extrahierten Titel als Query
   (kein stabiler externer Identifier verfügbar). Danach entfernt
   `_filter_and_dedupe()` das Anker-Paper aus der Rohtrefferliste und
   dedupliziert den Rest über `scripts/dedup.py`. Treffer werden **nur
   angezeigt**, nicht automatisch in den Vault geschrieben
7. Ergebnis melden: Anker angelegt + N verwandte Arbeiten gefunden, oder
   sauberer Fehlertext bei Auflösungs-/Extraktions-/Suchfehlern

## Abgrenzung

- **Kein neuer externer Dienst und keine Zitations-Graph-Datenbank** — die
  Zitations-/Referenz-Abfrage nutzt ausschließlich die Semantic-Scholar-API,
  die bereits Teil des `network_allowlist` ist; es wird kein eigener
  Zitations-Graph aufgebaut oder persistiert.
- **Folge-Treffer werden nicht automatisch importiert**: nur das Anker-Paper
  selbst landet im Vault, die Suchergebnisse sind Kandidaten zur Anzeige.
- Kein Cross-Skill-Import aus `github-repo-research`: eigenständige
  arXiv-Resolver-Implementierung, analog im Muster, aber ohne Code-Teilung.
- Findet die PDF-Heuristik keinen brauchbaren Titel, wird das offen
  gemeldet — es wird niemals ein Titel/Autor fabriziert.

## Sicherheitshinweise

- **Read-only Netz**: Nur lesende API-Zugriffe (arXiv; Semantic Scholar
  direkt für die Zitations-/Referenz-Abfrage der arXiv-Anker; Crossref,
  OpenAlex, Semantic Scholar über `scripts/search.py` für die
  Titel-Stichwortsuche der PDF-Anker)
- **Kein Schreiben in externe Systeme**: Nur der lokale Vault wird beschrieben
- **Keine Codeausführung**: Es wird kein Skript/Code aus einer PDF oder von
  arXiv ausgeführt, ausschließlich Text-/Metadaten-Extraktion
- **Provenance-Tag**: jeder Vault-Eintrag trägt `provenance="anchor-paper"`
  für den Audit-Trail (analog Issue #195)

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
- **Nur arXiv-Anker bekommen eine geprüfte Zitations-/Referenz-Beziehung**
  (Semantic-Scholar-`/citations`+`/references`). PDF-Anker haben keinen
  stabilen externen Paper-Identifier und fallen auf eine Titel-Stichwortsuche
  zurück — deren Treffer sind thematisch ähnlich, aber KEINE nachgewiesene
  Zitationsbeziehung. Trigger wie "welche Arbeiten zitieren dieses Paper"
  lösen den Skill für PDF-Anker korrekt aus, liefern in diesem Fall aber nur
  die Titel-Näherung, keine verifizierte Zitationsliste. Sehr generische
  oder gekürzte extrahierte Titel können dabei zusätzlich zu Streutreffern
  oder keinem Treffer führen
- Netz-Ausfälle bei arXiv/der Folge-Suche führen zu einem sauberen
  Fehlertext statt Crash oder fabriziertem Ergebnis — "nicht gelesen" ist
  nicht "nicht vorhanden"
- **Nur arXiv-IDs im Format `YYMM.NNNNN`** (seit 2007) werden erkannt;
  alte IDs (z. B. `hep-th/9901001`) scheitern mit Fehlermeldung (bekannte
  Lücke, kein Bug)
