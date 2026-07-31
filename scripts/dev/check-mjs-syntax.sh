#!/usr/bin/env bash
# Syntax gate for every tracked ESM file in the repo (#542).
# Runs `node --check` (parse-only, no execution) over each *.mjs file found.
#
# Why a script instead of an inline loop in ci.yml: the CI step used to iterate
# over the shell glob `hooks/*.mjs`, which does NOT recurse. That single
# non-recursive glob dictated the directory layout -- `hooks/vault-bridge.mjs`
# stayed flat in `hooks/` purely so the gate would still see it -- and it
# silently dropped coverage the moment a file moved into `hooks/lib/`.
# Scope is therefore the tracked-file list, not a hand-written glob.
#
# No argument (the CI/default case): scope is `git ls-files '*.mjs'` from the
# repo root. That -- rather than a raw `find` -- excludes untracked/generated
# trees (.venv/, .claude/worktrees/, node_modules/) for free: those never
# show up in the tracked-file list.
#
# One argument DIR (used by tests/test_issue_542_hooks_layout.py to prove
# failure detection against fixtures without touching the real repo tree):
# scope is every *.mjs file under DIR via `find`.
#
# CI: job hook-syntax in .github/workflows/ci.yml (blocking).
set -u
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

fail=0
checked=0
ERR_TMP="$(mktemp)"
trap 'rm -f "$ERR_TMP"' EXIT

check_one() {
  checked=$((checked + 1))
  if ! node --check "$1" 2>"$ERR_TMP"; then
    echo "SYNTAXFEHLER: $1"
    sed "s|^|  |" "$ERR_TMP"
    fail=1
  fi
}

if [ "$#" -ge 1 ]; then
  DIR="$1"
  [ -d "$DIR" ] || { echo "FEHLER: kein Verzeichnis: $DIR"; exit 1; }
  while IFS= read -r -d '' f; do
    check_one "$f"
  done < <(find "$DIR" -type f -name '*.mjs' -print0 | sort -z)
else
  cd "$REPO_ROOT" || exit 1
  while IFS= read -r -d '' f; do
    check_one "$f"
  done < <(git ls-files -z '*.mjs')
fi

if [ "$checked" -eq 0 ]; then
  echo "FEHLER: keine *.mjs-Dateien gefunden — Checker vermutlich fehlkonfiguriert."
  exit 1
fi

if [ "$fail" -eq 0 ]; then
  echo "OK: $checked ESM-Datei(en) syntaktisch valide."
fi

exit "$fail"
