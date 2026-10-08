# academic-research (Neustart): Belegnetz – Zielbild und Architektur

Stand: 2026-10-08 · Status: **Entwurf zur Freigabe**
Ablage: `docs/plan/` im neuen Repo `ahlerjam/academic-research` (Gerüst per `/agent-repo`, 08.10.2026). Zielbild-Kurzfassung → Vorschlag `NORTHSTAR.proposed.md` (NORTHSTAR.md ist Operator-Datei). Entscheidungen → ADRs unter `decisions/`, nur nach Rückfrage.

---

## 1. Zielbild

**Das Tool hält eine durchgehende, beweisbare Kette** vom Satz in der Arbeit zurück bis zur Zeichenfolge auf der PDF-Seite:

```
Quelle (PDF)
  └─ Belegstelle   wörtlich, Druckseite, gegen die PDF geprüft
       └─ Aussage   stützt / widerspricht / erwähnt
            └─ Gliederungspunkt
                 └─ Verweis im Text  [[b:7f3a]]
                      └─ Export      verweigert jede Lücke und nennt die Stelle
```

- **Für wen:**
  - Primär für den Autor selbst als Arbeitswerkzeug.
  - Sekundär Open Source, auch für Laien.
  - Nebensächlich als Portfolio.
- **Was das Tool selbst kann (Stationen 4–7):**
  - Belegstellen sichern
  - Argument bauen
  - Schreiben mit Belegen
  - Prüfen und Abgabe
- **Was nur angebunden wird:** Thema schärfen, Literatur finden und Quellen beschaffen. Das leisten Chat-KI, OpenAlex und Crossref, Zotero.
- **Leitprinzip:** Der Server denkt nicht, er beweist. Lesen, Urteilen und Formulieren übernimmt das Modell im Client. Der Server prüft deterministisch.
- **Alleinstellung**, belegt durch die Recherche vom 06.10.2026, siehe Anhang A:
  - Wir prüfen wörtlich und deterministisch, nicht per Ähnlichkeitswert.
  - Wir arbeiten mit Druckseiten, Beleg-IDs im Text und einer Export-Sperre.
  - Kein gefundenes Produkt bietet diese Kette.

## 2. Scope

