# Einrichtung durch den Operator (einmalig)

Danach baut eine Lead-Sitzung in der Claude-Cloud bis zum veröffentlichten Release v0.1.0, ohne dass du etwas tun musst. Reihenfolge einhalten; Schritt 1 muss vor Schritt 4 erledigt sein.

1. **Bypass im Ruleset 25426278 eintragen, bevor der Bootstrap-PR gemergt wird.** GitHub → Repository `ahlerjam/academic-research` → Settings → Rules → Rulesets → Ruleset 25426278 → Abschnitt „Bypass list" → **Add bypass** → Rolle „Repository admin" suchen, auswählen, **Add Selected** → im Menü (⋯) rechts neben „Always allow" **For pull requests only** wählen → speichern. Ohne diesen Eintrag sperrt dich `protect` nach dem Bootstrap selbst aus, weil es Kernpfade für jeden Autor rot meldet. Required Checks bleiben `gate` und `protect`.
2. **Auto-Merge erlauben.** Settings → General → Abschnitt „Pull Requests" → **Allow auto-merge** anhaken. Die Lead-Sitzung schaltet Auto-Merge je PR ein; GitHub merged erst, wenn `gate` und `protect` grün sind.
3. **Cloud-Umgebung `academic-research` anlegen.** claude.ai/code → im Startbildschirm das erste Bedienelement unter dem Eingabefeld (Umgebungsauswahl) → **New environment**:
   - Name: `academic-research`.
   - Network access: **Full**. Die Stufe „Trusted" (und „Custom" mit `nodejs.org`, `registry.npmjs.org`, `github.com`, `api.github.com` plus „Also include default list of common package managers") deckt Node, npm und GitHub laut Doku ab, aber nicht den Download der Playwright-Browser und nicht beliebige Doku-Seiten; welche Hosts Playwright braucht, ist Nicht verifiziert. Wer enger will: „Custom" wie oben und die Hosts nachtragen, die im ersten Lauf mit `403 host_not_allowed` scheitern.
   - Setup script: den Inhalt von `docs/autonomy/cloud-setup.sh` in das Feld „Setup script" kopieren (das Feld nimmt das Skript selbst, keinen Pfad). In welchem Verzeichnis das Skript startet, ist Nicht verifiziert; schlägt `cat .node-version` fehl, im Skript vorne `cd` auf den Klon setzen.
   - Environment variables (eine Zeile je Wert, `.env`-Format):

     ```
     CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
     CLAUDE_CODE_SUBAGENT_MODEL=sonnet
     GIT_AUTHOR_NAME=<dein Name>
     GIT_AUTHOR_EMAIL=<deine GitHub-noreply-Adresse>
     GIT_COMMITTER_NAME=<dein Name>
     GIT_COMMITTER_EMAIL=<deine GitHub-noreply-Adresse>
     ```

     Kein `NODE_ENV=production` (die Toolchain braucht die devDependencies), kein `GH_TOKEN` und kein anderes Token: GitHub läuft über den Proxy der Cloud, und Umgebungsvariablen sind für jeden lesbar, der die Umgebung nutzt.
4. **Bootstrap-Patch einspielen** (in deinem eigenen Terminal, nicht in einer Claude-Sitzung, weil dort `--admin` gesperrt ist):

   ```
   git switch main && git pull --ff-only
   git switch -c ops/bootstrap
   git am <Pfad zur Patch-Serie>/*.patch
   make setup
   make sync
   make controls-baseline
   make doctor
   make gates-selftest
   git add -A && git commit -m "bootstrap: regenerate synced files and controls baseline"
   git push -u origin ops/bootstrap
   gh pr create --base main --head ops/bootstrap --title "Bootstrap: autonomous build" --body "Operator bootstrap patch, docs/autonomy/operator-patch.md"
   gh pr merge <PR-Nummer> --admin --merge
   ```

   `doctor` und `gates-selftest` müssen grün sein, bevor du pushst. `protect` ist bei diesem PR erwartbar rot (Kernpfade); genau dafür ist der Bypass aus Schritt 1.
5. **Lead-Sitzung starten.** claude.ai/code → Repository `ahlerjam/academic-research`, Branch `main`, Umgebung `academic-research` → den Inhalt von `docs/autonomy/lead-goal.md` als erste Nachricht einfügen (er beginnt mit `/goal`) → senden. Den Berechtigungsmodus im Modus-Menü so wählen, dass die Sitzung ohne Rückfragen arbeitet, aber nie „bypassPermissions"; welcher Modus in der Cloud ohne Rückfragen läuft, ist Nicht verifiziert (Phase-B-Smoke-Test).
6. **Stündliche Wächter-Routine anlegen.** claude.ai/code/routines → **New task** → **Set up manually** → Name `ar-watchdog` → Prompt: Inhalt von `docs/autonomy/watchdog-routine.md` → Trigger „Schedule", stündlich, mit einer Minute nach der vollen Stunde (z. B. xx:07) → **Advanced settings** → Repository `ahlerjam/academic-research`, Cloud environment `academic-research` → Reiter „Connectors": alle entfernen → **Create**. `/schedule` geht nur im lokalen CLI, nicht in einer Cloud-Sitzung. Häufiger als stündlich lässt die Routine nicht zu.
7. **Pausieren und zuschauen.**
   - Pause: Label `conductor:pause` am Status-Issue „Conductor status" setzen (geht auch in der GitHub-App); die Lead-Sitzung startet dann keine neue Einheit, laufende enden regulär. Weiter: Label entfernen.
   - Ganz anhalten: zusätzlich die Routine `ar-watchdog` auf claude.ai/code/routines mit dem Schalter oben ausschalten.
   - Zuschauen: das Status-Issue (Prognose: Einheiten pro Tag, Rest bis zum nächsten Meilenstein und bis v0.1, Stopps durch das Nutzungslimit), die Sitzungsliste auf claude.ai/code oder im Reiter „Code" der Claude-App, die Läufe der Routine auf claude.ai/code/routines, den Verbrauch auf claude.ai/settings/usage.
   - Der einzige menschliche Punkt bleibt die Anfrage an Anthropic: ein Agent legt den Entwurf als Issue an, abschicken kannst nur du. Sie blockiert nichts.
