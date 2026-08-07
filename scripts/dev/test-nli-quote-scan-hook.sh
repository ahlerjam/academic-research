#!/usr/bin/env bash
# Regression-Harness fuer hooks/nli-quote-scan.mjs (Issue #717).
#
# Aufbau analog scripts/dev/test-pretooluse-blocker.sh: der Hook wird als
# echter Prozess mit echtem stdin gefahren, nicht importiert. Geprueft wird
# ausschliesslich beobachtbares Verhalten — Exit-Code, stdout-JSON, und ob ein
# Worker gestartet wurde.
#
# Der Worker wird NIE echt gestartet: ACADEMIC_PYTHON zeigt auf ein
# Stub-Skript, das seinen Start protokolliert und dann schlaeft. Damit ist
# beweisbar, dass der Hook nicht auf den Scan wartet (AC1) und dass er in den
# stummen Faellen gar nicht erst spawnt.
#
# Aufruf: bash scripts/dev/test-nli-quote-scan-hook.sh
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO_ROOT/hooks/nli-quote-scan.mjs"

WORK="$(mktemp -d)"
cleanup() {
  # Die Stub-Worker schlafen bewusst lange (Beweis, dass der Hook nicht auf
  # sie wartet) — am Ende werden sie eingesammelt statt liegen gelassen.
  if [ -f "$WORK/pids" ]; then
    while read -r pid; do kill "$pid" 2>/dev/null || true; done < "$WORK/pids"
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

pass=0
fail=0

ok() { pass=$((pass + 1)); return 0; }
bad() { echo "FAIL: $1"; fail=$((fail + 1)); return 0; }
check() { if [ "$1" = "0" ]; then ok; else bad "$2"; fi; }

# --- Stub-Interpreter: protokolliert den Start, blockiert dann ---------------
STUB_PY="$WORK/stub-python.sh"
cat > "$STUB_PY" <<'STUB'
#!/usr/bin/env bash
echo "$@" >> "$SPAWN_LOG"
echo $$ >> "$PID_LOG"
sleep 30
STUB
chmod +x "$STUB_PY"
: > "$WORK/pids"

# --- Vault-DB-Attrappe: der Hook spawnt nur, wenn eine DB existiert ---------
FAKE_DB="$WORK/vault.db"
: > "$FAKE_DB"

CHAPTER_DIR="$WORK/projekt/kapitel"
mkdir -p "$CHAPTER_DIR"
CHAPTER="$CHAPTER_DIR/03.md"
echo 'Kapiteltext.' > "$CHAPTER"

# run <spool-dir> <stdin-json> [extra env assignments...] — fuehrt den Hook aus,
# schreibt stdout nach "$WORK/out.json" und den Exit-Code nach "$WORK/code".
run() {
  local spool="$1" payload="$2"
  shift 2
  printf '%s' "$payload" | env \
    SPAWN_LOG="$WORK/spawn.log" \
    PID_LOG="$WORK/pids" \
    ACADEMIC_PYTHON="$STUB_PY" \
    VAULT_DB_PATH="$FAKE_DB" \
    ACADEMIC_NLI_SCAN_SPOOL="$spool" \
    "$@" \
    node "$HOOK" > "$WORK/out.json" 2> "$WORK/err.txt"
  echo $? > "$WORK/code"
}

write_payload() {
  # write_payload <file_path> <content>
  python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"PostToolUse","tool_name":"Write","tool_input":{"file_path":sys.argv[1],"content":sys.argv[2]}}))' "$1" "$2"
}

spawned() { [ -s "$WORK/spawn.log" ]; }
reset_spawn_log() { : > "$WORK/spawn.log"; }

# Der Worker laeuft ABGEKOPPELT — er protokolliert seinen Start erst, nachdem
# der Hook laengst zurueck ist. Positive Faelle warten deshalb kurz auf den
# Eintrag; negative Faelle geben dem Prozess dieselbe Zeit und pruefen dann,
# dass nichts kam (sonst waere "kein Spawn" nur eine Aussage ueber die
# Reihenfolge, nicht ueber das Verhalten).
wait_for_spawn() {
  local i=0
  while [ "$i" -lt 20 ]; do
    spawned && return 0
    sleep 0.25
    i=$((i + 1))
  done
  return 1
}
settle() { sleep 1; }

