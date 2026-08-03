# Vault-weite Retraction-Prüfung (Issue #604)

Der Retraction-Check beim Import (`SKILL.md`, Pipeline-Schritt „Retraction-Check")
prüft nur DOIs, die gerade neu importiert werden — ein Einmal-Ereignis pro
Paper. Läuft eine Arbeit über Jahre, kann ein 2024 sauber importiertes Paper
2026 zurückgezogen worden sein, ohne dass es je erneut geprüft wird. Dafür
gibt es das MCP-Tool `vault.check_retractions(max_age_days=90, force=False,
project_dir=".")`.

## Ablauf

1. Iteriert über **alle** Vault-Papers mit `source_kind='literature'` und
   DOI — unabhängig vom Importweg (`zotero-import`, `anchor-paper-survey`,
   `github-repo-research`, `fetch`, dieser Skill). Nutzt dieselbe geteilte
   Crossref-Logik (`academic_vault.retraction`), die auch der Import-Pfad
   in `SKILL.md` verwendet.
2. Prüft standardmäßig nur Papers, die noch nie oder seit mehr als
   `max_age_days` Tagen nicht geprüft wurden (`force=True` erzwingt eine
   erneute Prüfung aller Papers mit DOI).
3. Legt einen Treffer **vor** — anders als der automatische Import-Pfad
   schreibt dieser Weg NIE selbst nach `excluded_sources`. Jeder Treffer
   trägt die Fundstelle (`source`: Crossref-DOI der Retraction-Notiz) sowie
   ein heuristisches `cited_in_chapter`-Flag (Autor-Familienname + Jahr
   gegen `kapitel/**/*.md`).
4. Der Skill präsentiert Treffer, hervorgehoben nach `cited_in_chapter`, und
   fragt bei jedem via `AskUserQuestion`, ob das Paper nach
   `vault.add_excluded_source(paper_id, reason=...)` wandern soll — ein
   Rückzug kann bewusst zitiert bleiben, wenn die Arbeit ihn selbst zum
   Gegenstand hat.
5. Papers ohne DOI erscheinen als „nicht prüfbar" (`no_doi`), ein
   Crossref-Ausfall als sichtbarer Fehler (`error`, `error_count`) — nie als
   stillschweigendes „keine Rückzüge gefunden".

## Trigger-Phrasen

„Rückzüge im Vault prüfen / pruefen", „Retraction-Check über den gesamten
Vault", „zurückgezogene Papers finden", „Vault auf Retractions prüfen".