### Nie
- kein LLM und kein API-Key im Server (vgl. #632)
- keine Nischen-Methodik: Meta-Analyse, Risk-of-Bias, Grant, Poster, Defense, Präregistrierung
- keine lokalen Großmodelle
- kein Versprechen, Plagiate oder KI-Texte zu erkennen
- kein Meta-Prozess-Overhead: keine eigene Review-Pipeline, keine Auto-Issues, keine Tests auf Prompt-Text
- kein SciHub und keine Umgehung von Paywalls (entschieden 08.10.)
- kein Zotero-Ersatz: Zotero wird angebunden, nicht nachgebaut (entschieden 08.10.)

### Später vielleicht
- Ghostwriting-Hilfe (nicht in den Meilensteinen)

### Zugänge (alle fest im Zielbild)
Reihenfolge: **MCP + CLI → Zotero-Add-in → Web-App.** Eine JSON-HTTP-API gibt es ab v1.

### Meilensteine (Schnitt von v1 „voll, Stationen 4–7“ entschieden 08.10.)

| Meilenstein | Inhalt |
|---|---|
| **v1 Belegnetz lokal** | Quellen aufnehmen (PDF lokal, DOI-Metadaten), Seitenzuordnung, Belegstellen, Suche, Aussagen, Bezüge, Gliederung, `network_status`, `check_text`, Export Markdown → DOCX/PDF. Zugänge MCP (stdio + lokales HTTP), CLI, JSON-API. Nur localhost |
| v1.x Öffentlicher Modus | eingebauter OAuth-Server, Einladungslinks, Upload-Weg für PDFs, Tunnel-Anleitung. Damit funktionieren claude.ai und ChatGPT |
| v2 Zotero | Import (Metadaten, PDFs, Markierungen als Beleg-Kandidaten), dann das Zotero-Add-in über die JSON-API |
| v3 Sichtbarkeit | MCP-Apps-Ansichten (Netz, Thesen, PDF-Seite), Web-App mit denselben Ansichten |
| v4 Beschaffung | externe Suche (OpenAlex, Crossref, EconBiz), Open-Access-Abruf per DOI |

## 3. Datenmodell

| Objekt | Felder (Kern) | Ebene |
|---|---|---|
| Quelle | id, citekey, DOI, Titel, Autoren, Jahr, `pdf_sha256`, Seitenzuordnung | Bibliothek |
| Seite | Quelle, PDF-Seite, Druckseiten-Label, Text, Textlayer ja/nein | Bibliothek |
| Belegstelle | id (`b:` + kurz), Quelle, PDF-Seite, Druckseite, Wortlaut aus der Quelle, Zeichenposition, Prüfklasse, Herkunft (`user`, `ai`, `zotero-annotation`), Seiten-Hash zum Prüfzeitpunkt, angelegt | Bibliothek |
| Kandidat | wie Belegstelle, aber nicht im Netz; Grund (`no-match`, `no-textlayer`, `page-mismatch`, `source-changed`) und nächste Fundstelle | Bibliothek |
| Aussage | id (`a:`), Text, Projekt | Projekt |
| Bezug | Belegstelle ↔ Aussage, Art `supports`, `contradicts` oder `mentions` | Projekt |
| Gliederung | Baum aus Punkten, Aussagen hängen an Punkten | Projekt |
| Projekt | id, Titel, Zitierstil (CSL), Sprache | – |

**Invarianten (im Kern durchgesetzt):**
1. Ins Netz kommt nur Geprüftes. Eine Belegstelle entsteht nur bei einer Prüfklasse, die als *belegt* gilt (§4). Alles andere wird Kandidat und bekommt einen Grund.
2. Gespeichert wird der Quelltext, nie die Fassung des Modells.
3. Belegstellen sind unveränderlich. Eine Korrektur erzeugt eine neue Belegstelle, die alte wird als `superseded` markiert.
4. Die PDF ist per Hash gebunden. Ändert sich der Hash, werden die zugehörigen Belegstellen neu geprüft. Fehlschläge werden `source-changed`.
5. Der Export löst jeden Verweis auf. Bei einer Lücke gibt es keinen Export, dafür einen Bericht mit Zeile, Verweis und Grund.

**Speicher:** SQLite mit FTS5 je Nutzer, dazu ein PDF-Ordner, adressiert nach Hash. Layout `/data/users/<id>/{db.sqlite,pdfs/}`, lokal mit genau einem Nutzer. Das Netz lässt sich jederzeit als JSON und Markdown exportieren.

## 4. Prüfvertrag (der testbare Kern)

### 4.1 Prüfklassen des Wortlaut-Prüfers
Portiert aus `academic_vault/verbatim.py`. Die Klassen dort heißen `exact`, `snapped`, `no-match` und `no-textlayer`.

| Klasse | Bedeutung | Gilt als belegt? |
|---|---|---|
| `exact` | Treffer nach schwacher Normalisierung (Anführungszeichen-Varianten, Whitespace) | ja |
| `normalized` | Treffer erst nach voller Normalisierung (NFKC, Ligaturen, zusammengeführte Silbentrennung), aber **exakter Substring** | ja |
| `snapped` | nur ein Fuzzy-Treffer ≥ Schwelle (alt: 0,90, rapidfuzz) | **nein**, wird Kandidat; Vorschlag des echten Wortlauts zur Bestätigung |
| `no-match` | nichts gefunden | nein, Kandidat |
| `no-textlayer` | Seite ohne Text, z. B. ein Scan | nein, Kandidat; v1 ohne OCR |

Änderung gegenüber dem alten Code: `snapped` mischt dort Normalisierung und Fuzzy. Neu wird das getrennt. Nur exakte Substrings, schwach oder voll normalisiert, gelten als belegt. Ein Fuzzy-Treffer liefert nur den echten Wortlaut als Vorschlag. Wird dieser Vorschlag übernommen, entsteht er erneut als `exact`.
**Release-Gate:** 0 falsch-positive im Goldset. Gemeint ist: Ein gefälschtes Zitat wird nie *belegt*.

### 4.2 Seitenzuordnung
Ein einzelner Offset (`printed = pdf − offset`, alt) reicht nicht, denn er bricht bei römischer Vorrede und bei Zeitschriften-Paginierung. Neu:
1. **PDF-`/PageLabels`** werden ausgelesen, wenn vorhanden.
2. Sonst gibt es **Segmente**: `[(pdf_von, pdf_bis, druck_start, stil arabisch|römisch)]`. Ein Vorschlag kommt aus der Kopf- und Fußzeilenerkennung, bei Unsicherheit wird nachgefragt.
3. Eine Belegstelle speichert die PDF-Seite *und* das aufgelöste Druckseiten-Label.

### 4.3 Text prüfen (`check_text`)
Eingabe ist Markdown-Text mit `[[b:…]]`-Verweisen.
- **Hart, das sperrt den Export:**
  - Ein Verweis zeigt auf eine unbekannte oder ersetzte Belegstelle.
  - Ein Anführungszeichen-Zitat steht unmittelbar vor einem Verweis, und sein Wortlaut stimmt nicht mit der Belegstelle überein.
  - Ein Anführungszeichen-Zitat hat keinen Verweis.
- **Anführungszeichen:** „…“, »…«, "…", ‚…‘. Damit ironische Anführungszeichen oder Titel keine Sperre auslösen, gibt es eine ausdrückliche Markierung `[[nq]]` direkt hinter dem schließenden Zeichen (Name offen). Der Bericht erklärt sie bei jeder Sperre.
- **Paraphrasen:** Durchgesetzt wird nur, was einen expliziten `[[b:…]]` hat. Ob ein Satz ohne Verweis einen bräuchte und ob eine Paraphrase sinngemäß stimmt, prüft der Server **nicht**. Das übernimmt das Modell im Client, angeleitet durch MCP-Prompts. Die Dokumentation sagt das offen.
- **Ausgabe:** ein Bericht mit Zeile, Spalte, Klasse, Grund und nächstem Schritt, auf DE und EN.

### 4.4 Export
- Ein Export ist nur mit sauberem Bericht möglich.
- `[[b:…]]` wird zu Pandoc-Zitaten `[@citekey, S. 47]`, danach folgt Pandoc mit CSL. Zielformate in v1: DOCX und PDF.
- Nicht verifiziert: Pandoc als Systemabhängigkeit im Docker-Image ist naheliegend, lokal ohne Docker aber eine Hürde. Das wird beim Plan geklärt.

## 5. Bausteine

```
 Zugänge    MCP (stdio + HTTP) · CLI · JSON-HTTP-API ── später Zotero-Add-in, Web-App
 Dienste    add_source · map_pages · add_evidence · link · outline · network_status ·
            check_text · export · search      ← einziger Ort für Nutzer, Rechte, Projekt
 Kern       Modell · Invarianten · Wortlaut-Prüfer · Seitenzuordnung · Verweis-Auflöser
 Adapter    SQLite/FTS5 · PDF-Ablage · PyMuPDF · Metadaten (Crossref/OpenAlex per DOI) · Pandoc
```
- Abhängigkeiten zeigen nur nach innen. Der Kern hat keine I/O.
- Zugänge enthalten keine Regeln.
- **Aus dem alten Repo portiert**, jeweils mit neuen Verhaltenstests: `verbatim.py`, `quote_match.py` (zu prüfen), `chunking.extract_pages`, die Normalisierung.
- Nicht portiert: alles andere, siehe Anhang B.

## 6. MCP-Tool-Fläche (v1)

`add_source`, `set_page_mapping`, `read_source`, `search`, `add_evidence`, `get_evidence`, `upsert_claim`, `link`, `outline`, `network_status`, `check_text`, `export`.

- Jedes Ergebnis hat `status`, `reason` und `next_step` und ist zweisprachig.
- MCP-Prompts: „Quelle durcharbeiten“, „These belegen“, „Abgabe prüfen“.
- Eine Anleitungs-Ressource erklärt die Regeln für jeden Client.
- Code und Tool-Namen sind englisch. Meldungen und Doku gibt es auf DE und EN, DE wird zuerst gepflegt.

## 7. Betrieb

| Modus | Meilenstein | Zugänge | Schutz |
|---|---|---|---|
| Lokal | v1 | stdio (Desktop/CLI-Clients), HTTP auf `127.0.0.1` | lokaler Token für die JSON-API, wird automatisch angelegt |
| Lokal + Tunnel | v1.x | zusätzlich HTTPS über Cloudflare Tunnel | OAuth Pflicht |
| Gehostet | v1.x | HTTPS auf einem VPS, mehrere Nutzer | OAuth, Einladungslinks |

- **Start ohne Konfiguration:** `docker run -p 127.0.0.1:8000:8000 -v academic-research:/data ghcr.io/ahlerjam/academic-research`. Wichtig ist `127.0.0.1`, denn ohne diese Angabe ist der Port im LAN offen. Alternativ `uvx academic-research`.
- **JSON-API:** eigene Starlette-Routen mit Token-Middleware. *Nicht* über `@mcp.custom_route()`, denn solche Routen sind nicht authentifiziert. Belege: py.sdk.modelcontextprotocol.io/run/asgi/. Host-Prüfung und `transport_security` müssen gesetzt sein, sonst gibt es 421.
- **Verbindungsmatrix v1:**

| Client | Weg in v1 | Status |
|---|---|---|
| Claude Code, Codex CLI, VS Code, Cursor | stdio (`uvx … --stdio`) | Nicht verifiziert je Client, beim Plan prüfen |
| Claude Desktop | stdio über `claude_desktop_config.json` | ob lokales HTTP geht: Nicht verifiziert |
| Docker + stdio | `docker run -i` plus Volume für die PDFs des Hosts | Nicht verifiziert |
| claude.ai (Web), ChatGPT-Chat | **erst v1.x**, sie brauchen Remote-HTTPS mit OAuth | belegt (Anhang A) |

- **OAuth (v1.x):**
  - Der Server ist Resource Server nach MCP-Spec 2026-07-28 (RFC 9728 PRM, RFC 8707 `resource`, Audience-Prüfung, 401 mit `resource_metadata`).
  - Ein eingebauter Authorization Server ist Pflicht, weil das SDK `mcp` 1.30.0 keinen mitliefert. Er unterstützt CIMD, mit DCR als Rückfall für Clients, PKCE S256, `token`-Endpunkt mit form-urlencoded und RFC 9207 `iss`.
  - Kandidat dafür ist Authlib (Nicht verifiziert).
  - Ein eigener Meilenstein mit Sicherheits-Review.
- **PDF-Upload, wenn der Server entfernt läuft (v1.x):**
  - ChatGPT übergibt Dateien per `_meta["openai/fileParams"]`, das ist belegt.
  - Für claude.ai ist kein Mechanismus belegt.
  - Deshalb gibt es eine eigene Upload-Seite und später das Zotero-Add-in.

## 8. Tests und Qualität
- **Kern:** Unit-Tests plus Hypothesis-Property-Tests für Normalisierung, Ligaturen, Silbentrennung, Anführungszeichen und Zeilenumbrüche.
- **Goldset:** rund 10 Open-Access-PDFs mit Absicht schwierig: zweispaltig, römische Vorrede, Scan, Ligaturen, Fußnoten. Dazu echte und gefälschte Zitate. **Gate: 0 falsch-positive.**
- **Dienste:** Tests gegen eine temporäre SQLite-Datei, inklusive aller Sperrfälle.
- **Zugänge:** **eine** gemeinsame Suite läuft gegen MCP, JSON-API und CLI und verlangt dasselbe Ergebnis.
- **Durchstich:** ein MCP-Client im Prozess geht den goldenen Pfad. Ein erfundenes Zitat wird gesperrt.
- **CI:** eine Datei mit Ruff, Typprüfung, pytest und Docker-Build. Keine KI-Evals in der CI.
- Gates, Hooks und Make-Verben kommen aus dem `/agent-repo`-Gerüst.

## 9. Überführung (Checkliste; jeder irreversible Schritt nur mit ausdrücklichem Ja)
1. Den Plan freigeben (dieses Dokument).
2. Lokal ein neues Verzeichnis anlegen, dessen Basename `academic-research` ist, z. B. `~/Repos/next/academic-research`. `/agent-repo` leitet `project_name` aus dem Basename ab.
3. Der Nutzer ruft `/agent-repo new ~/Repos/next/academic-research` auf. Daraus entsteht das Gerüst mit Python-Komponente.
4. Dieses Dokument wird als erstes Planungsdokument hineingelegt, dazu `NORTHSTAR.md` und die ADRs. ADRs entstehen nur nach Rückfrage.
5. **Irreversibel, braucht ein Ja:** den letzten Stand im alten Repo taggen (`v8-final`).
6. **Irreversibel, braucht ein Ja:** das alte GitHub-Repo in `academic-research-legacy` umbenennen und archivieren. Die offenen Issues bekommen vorher einen Abschlusskommentar mit Verweis.
7. **Irreversibel, braucht ein Ja:** das neue GitHub-Repo `ahlerjam/academic-research` anlegen und pushen.
8. **Folgen, die bewusst in Kauf genommen werden:**
   - Die Weiterleitungen zum alten Repo brechen. Alte Links zeigen dann auf das neue Repo.
   - Plugin- und Marketplace-Einträge mit `ahlerjam/academic-research` werden ungültig.
   - Die Registrierung bei flowkit-cloud muss umgezogen werden.
   - Die lokale MCP-Konfiguration `academic-vault` ist bereits jetzt defekt (ENOENT) und wird entfernt.
9. Danach geht es mit der Planung im neuen Repo weiter: Implementierungsplan, Issues und Umsetzung.

## 10. Entscheidungen
Entschieden 08.10.: v1 = voll (Stationen 4–7) · SciHub nie · Zotero-Ersatz nie, Ghostwriting-Hilfe später vielleicht · Netz in v1 als Text in Chat/CLI, MCP Apps ab v3.

Noch offen (im Implementierungsplan klären):
1. **Name der Markierung für Nicht-Zitate** (`[[nq]]`) und das Format der Beleg-IDs.
2. **Pandoc als Abhängigkeit**, oder ein reiner DOCX-Export in Python.

---

## Anhang A: Belege (Recherche 06.10.2026)
- **MCP-Autorisierung:**
  - Version 2026-07-28: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization
  - Die Spec erlaubt, dass der Authorization Server mit dem Resource Server zusammen gehostet wird.
- **claude.ai-Connectors:** https://claude.com/docs/connectors/building/authentication.md
  - Auth per `oauth_cimd`, `oauth_dcr` oder `none`
  - PKCE S256
  - Callback `https://claude.ai/api/mcp/auth_callback`
  - Timeout 10 s
- **ChatGPT:**
  - Auth: https://developers.openai.com/apps-sdk/build/auth
  - `openai/fileParams`: https://developers.openai.com/apps-sdk/reference
- **Python-SDK `mcp` 1.30.0** (07.09.2026):
  - Paketdaten: https://pypi.org/pypi/mcp/json
  - Kein Authorization Server: https://py.sdk.modelcontextprotocol.io/run/authorization/
  - ASGI-Mount: https://py.sdk.modelcontextprotocol.io/run/asgi/
- **MCP Apps:**
  - Überblick: https://modelcontextprotocol.io/extensions/apps/overview
  - Python-SDK: https://py.sdk.modelcontextprotocol.io/advanced/apps/
  - ChatGPT-Unterstützung: Nicht verifiziert.
- **GitHub-Umbenennung:** Weiterleitungen brechen, sobald der alte Name neu vergeben wird. https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository
- **Konkurrenz:**
  - Prüfen nur, ob ein Paper existiert: citecheck (arXiv 2603.17339), doi-mcp
  - Lassen ein LLM urteilen: CiteGuard, PaperQA2, Kotaemon
  - Liefern nur Rohtext: Zotero-MCPs (54yyyu 5,3k Sterne, cookjohn)
  - Prüft per Vektor-Score: GRaDOS
  - Prüft per Wortüberlappung: footnote-mcp
  - Suche per MCP (Massenware): Consensus, Scite, Undermind
  - Keines bietet wörtlich, Druckseite, Beleg-IDs und Export-Sperre zusammen. Das ist ein Negativbefund aus nicht erschöpfender Suche.
- **Übernehmbare Ideen** (beide MIT-lizenziert):
  - aus GRaDOS: Hash der Quellblöcke zum Prüfzeitpunkt
  - aus GRaDOS: differenzierte Fehlerklassen
  - aus footnote-mcp: `needs_review` statt einer stillen Entscheidung

## Anhang B: Was aus dem alten Repo nicht übernommen wird
- 46 Skills, 21 Agents und 13 Commands des Plugins. Prompt-Ideen dienen höchstens als Vorlage für die MCP-Prompts.
- `server.py` mit 4266 Zeilen und 52 Tools.
- `migrate.py`.
- Spekulative Tabellen: score_history, paper_fulltext/tables, risk_of_bias, codings, figures.
- `sqlite-vec` und `nli_prefilter.py` mit zwei NLI-Modellen.
- Drei lokale Modelle mit zusammen rund 5,7 GB.
- 9 weiche Hooks.
- Die Browser-Fetcher und SciHub.
- Die flowkit-Review-Pipeline.
- Rund 200 `test_issue_*`-Dateien, die Prompt-Text prüfen.
