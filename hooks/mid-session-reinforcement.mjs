#!/usr/bin/env node
/**
 * hooks/mid-session-reinforcement.mjs — Mid-Conversation Reinforcement Hook
 *
 * Nicht-blockierender Hook auf zwei Events, deren stdout laut Claude-Code-Doku
 * (code.claude.com/docs/en/hooks, Stand #382) tatsaechlich als Modell-Kontext
 * injiziert wird — im Gegensatz zu Notification/PostCompact, deren stdout NICHT
 * zu den Context-Injection-Ausnahmen zaehlt:
 *   - UserPromptSubmit: Trigger nach jeder 20. User-Message.
 *   - SessionStart mit source==="compact": Trigger nach Compaction.
 * Liest Top-5 aktive Decisions aus Vault und erinnert Modell als System-Hint.
 * Loest max. 1× pro 20 Messages aus (State-Datei verhindert Duplikate).
 *
 * Zaehlung der User-Messages (Fix #382 P2-Finding aus PR #420-Review):
 * Der UserPromptSubmit-Payload von Claude Code enthaelt laut Doku KEIN
 * `message_count`-Feld (nur session_id, prompt_id, transcript_path, cwd,
 * permission_mode, effort, hook_event_name, optional agent_id/agent_type).
 * Ein Trigger, der auf `input.message_count` haengt, feuert daher in echten
 * Sessions nie. Statt eines externen Feldes zaehlt der Hook seine eigenen
 * UserPromptSubmit-Aufrufe persistent in der State-Datei (`prompt_count`) —
 * jeder Aufruf entspricht genau einer realen User-Message.
 *
 * Protokoll:
 *   - Eingabe: JSON via stdin (Claude Code UserPromptSubmit/SessionStart-Format)
 *   - Ausgabe: Reminder-Text auf stdout (als System-Hint fuer Modell)
 *   - Exit 0: immer (nie blockierend)
 *
 * Konfiguration via Umgebungsvariablen:
 *   VAULT_DB_PATH                 — Pfad zur Vault-DB
 *   ACADEMIC_REINFORCEMENT_STATE  — Pfad zur State-Datei (default: ~/.academic-research/reinforcement-state.json)
 *   ACADEMIC_REINFORCEMENT_N      — Trigger-Interval (default: 20)
 */

import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync, mkdirSync, chmodSync } from 'node:fs';
import { dirname, join, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as os from 'node:os';
import * as path from 'node:path';

const HOOK_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = dirname(HOOK_DIR);
const VAULT_SRC = REPO_ROOT;

// Kanonischer DB-Default (Single Source of Truth, Issue #190):
// VAULT_DB_PATH aus Env, sonst ~/.academic-research/projects/<slug>/vault.db
// mit slug=basename(CWD). Kein hart kodierter 'default'-Bucket mehr.
const SLUG = basename(process.env.CLAUDE_PROJECT_DIR || process.cwd()) || 'default';
const VAULT_DB = process.env.VAULT_DB_PATH
  || join(os.homedir(), '.academic-research', 'projects', SLUG, 'vault.db');

const STATE_FILE = process.env.ACADEMIC_REINFORCEMENT_STATE
  || join(os.homedir(), '.academic-research', 'reinforcement-state.json');

const TRIGGER_N = parseInt(process.env.ACADEMIC_REINFORCEMENT_N || '20', 10);
const MAX_DECISIONS = 5;

// ---------------------------------------------------------------------------
// Stdin lesen
// ---------------------------------------------------------------------------

async function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf-8');
    process.stdin.on('data', (chunk) => { data += chunk; });
    process.stdin.on('end', () => resolve(data.replace(/^﻿/, '')));
    process.stdin.on('error', reject);
    process.stdin.resume();
  });
}

// ---------------------------------------------------------------------------
// State-Verwaltung
// ---------------------------------------------------------------------------

/**
 * Laedt den State aus der State-Datei. Gibt {prompt_count: 0} als Default.
 */
function loadState() {
  try {
    if (existsSync(STATE_FILE)) {
      return JSON.parse(readFileSync(STATE_FILE, 'utf-8'));
    }
  } catch {
    // Ignore
  }
  return { prompt_count: 0 };
}

/**
 * Speichert den State in die State-Datei.
 */
