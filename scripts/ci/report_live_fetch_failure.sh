#!/usr/bin/env bash
# Wertet einen JUnit-XML-Report (von `pytest --junitxml`) aus und legt fuer
# jeden fehlgeschlagenen Testfall ein GitHub-Issue an, das den betroffenen
# Testfall/Fetcher im Titel nennt (Issue #603, AC4). Aufgerufen aus
# .github/workflows/live-fetch-weekly.yml nach den beiden Live-Suiten
# (tests/test_issue_449_live_fetch.py, tests/test_issue_450_live_fetch.py).
#
# Wiederholte Fehlschlaege DESSELBEN Testfalls erzeugen kein Duplikat: Dedup
# laeuft ueber das feste Label "live-fetch-failure" + einen Marker-Substring
# (Testname) im Issue-Titel, lokal per `jq` gefiltert -- bewusst KEINE
# `gh issue list --search`-Volltextsuche, weil GH-Suchoperatoren `::`/`[]`
# in pytest-Node-IDs (z.B.
# "tests/test_issue_449_live_fetch.py::test_jstor_...") falsch interpretiert
# wuerden (siehe Plan-Kommentar zu #603 und das analoge Dedup-Muster in
# .claude/hooks/inject-context.sh, stranded_work()). Mehrere gleichzeitig
# ausgefallene Fetcher erzeugen je EIN eigenes Issue -- keine Buendelung,
# sonst waere der betroffene Fetcher im Titel nicht mehr eindeutig benannt.
#
# Usage: report_live_fetch_failure.sh <junit-xml-path> [<workflow-run-url>]
#
#   <junit-xml-path>    von `pytest --junitxml=...` erzeugte Datei
#   <workflow-run-url>  optional, wird im Issue-Body verlinkt
#
# Voraussetzungen: `gh` authentifiziert (GH_TOKEN/GITHUB_TOKEN mit
# issues:write gesetzt), `jq` und `python3` im PATH.
set -euo pipefail

JUNIT_PATH="${1:?Usage: report_live_fetch_failure.sh <junit-xml-path> [<workflow-run-url>]}"
RUN_URL="${2:-}"
LABEL="live-fetch-failure"

[ -f "$JUNIT_PATH" ] || { echo "FEHLER: JUnit-Report nicht gefunden: $JUNIT_PATH" >&2; exit 1; }

# Fehlgeschlagene/fehlerhafte Testfaelle als pytest-Node-IDs extrahieren
# (klassischer JUnit-Report von pytest: <testsuite>/<testsuites> mit
# <testcase classname="tests.modul" name="test_x"><failure/oder<error/></testcase>).
# Der Modulpfad wird aus dem gepunkteten classname rekonstruiert, wie pytest
# ihn selbst aus der Verzeichnisstruktur ableitet.
FAILED_NODE_IDS="$(python3 -c '
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
for suite in suites:
    for tc in suite.findall("testcase"):
        if tc.find("failure") is not None or tc.find("error") is not None:
            classname = tc.get("classname", "")
            name = tc.get("name", "")
            path = (classname.replace(".", "/") + ".py") if classname else ""
            print(f"{path}::{name}" if path else name)
' "$JUNIT_PATH")"

if [ -z "$FAILED_NODE_IDS" ]; then
  echo "Keine fehlgeschlagenen Testfaelle in $JUNIT_PATH -- nichts zu melden."
  exit 0
fi

# Label idempotent sicherstellen -- `gh issue create --label` schlaegt fehl,
# wenn das Label im Repo noch nicht existiert. `|| true`: existiert es
# schon, ist der Fehlschlag erwartet und kein Problem.
gh label create "$LABEL" \
  --color "d73a4a" \
  --description "Woechentlicher Live-Fetch-Lauf ist fuer einen Fetcher fehlgeschlagen (Issue #603)" \
  >/dev/null 2>&1 || true

report_one() {
  local node_id="$1"
  # Marker: der Testfunktionsname nach dem letzten "::" -- menschenlesbar
  # auf den betroffenen Fetcher schliessend (z.B. "test_cambridge_core_..."),
  # ohne Dateipfad/Doppelpunkte.
  local marker="${node_id##*::}"

  # Plain JSON von gh, gefiltert mit echtem `jq --arg` -- gh's eigenes
  # `--jq` nimmt nur einen Ausdruck ohne Moeglichkeit, `--arg` mitzugeben,
  # waere also fuer einen sicher escapeten Marker-Vergleich ungeeignet.
  local existing
  existing="$(gh issue list --state open --label "$LABEL" --json number,title \
    | jq -r --arg m "$marker" '[.[] | select(.title | contains($m))][0].number // empty')"

  if [ -n "$existing" ]; then
    echo "Bestehendes Issue #$existing deckt '$marker' bereits ab -- kein Duplikat angelegt."
    return 0
  fi

  local title="live-fetch: ${marker} schlaegt fehl"
  local body="Der woechentliche Live-Fetch-Lauf (\`.github/workflows/live-fetch-weekly.yml\`) meldet einen Fehlschlag fuer:

\`\`\`
${node_id}
\`\`\`
"
  if [ -n "$RUN_URL" ]; then
    body="${body}
Lauf: ${RUN_URL}
"
  fi
  body="${body}
Automatisch angelegt (Issue #603). Dedup ueber Label \`${LABEL}\` + Marker \`${marker}\` im Titel -- ein wiederholter Fehlschlag desselben Testfalls erzeugt kein weiteres Issue."

  local create_out new_number
  create_out="$(gh issue create --title "$title" --body "$body" --label "$LABEL")"
  new_number="${create_out##*/}"
  echo "Neues Issue #$new_number angelegt fuer '$marker' ($create_out)."
}

status=0
while IFS= read -r node_id; do
  [ -n "$node_id" ] || continue
  report_one "$node_id" || status=1
done <<EOF
$FAILED_NODE_IDS
EOF

exit "$status"