# ---------------------------------------------------------------------------
# 1. Kapitel-Write: Worker wird gestartet, der Hook wartet NICHT auf ihn
# ---------------------------------------------------------------------------
reset_spawn_log
SPOOL="$WORK/spool1"
START=$(date +%s)
run "$SPOOL" "$(write_payload "$CHAPTER" 'Kapiteltext ohne Bypass.')"
ELAPSED=$(( $(date +%s) - START ))
check "$(cat "$WORK/code")" "Kapitel-Write: Exit-Code $(cat "$WORK/code") statt 0"
if wait_for_spawn; then ok; else bad "Kapitel-Write: kein Worker gestartet"; fi
if [ "$ELAPSED" -lt 5 ]; then ok; else bad "Kapitel-Write: Hook wartete $ELAPSED s auf den Worker (Stub schlaeft 30 s)"; fi
if grep -q 'permissionDecision' "$WORK/out.json"; then bad "Kapitel-Write: Hook setzt permissionDecision (darf nie blockieren)"; else ok; fi

# ---------------------------------------------------------------------------
# 2. Nicht-Kapitelpfad: stumm, kein Spawn
# ---------------------------------------------------------------------------
reset_spawn_log
run "$WORK/spool2" "$(write_payload "$WORK/projekt/notizen.md" 'Irgendein Text.')"
check "$(cat "$WORK/code")" "Nicht-Kapitelpfad: Exit-Code != 0"
settle
if spawned; then bad "Nicht-Kapitelpfad: Worker trotzdem gestartet"; else ok; fi
if [ -s "$WORK/out.json" ]; then bad "Nicht-Kapitelpfad: Hook hat gemeldet statt zu schweigen"; else ok; fi

# ---------------------------------------------------------------------------
# 3. Schalter aus (Env): kein Spawn, kein Drain
# ---------------------------------------------------------------------------
reset_spawn_log
SPOOL="$WORK/spool3"
mkdir -p "$SPOOL"
cat > "$SPOOL/befund.json" <<'JSON'
{"schema":1,"chapter":"kapitel/03.md","created_at":0,"scanned":1,
 "findings":[{"quote_id":"q1","paper_id":"p1","paper_ref":"Mueller (2021): Titel",
 "verbatim":"Ein woertliches Zitat aus der Quelle.","chapter_claim":"Der Kapitelsatz dazu.",
 "raw_score":0.11}]}
JSON
run "$SPOOL" "$(write_payload "$CHAPTER" 'Text.')" ACADEMIC_RESEARCH_NLI_PREFILTER=0
check "$(cat "$WORK/code")" "Schalter aus: Exit-Code != 0"
settle
if spawned; then bad "Schalter aus: Worker trotzdem gestartet"; else ok; fi
if [ -s "$WORK/out.json" ]; then bad "Schalter aus: Hook hat trotzdem gemeldet"; else ok; fi
if [ -f "$SPOOL/befund.json" ]; then ok; else bad "Schalter aus: Spool wurde trotzdem geleert"; fi

# ---------------------------------------------------------------------------
# 4. Bypass-Marker: stumm, kein Spawn
# ---------------------------------------------------------------------------
reset_spawn_log
run "$WORK/spool4" "$(write_payload "$CHAPTER" 'Kapiteltext. <!-- vault-guard: skip -->')"
check "$(cat "$WORK/code")" "Bypass: Exit-Code != 0"
settle
if spawned; then bad "Bypass-Marker: Worker trotzdem gestartet"; else ok; fi

# ---------------------------------------------------------------------------
# 5. Kaputtes stdin: Exit 0, keine Ausgabe
# ---------------------------------------------------------------------------
reset_spawn_log
run "$WORK/spool5" 'das ist kein JSON {{{'
check "$(cat "$WORK/code")" "Kaputtes stdin: Exit-Code != 0"
if [ -s "$WORK/out.json" ]; then bad "Kaputtes stdin: Hook hat gemeldet"; else ok; fi

# ---------------------------------------------------------------------------
# 6. Spool mit Befund: Zitat, Beleg und Kapitelsatz stehen in der Meldung
# ---------------------------------------------------------------------------
reset_spawn_log
SPOOL="$WORK/spool6"
mkdir -p "$SPOOL"
cat > "$SPOOL/befund.json" <<'JSON'
{"schema":1,"chapter":"kapitel/03.md","created_at":0,"scanned":3,
 "findings":[{"quote_id":"q1","paper_id":"p1","paper_ref":"Mueller (2021): Governance",
 "verbatim":"Ein woertliches Zitat aus der Quelle.","chapter_claim":"Der Kapitelsatz dazu.",
 "raw_score":0.11}]}
