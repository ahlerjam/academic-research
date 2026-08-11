# Release-Weg

[← Doku-Übersicht](README.md)

Wie ein Release entsteht — vom sauberen `main`-Stand bis zum GitHub-Release. Das
**Tag-Setzen und das Anlegen des GitHub-Release wirken nach außen und sind schwer
rücknehmbar — das macht ausschließlich ein Mensch**, nie ein Agent. Diese Seite ist so
geschrieben, dass sie ohne weiteren Repo-Kontext abarbeitbar ist.

## Wann eine Version erhöht wird

Nach [Semantic Versioning](https://semver.org/lang/de/): `MAJOR.MINOR.PATCH`.

- **MAJOR** — Breaking Change für Installationen oder Datenformat (z. B. Vault-Schema,
  entfernte Skills/Commands), oder ein Umbau groß genug, dass er einen benannten,
  zitierfähigen Stand verdient (Referenzfall: `v8.0.0` selbst — der Sprung über `7.x`
  hinweg folgt der Größe des Retrieval-/Eval-/MCP-Umbaus, nicht einer lückenlosen
  Zählung).
- **MINOR** — neues Feature, neuer Skill/Agent/Command, rückwärtskompatibel.
- **PATCH** — Bugfix, Doku, interne Härtung ohne sichtbares neues Verhalten.

Ein Release ist **nicht** an einen Kalender gebunden. Es entsteht, wenn genug seit dem
letzten Tag zusammengekommen ist, um einen benannten Stand zu rechtfertigen — nicht bei
jedem Merge.

## Prüfliste vor dem Tag

Alles muss grün sein, bevor `git tag` läuft:

1. **Lokale Gates grün** (siehe [Entwicklung, Tests und Evals](development.md)):
   ```bash
   uv run pytest tests/ --ignore=tests/evals
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy
   bash scripts/dev/check-mjs-syntax.sh
   bash scripts/dev/test-pretooluse-blocker.sh
   bash scripts/dev/check-shell-syntax.sh
   ```
2. **Versionsgleichstand** zwischen allen drei Manifesten — von Hand oder per Harness:
   ```bash
   jq -r .version .claude-plugin/plugin.json
   jq -r .plugins[0].version .claude-plugin/marketplace.json
   grep -m1 '^version' pyproject.toml
   bash scripts/dev/test-release-version-match.sh
   ```
   Alle drei Werte müssen identisch sein — `plugin.json` == `pyproject.toml` ==
   `marketplace.json`. `uv.lock` enthält einen eigenen `version`-Eintrag für das Paket
   selbst; nach jeder Versionsänderung `uv lock` laufen lassen und das aktualisierte
   `uv.lock` mit committen, sonst driftet es gegen `pyproject.toml`.
3. **Badges und Zähler gegen das Dateisystem verifiziert, nicht geschätzt:**
   ```bash
   find skills -maxdepth 2 -name "SKILL.md" | wc -l    # Skills
   find agents -maxdepth 1 -name "*.md" | wc -l         # Agents
   ```
   Ergebnisse müssen übereinstimmen mit:
   - `README.md` — Version- und Skills-Badge (Kopfzeile)
   - `AGENTS.md` — Kopfzeile („N Skills, M Agents")
   - `.claude-plugin/plugin.json` — `description`
   - `.claude-plugin/marketplace.json` — `plugins[0].description`

   `skills/_common/` zählt nicht als Skill (nur geteilte Markdown-Fragmente, keine
   eigene `SKILL.md`) — deshalb `find ... -name "SKILL.md"`, nicht `-type d`.
4. **`CHANGELOG.md` aktuell:** Abschnitt `[Unreleased]` in `[X.Y.Z] — YYYY-MM-DD`
   umbenannt, Compare-Link-Fußzeile ergänzt (`[X.Y.Z]: .../compare/vVORHER...vX.Y.Z`),
   Einträge nach Vorhaben/Issue gegliedert statt als rohe Commit-Liste.
5. **Release-Notes-Entwurf** unter `docs/release-notes/<X.Y.Z>.md` vorhanden, nennt
   Kann/Kann-nicht (Beispiel: [`docs/release-notes/8.0.0.md`](release-notes/8.0.0.md)).
6. **Saubere Arbeitskopie:** `git status` zeigt nichts Uncommittetes, `main` ist auf
   dem Stand von `origin/main`.

## Der Weg selbst

1. Prüfliste oben vollständig abarbeiten, alle Änderungen über einen normalen PR nach
   `main` gemergt (kein direkter Push auf `main`).
2. Auf dem gemergten `main`-Stand: `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. Der Tag-Push löst `.github/workflows/release.yml` aus (Job `version-match`):
   - Tag-Version vs. `plugin.json`
   - `marketplace.json` vs. `plugin.json`
   - `pyproject.toml` vs. `plugin.json`

   Jede Abweichung lässt den Job mit `::error::` fehlschlagen — das Release stoppt hier,
   bevor irgendetwas veröffentlicht ist. Bei Erfolg gibt ein zweiter Job
   (`marketplace-notice`) einen Hinweis aus, dass der Marketplace-Refresh automatisch
   beim nächsten Plugin-Sync erfolgt (kein Push-Mechanismus).
4. **Manuell, durch den Menschen:** `gh release create vX.Y.Z --title "vX.Y.Z" --notes-file docs/release-notes/X.Y.Z.md`
   (oder gleichwertig über die GitHub-UI). Das ist der einzige Schritt, der nach außen
   sichtbar wird und in dieser Doku bewusst nicht automatisiert ist.

## CI-Job-Entscheidung: `version-match` bleibt wie er ist

`.github/workflows/release.yml` prüft den Versionsgleichstand bereits — aber nur
**tag-getriggert**, nicht bei jedem PR. Entscheidung: **beibehalten, kein zusätzlicher
PR-Zeit-Check.**

Begründung:

- Der PR-Zeit-Punkt ist der falsche Zeitpunkt für diese Prüfung. Zwischen zwei Releases
  laufen viele PRs, ohne dass die Version bei jedem einzelnen angehoben wird — ein
  PR-Gate würde entweder ständig rot sein (falscher Alarm) oder müsste erkennen, *ob*
  ein PR eine Versionsänderung enthält (zusätzliche Komplexität für einen Fall, der nur
  beim eigentlichen Release-Vorbereitungs-PR eintritt).
- Der Tag-Push ist der Moment, in dem die Version tatsächlich Konsequenzen hat
  (Release wird sichtbar) — genau dort greift der Job und stoppt vor der
  Veröffentlichung, nicht danach. Das ist der sicherheitsrelevante Zeitpunkt.
- `scripts/dev/test-release-version-match.sh` deckt denselben Vergleich bereits lokal
  ab (Schritt 2 der Prüfliste oben) — wer die Prüfliste befolgt, bekommt den Check vor
  dem Tag, nicht erst danach vom CI-Job.
- Das Label `area/ci` auf Issue #738 bezieht sich auf diesen bestehenden Job (er wird
  referenziert und dokumentiert), nicht auf eine inhaltliche Änderung an
  `.github/workflows/release.yml` — die Datei bleibt in diesem Release unverändert.

Diese Einschätzung gilt für den aktuellen Repo-Stand; sie kann sich ändern, wenn
Release-Vorbereitungs-PRs künftig regelmäßig Versionsdrift zwischen den drei Manifesten
zeigen, ohne dass jemand die Prüfliste befolgt.
