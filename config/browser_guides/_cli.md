# browser-use — Aufrufform (kanonisch)

**Diese Datei ist die einzige Stelle im Repo, die beschreibt, wie die
`browser-use`-CLI bedient wird.** Alle Browser-Guides und Fetcher-Agenten
verweisen hierher und enthalten nur noch Site-Wissen (URLs, Filter,
Fallstricke, Pickup-Trigger).

Festgestellt gegen die installierte CLI in Version 0.1.8 (CLI-3-Form). Ändert
sich die CLI, ändert
sich **diese** Datei — und `tests/test_issue_906_browser_use_cli_form.py` fängt
Rückfälle in die alte Form ab.

## Aufruf

Die CLI hat keine Aktions-Unterbefehle mehr. Sie nimmt **Python auf stdin** und
führt es in einer persistenten Browser-Session aus; Daemon-Start, Chrome-/
CDP-Attach, Tab-Verwaltung und Warten übernimmt sie selbst:

```bash
browser-use <<'PY'
ensure_real_tab()
new_tab("https://example.org")
wait_for_load()
print(page_info())
PY
```

Der Heredoc-Delimiter ist **immer gequotet** (`<<'PY'`), damit die Shell nichts
im Skripttext expandiert (siehe „Credentials").

Verbliebene echte Unterbefehle: `--version`, `--doctor` / `doctor`, `auth`,
`skill`, `recordings`, `video`, `telemetry`, `--update`, `--reload`.

Entfernt und ersatzlos weg — die CLI antwortet darauf mit einer
Migrationsmeldung: `open`, `state`, `click`, `input`, `screenshot`, `download`,
`eval`, `cookies`, `python`, `run`, `connect`, `close`, `sessions`, `profile`,
`cloud`, `daemon`, `record`, `mcp`, `--session`, `--headed`, `--cdp-url`,
`--profile`, `--json`, `-c`, `--code`. Ebenfalls ungültig ist die frühere
Prompt-Form, bei der eine Anweisung in Prosa als Argument übergeben wurde
(`browser-use` gefolgt von einem Anführungszeichen) — dieser Text würde heute
als Python ausgeführt und mit einem `SyntaxError` enden.

## Vorimportierte Helfer

Alles unten ist im Heredoc ohne Import verfügbar.

| Zweck | Helfer |
|---|---|
| Navigation | `new_tab(url='about:blank')` — **erste** Navigation; `goto_url(url)` danach |
| Seitenzustand | `page_info()`, `js(expression, target_id=None)`, `current_tab()` |
| Rohes CDP | `cdp(method, session_id=None, **params)` |
| Klicken | `click_at_xy(x, y, button='left', clicks=1)` |
| Eingabe | `fill_input(selector, text, clear_first=True, timeout=0.0)`, `type_text(text)`, `press_key(key, modifiers=0)`, `dispatch_key(selector, key='Enter', event='keypress')` |
| Scrollen | `scroll(x, y, dy=-300, dx=0)` |
| Warten | `wait_for_load(timeout=15.0)`, `wait_for_element(selector, timeout=10.0, visible=False)`, `wait_for_network_idle(timeout=10.0, idle_ms=500)`, `wait(seconds=1.0)` |
| Tabs | `list_tabs(include_chrome=True)`, `switch_tab(target)`, `close_tab(target=None)`, `ensure_real_tab()`, `iframe_target(url_substr)` |
| Screenshot | `capture_screenshot(path=None, full=False, max_dim=None)` |
| Dateien | `upload_file(selector, path)` |
| HTTP ohne Browser | `http_get(url, headers=None, timeout=20.0)` |
| Sonstiges | `drain_events()`, `start_recording(name=None, title=None)`, `stop_recording()`, `recording_dir()`, `Path`, `urlparse` |

Daneben existieren Daemon-/Cloud-Funktionen (`ensure_daemon`, `restart_daemon`,
`start_remote_daemon`, …). Sie gehören nicht in Guides oder Agenten.

## Elemente adressieren — kein Index-Modell mehr

Die alte Form gab über das entfernte `state`-Kommando durchnummerierte Elemente
aus und man klickte „Index 7". **Diese Nummern gibt es nicht mehr.** Zwei Wege
ersetzen sie:

**1. CSS-Selektor, wenn einer trägt** (Suchfelder, Formulare):

```bash
browser-use <<'PY'
fill_input("input[name='q']", "devops governance")
press_key("Enter")
wait_for_load()
PY
```

**2. Accessibility-Baum → Koordinaten → Klick**, wenn kein stabiler Selektor
existiert (Buttons mit sprechendem Label, dynamische Widgets):

```bash
browser-use <<'PY'
nodes = cdp("Accessibility.getFullAXTree")["nodes"]
hits = [
    n for n in nodes
    if n.get("role", {}).get("value") in ("button", "link")
    and "download" in n.get("name", {}).get("value", "").lower()
]
n = hits[0]
q = cdp("DOM.getBoxModel", backendNodeId=n["backendDOMNodeId"])["model"]["content"]
x, y = sum(q[0::2]) / 4, sum(q[1::2]) / 4
click_at_xy(x, y)
wait_for_load()
print(page_info())
PY
```

Der AX-Baum hat leicht tausende Knoten — **in Python filtern, nicht ausgeben**.
Negative oder viel zu große Koordinaten heißen: erst `scroll(...)`, dann erneut
messen. Nach jedem Klick das Ergebnis prüfen (`page_info()` oder ein gezieltes
`js(...)`), nicht blind weiterklicken.

Für reines Auslesen von Trefferlisten ist `js(...)` der direkte Weg:

```bash
browser-use <<'PY'
print(js("""
  [...document.querySelectorAll('.gs_ri')].slice(0, 10).map(r => ({
    title: r.querySelector('.gs_rt')?.innerText,
    meta: r.querySelector('.gs_a')?.innerText,
  }))
"""))
PY
```

## Download

Es gibt **keinen** `download`-Helfer. Der Weg führt über CDP: Zielverzeichnis
setzen, klicken, warten bis die `.crdownload`-Teildatei verschwunden ist.

```bash
browser-use <<'PY'
out = Path("<output_dir>")
out.mkdir(parents=True, exist_ok=True)
cdp("Browser.setDownloadBehavior", behavior="allow",
    downloadPath=str(out), eventsEnabled=True)

# … Download-Button über AX-Baum finden und click_at_xy(...) …

import time
deadline = time.time() + 120
while time.time() < deadline:
    partial = list(out.glob("*.crdownload"))
    done = [p for p in out.glob("*.pdf") if p.stat().st_size > 0]
    if done and not partial:
        break
    wait(1.0)
print([str(p) for p in out.glob("*.pdf")])
PY
```

`http_get()` ist **kein** Ersatz für einen PDF-Download: es dekodiert die
Antwort nach `str` und zerstört damit die PDF-Bytes. `http_get()` nur für
Text/JSON verwenden.

Läuft der Download über eine Direkt-URL ohne Klickstrecke und ohne Session-
Cookie-Zwang, ist `curl`/`Write` der ehrlichere Weg — sofern der Agent das darf.

## Credentials

Passwörter dürfen weder im Skripttext noch in einem Prompt stehen. Sie kommen
aus ENV-Variablen und werden im Heredoc über `os.environ` gelesen:

```bash
BROWSER_USE_USER="…" BROWSER_USE_PASS="…" browser-use <<'PY'
import os
fill_input("input[name='username']", os.environ["BROWSER_USE_USER"])
fill_input("input[name='password']", os.environ["BROWSER_USE_PASS"])
press_key("Enter")
wait_for_load()
print(page_info())
PY
```

Der gequotete Delimiter `<<'PY'` ist hier Pflicht: sonst expandiert die Shell
`$BROWSER_USE_PASS` und der Klartext landet in der sichtbaren Kommandozeile,
in Shell-History und in Hook-Logs. Credential-Variablen nie per `echo`/`print`
ausgeben.

## Verbindung: eigenes Automations-Chrome statt Default-Profil

Ohne weitere Angabe hängt sich die CLI an das laufende Chrome mit dem
Default-Profil. Chrome verlangt dafür seit M144 **pro Verbindung** einen Klick
auf „Allow remote debugging?"; bleibt er aus, endet jeder Aufruf mit
`permission-blocked`. Ein Agent kann diesen Klick nicht auslösen — er ist damit
über den Default-Weg handlungsunfähig.

Der Ausweg braucht keine Bestätigung: ein **eigener** Chrome-Prozess mit
eigenem `--user-data-dir` und offenem Debug-Port, an den sich die CLI über
`BU_CDP_URL` hängt. Ein separates Profil fällt weder unter das Allow-Popup noch
unter die Default-Profil-Sperre; das laufende Chrome des Nutzers bleibt
unangetastet.

```bash
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE="$(mktemp -d)/chrome-automation"

"$CHROME" --remote-debugging-port=9333 --user-data-dir="$PROFILE" \
  --no-first-run --no-default-browser-check about:blank &
until curl -sf http://127.0.0.1:9333/json/version > /dev/null; do sleep 1; done

BU_CDP_URL=http://127.0.0.1:9333 browser-use <<'PY'
ensure_real_tab()
new_tab("https://example.org")
wait_for_load()
print(page_info())
PY
```

`BU_CDP_URL` ist der **HTTP**-Endpunkt (`http://host:port`), nicht die
WebSocket-URL — die löst die CLI selbst auf. `BU_CDP_URL` muss bei **jedem**
Aufruf gesetzt sein, sonst greift wieder der Default-Weg.

Das frische Profil hat keine Logins und keine Cookies. Für Guides hinter einer
Anmeldung (`han_login`, `nationallizenzen`, Verlagszugänge) heißt das: entweder
im Automations-Chrome anmelden — die Session hält, solange das Profil liegen
bleibt — oder das Default-Profil nehmen und den Klick beim Nutzer einholen.

## Fehlerpfade

- Verbindet sich der Daemon nicht: `browser-use --doctor`. Läuft Chrome gar
  nicht, startet die CLI es selbst.
- `permission-blocked` oder „Chrome is asking 'Allow remote debugging?'":
  Default-Profil-Weg. Auf das Automations-Chrome oben umsteigen; nur wenn
  genau dieses Profil gebraucht wird, den Nutzer um den Klick bitten. **Nicht
  in einer Schleife wiederholen** — Chrome öffnet für jede neue Verbindung ein
  neues Popup.
- Läuft Chrome, ist aber Remote-Debugging aus, öffnet die CLI
  `chrome://inspect/#remote-debugging` — der Nutzer muss „Allow remote debugging
  for this browser instance" bestätigen. Danach denselben Aufruf wiederholen.
- Stale oder interner Tab: `ensure_real_tab()` vor der ersten Navigation.
- CAPTCHA/Login-Wall: `capture_screenshot(path=…)` sichern, den entsprechenden
  `status` melden, **nicht** in einer Schleife erneut versuchen.
