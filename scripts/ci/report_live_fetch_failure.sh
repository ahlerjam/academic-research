#!/usr/bin/env bash
# Wertet einen JUnit-XML-Report (von `pytest --junitxml`) aus und legt fuer
# jeden fehlgeschlagenen Testfall ein GitHub-Issue an, das den betroffenen
# Testfall/Fetcher im Titel nennt (Issue #603, AC4). Aufgerufen aus
# .github/workflows/live-fetch-weekly.yml nach den beiden Live-Suiten
# (tests/test_issue_449_live_fetch.py, tests/test_issue_450_live_fetch.py).
#
# Duenner Wrapper um die generische Funktion in
# scripts/ci/lib/report_pytest_failure.sh (seit Issue #597, das dieselbe
# Maschinerie fuer eval-behavior.yml braucht -- siehe
# scripts/ci/report_eval_behavior_failure.sh). Label, Titel-Praefix und
# Issue-Referenz bleiben unveraendert gegenueber dem Stand vor #597.
#
# Usage: report_live_fetch_failure.sh <junit-xml-path> [<workflow-run-url>]
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

JUNIT_PATH="${1:?Usage: report_live_fetch_failure.sh <junit-xml-path> [<workflow-run-url>]}"
RUN_URL="${2:-}"

report_test_failure \
  "$JUNIT_PATH" \
  "$RUN_URL" \
  "live-fetch-failure" \
  "live-fetch" \
  ".github/workflows/live-fetch-weekly.yml" \
  "Issue #603"