function saveState(state) {
  try {
    const dir = dirname(STATE_FILE);
    if (!existsSync(dir)) {
      // Verzeichnis restriktiv (0700) anlegen — kann Session-Kontext enthalten.
      mkdirSync(dir, { recursive: true, mode: 0o700 });
    }
    // State-Datei nur owner-readable/writable (0600) schreiben.
    // mode bei writeFileSync greift nur bei Neuanlage — chmodSync erzwingt
    // 0600 auch beim Ueberschreiben einer bereits existierenden Datei.
    writeFileSync(STATE_FILE, JSON.stringify(state, null, 2), { encoding: 'utf-8', mode: 0o600 });
    chmodSync(STATE_FILE, 0o600);
  } catch (err) {
    process.stderr.write(`[Reinforcement] State-Datei konnte nicht gespeichert werden: ${err.message}\n`);
  }
}

// ---------------------------------------------------------------------------
// Vault-Decisions abrufen
// ---------------------------------------------------------------------------

/**
 * Laedt Top-N aktive Decisions aus dem Vault.
 * Gibt leeres Array bei Fehler oder fehlendem Vault (fail-open).
 */
function loadTopDecisions() {
  if (!existsSync(VAULT_DB)) {
    process.stderr.write(`[Reinforcement] Vault-DB nicht gefunden (${VAULT_DB}). Übersprungen.\n`);
    return [];
  }

  const pyCode = [
    'import sys, json',
    `sys.path.insert(0, ${JSON.stringify(VAULT_SRC)})`,
    'from academic_vault.server import list_decisions',
    `decisions = list_decisions(sys.argv[1], active_only=True)`,
    `print(json.dumps(decisions[:${MAX_DECISIONS}]))`,
  ].join('; ');

  try {
    const output = execFileSync('python3', ['-c', pyCode, VAULT_DB], {
      encoding: 'utf-8',
      timeout: 10000,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    return JSON.parse(output.trim()) || [];
  } catch (err) {
    process.stderr.write(`[Reinforcement] Vault-Lookup fehlgeschlagen: ${err.message}\n`);
    return [];
  }
}

// ---------------------------------------------------------------------------
// Reminder ausgeben
// ---------------------------------------------------------------------------

/**
 * Gibt System-Hint auf stdout aus.
 */
function printReminder(decisions) {
  const lines = ['[Reinforcement] Aktive Decisions:'];
  for (const d of decisions) {
    const cat = d.category ? `[${d.category}] ` : '';
    lines.push(`  - ${cat}${d.text}`);
  }
  if (decisions.length === 0) {
    lines.push('  (keine aktiven Decisions)');
  }
  // Auf stdout (wird als System-Hint an Modell weitergegeben)
  process.stdout.write(lines.join('\n') + '\n');
}

// ---------------------------------------------------------------------------
// Haupt-Logik
// ---------------------------------------------------------------------------

async function main() {
  let input = {};
  try {
    const raw = await readStdin();
    if (raw.trim()) {
      input = JSON.parse(raw);
    }
  } catch {
    // Malformed stdin — fail-open
    process.exit(0);
  }

  const eventName = input?.hook_event_name || '';
  const source = input?.source || '';

  const isCompaction = eventName === 'SessionStart' && source === 'compact';
  const isUserPromptSubmit = eventName === 'UserPromptSubmit';

  if (!isCompaction && !isUserPromptSubmit) {
    // Kein bekanntes Trigger-Event
    process.exit(0);
  }

  const state = loadState();

  if (!isCompaction) {
    // UserPromptSubmit: kein `message_count`-Feld im realen Payload (#382 P2).
    // Eigener persistenter Zaehler in der State-Datei zaehlt die tatsaechlichen
    // Hook-Aufrufe — jeder Aufruf entspricht genau einer realen User-Message.
    const promptCount = (Number(state.prompt_count) || 0) + 1;
    state.prompt_count = promptCount;

    if (promptCount % TRIGGER_N !== 0) {
      // Noch nicht die N-te Message dieser Runde — Zaehler trotzdem persistieren.
      saveState(state);
      process.exit(0);
    }
  }

  // Decisions laden
  const decisions = loadTopDecisions();

  // Reminder ausgeben
  printReminder(decisions);

  // State aktualisieren (prompt_count wurde fuer den Intervall-Pfad bereits
  // oben erhoeht und persistiert; Compaction veraendert den Zaehler nicht).
  saveState(state);

  process.exit(0);
}

main().catch((err) => {
  process.stderr.write(`[Reinforcement] Unerwarteter Fehler: ${err.message}\n`);
  process.exit(0); // fail-open
});
