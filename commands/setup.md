---
description: Set up the academic research plugin (Python env, browser-use CLI, permissions)
disable-model-invocation: true
allowed-tools: Bash(bash *), Bash(python3 *), AskUserQuestion
argument-hint: [--uni <profil>] [--skip-browser] [--enable-scihub]
---

# Academic Research v5 Setup

Vollständiges Setup über das zentrale Installationsskript. Ein Aufruf, alle Abhängigkeiten, klare Statusmeldungen.

## Ausführung

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh $ARGUMENTS
```

Das Skript übernimmt in acht Schritten:

1. Legt `~/.academic-research/{sessions,pdfs,venv}` an.
2. Erstellt die Python-venv und installiert `httpx`, `pypdf`, `pyyaml`, `openpyxl` (aus `scripts/requirements.txt`).
3. Prüft, ob `browser-use` CLI vorhanden ist. Falls nicht: installiert automatisch via `uv tool install` oder `pipx install`, sofern eines der beiden Tools vorhanden ist. Führt anschließend `browser-use doctor` aus.
4. Prüft, ob der globale `browser-use` Claude-Skill unter `~/.claude/skills/browser-use/` liegt.
4a. Prüft, ob der `humanizer-de`-Skill unter `~/.codex/skills/humanizer-de/`
    global installiert ist. Dieser Skill ist im Plugin bereits vendoriert
    (`skills/humanizer-de/`) und damit immer verfügbar. Der globale Check
    gilt für eigenständige Nutzung außerhalb des Plugins.
    - Gefunden: `✅ humanizer-de Skill (global): vorhanden`
    - Nicht gefunden: `⚠️ humanizer-de Skill (global): nicht gefunden — für eigenständige Nutzung installieren: https://github.com/marmbiz/humanizer-de`
    (kein Hard-Fail — der vendorierte Skill im Plugin bleibt funktionsfähig)
5. **Claude-Code-Permissions (benutzerweit, nicht projektbezogen).** Zeigt die
   neu zu setzenden Regeln über `scripts/configure_permissions.py` an und
   schreibt sie erst nach Bestätigung nach `~/.claude/settings.local.json` —
   diese Datei gilt für **alle** Claude-Code-Projekte auf dem Rechner, nicht
   nur für academic-research. Keine der Regeln erlaubt pauschale
   Codeausführung (nur eng gescopte Muster, z. B.
   `Bash(~/.academic-research/venv/bin/python *)`). Sind bereits alle Regeln
   vorhanden (idempotenter Re-Lauf), entfällt die Rückfrage vollständig.
   **Rücknahme:** die geschriebenen Zeilen manuell aus dem
   `permissions.allow`-Array in `~/.claude/settings.local.json` entfernen.

   **Bestätigungs-Gate, wenn `/setup` (dieser Command) läuft — kein TTY:**
   `setup.sh` läuft ohne Terminal-Eingabe, daher greift in
   `configure_permissions.py` der sichere Default (kein automatisches
   Schreiben) und das Skript meldet sichtbar
   `⚠️ Schritt 5 (Claude-Code-Permissions) nicht abgeschlossen …` samt der
   pending-Regeln. In diesem Fall holt Claude die Bestätigung selbst ein,
   bevor das Setup als abgeschlossen gilt:

   1. Die im Setup-Output aufgelisteten pending-Regeln (`+ Bash(...)`-Zeilen)
      unverändert anzeigen.
   2. Per **AskUserQuestion** fragen, ob diese Regeln jetzt benutzerweit nach
      `~/.claude/settings.local.json` geschrieben werden sollen.
   3. Bei Zustimmung:
      ```bash
      python3 ${CLAUDE_PLUGIN_ROOT}/scripts/configure_permissions.py --yes
      ```
      Bei Ablehnung: nichts weiter tun — Schritt 5 bleibt offen, ein späterer
      `/setup`-Lauf zeigt dieselben pending-Regeln erneut an.

   Läuft `setup.sh` dagegen direkt in einem echten Terminal (nicht über
   Claude Code), fragt `configure_permissions.py` bereits selbst interaktiv
   nach — dieses zusätzliche Gate entfällt dann.
