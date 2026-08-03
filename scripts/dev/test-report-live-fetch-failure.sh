#!/usr/bin/env bash
# Regressions-Harness fuer scripts/ci/report_live_fetch_failure.sh (Issue #603,
# AC4). Stubbt `gh` (kein echtes Netz/Repo noetig), erzeugt echte JUnit-XML-
# Fixtures und prueft:
#   (a) ein fehlgeschlagener Testfall, kein bestehendes Issue -> `gh issue
#       create` wird genau einmal aufgerufen, Titel enthaelt den Testnamen.
#   (b) bestehendes offenes Issue mit Marker im Titel -> KEIN
#       `gh issue create`-Aufruf (Dedup), Exit 0.
#   (c) Praefix-Ueberschneidung: ein Issue mit nur einem PRAEFIX des Markers
#       im Titel deckt den vollen Marker NICHT ab -> `gh issue create` wird
#       trotzdem aufgerufen.
#   (d) zwei gleichzeitig fehlgeschlagene Testfaelle -> zwei GETRENNTE
#       `gh issue create`-Aufrufe (kein Buendel-Issue, AC4-Kern).
#   (e) `gh label create` schlaegt fehl (Label existiert schon) -> Skript
#       laeuft trotzdem durch (kein harter Fehler).
#   (f) keine Fehlschlaege im Report -> KEIN `gh issue create`-Aufruf.
# Usage: test-report-live-fetch-failure.sh [path-to-script]
set -u
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="${1:-$REPO_ROOT/scripts/ci/report_live_fetch_failure.sh}"
[ -f "$SCRIPT" ] || { echo "FEHLT: $SCRIPT"; exit 1; }
[ -x "$SCRIPT" ] || { echo "NICHT AUSFUEHRBAR (chmod +x fehlt): $SCRIPT"; exit 1; }

JQ_BIN="$(command -v jq 2>/dev/null || true)"
if [ -z "$JQ_BIN" ]; then
  echo "SKIP: jq nicht verfuegbar -- das Skript selbst braucht jq zum Filtern."
  exit 0
fi
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 nicht verfuegbar -- das Skript braucht es zum JUnit-Parsen."; exit 0; }

pass=0; fail=0
ok() { pass=$((pass+1)); }
ko() { echo "FAIL: $1"; fail=$((fail+1)); }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

STUB="$WORK/bin"
mkdir -p "$STUB"

# gh-Stub: protokolliert jeden Aufruf (Subcommand + Args) nach $GH_STUB_CALLS.
#   `gh issue list ...`   -> gibt den Inhalt von $GH_STUB_ISSUES aus (plain
#                            JSON, wie das echte gh ohne --jq).
#   `gh issue create ...` -> gibt eine fortlaufende Fake-Issue-URL aus.
#   `gh label create ...` -> Exit-Code aus $GH_STUB_LABEL_CREATE_RC.
cat > "$STUB/gh" <<'EOSTUB'
#!/usr/bin/env bash
set -u
echo "$*" >> "$GH_STUB_CALLS"
case "${1:-}/${2:-}" in
  label/create)
    exit "${GH_STUB_LABEL_CREATE_RC:-0}"
    ;;
  issue/list)
    cat "$GH_STUB_ISSUES"
    ;;
  issue/create)
    n="$(( $(cat "$GH_STUB_ISSUE_COUNTER" 2>/dev/null || echo 9000) + 1 ))"
    echo "$n" > "$GH_STUB_ISSUE_COUNTER"
    echo "https://github.com/ahlerjam/academic-research/issues/$n"
    ;;
  *)
    echo "gh-Stub: unerwarteter Aufruf: $*" >&2
    exit 1
    ;;
esac
EOSTUB
chmod +x "$STUB/gh"

CALLS="$WORK/calls.log"
COUNTER="$WORK/counter"

# Baut eine minimale, aber echte JUnit-XML mit den uebergebenen
# testcase-Zeilen (jede Zeile: "classname|name|status", status in
# {pass,failure,error}).
make_junit() {
  local out="$1"; shift
  {
    echo '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" tests="1">'
    for spec in "$@"; do
      IFS='|' read -r cls name status <<<"$spec"
      case "$status" in
        pass)    echo "<testcase classname=\"$cls\" name=\"$name\" time=\"0.0\"/>" ;;
        failure) echo "<testcase classname=\"$cls\" name=\"$name\" time=\"0.0\"><failure message=\"boom\">boom</failure></testcase>" ;;
        error)   echo "<testcase classname=\"$cls\" name=\"$name\" time=\"0.0\"><error message=\"boom\">boom</error></testcase>" ;;
      esac
    done
    echo '</testsuite></testsuites>'
  } > "$out"
}

run_script() {
  local issues_json="$1" junit_path="$2" label_rc="${3:-0}"
  : > "$CALLS"
  : > "$COUNTER"
  env PATH="$STUB:$PATH" GH_STUB_CALLS="$CALLS" GH_STUB_ISSUE_COUNTER="$COUNTER" \
    GH_STUB_ISSUES="$issues_json" GH_STUB_LABEL_CREATE_RC="$label_rc" \
    bash "$SCRIPT" "$junit_path" 2>&1
}

