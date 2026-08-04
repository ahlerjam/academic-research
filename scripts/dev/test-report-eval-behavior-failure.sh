#!/usr/bin/env bash
# Regressions-Harness fuer scripts/ci/report_eval_behavior_failure.sh (Issue
# #597, AC4). Die eigentlichen Pruefungen (Stub-gh, JUnit-Fixtures, Dedup,
# Praefix-Ueberschneidung, Buendel-Verbot, Label-Idempotenz, Kein-Fehlschlag)
# sind identisch zu scripts/dev/test-report-live-fetch-failure.sh (Issue
# #603) -- beide Report-Skripte teilen sich seit #597 dieselbe generische
# Funktion in scripts/ci/lib/report_pytest_failure.sh. Statt der Logik eine
# zweite, driftende Kopie zu geben, ruft dieser Harness den bestehenden Test
# mit dem neuen Zielskript als Parameter auf.
set -u
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
exec bash "$REPO_ROOT/scripts/dev/test-report-live-fetch-failure.sh" \
  "$REPO_ROOT/scripts/ci/report_eval_behavior_failure.sh"
