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
 * Liest die aktiven Decisions aus dem Vault und erinnert das Modell als
 * System-Hint. Ausgegeben wird in zwei Bloecken (#527): bis zu 5 manuell
 * gepflegte Decisions und, davon getrennt, bis zu 3 automatisch protokollierte
 * Datei-Aenderungen (Kategorie `file-change`) — sonst wuerden die Auto-Eintraege
 * die echten Entscheidungen aus dem Fenster draengen.
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
 *   ACADEMIC_PYTHON               — Interpreter fuer den Vault-Lookup
 *                                   (Kaskade in hooks/lib/vault-bridge.mjs)
 *
 * Live-Nachweis der Kontext-Injection: scripts/dev/verify_reinforcement_context.py
 */

import { existsSync, readFileSync, writeFileSync, mkdirSync, chmodSync } from 'node:fs';
import { dirname, join } from 'node:path';
import * as os from 'node:os';

import { resolveVaultDb, VAULT_SRC, runVaultPython } from './lib/vault-bridge.mjs';

// Kanonischer DB-Default (Single Source of Truth, Issue #190/#527): kommt aus
// hooks/lib/vault-bridge.mjs — derselben Aufloesung, die der PostToolUse-Hook zum
// SCHREIBEN benutzt. Zwei getrennte Formeln waren die Wurzel von #527.
const VAULT_DB = resolveVaultDb();

const STATE_FILE = process.env.ACADEMIC_REINFORCEMENT_STATE
  || join(os.homedir(), '.academic-research', 'reinforcement-state.json');

const TRIGGER_N = parseInt(process.env.ACADEMIC_REINFORCEMENT_N || '20', 10);
// Manuell gepflegte Decisions (Kategorie != file-change).
const MAX_DECISIONS = 5;
// Automatisch protokollierte Datei-Aenderungen — bewusst knapper: sie sind
// Kontext, keine Entscheidungen, und duerfen die echten nicht verdraengen.
const MAX_FILE_CHANGES = 3;

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
 * Laedt die aktiven Decisions aus dem Vault, getrennt in zwei Toepfe:
 *   manual — manuell gepflegte Entscheidungen (Kategorie != file-change)
 *   auto   — vom PostToolUse-Hook protokollierte Datei-Aenderungen (#527)
 *
 * Die Trennung passiert bereits in Python: `list_decisions()` sortiert nach
 * `created_at DESC`, und in einer aktiven Schreibsession sind die letzten
 * Eintraege fast immer Datei-Aenderungen. Ein blosses Top-5 wuerde die echten
 * Entscheidungen aus dem Fenster draengen — genau der Effekt, den AC2 von
 * #527 ausschliesst.
 *
 * Der Lookup importiert bewusst `academic_vault.db` statt `academic_vault.server`:
 * letzteres zieht die fastmcp/pydantic-Kette nach (~1,2 s CPU statt ~0,06 s).
 *
 * Gibt leere Toepfe bei Fehler oder fehlendem Vault zurueck (fail-open).
 */
function loadTopDecisions() {
  const empty = { manual: [], auto: [] };

  if (!existsSync(VAULT_DB)) {
    process.stderr.write(`[Reinforcement] Vault-DB nicht gefunden (${VAULT_DB}). Übersprungen.\n`);
    return empty;
  }

  const pyCode = [
    'import sys, json',
    `sys.path.insert(0, ${JSON.stringify(VAULT_SRC)})`,
    'from academic_vault.db import VaultDB',
    'from academic_vault.decision_log import AUTO_CATEGORY',
    'db = VaultDB(sys.argv[1])',
    'rows = db.list_decisions(active_only=True)',
    "manual = [d for d in rows if d.get('category') != AUTO_CATEGORY]",
    "auto = [d for d in rows if d.get('category') == AUTO_CATEGORY]",
    `print(json.dumps({'manual': manual[:${MAX_DECISIONS}], 'auto': auto[:${MAX_FILE_CHANGES}]}))`,
  ].join('; ');

  const output = runVaultPython(pyCode, [VAULT_DB], { timeout: 10000, label: 'Reinforcement' });
  if (output === null) {
    return empty;
  }
  try {
    const parsed = JSON.parse(output.trim());
    return {
      manual: Array.isArray(parsed?.manual) ? parsed.manual : [],
      auto: Array.isArray(parsed?.auto) ? parsed.auto : [],
    };
  } catch (err) {
    process.stderr.write(`[Reinforcement] Vault-Antwort nicht lesbar: ${err.message}\n`);
    return empty;
  }
}

// ---------------------------------------------------------------------------
// Reminder ausgeben
// ---------------------------------------------------------------------------

/**
 * Gibt den System-Hint auf stdout aus — zwei Bloecke (#527):
 * die manuell gepflegten Decisions und, davon getrennt, die zuletzt
 * geaenderten Dateien.
 */
function printReminder({ manual = [], auto = [] } = {}) {
  const lines = ['[Reinforcement] Aktive Decisions:'];
  for (const d of manual) {
    const cat = d.category ? `[${d.category}] ` : '';
    lines.push(`  - ${cat}${d.text}`);
  }
  if (manual.length === 0) {
    lines.push('  (keine aktiven Decisions)');
  }
  if (auto.length > 0) {
    lines.push('[Reinforcement] Zuletzt geänderte Dateien:');
    for (const d of auto) {
      lines.push(`  - ${d.text}`);
    }
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

    // Zaehler SOFORT persistieren — auf beiden Pfaden und vor dem Vault-Lookup.
    // Der Lookup blockiert pro Interpreter-Kandidat bis zu 10 s (execFileSync-
    // timeout, bis zu vier Kandidaten), das UserPromptSubmit-Timeout in
    // hooks.json betraegt 15 s. Wuerde erst nach dem Lookup gespeichert, bliebe
    // bei einem abgeschossenen Trigger-Aufruf TRIGGER_N-1 in der State-Datei
    // stehen: der naechste Prompt traefe wieder den Trigger-Pfad, haenge wieder,
    // wuerde wieder gekillt. Der Zaehler waere dauerhaft eingefroren und der
    // teure Lookup liefe ab da bei jeder Message. Preis dieser Reihenfolge:
    // stirbt der Hook waehrend des Lookups, entfaellt der Reminder dieser Runde
    // — deutlich guenstiger als eine Endlosschleife teurer Lookups.
    saveState(state);

    if (promptCount % TRIGGER_N !== 0) {
      // Noch nicht die N-te Message dieser Runde.
      process.exit(0);
    }
  }

  // Decisions laden
  const decisions = loadTopDecisions();

  // Reminder ausgeben
  printReminder(decisions);

  // Kein weiterer saveState: prompt_count ist oben bereits persistiert, der
  // Compaction-Pfad veraendert den State ueberhaupt nicht.
  process.exit(0);
}

main().catch((err) => {
  process.stderr.write(`[Reinforcement] Unerwarteter Fehler: ${err.message}\n`);
  process.exit(0); // fail-open
});
