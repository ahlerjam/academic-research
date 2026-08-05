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
# .claude/hooks/inject-context.sh, stranded_work()). Bis zu MAX_INDIVIDUAL_ISSUES
# (5) gleichzeitig ausgefallene Faelle erzeugen je EIN eigenes Issue -- keine
# Buendelung, der betroffene Fall bleibt im Titel eindeutig benannt. Alles
# darueber hinaus (korrelierter Ausfall -- Modell-Drift, Quota-Abbruch
# mitten im Lauf) landet gebuendelt in GENAU EINEM Sammel-Issue, das die
# betroffene(n) Suite(n) im Titel nennt (AC4 bleibt erfuellt: Fehlschlag ->
# Issue), statt Dutzende bis Hunderte Einzel-Issues plus GitHub
# Secondary-Rate-Limit zu riskieren.
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

# Deckel fuer Einzel-Issues pro Lauf -- siehe Kommentar oben. Alles jenseits
# dieser Zahl wandert ins Sammel-Issue statt in weitere Einzel-Issues.
MAX_INDIVIDUAL_ISSUES=5

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

  # Reihenfolge erhalten: die ersten MAX_INDIVIDUAL_ISSUES Faelle bekommen je
  # ein eigenes Issue, alles danach wird gebuendelt (siehe Kommentar oben).
  local total individual_ids overflow_ids
  total="$(printf '%s\n' "$failed_node_ids" | grep -c .)"
  individual_ids="$(printf '%s\n' "$failed_node_ids" | head -n "$MAX_INDIVIDUAL_ISSUES")"
  overflow_ids=""
  if [ "$total" -gt "$MAX_INDIVIDUAL_ISSUES" ]; then
    overflow_ids="$(printf '%s\n' "$failed_node_ids" | tail -n "+$((MAX_INDIVIDUAL_ISSUES + 1))")"
  fi

  local status=0
  while IFS= read -r node_id; do
    [ -n "$node_id" ] || continue
    _report_pytest_failure_one "$node_id" "$run_url" "$label" "$title_prefix" \
      "$workflow_path" "$issue_ref" || status=1
  done <<EOF
$individual_ids
EOF

  if [ -n "$overflow_ids" ]; then
    _report_pytest_failure_bundle "$overflow_ids" "$run_url" "$label" "$title_prefix" \
      "$workflow_path" "$issue_ref" || status=1
  fi

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
  # --limit 200: der gh-Default liefert hoechstens 30 Eintraege -- bei mehr
  # offenen Issues mit demselben Label bricht die Dedup-Pruefung sonst
  # lautlos (P2-Fund, Issue #597 Review).
  local existing
  existing="$(gh issue list --state open --label "$label" --limit 200 --json number,title \
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

# Sammel-Issue fuer alles jenseits von MAX_INDIVIDUAL_ISSUES: EIN Issue statt
# vieler, mit den Einzelfaellen im Body und der/den betroffenen Suite(n) im
# Titel (AC4 -- "Fehlschlag -> Issue" -- bleibt damit erfuellt, ohne bei
# korreliertem Ausfall Dutzende bis Hunderte Issues zu erzeugen).
_report_pytest_failure_bundle() {
  local overflow_ids="$1" run_url="$2" label="$3" title_prefix="$4" workflow_path="$5" issue_ref="$6"

  local count
  count="$(printf '%s\n' "$overflow_ids" | grep -c .)"

  # Betroffene Suite(n) -- der Dateipfad vor "::", eindeutig und sortiert,
  # kommasepariert. Das ist die "gerissene Suite" im Titel (AC4).
  local suites
  suites="$(printf '%s\n' "$overflow_ids" | sed 's/::.*//' | sort -u | paste -sd, - | sed 's/,/, /g')"

  # Marker fuer Dedup: Label + diese Zeichenkette. Bewusst OHNE die
  # veraenderliche Fallzahl -- ein wiederholter Sammelfehler in derselben
  # Suite soll kein zweites Sammel-Issue erzeugen, auch wenn sich die Zahl
  # der ueberzaehligen Faelle von Lauf zu Lauf leicht verschiebt.
  local marker="Sammelfehler in ${suites}"

  local existing
  existing="$(gh issue list --state open --label "$label" --limit 200 --json number,title \
    | jq -r --arg m "$marker" '[.[] | select(.title | contains($m))][0].number // empty')"

  if [ -n "$existing" ]; then
    echo "Bestehendes Sammel-Issue #$existing deckt '$marker' bereits ab -- kein Duplikat angelegt."
    return 0
  fi

  local title="${title_prefix}: ${marker} -- ${count} weitere Faelle"
  local body="Der geplante Lauf (\`${workflow_path}\`) meldet ${count} weitere fehlgeschlagene Faelle jenseits der ersten ${MAX_INDIVIDUAL_ISSUES} Einzel-Issues -- gebuendelt in diesem einen Issue, um bei korreliertem Ausfall (Modell-Drift, Quota-Abbruch mitten im Lauf) keine Issue-Flut samt GitHub-Secondary-Rate-Limit auszuloesen:

\`\`\`
${overflow_ids}
\`\`\`
"
  if [ -n "$run_url" ]; then
    body="${body}
Lauf: ${run_url}
"
  fi
  body="${body}
Automatisch angelegt (${issue_ref}). Dedup ueber Label \`${label}\` + Marker \`${marker}\` im Titel -- ein wiederholter Sammelfehler in derselben Suite erzeugt kein weiteres Sammel-Issue."

  local create_out new_number
  create_out="$(gh issue create --title "$title" --body "$body" --label "$label")"
  new_number="${create_out##*/}"
  echo "Neues Sammel-Issue #$new_number angelegt fuer ${count} weitere Faelle in ${suites} ($create_out)."
}
