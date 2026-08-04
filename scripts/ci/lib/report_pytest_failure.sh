# shellcheck shell=bash
# Gemeinsame Funktion fuer "geplanter Lauf schlaegt fehl -> Issue anlegen,
# dedupliziert". Extrahiert aus scripts/ci/report_live_fetch_failure.sh
# (Issue #603) im Zuge von Issue #597, das dieselbe Maschinerie fuer
# .github/workflows/eval-behavior.yml braucht -- Wiederverwendung statt
# zweiter, driftender Kopie (Owner-Kommentar zu #597: "Zwei Implementierungen
# mit zwei Gelegenheiten auseinanderzulaufen").
#
# Wertet einen JUnit-XML-Report (von `pytest --junitxml`) aus und legt fuer
# jeden fehlgeschlagenen Testfall ein GitHub-Issue an, das den betroffenen
# Testfall im Titel nennt.
#
# Wiederholte Fehlschlaege DESSELBEN Testfalls erzeugen kein Duplikat: Dedup
# laeuft ueber ein festes Label + einen Marker-Substring (Testname) im
# Issue-Titel, lokal per `jq` gefiltert -- bewusst KEINE
# `gh issue list --search`-Volltextsuche, weil GH-Suchoperatoren `::`/`[]`
# in pytest-Node-IDs (z.B.
# "tests/test_issue_449_live_fetch.py::test_jstor_...") falsch interpretiert
# wuerden (siehe Plan-Kommentar zu #603 und das analoge Dedup-Muster in
# .claude/hooks/inject-context.sh, stranded_work()). Mehrere gleichzeitig
# ausgefallene Faelle erzeugen je EIN eigenes Issue -- keine Buendelung, sonst
# waere der betroffene Fall im Titel nicht mehr eindeutig benannt.
#
# report_test_failure <junit-xml-path> <workflow-run-url> <label> \
#                      <title-prefix> <workflow-path> <issue-ref>
#
#   <junit-xml-path>   von `pytest --junitxml=...` erzeugte Datei
#   <workflow-run-url> optional (leerer String zulaessig), wird im Issue-Body verlinkt
#   <label>             GitHub-Label fuer Dedup + Kennzeichnung (z.B. "live-fetch-failure")
#   <title-prefix>      Praefix im Issue-Titel (z.B. "live-fetch")
#   <workflow-path>     Pfad der auslösenden Workflow-Datei, nur fuer den Issue-Body
#   <issue-ref>         Ausgangs-Issue, das die Automatisierung angelegt hat (z.B. "#603")
#
# Voraussetzungen: `gh` authentifiziert (GH_TOKEN/GITHUB_TOKEN mit
# issues:write gesetzt), `jq` und `python3` im PATH.
report_test_failure() {
  local junit_path="$1"
  local run_url="$2"
  local label="$3"
  local title_prefix="$4"
  local workflow_path="$5"
  local issue_ref="$6"

  [ -f "$junit_path" ] || { echo "FEHLER: JUnit-Report nicht gefunden: $junit_path" >&2; return 1; }

  # Fehlgeschlagene/fehlerhafte Testfaelle als pytest-Node-IDs extrahieren
  # (klassischer JUnit-Report von pytest: <testsuite>/<testsuites> mit
  # <testcase classname="tests.modul" name="test_x"><failure/oder<error/></testcase>).
  # Der Modulpfad wird aus dem gepunkteten classname rekonstruiert, wie pytest
  # ihn selbst aus der Verzeichnisstruktur ableitet.
  local failed_node_ids
  failed_node_ids="$(python3 -c '
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
' "$junit_path")"

  if [ -z "$failed_node_ids" ]; then
    echo "Keine fehlgeschlagenen Testfaelle in $junit_path -- nichts zu melden."
    return 0
  fi

  # Label idempotent sicherstellen -- `gh issue create --label` schlaegt fehl,
  # wenn das Label im Repo noch nicht existiert. `|| true`: existiert es
  # schon, ist der Fehlschlag erwartet und kein Problem.
  gh label create "$label" \
    --color "d73a4a" \
    --description "Geplanter Lauf ($workflow_path) ist fehlgeschlagen ($issue_ref)" \
    >/dev/null 2>&1 || true

  local status=0
  while IFS= read -r node_id; do
    [ -n "$node_id" ] || continue
    _report_pytest_failure_one "$node_id" "$run_url" "$label" "$title_prefix" \
      "$workflow_path" "$issue_ref" || status=1
  done <<EOF
$failed_node_ids
EOF

  return "$status"
}

_report_pytest_failure_one() {
  local node_id="$1" run_url="$2" label="$3" title_prefix="$4" workflow_path="$5" issue_ref="$6"
  # Marker: der Testfunktionsname nach dem letzten "::" -- menschenlesbar auf
  # den betroffenen Fall schliessend, ohne Dateipfad/Doppelpunkte.
  local marker="${node_id##*::}"

  # Plain JSON von gh, gefiltert mit echtem `jq --arg` -- gh's eigenes
  # `--jq` nimmt nur einen Ausdruck ohne Moeglichkeit, `--arg` mitzugeben,
  # waere also fuer einen sicher escapeten Marker-Vergleich ungeeignet.
  local existing
  existing="$(gh issue list --state open --label "$label" --json number,title \
    | jq -r --arg m "$marker" '[.[] | select(.title | contains($m))][0].number // empty')"

  if [ -n "$existing" ]; then
    echo "Bestehendes Issue #$existing deckt '$marker' bereits ab -- kein Duplikat angelegt."
    return 0
  fi

  local title="${title_prefix}: ${marker} schlaegt fehl"
  local body="Der geplante Lauf (\`${workflow_path}\`) meldet einen Fehlschlag fuer:

\`\`\`
${node_id}
\`\`\`
"
  if [ -n "$run_url" ]; then
    body="${body}
Lauf: ${run_url}
"
  fi
  body="${body}
Automatisch angelegt (${issue_ref}). Dedup ueber Label \`${label}\` + Marker \`${marker}\` im Titel -- ein wiederholter Fehlschlag desselben Testfalls erzeugt kein weiteres Issue."

  local create_out new_number
  create_out="$(gh issue create --title "$title" --body "$body" --label "$label")"
  new_number="${create_out##*/}"
  echo "Neues Issue #$new_number angelegt fuer '$marker' ($create_out)."
}
