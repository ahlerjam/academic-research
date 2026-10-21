#!/bin/bash
# constraint: setup script of the Claude Code cloud environment; runs as root before Claude Code starts and before the repo is known, cached when it stays under about 5 minutes.
# constraint: the SessionStart hook only reports the toolchain; every lead and routine prompt runs make setup first. Keep want in step with .node-version.
# constraint: /opt/node22/bin precedes /usr/local/bin on the session PATH, so Node 24 is unpacked over the image's Node 22.
# constraint: the tarball is unpacked only when its sha256 matches the line of SHASUMS256.txt published next to it on nodejs.org.
set -euo pipefail

want="24.14.1"
if [ "$(/opt/node22/bin/node --version 2>/dev/null)" != "v$want" ]; then
  dir="$(mktemp -d)"
  curl -fsSLo "$dir/node-v$want-linux-x64.tar.xz" "https://nodejs.org/dist/v$want/node-v$want-linux-x64.tar.xz"
  curl -fsSLo "$dir/SHASUMS256.txt" "https://nodejs.org/dist/v$want/SHASUMS256.txt"
  (cd "$dir" && grep " node-v$want-linux-x64.tar.xz\$" SHASUMS256.txt | sha256sum -c -) || { echo "node tarball checksum mismatch" >&2; exit 1; }
  rm -rf /opt/node22/lib/node_modules/npm /opt/node22/lib/node_modules/corepack \
         /opt/node22/bin/npm /opt/node22/bin/npx /opt/node22/bin/corepack /opt/node22/include/node
  tar -xJf "$dir/node-v$want-linux-x64.tar.xz" -C /opt/node22 --strip-components=1
  rm -rf "$dir"
fi
hash -r
node --version
npm --version

npm install --global @ast-grep/cli@0.45.3 || { tail -40 /root/.npm/_logs/*-debug-0.log; exit 1; }
corepack enable