6. **Projekt-Bootstrap (Auto-Detect).** Wenn das aktuelle Verzeichnis ein leerer Ordner ist, fragt `/setup` `"Hier einen Facharbeit-Arbeitsordner initialisieren?"`. Bei `y` werden `academic_context.md` (Stub), `CLAUDE.md`, `.gitignore`, sowie `kapitel/`, `literatur/`, `pdfs/` angelegt. In einem bestehenden Facharbeit-Ordner (mit `academic_context.md`) werden nur fehlende Artefakte nachgezogen — idempotent, keine Rückfrage. In Code-Repos (erkannt an `package.json`, `pyproject.toml`, …) oder nicht-leeren fremden Verzeichnissen: keine Aktion. Findet der Bootstrap zusätzlich bestehenden Kontext in Claude-Memory, bietet er an, ihn einmalig ins Projekt zu kopieren; die Memory-Dateien bleiben als Backup liegen.
7. **Uni-Profil-Setup (F16.5).** Mit `--uni <profil>` (z.B. `/academic-research:setup --uni tum`) wird `config/library-profiles/<profil>.yaml` nicht-interaktiv nach `~/.academic-research/library-profiles/active.yaml` kopiert. Ohne `--uni` fragt das Skript interaktiv (Opt-in), ob jetzt ein Hochschul-Profil gewählt werden soll — bei Zustimmung folgt eine nummerierte Profil-Auswahl. Bei Opt-out oder nicht-interaktivem stdin (z.B. CI) bleibt das aktive Profil leer/Default, ohne Fehler. Verfügbare Profile: siehe [Per-Uni-Profile](../docs/reference/uni-profiles.md). Hinweis: Ein unbekannter `--uni`-Wert bricht das Setup ab (`set -euo pipefail`).
8. **SciHub Opt-in (F18).** Das Skript fragt am Ende:

   ```
   SciHub-Tier aktivieren? (Rechtlich umstritten — Nutzung auf deine eigene Verantwortung)
   SciHub ist ein Dienst, der Zugang zu wissenschaftlichen Artikeln ohne Genehmigung der
   Verlage bereitstellt. Die Nutzung kann in deinem Land gegen das Urheberrecht verstossen.
   Nur aktivieren, wenn du die rechtliche Lage in deinem Land kennst und akzeptierst.
   [j/N] SciHub aktivieren?
   ```

   - **`N` (Default):** `scihub_optin: false` in `~/.academic-research/library-profiles/active.yaml` — SciHub bleibt deaktiviert.
   - **`j`:** `scihub_optin: true` — SciHub wird als letzter Fallback in der Fetch-Pipeline aktiviert. Die rechtliche Aufklärung (dieser Dialog) erfolgt einmalig hier beim Opt-in — läuft der Tier anschließend, geschieht das ohne wiederholte Warnhinweise pro Fund. Die Herkunft bleibt im Vault als `provenance:scihub` nachvollziehbar.

## Interpretation der Ausgabe

| Marker | Bedeutung |
|--------|-----------|
| ✅ Python environment: ready | venv + requirements.txt erfolgreich installiert |
| ✅ browser-use CLI: ready | CLI vorhanden und `browser-use doctor` meldet keinen Fehler |
| ✅ browser-use Claude-Skill: vorhanden | Skill unter `~/.claude/skills/browser-use/` |
| ✅ humanizer-de Skill (global): vorhanden | Skill global unter `~/.codex/skills/humanizer-de/` installiert |
| ⚠️ humanizer-de Skill (global): nicht gefunden | Nur vendorierter Plugin-Skill verfügbar (ausreichend für Plugin-Nutzung) |
| ⚠️ … | siehe Hinweistext direkt unter dem Marker |
| ✅ Facharbeit-Arbeitsordner initialisiert | Projekt-Struktur wurde im aktuellen Verzeichnis angelegt |
| ✅ Uni-Profil '\<profil\>' aktiviert | `config/library-profiles/<profil>.yaml` wurde nach `active.yaml` kopiert |
| ℹ️ Uni-Profil-Setup übersprungen (Default) | Kein `--uni` gesetzt und Opt-in abgelehnt/nicht-interaktiv — aktives Profil bleibt leer/Default |
| ✅ SciHub Opt-in: aktiviert | `scihub_optin: true` in active.yaml — SciHub als Last-Resort aktiv |
| ℹ️ SciHub Opt-in: deaktiviert (Default) | `scihub_optin: false` — SciHub wird nicht genutzt |

## Was passiert, wenn etwas fehlt

- **Ohne `browser-use` CLI:** API-basierte Suchmodule (CrossRef, OpenAlex, Semantic Scholar, BASE, EconBiz, EconStor, arXiv) laufen weiter. Browser-basierte Suchmodule (Scholar, Springer, OECD, RePEc, OPAC, EBSCOhost, ProQuest) werden übersprungen.
- **Ohne `browser-use` Claude-Skill:** Claude fällt bei Browser-Aufrufen auf direkte CLI-Kommandos zurück (funktional identisch, nur ohne den Skill-Wrapper mit seinen Best-Practice-Hinweisen).

## Erneutes Ausführen

Das Skript ist idempotent. Ein zweiter Aufruf:

- erstellt kein zweites venv, installiert nur fehlende Pakete
- überspringt die `browser-use` CLI-Installation, wenn bereits installiert
- wiederholt `browser-use doctor` (harmlos, aktualisiert den Status)
- überschreibt keine Seed-Dateien
- fügt Permissions nur hinzu, wenn sie noch nicht in `~/.claude/settings.local.json` stehen