JSON
run "$SPOOL" "$(write_payload "$WORK/projekt/notizen.md" 'kein Kapitel')"
check "$(cat "$WORK/code")" "Drain: Exit-Code != 0"
for needle in 'Ein woertliches Zitat aus der Quelle.' 'Mueller (2021): Governance' 'Der Kapitelsatz dazu.'; do
  if grep -qF "$needle" "$WORK/out.json"; then ok; else bad "Drain: '$needle' fehlt in der Meldung"; fi
done
if grep -q 'additionalContext' "$WORK/out.json"; then ok; else bad "Drain: kein additionalContext im stdout-JSON"; fi
if [ -f "$SPOOL/befund.json" ]; then bad "Drain: Spool-Datei nicht geleert"; else ok; fi

# Zweiter Lauf ueber denselben (jetzt leeren) Spool: keine Wiederholung.
run "$SPOOL" "$(write_payload "$WORK/projekt/notizen.md" 'kein Kapitel')"
if [ -s "$WORK/out.json" ]; then bad "Drain: Befund wurde ein zweites Mal gemeldet"; else ok; fi

# ---------------------------------------------------------------------------
# 7. Fehler-Datensatz: genau EINMAL gemeldet, Sitzung laeuft weiter (AC5)
# ---------------------------------------------------------------------------
SPOOL="$WORK/spool7"
mkdir -p "$SPOOL"
error_record() {
  cat > "$SPOOL/fehler.json" <<'JSON'
{"schema":1,"chapter":"kapitel/03.md","created_at":0,"scanned":0,"findings":[],
 "error":"NLI-Modell nicht verfuegbar: Modellgewichte nicht gefunden"}
JSON
}
error_record
run "$SPOOL" "$(write_payload "$WORK/projekt/notizen.md" 'kein Kapitel')"
check "$(cat "$WORK/code")" "Fehlerpfad: Exit-Code != 0"
if grep -qF 'Modellgewichte nicht gefunden' "$WORK/out.json"; then ok; else bad "Fehlerpfad: Fehler nicht gemeldet"; fi
if grep -q 'permissionDecision' "$WORK/out.json"; then bad "Fehlerpfad: Hook blockiert"; else ok; fi

error_record
run "$SPOOL" "$(write_payload "$WORK/projekt/notizen.md" 'kein Kapitel')"
if grep -qF 'Modellgewichte nicht gefunden' "$WORK/out.json"; then
  bad "Fehlerpfad: derselbe Fehler ein zweites Mal gemeldet (AC5 verlangt einmal)"
else
  ok
fi

# ---------------------------------------------------------------------------
# 8. UserPromptSubmit: Drain ja, Spawn nein
# ---------------------------------------------------------------------------
reset_spawn_log
SPOOL="$WORK/spool8"
mkdir -p "$SPOOL"
cat > "$SPOOL/befund.json" <<'JSON'
{"schema":1,"chapter":"kapitel/04.md","created_at":0,"scanned":1,
 "findings":[{"quote_id":"q9","paper_id":"p9","paper_ref":"Schmidt (2019): Studie",
 "verbatim":"Noch ein woertliches Zitat.","chapter_claim":"Und der Satz dazu.","raw_score":0.2}]}
JSON
run "$SPOOL" '{"hook_event_name":"UserPromptSubmit","prompt":"weiter"}'
check "$(cat "$WORK/code")" "UserPromptSubmit: Exit-Code != 0"
settle
if spawned; then bad "UserPromptSubmit: Worker gestartet (darf nur drainen)"; else ok; fi
if grep -qF 'Noch ein woertliches Zitat.' "$WORK/out.json"; then ok; else bad "UserPromptSubmit: Befund nicht gemeldet"; fi
if grep -q '"hookEventName": *"UserPromptSubmit"' "$WORK/out.json"; then ok; else bad "UserPromptSubmit: falscher hookEventName im stdout-JSON"; fi

# ---------------------------------------------------------------------------
# 9. Fremdes Spool-Schema wird verworfen, nicht geraten
# ---------------------------------------------------------------------------
SPOOL="$WORK/spool9"
mkdir -p "$SPOOL"
echo '{"schema":99,"findings":[{"verbatim":"Aus der Zukunft."}]}' > "$SPOOL/fremd.json"
run "$SPOOL" "$(write_payload "$WORK/projekt/notizen.md" 'kein Kapitel')"
check "$(cat "$WORK/code")" "Fremdes Schema: Exit-Code != 0"
if grep -qF 'Aus der Zukunft.' "$WORK/out.json"; then bad "Fremdes Schema: trotzdem gemeldet"; else ok; fi

echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
