# Glossar

[← Doku-Übersicht](../README.md)

Die Begriffe, die in der übrigen Dokumentation vorausgesetzt werden. Wer über einen
Ausdruck stolpert, schlägt ihn hier nach — jede Zeile erklärt den Begriff so, dass sie
ohne den Rest der Seite verständlich bleibt.

## Glossar

| Begriff | Bedeutung |
|---------|-----------|
| **Vault** | SQLite-basierter MCP-Server des Plugins. Speichert Papers, Verbatim-Zitate, Entscheidungen, RoB-Assessments und Score-Historie. Ersetzt `literature_state.md` als Single Source of Truth. |
| **Subagent** | LLM-Unteragent, der von einem Skill oder Command gestartet wird, um eine spezialisierte Aufgabe zu erledigen (z. B. ein Site-Subagent für Buch-Download auf tib.eu). |
| **Site-Profile** | YAML-Konfiguration einer Hochschule, die Auth-Typ (HAN/Shibboleth/EZproxy), lizenzierte Seiten und Zugangsdaten-Keys beschreibt. Wird von `auth-helper` und `book-fetcher` genutzt. |
| **Material-Passport** | Unveränderlicher Metadaten-Passport für ein Artefakt (Paper, Kapitel). Kann via `vault.lock_passport()` eingefroren werden — danach keine Änderungen mehr möglich. |
| **Contextual Retrieval** | Anthropic-Pattern: vor jedem Chunk-Embedding wird ein 1-Satz-Kontext angehängt. Verbessert Recall@10 deutlich vs. Vanilla-vec0. Im Vault erzeugt der seitenbewusste Chunking-Pfad den Kontextsatz deterministisch und offline (`default_context_sentence`) — seit #632 der einzige Weg, ein Modellaufruf pro Chunk ist entfallen. |
| **Decision-Log** | Append-only-Protokoll aller `.md`-Änderungen und Entscheidungen. Wird vom Hook `post-tool-use-decisions.mjs` (PostToolUse) automatisch befüllt; programmatisch via `vault.add_decision(text, category)`. |
| **Vault-Lock** | Read-only-Sperre des Vault. Nach `vault.lock_passport(paper_id)` sind keine Schreibzugriffe mehr möglich — Grundlage für reproduzierbare Abgaben (siehe Repro-Lock, Skill `material-passport`). |
| **Repro-Lock** | Reproduzierbarkeits-Sperre des Skills `material-passport`: friert den Material-Passport ein und sperrt den Vault read-only (Vault-Lock), damit Dritte den Stand exakt nachvollziehen können. |
| **OCR-Detection** | Automatische Prüfung, ob ein PDF einen Text-Layer besitzt (`scripts/pdf.py:detect_needs_ocr`). Fehlt der Layer, schlägt das Plugin OCR via `ocrmypdf` vor. |
| **page_offset** | Differenz zwischen PDF-Seitenzahl und gedruckter Seitenzahl bei Büchern mit Vorseiten (`printed_page = pdf_page - offset`). Wird von `scripts/page_offset.py` ermittelt und vom `book-handler` für seitengenaue Zitate genutzt. |
| **output_targets** | Opt-in-Eintrag im Projekt-State, der Default-Off-Output-Skills (`grant-proposal`, `conference-poster`, `reviewer-response`) aktiviert. Nur wenn der passende Wert gesetzt ist, läuft der jeweilige Skill (v6.5-Opt-in-Pattern). |
| **PRISMA** | Preferred Reporting Items for Systematic Reviews and Meta-Analyses — Standard-Framework für Transparent-Reporting. Das Plugin generiert PRISMA-2020-konforme Mermaid-Flussdiagramme. |
| **HAN** | Hochschulauthentifizierungs-Netzwerk — Bibliotheks-Proxy für lizenzpflichtige Datenbanken. |
| **RRF** | Reciprocal-Rank-Fusion — Methode zum Zusammenführen von BM25- und vec0-Rankings im Vault. |
| **Abstract** | Kurzfassung der Arbeit (150–300 Wörter), IMRaD-konform. |
| **IMRaD** | Introduction, Methods, Results, and Discussion — Standard für wissenschaftliche Abstracts. |
| **Peer-Review** | Wissenschaftlicher Begutachtungsprozess vor Publikation. |
| **5D-Score** | Eigene Metrik: Relevanz (35 %), Aktualität (20 %), Qualität (15 %), Autorität (15 %), Zugang (15 %). |
| **Cluster** | Gruppierung von Papers: Kern-, Ergänzungs-, Hintergrund-, Methodenliteratur. |
| **Skill** | Selbstaktivierende Claude-Erweiterung. Claude erkennt Keywords und lädt die passende Anleitung. |
| **BibTeX** | Textbasiertes Literatur-Format für LaTeX. Andere Formate: APA7, IEEE, Harvard, Chicago, DIN 1505, MLA, Vancouver, Springer Author-Date. |
| **CSL** | Citation Style Language — XML-basiertes Format für Zitierstile. 10.000+ Stile im CSL-Repository. |
| **humanizer-de** | Globaler Skill für Anti-KI-Audit deutschsprachiger Texte. Schützt vor Turnitin/GPTZero/OriginalityAI. |
