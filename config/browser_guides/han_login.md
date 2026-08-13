# HAN-Login — Shared Auth-Guide für Leibniz FH

> **Aufrufform der CLI:** `config/browser_guides/_cli.md` — Heredoc-Aufruf,
> Helfer, Element-Adressierung, Credential-Regel. Dieser Guide enthält nur
> Site-Wissen.

**URL:** https://han.leibniz-fh.de
**Purpose:** Zentrale Authentifizierung für EBSCOhost, ProQuest, OPAC und weitere lizenzierte Datenbanken der Leibniz FH.
**Credentials-Quelle:** `~/.academic-research/credentials.json` — Keys `han_user`, `han_password`. Falls Datei fehlt oder Keys leer, User informieren und Modul überspringen.

## Login-Flow

1. `https://han.leibniz-fh.de` öffnen.
2. Login-Formular: Felder heißen meist `Benutzername`/`Username` und
   `Passwort`/`Password`. Ein CSS-Selektor trägt hier zuverlässig — sonst über
   den AX-Baum nach der Rolle `textbox` mit passendem Namen suchen.
3. Credentials **nur** aus ENV-Variablen (`BROWSER_USE_USER` /
   `BROWSER_USE_PASS`) über `os.environ` in `fill_input(...)` — nie im
   Skripttext, nie im Prompt. Siehe Abschnitt „Credentials" in `_cli.md`.
4. Absenden per `press_key("Enter")` oder Klick auf den „Login"-Button.
5. Auf Weiterleitung warten (`wait_for_load()`), dann zur Zieldatenbank
   navigieren (meist Link auf der HAN-Portal-Seite).

## Fehlerbehandlung

- Falsche Credentials → die HAN-Seite meldet das im Klartext („Anmeldung
  fehlgeschlagen" o. ä.), erkennbar in `page_info()` bzw. per `js(...)`.
  Abbrechen, User informieren.
- 2FA-Prompt → `capture_screenshot(path=…)`, User muss manuell bestätigen.
  Skill pausiert.
- Wartung-Ankündigung → Datenbank-Zugriff heute unmöglich. User informieren,
  API-Suche fortsetzen.

## Hinweise

- Eine Session reicht meist für alle Leibniz-FH-Datenbanken innerhalb eines Tages.
- Credentials niemals in Logs oder Commits schreiben — Dateipfad ist in `.gitignore`.
