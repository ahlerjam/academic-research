#!/usr/bin/env bash
# Regression harness for the DEPLOYED version-match job in
# .github/workflows/release.yml (Issue #370). Extracts the three "run: |"
# script blocks of the version-match job directly from the workflow file —
# so drift there surfaces here too, not first in a real tag push — and
# executes them as a bash dry run against real / temporarily modified
# manifest files. No `act`, no real tag, no push.
# Optional $1 overrides the workflow file under test.
set -u
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORKFLOW="${1:-$REPO_ROOT/.github/workflows/release.yml}"
[ -f "$WORKFLOW" ] || { echo "FEHLT: $WORKFLOW"; exit 1; }

# Extrahiert die "run: |"-Bloecke des version-match-Jobs in einzelne Dateien.
# Kein YAML-Parser noetig: die Bloecke sind an fester Einrueckung erkennbar
# (Step-Name 6, "run: |" 8, Skript-Body 10 Leerzeichen). Ein NUL-/Trenner-Byte
# als Rueckgabe ueber stdout ist mit awk-Strings nicht verlaesslich moeglich
# (interne C-Strings) — daher schreibt awk direkt eine Datei pro Block.
STEPS_DIR="$(mktemp -d)"
trap 'rm -rf "$STEPS_DIR"' EXIT
awk -v outdir="$STEPS_DIR" '
  /^  version-match:$/ { in_job=1 }
  in_job && /^  [a-zA-Z_-]+:$/ && !/^  version-match:$/ { exit }
  in_job && /^ {8}run: \|$/ { capturing=1; block=""; next }
  capturing && /^ {10}/ { block = block substr($0, 11) "\n"; next }
  capturing { idx++; f = outdir "/step" idx ".sh"; printf "%s", block > f; close(f); capturing=0 }
  END { if (capturing) { idx++; f = outdir "/step" idx ".sh"; printf "%s", block > f; close(f) } }
' "$WORKFLOW"

STEPS=()
for f in "$STEPS_DIR"/step*.sh; do
  [ -e "$f" ] || continue
  STEPS+=("$(cat "$f")")
done
if [ "${#STEPS[@]}" -ne 3 ]; then
  echo "FEHLER: erwarte 3 run-Bloecke im version-match-Job, gefunden: ${#STEPS[@]}"
  echo "(Workflow-Struktur geaendert? Harness an neue Einrueckung/Step-Zahl anpassen.)"
  exit 1
fi

pass=0; fail=0
run_step() {
  local label="$1" script="$2" expect="$3" workdir="$4" extra_env="${5:-}"
  local out rc
  # shellcheck disable=SC2086 # extra_env ist absichtlich ungequotet: einzelnes
  # "KEY=val"-Token soll fuer env in Variable+Wert zerlegt werden (kein Glob-Risiko).
  out="$(cd "$workdir" && env $extra_env bash -c "$script" 2>&1)"
  rc=$?
  if { [ "$expect" = "ok" ] && [ "$rc" -eq 0 ]; } || { [ "$expect" = "fail" ] && [ "$rc" -ne 0 ]; }; then
    pass=$((pass + 1))
  else
    echo "FAIL [$label] erwartet=$expect tatsaechlich rc=$rc"
    echo "$out"
    fail=$((fail + 1))
  fi
}

PLUGIN_VERSION="$(jq -r '.version' "$REPO_ROOT/.claude-plugin/plugin.json")"

echo "== Erfolgsfall: simulierter Tag v$PLUGIN_VERSION gegen echte Manifeste =="
run_step "1 Tag<->plugin.json" "${STEPS[0]}" ok "$REPO_ROOT" "GITHUB_REF_NAME=v$PLUGIN_VERSION"
run_step "2 marketplace.json<->plugin.json" "${STEPS[1]}" ok "$REPO_ROOT"
run_step "3 pyproject.toml<->plugin.json" "${STEPS[2]}" ok "$REPO_ROOT"

echo "== Bruchfall: pyproject.toml mit absichtlich abweichender Version =="
NEG_DIR="$(mktemp -d)"
trap 'rm -rf "$STEPS_DIR" "$NEG_DIR"' EXIT
cp -r "$REPO_ROOT/.claude-plugin" "$NEG_DIR/"
sed -E 's/^version[[:space:]]*=[[:space:]]*".*"/version = "9.9.9"/' \
  "$REPO_ROOT/pyproject.toml" > "$NEG_DIR/pyproject.toml"
run_step "3-neg pyproject.toml!=plugin.json" "${STEPS[2]}" fail "$NEG_DIR"

echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
