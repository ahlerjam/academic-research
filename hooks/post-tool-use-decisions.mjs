#!/usr/bin/env node
/**
 * hooks/post-tool-use-decisions.mjs — PostToolUse Decision-Log Hook
 *
 * Bei Write/Edit/MultiEdit-Events auf *.md-Dateien im Projekt-Verzeichnis wird
 * die Aenderung im VAULT protokolliert: eine Decision der Kategorie
 * `file-change` in der SQLite-Tabelle `decisions` — genau die Tabelle, die
 * `hooks/mid-session-reinforcement.mjs` in der naechsten Session vorliest.
 *
 * Bis Issue #527 schrieb dieser Hook stattdessen in die Textdatei
 * `~/.academic-research/decisions.log`, waehrend das Reinforcement die
 * SQLite-Tabelle las. Beide Seiten liefen auseinander, das Feature war tot.
 * `decisions.log` ist seither ein reines OPT-IN-DEBUG-LOG: es entsteht nur
 * noch, wenn `ACADEMIC_DECISIONS_LOG` gesetzt ist.
 *
 * Datenschutz (CWE-532), unveraendert gueltig fuer beide Senken:
 *   - KEIN Content-Snippet im Klartext — nur der SHA-256-Hash des Inhalts.
 *   - Logfile wird mit 0600-Permissions geschrieben (nur Owner).
 *   - Rotation bei >10 MB: decisions.log -> decisions.log.1.
 *
 * Protokoll:
 *   - Eingabe: JSON via stdin (Claude Code PostToolUse-Format)
 *   - Exit 0: immer (fail-open, nie blockierend)
 *
 * Konfiguration via Umgebungsvariablen:
 *   VAULT_DB_PATH           — Vault-DB (Default siehe hooks/lib/vault-bridge.mjs)
 *   ACADEMIC_PYTHON         — Interpreter fuer den Vault-Schreibpfad
 *   ACADEMIC_DECISIONS_LOG  — Pfad zum Opt-in-Debug-Log (ohne: kein Log)
 *   CLAUDE_PROJECT_DIR      — Projekt-Verzeichnis (default: cwd)
 */

import { appendFileSync, mkdirSync, existsSync, chmodSync, statSync, renameSync } from 'node:fs';
import { dirname, relative, basename } from 'node:path';
import { createHash } from 'node:crypto';
import * as path from 'node:path';

import { resolveVaultDb, VAULT_SRC, runVaultPython } from './lib/vault-bridge.mjs';

// Rotation: maximale Logfile-Groesse in Bytes (10 MB), dann -> decisions.log.1
const MAX_LOG_BYTES = 10 * 1024 * 1024;

// Zeitbudget fuer den Vault-Schreibpfad. hooks.json gibt dem PostToolUse-Hook
// 10 s; die Bruecke probiert bis zu vier Interpreter durch und bricht ab,
// sobald das Budget erschoepft ist, statt in den harten Hook-Timeout zu laufen.
const VAULT_WRITE_BUDGET_MS = 8000;
const VAULT_WRITE_TIMEOUT_MS = 5000;

// ---------------------------------------------------------------------------
// Konfiguration
// ---------------------------------------------------------------------------

// Opt-in: ohne gesetzte Variable entsteht KEIN Debug-Log (#527). Der
// verbindliche Speicherort ist der Vault.
const DECISIONS_LOG = process.env.ACADEMIC_DECISIONS_LOG || '';
const PROJECT_DIR = process.env.CLAUDE_PROJECT_DIR || process.cwd();

// Tools die Dateiinhalte schreiben und daher protokolliert werden (#220).
const WRITE_LIKE_TOOLS = new Set(['Write', 'Edit', 'MultiEdit']);

/**
 * Extrahiert den geschriebenen Text aus tool_input — abhaengig vom Tool:
 *   - Write:     tool_input.content
 *   - Edit:      tool_input.new_string
 *   - MultiEdit: alle edits[].new_string (zusammengefuegt)
 */
function extractContent(toolName, toolInput) {
  if (toolName === 'MultiEdit' && Array.isArray(toolInput.edits)) {
    return toolInput.edits.map((e) => (e && e.new_string) || '').join('\n');
  }
  if (toolName === 'Edit') {
    return toolInput.new_string || '';
  }
  return toolInput.content || '';
}

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
// Pfad-Check
// ---------------------------------------------------------------------------

/**
 * Gibt true zurueck wenn die Datei eine .md-Datei im Projekt-Verzeichnis ist.
 */
function isMdInProject(filePath) {
  if (!filePath) return false;
  if (!filePath.endsWith('.md')) return false;

  // Normalisiere Pfade fuer Vergleich
  const normalized = path.resolve(filePath);
  const projectResolved = path.resolve(PROJECT_DIR);

  return normalized.startsWith(projectResolved + path.sep) || normalized === projectResolved;
}

// ---------------------------------------------------------------------------
// Log-Zeile schreiben
// ---------------------------------------------------------------------------

