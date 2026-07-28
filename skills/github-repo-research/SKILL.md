---
name: github-repo-research
description: >
  Verwende diesen Skill, wenn der User eine GitHub-Repo-URL als zusätzlichen
  Recherche-Einstiegspunkt nutzen möchte, um von einem konkreten
  Code-Repository aus zur zugehörigen Literatur zu gelangen, statt von einem
  Thema oder Paper auszugehen. Trigger-Phrasen: "GitHub-Repo analysieren",
  "Repo-URL analysieren", "Paper zu einem Repo finden",
  "GitHub-Repository für Recherche / GitHub-Repository fuer Recherche",
  "verlinkte Publikationen im Repo finden",
  "welches Paper gehört zu diesem Repository",
  "Themenfindung aus einem Code-Repository".
  Liest README + CITATION.cff eines Repos ausschließlich über die öffentliche
  GitHub-REST-API (kein git clone, keine Codeausführung des Zielrepos),
  extrahiert arXiv-IDs/DOIs, löst sie via arXiv-API/Crossref auf und legt
  Treffer via vault.add_paper(provenance="github-repo") ab.
license: MIT
allowed-tools:
  - Bash
  - Read
security:
  - network_allowlist:
      - "api.github.com"
      - "raw.githubusercontent.com"
      - "export.arxiv.org"
      - "api.crossref.org"
---

# GitHub-Repo-Research Skill

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Zweck

Nimmt eine GitHub-Repo-URL entgegen und leitet daraus Themenfindungs- bzw.
Recherche-Kandidaten ab: README und `CITATION.cff` werden nach arXiv-Links,
DOIs bzw. strukturierten Zitationsfeldern durchsucht. Gefundene Kandidaten
werden über die arXiv-API bzw. Crossref zu CSL-JSON aufgelöst und im Vault
angelegt (`provenance="github-repo"`). Zusätzlicher Einstiegspunkt für
Nutzer, die von einem konkreten Code-Repository aus in die zugehörige
Literatur recherchieren wollen.

Konzept-Idee nach `lingzhi227/agent-research-skills` (keine Lizenz laut
GitHub-API — ausschließlich als Ideengeber zitiert; diese Implementierung
teilt keinen Code mit dem Originalrepo).

## Voraussetzungen

### 1. Abhängigkeiten

```bash
# requests + pyyaml sind bereits Projekt-Dependencies (pyproject.toml)
uv sync --extra dev
```

### 2. Vault-Datenbank vorhanden

Der Vault muss initialisiert sein (z.B. via `vault.init_schema()`).

## Verwendung

### Automatisch (Skill-Trigger)

Claude erkennt Phrasen wie "GitHub-Repo analysieren" oder
"Paper zu einem Repo finden" und fragt nach der Repo-URL, falls nicht
mitgeliefert.

### Manuell

```bash
python ${CLAUDE_PLUGIN_ROOT}/skills/github-repo-research/scripts/analyze_repo.py \
  --url https://github.com/<owner>/<repo> \
  --db ~/.academic-research/projects/meine-arbeit/vault.db
```

## Pipeline

```
GitHub-Repo-URL
    ↓
(owner, repo)-Parsing
    ↓
README-Fetch (GET /repos/{owner}/{repo}/readme, GitHub-REST-API)
    ↓                                    ↘
arXiv-ID-/DOI-Regex                CITATION.cff-Fetch (Contents-API)
    ↓                                    ↓
    ↓                              YAML-Parse (preferred-citation/Top-Level)
    ↓                                    ↓
    ←──────────── Kandidaten-Liste (arXiv-IDs + DOIs) ───────────→
    ↓
Kein Kandidat? → strukturiertes Leer-Ergebnis, keine Exception, kein Fake-Paper
    ↓
Resolution: arXiv-API (id_list=) bzw. Crossref → CSL-JSON je Kandidat
    ↓
vault.add_paper(..., provenance="github-repo") pro erfolgreich aufgelöstem Kandidat
    ↓
Ergebnis: {candidates: [...], message: "N Kandidat(en) ... "}
```

## Verhalten

1. GitHub-Repo-URL entgegennehmen (Argument oder via User-Frage)
2. `(owner, repo)` aus der URL parsen
3. README **nur über die GitHub-REST-API** lesen (`GET /repos/{owner}/{repo}/readme`)
4. `CITATION.cff` **nur über die GitHub-Contents-API** lesen, falls vorhanden
5. arXiv-IDs/DOIs aus README-Freitext per Regex extrahieren;
   `CITATION.cff` strukturiert parsen (`preferred-citation` bevorzugt)
6. Jeden Kandidaten über arXiv-API bzw. Crossref zu CSL-JSON auflösen
7. Erfolgreich aufgelöste Kandidaten via `vault.add_paper()` ablegen
   (Dedup über bestehende DOI-Logik des Vaults)
8. Ergebnis melden: N Kandidaten gefunden/abgelegt, oder verständliche
   Meldung ohne Treffer

## Abgrenzung

- **Kein `git clone`, kein Checkout, keine Ausführung von Code aus dem
  analysierten Repository** — ausschließlich Lesezugriffe auf die
  öffentliche GitHub-REST-API (README + `CITATION.cff` als Text/Metadaten).
- Kein Cross-Skill-Import aus `reading-list-import`: eigenständige
  Resolver-Implementierung (`resolve_arxiv_id`, `resolve_doi`), analog im
  Muster, aber ohne Code-Teilung.
- Liefert Kandidaten, keine Bewertung der Repo-Qualität oder des Codes selbst.
- Findet der Skill keine Referenz, wird das offen gemeldet — es wird
  niemals ein Paper fabriziert oder geraten.

## Sicherheitshinweise

- **Read-only Netz**: Nur lesende API-Zugriffe (GitHub, arXiv, Crossref)
- **Keine Schreib-/Ausführ-Operationen gegen das Zielrepo**: kein Klonen,
  kein Checkout, kein Aufruf von Skripten/Code aus dem Repo
- **Kein Schreiben in externe Systeme**: Nur der lokale Vault wird beschrieben
- **Provenance-Tag**: jeder Vault-Eintrag trägt `provenance="github-repo"`
  für den Audit-Trail (analog Issue #195)

## Bekannte Einschränkungen

- Regex-Erkennung deckt nicht jedes README-Format ab (z.B. reine
  Freitext-Erwähnungen ohne Link/ID) — dokumentierte Einschränkung, kein
  Anspruch auf Vollständigkeit
- GitHub-API-Rate-Limit (60 Requests/Stunde ohne Token) kann zu 403/429
  führen — wird wie Netzwerkfehler behandelt (kein Crash, leeres Ergebnis)
- `CITATION.cff`-Schema variiert zwischen Repos (`preferred-citation` vs.
  Top-Level-Felder, fehlende Keys) — Parsing ist rein `.get()`-basiert
- Netzausfälle bei arXiv/Crossref führen zu übersprungenen Kandidaten statt
  Crash oder fabriziertem Fallback-CSL
