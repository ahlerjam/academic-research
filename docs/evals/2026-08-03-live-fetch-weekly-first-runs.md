# `live-fetch-weekly` — erste echte Läufe (Issue #612)

> **Historisches Dokument.** Momentaufnahme der ersten beiden echten Läufe von
> `.github/workflows/live-fetch-weekly.yml`. Wächst nicht automatisch mit
> jedem weiteren Wochenlauf — der aktuelle Live-Test-Status je Fetcher steht
> in der Buchbeschaffungs-Tabelle in
> [`docs/reference/agents.md`](../reference/agents.md#buchbeschaffung).

[← Doku-Übersicht](../README.md)

**Datum:** 2026-08-03
**Auslöser:** Issue #612 Fix-Runde — `live-fetch-weekly.yml` stand seit seiner
Einführung (Issue #603) bei 0 Runs (`gh run list --workflow=live-fetch-weekly.yml`).
Ohne mindestens einen echten Lauf ließ sich AC1 aus #612 ("Auswertung über
mehrere Live-Läufe je Fetcher") nicht erbringen — diese Fix-Runde hat den
Workflow deshalb zweimal manuell per `workflow_dispatch` angestoßen.

## Läufe

| Run | Zeitpunkt (UTC) | Ergebnis | Link |
|-----|-----------------|----------|------|
| 1 | 2026-08-03 20:38 | 3 failed, 12 passed, 1 skipped | [Run 30851138735](https://github.com/ahlerjam/academic-research/actions/runs/30851138735) |
| 2 | 2026-08-03 20:40 | 2 failed, 13 passed, 1 skipped | [Run 30851295819](https://github.com/ahlerjam/academic-research/actions/runs/30851295819) |

Zusätzlich zu den beiden Workflow-Läufen (GitHub-Actions-Runner-IPs) wurde
`pf-07` (Oxford Academic) ein drittes Mal direkt aus einem unabhängigen Netz
abgerufen, um eine reine GH-Actions-IP-Sperre als Erklärung auszuschließen
(siehe Auswertung unten).

## Auswertung je Fetcher

Spalte **Status** folgt dem AC1-Vokabular aus Issue #612: `zuverlässig`,
`wiederholt gebrochen`, `ungeprüft`. Fetcher ohne Live-Test (bereits vor
dieser Fix-Runde in `docs/reference/agents.md` als `ungeprüft` markiert) sind
der Vollständigkeit halber mit aufgeführt, wurden aber nicht erneut geprüft.

| Fetcher | Live-Test | Lauf 1 | Lauf 2 | Status | Begründung |
|---------|-----------|--------|--------|--------|------------|
| `cambridge-core` | `test_cambridge_core_still_serves_the_recorded_pdf` | PASS | PASS | zuverlässig | Byteweise identisches PDF in beiden Läufen (sha256 stabil laut Aufzeichnung). |
| `oxford-academic` | `test_oxford_academic_still_serves_the_recorded_pdf`, `test_oxford_academic_pdf_is_served_without_login` | FAIL (403) | FAIL (403) | **wiederholt gebrochen** — nur der anonyme No-Login-Pfad | Beide Läufe: Cloudflare-Managed-Challenge (`Cf-Mitigated: challenge`, „Just a moment…") statt des 2026-07-29 aufgezeichneten offenen PDF-Zugriffs. Dritter, unabhängiger Abruf außerhalb GitHub Actions bestätigt: keine GH-Actions-IP-Sperre, sondern eine strukturelle Bot-Challenge. Der produktive Zugriffsweg des Agenten (`browser-use` + Shibboleth/OpenAthens) ist von diesem Befund nicht betroffen — er nutzte den anonymen Pfad nie und bleibt ungeprüft. Entscheidung und Beleg: `anonymous_access_correction_612` in `evals/publisher-fetchers/live-verification.json`. |
| `jstor` | `test_jstor_fulltext_endpoint_still_answers_with_a_challenge`, `test_jstor_block_reference_rotates` | PASS | PASS | zuverlässig (erwarteter Zustand: Bot-Challenge) | Konsistent 403 + stabile DOM-Marker der Challenge in beiden Läufen — genau der seit #449 erwartete Ausgang. |
| `internetarchive-fetcher` | `test_internet_archive_still_serves_the_recorded_pdf` u. a. | PASS | PASS | zuverlässig | Byteweise identisches PDF, Metadaten-Bindung ans Item in beiden Läufen bestätigt. |
| `internetarchive-fetcher` (Sub-Test Knoten-Hostname) | `test_internet_archive_redirects_to_an_assigned_node` | FAIL | PASS | Test-Bug, kein Fetcher-Fehler | `ia800108.us.archive.org` (Lauf 1) matchte das zu enge Muster `IA_NODE_HOST_RE` (nur `dn`-Präfix) nicht, `dn720200.ca.archive.org` (Lauf 2, plus ein dritter Abruf) schon. archive.org vergibt Speicherknoten nachweislich unter beiden Präfixen — Muster jetzt korrigiert (`tests/test_issue_450_live_fetch.py`), Regression in `tests/test_issue_450_fetcher_evidence.py::test_ia_node_host_pattern_accepts_both_observed_node_prefixes`. |
| `mdz-fetcher` | `test_mdz_*` (3 Tests) | PASS | PASS | zuverlässig | Rechtehinweis-Gate, normalisierte Prüfsumme und Job-Präfix-Rotation in beiden Läufen wie aufgezeichnet. |
| `hathitrust-fetcher` | `test_hathitrust_*` (3 Tests) | PASS | PASS | zuverlässig (erwarteter Zustand: Sperre) | Download-Endpunkt konsistent gesperrt, Bib-API konsistent offen — wie seit #450 erwartet. |
| `kvk-fetcher` | — | — | — | n/a — kein Volltext-Host | Unverändert (Meta-Suche, kann das PDF-Ebenen-Falsch-Negativ aus #603 nicht erzeugen). |
| `scihub-fetcher` | — | — | — | bewusst ungetestet (Opt-in) | Unverändert (#603 Scope-Out). |
| `tib-fetcher`, `springer-book`, `oapen-fetcher`, `doabooks-fetcher`, `degruyter`, `nationallizenzen`, `ebook-central`, `generic-fetcher`, `auth-helper` | — | — | — | ungeprüft | Kein Live-Test vorhanden — unverändert gegenüber dem AC4-Stand dieser PR. Kein Fund dieser Runde beauftragt einen neuen Live-Test für diese neun Agents. |

## Entscheidung (AC2/AC6)

Von 6 mit Live-Test abgedeckten Fetchern war nach zwei Läufen **einer**
(`oxford-academic`, nur der anonyme No-Login-Pfad) wiederholt gebrochen. Die
Entscheidung stützt sich auf mehr als einen Lauf (AC6: 2 Workflow-Läufe + 1
unabhängiger Cross-Check) und ist in
`evals/publisher-fetchers/live-verification.json` (`anonymous_access_correction_612`)
sowie im CHANGELOG-Eintrag dieser Fix-Runde festgehalten: Der Agent
`agents/oxford-academic.md` bleibt unverändert (kein Beleg für einen Bruch
seines tatsächlichen, Auth-basierten Zugriffswegs; ein Bypass der
Cloudflare-Challenge wäre zudem laut Issue #612 Scope-Out unzulässig).
Repariert wurde stattdessen der dadurch irreführend gewordene Live-Test
(`tests/test_issue_449_live_fetch.py`, jetzt `xfail(strict=True)` für die
beiden betroffenen Tests plus ein neuer Test, der die Challenge aktiv
bestätigt). Der zweite reale Befund — die zu enge `archive.org`-Knoten-Regex —
ist kein Fetcher-Fehler, sondern ein Test-Bug, ebenfalls behoben.

## Notizen

- `report_live_fetch_failure.sh` hat für Lauf 1 automatisch drei Issues
  angelegt (#667, #668, #669) — dedupliziert über das Label
  `live-fetch-failure`. Alle drei sind mit Verweis auf diese Auswertung und
  die jeweiligen Fixes geschlossen.
- Beide Läufe zusammen kosteten keine zusätzlichen API-Kosten (reine
  `urllib`-Abrufe gegen echte Verlags-/Archivseiten, kein LLM-Aufruf).