EMPTY="$WORK/empty.json"
printf '[]\n' > "$EMPTY"

# --- (a) ein Fehlschlag, keine passenden Issues -> genau 1x issue create --
JUNIT_A="$WORK/a.xml"
make_junit "$JUNIT_A" "tests.test_issue_449_live_fetch|test_cambridge_core_still_serves_the_recorded_pdf|failure"
OUT="$(run_script "$EMPTY" "$JUNIT_A")"; RC=$?
CREATE_CALLS="$(grep -c '^issue create' "$CALLS" || true)"
if [ "$RC" -eq 0 ] && [ "$CREATE_CALLS" = "1" ] \
  && grep -q "test_cambridge_core_still_serves_the_recorded_pdf" "$CALLS"; then ok
else ko "(a) erwartet genau 1x 'issue create' mit Testnamen im Titel, bekam rc=$RC calls='$(cat "$CALLS")' out='$OUT'"; fi

# --- (b) bestehendes offenes Issue mit vollem Marker im Titel -> Dedup ----
DEDUP="$WORK/dedup.json"
cat > "$DEDUP" <<'EOF'
[
  {"number": 42, "title": "live-fetch: test_cambridge_core_still_serves_the_recorded_pdf schlaegt fehl"}
]
EOF
OUT="$(run_script "$DEDUP" "$JUNIT_A")"; RC=$?
CREATE_CALLS="$(grep -c '^issue create' "$CALLS" || true)"
if [ "$RC" -eq 0 ] && [ "$CREATE_CALLS" = "0" ] && printf '%s' "$OUT" | grep -q "#42"; then ok
else ko "(b) erwartet Dedup (0x 'issue create', Hinweis auf #42), bekam rc=$RC calls='$(cat "$CALLS")' out='$OUT'"; fi

# --- (c) Praefix-Ueberschneidung ohne vollen Marker -> KEIN Dedup ---------
PREFIX_ONLY="$WORK/prefix.json"
cat > "$PREFIX_ONLY" <<'EOF'
[
  {"number": 7, "title": "live-fetch: test_cambridge_core schlaegt fehl"}
]
EOF
OUT="$(run_script "$PREFIX_ONLY" "$JUNIT_A")"; RC=$?
CREATE_CALLS="$(grep -c '^issue create' "$CALLS" || true)"
if [ "$RC" -eq 0 ] && [ "$CREATE_CALLS" = "1" ]; then ok
else ko "(c) Praefix-Titel darf den vollen Marker nicht abdecken, bekam rc=$RC calls='$(cat "$CALLS")' out='$OUT'"; fi

# --- (d) zwei gleichzeitige Fehlschlaege -> zwei getrennte Issues ---------
JUNIT_D="$WORK/d.xml"
make_junit "$JUNIT_D" \
  "tests.test_issue_449_live_fetch|test_cambridge_core_still_serves_the_recorded_pdf|failure" \
  "tests.test_issue_450_live_fetch|test_hathitrust_download_endpoint_is_still_blocked|error" \
  "tests.test_issue_449_live_fetch|test_jstor_block_reference_rotates|pass"
OUT="$(run_script "$EMPTY" "$JUNIT_D")"; RC=$?
CREATE_CALLS="$(grep -c '^issue create' "$CALLS" || true)"
if [ "$RC" -eq 0 ] && [ "$CREATE_CALLS" = "2" ] \
  && grep -q "test_cambridge_core_still_serves_the_recorded_pdf" "$CALLS" \
  && grep -q "test_hathitrust_download_endpoint_is_still_blocked" "$CALLS" \
  && ! grep -q "test_jstor_block_reference_rotates" "$CALLS"; then ok
else ko "(d) erwartet 2 getrennte 'issue create'-Aufrufe (kein Buendel, passender Test uebersprungen), bekam rc=$RC calls='$(cat "$CALLS")' out='$OUT'"; fi

# --- (e) Label existiert schon (label create schlaegt fehl) -> laeuft durch
OUT="$(run_script "$EMPTY" "$JUNIT_A" "1")"; RC=$?
if [ "$RC" -eq 0 ] && grep -q '^issue create' "$CALLS"; then ok
else ko "(e) label-create-Fehlschlag darf das Skript nicht abbrechen, bekam rc=$RC calls='$(cat "$CALLS")' out='$OUT'"; fi

# --- (f) keine Fehlschlaege -> kein issue create --------------------------
JUNIT_F="$WORK/f.xml"
make_junit "$JUNIT_F" "tests.test_issue_449_live_fetch|test_cambridge_core_still_serves_the_recorded_pdf|pass"
OUT="$(run_script "$EMPTY" "$JUNIT_F")"; RC=$?
CREATE_CALLS="$(grep -c '^issue create' "$CALLS" || true)"
if [ "$RC" -eq 0 ] && [ "$CREATE_CALLS" = "0" ]; then ok
else ko "(f) keine Fehlschlaege: erwartet 0x 'issue create', bekam rc=$RC calls='$(cat "$CALLS")' out='$OUT'"; fi

echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
