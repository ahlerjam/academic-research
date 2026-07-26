#!/usr/bin/env bash
# Regression harness for the DEPLOYED flowkit PreToolUse blocker (#343).
# Tests .claude/hooks/pretooluse-blocker.sh — the file Claude Code actually
# executes — so template drift and broken local edits surface here, not first
# in a live session. Optional $1 overrides the script under test.
# CI: job flowkit-hook-harness in .github/workflows/ci.yml (blocking).
set -u
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="${1:-$REPO_ROOT/.claude/hooks/pretooluse-blocker.sh}"
[ -f "$SCRIPT" ] || { echo "FEHLT: $SCRIPT"; exit 1; }
[ -x "$SCRIPT" ] || { echo "NICHT AUSFÜHRBAR (chmod +x fehlt): $SCRIPT"; exit 1; }
TMP=$(mktemp)
cp "$SCRIPT" "$TMP"
pass=0; fail=0
run() {
  printf '{"tool_input":{"command":%s}}' "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1")" \
    | bash "$TMP" >/dev/null 2>&1
}
must_block() { if run "$1"; then echo "FAIL (durchgelassen): $1"; fail=$((fail+1)); else pass=$((pass+1)); fi; }
must_allow() { if run "$1"; then pass=$((pass+1)); else echo "FAIL (geblockt): $1"; fail=$((fail+1)); fi; }
# Force/Destruktiv-Push auf geschützte Branches
must_block 'git push --force origin main'
must_block 'git push -f origin feature'
must_block 'git push origin --delete main'
must_block 'git push origin :master'
# no-verify / gh-admin / gh-api-Mutationen / Override-Label
must_block 'git commit --no-verify -m x'
must_block 'gh api -X DELETE repos/o/r/issues/1'
must_block 'gh api repos/o/r --method PATCH'
must_block 'gh pr edit 5 --add-label override-claude-review'
# Systemzerstörung + Secrets
must_block 'rm -rf /'
must_block 'chmod 777 /etc'
must_block 'export MY_TOKEN=abcdefghij1234567890'
must_block 'MY_API_KEY=abcdefghij1234567890 ./deploy.sh'
# Legitimes darf NICHT blocken
must_allow 'git push origin feature-branch'
must_allow 'git push origin --delete stale-feature'
must_allow 'git push origin --delete main-backup'
must_allow 'git push origin main'
must_allow 'git commit -m "no verify later"'
must_allow 'gh api repos/o/r/issues --jq length'
must_allow 'gh pr edit 5 --add-label bug'
must_allow 'echo TOKEN=short'
echo "pass=$pass fail=$fail"
rm -f "$TMP"
[ "$fail" -eq 0 ]
