#!/usr/bin/env bash
# Syntax gate for every tracked shell script in the repo (#469 AC3).
# Runs `bash -n` (parse-only, no execution) over each *.sh file found.
#
# No argument (the CI/default case): scope is `git ls-files '*.sh'` from the
# repo root. That -- rather than a raw `find` -- excludes untracked/generated
# trees (.venv/, .claude/worktrees/, node_modules/) for free: those never
# show up in the tracked-file list.
#
# One argument DIR (used by scripts/dev/test-check-shell-syntax.sh to prove
# failure detection against fixtures without touching the real repo tree):
# scope is every *.sh file under DIR via `find`.
#
# CI: job shell-syntax in .github/workflows/ci.yml (blocking).
set -u
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

fail=0
checked=0
ERR_TMP="$(mktemp)"
trap 'rm -f "$ERR_TMP"' EXIT

check_one() {
  checked=$((checked + 1))
  if ! bash -n "$1" 2>"$ERR_TMP"; then
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
  done < <(find "$DIR" -type f -name '*.sh' -print0 | sort -z)
else
  cd "$REPO_ROOT" || exit 1
  while IFS= read -r -d '' f; do
    check_one "$f"
  done < <(git ls-files -z '*.sh')
fi

if [ "$checked" -eq 0 ]; then
  echo "FEHLER: keine *.sh-Dateien gefunden — Checker vermutlich fehlkonfiguriert."
  exit 1
fi

if [ "$fail" -eq 0 ]; then
  echo "OK: $checked Shell-Skript(e) syntaktisch valide."
fi

exit "$fail"
