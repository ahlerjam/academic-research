#!/usr/bin/env bash
# Wertet einen JUnit-XML-Report (von `pytest --junitxml`) aus und legt fuer
# jede fehlgeschlagene Kern-Set-Suite ein GitHub-Issue an, das den
# betroffenen Testfall im Titel nennt (Issue #597, AC4). Aufgerufen aus
# .github/workflows/eval-behavior.yml nach dem geplanten Kern-Set-Lauf
# (`-m eval_core_set`).
#
# Duenner Wrapper um dieselbe generische Funktion, die bereits
# scripts/ci/report_live_fetch_failure.sh (Issue #603) nutzt --
# scripts/ci/lib/report_pytest_failure.sh. Eigenes Label
# (eval-behavior-failure) statt live-fetch-failure, um Namenskollision zu
# vermeiden (Plan-Kommentar zu #597, Risiken).
#
# Usage: report_eval_behavior_failure.sh <junit-xml-path> [<workflow-run-url>]
#
#   <junit-xml-path>    von `pytest --junitxml=...` erzeugte Datei
#   <workflow-run-url>  optional, wird im Issue-Body verlinkt
#
# Voraussetzungen: `gh` authentifiziert (GH_TOKEN/GITHUB_TOKEN mit
# issues:write gesetzt), `jq` und `python3` im PATH.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/report_pytest_failure.sh
source "$SCRIPT_DIR/lib/report_pytest_failure.sh"

JUNIT_PATH="${1:?Usage: report_eval_behavior_failure.sh <junit-xml-path> [<workflow-run-url>]}"
RUN_URL="${2:-}"

report_test_failure \
  "$JUNIT_PATH" \
  "$RUN_URL" \
  "eval-behavior-failure" \
  "eval-behavior" \
  ".github/workflows/eval-behavior.yml" \
  "Issue #597"