/**
 * Rotiert das Logfile, wenn es MAX_LOG_BYTES ueberschreitet.
 * decisions.log -> decisions.log.1 (ueberschreibt eine evtl. vorhandene .1).
 */
function rotateIfNeeded() {
  try {
    if (!existsSync(DECISIONS_LOG)) return;
    const size = statSync(DECISIONS_LOG).size;
    if (size <= MAX_LOG_BYTES) return;
    renameSync(DECISIONS_LOG, `${DECISIONS_LOG}.1`);
  } catch {
    // Rotation ist best-effort — nie blockierend.
  }
}

/**
 * Projekt-relativer Pfad der geaenderten Datei (Fallback: Dateiname).
 */
function toRelPath(filePath) {
  try {
    return relative(PROJECT_DIR, path.resolve(filePath));
  } catch {
    return basename(filePath);
  }
}

/**
 * Protokolliert die Aenderung im Vault (Kategorie `file-change`, #527).
 *
 * Fail-open an jeder Stelle: existiert keine Vault-DB, wird NICHTS angelegt
 * (der Hook darf keine DB aus dem Nichts erzeugen — er wuerde sonst bei jedem
 * beliebigen Projektverzeichnis eine leere vault.db hinterlassen). Scheitert
 * der Subprozess, bleibt es bei einer Diagnosezeile auf stderr.
 *
 * Der Python-Aufruf importiert bewusst nur `academic_vault.decision_log`
 * (-> `academic_vault.db`), nicht `academic_vault.server`: der Hook feuert bei
 * JEDEM `.md`-Write, und die fastmcp/pydantic-Kette kostet ~1,2 s statt ~0,06 s.
 * Argumente gehen ueber argv, nicht per String-Interpolation in den Code.
 */
function recordInVault(toolName, relPath, hash) {
  try {
    const dbPath = resolveVaultDb();
    if (!existsSync(dbPath)) {
      return;
    }
    const pyCode = [
      'import sys',
      `sys.path.insert(0, ${JSON.stringify(VAULT_SRC)})`,
      'from academic_vault.decision_log import record_file_change',
      'record_file_change(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])',
    ].join('; ');

    runVaultPython(pyCode, [dbPath, toolName, relPath, hash], {
      timeout: VAULT_WRITE_TIMEOUT_MS,
      budget: VAULT_WRITE_BUDGET_MS,
      label: 'Decisions-Log',
    });
  } catch (err) {
    process.stderr.write(`[Decisions-Log] Vault-Schreibpfad fehlgeschlagen: ${err.message}\n`);
  }
}

/**
 * Schreibt eine Zeile in das Opt-in-Debug-Log (nur bei gesetztem
 * `ACADEMIC_DECISIONS_LOG`).
 * Format: ISO-Timestamp | <Tool> | <relativer-Pfad> | sha256=<hash>
 *
 * Der Tool-Name (Write/Edit/MultiEdit, #220) wird mitprotokolliert.
 *
 * Aus Datenschutzgruenden (CWE-532) wird KEIN Content-Snippet im Klartext
 * geloggt. Stattdessen steht der SHA-256-Hash des Inhalts in der Zeile —
 * ausreichend fuer Idempotenz-/Aenderungs-Checks, ohne PII zu leaken.
 */
function writeLogLine(toolName, relPath, hash) {
  if (!DECISIONS_LOG) {
    return;
  }

  const ts = new Date().toISOString();
  const line = `${ts} | ${toolName} | ${relPath} | sha256=${hash}\n`;

  try {
    // Log-Verzeichnis sicherstellen
    const logDir = dirname(DECISIONS_LOG);
    if (!existsSync(logDir)) {
      mkdirSync(logDir, { recursive: true, mode: 0o700 });
    }
    rotateIfNeeded();
    appendFileSync(DECISIONS_LOG, line, 'utf-8');
    // Restriktive Permissions: nur Owner darf lesen/schreiben (0600).
    chmodSync(DECISIONS_LOG, 0o600);
  } catch (err) {
    process.stderr.write(`[Decisions-Log] Fehler beim Schreiben: ${err.message}\n`);
  }
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

  // Schreibende Tool-Events protokollieren: Write, Edit, MultiEdit (#220)
  const toolName = input?.tool_name || input?.hook_event_name || '';
  if (!WRITE_LIKE_TOOLS.has(toolName)) {
    process.exit(0);
  }

  const toolInput = input?.tool_input || {};
  const filePath = toolInput.file_path || '';
  const content = extractContent(toolName, toolInput);

  // Nur .md-Dateien im Projekt
  if (!isMdInProject(filePath)) {
    process.exit(0);
  }

  const relPath = toRelPath(filePath);
  // SHA-256-Hash des Inhalts statt Klartext-Snippet (Idempotenz-Check ohne Leak).
  const hash = createHash('sha256').update(content || '', 'utf-8').digest('hex');

  recordInVault(toolName, relPath, hash);
  writeLogLine(toolName, relPath, hash);
  process.exit(0);
}

main().catch((err) => {
  process.stderr.write(`[Decisions-Log] Unerwarteter Fehler: ${err.message}\n`);
  process.exit(0); // fail-open
});
