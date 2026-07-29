#!/usr/bin/env bash
# Regression harness for scripts/dev/check-shell-syntax.sh (#469 AC3).
# Proves the checker actually detects a syntax error (not just that it
# claims to) by running it against a fixture dir with one valid and one
# syntactically broken *.sh file, then re-checks the positive-only case.
# CI: job shell-syntax in .github/workflows/ci.yml (blocking).
set -u
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CHECKER="${1:-$REPO_ROOT/scripts/dev/check-shell-syntax.sh}"
[ -f "$CHECKER" ] || { echo "FEHLT: $CHECKER"; exit 1; }
[ -x "$CHECKER" ] || { echo "NICHT AUSFÜHRBAR (chmod +x fehlt): $CHECKER"; exit 1; }

pass=0
fail=0

expect_fail_with_filename() {
  local dir="$1" expect_name="$2"
  local out
  out="$(bash "$CHECKER" "$dir" 2>&1)"
  local rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "FAIL (sollte fehlschlagen, Exit 0): $dir"
    fail=$((fail + 1))
    return
  fi
  if ! echo "$out" | grep -q "$expect_name"; then
    echo "FAIL (Dateiname fehlt in Fehlermeldung): $dir"
    echo "$out"
    fail=$((fail + 1))
    return
  fi
  pass=$((pass + 1))
}

expect_pass() {
  local dir="$1"
  if bash "$CHECKER" "$dir" >/dev/null 2>&1; then
    pass=$((pass + 1))
  else
    echo "FAIL (sollte durchlaufen, Exit != 0): $dir"
    fail=$((fail + 1))
  fi
}

# --- Fixture 1: nur ein valides Skript -> muss durchlaufen ---
VALID_DIR="$(mktemp -d)"
cat > "$VALID_DIR/ok.sh" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "x" ]; then
  echo "x"
fi
EOF
expect_pass "$VALID_DIR"

# --- Fixture 2: valides + syntaktisch kaputtes Skript (fehlendes `fi`) ---
BROKEN_DIR="$(mktemp -d)"
cat > "$BROKEN_DIR/ok.sh" <<'EOF'
#!/usr/bin/env bash
echo "fine"
EOF
cat > "$BROKEN_DIR/broken.sh" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "x" ]; then
  echo "missing fi"
EOF
expect_fail_with_filename "$BROKEN_DIR" "broken.sh"

# --- Fixture 3: leeres Verzeichnis -> Checker muss selbst fehlschlagen (Fehlkonfigurations-Schutz) ---
EMPTY_DIR="$(mktemp -d)"
if bash "$CHECKER" "$EMPTY_DIR" >/dev/null 2>&1; then
  echo "FAIL (leeres Verzeichnis sollte fehlschlagen): $EMPTY_DIR"
  fail=$((fail + 1))
else
  pass=$((pass + 1))
fi

rm -rf "$VALID_DIR" "$BROKEN_DIR" "$EMPTY_DIR"
echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
