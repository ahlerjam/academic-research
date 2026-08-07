#!/usr/bin/env node
/**
 * hooks/nli-quote-scan.mjs — NLI-Zitatscan, produktiv angebunden (Issue #717)
 *
 * Der Scan selbst (academic_vault/nli_prefilter.py) existiert seit #592, hatte
 * aber keinen produktiven Aufrufer: geprueft wurde nur, was der
 * claim-drift-guard zufaellig anfasste. Ein Zitat, das von Anfang an falsch
 * verwendet und nie wieder angeruehrt wurde, fiel komplett durch. Dieser Hook
 * schliesst die Luecke.
 *
 * Zweiphasig, und das ist der Kern des Entwurfs:
 *
 *   1. SPAWN (nur PostToolUse, nur Kapitelpfade): startet den Python-Worker
 *      `academic_vault.nli_scan_worker` ABGEKOPPELT (detached + unref) und
 *      kehrt sofort zurueck. Der Hook wartet nie auf das Modell. Ein
 *      synchroner Scan wuerde beim ersten Kapitel-Write jeder Installation
 *      den ~1,1-GB-Download von mDeBERTa in den Hook-Timeout laufen lassen —
 *      AC1 ("ohne den Write zu verzoegern") und AC5 ("die Sitzung laeuft
 *      normal weiter") sind nur ohne Inline-Modellladung beide erfuellbar.
 *   2. DRAIN (jeder Aufruf): liest das Spool-Verzeichnis des Workers leer und
 *      meldet Fundstellen als systemMessage + additionalContext.
 *
 * Damit ein Befund nicht bis zum naechsten Kapitel-Write liegen bleibt, ist
 * derselbe Hook zusaetzlich unter `UserPromptSubmit` verdrahtet — dort
 * ausschliesslich als Drain (kein Spawn). Welcher Modus gilt, entscheidet
 * `hook_event_name` aus dem stdin-Payload.
 *
 * Abgrenzung: KEIN PreToolUse. Die bestehenden Guards (verbatim-guard,
 * claim-drift-guard, context-fidelity-guard) bleiben dort, weil sie
 * blockieren bzw. sofort markieren muessen. Dieser Hook blockiert nie und
 * setzt bewusst kein permissionDecision.
 *
 * Protokoll:
 *   - Eingabe: JSON via stdin (PostToolUse- bzw. UserPromptSubmit-Format)
 *   - Ausgabe: JSON via stdout (systemMessage + hookSpecificOutput.additionalContext)
 *   - Exit-Code: IMMER 0, in jedem Zweig (fail-open)
 *
 * Bypass: Der geschriebene Inhalt enthaelt <!-- vault-guard: skip --> → kein
 * Spawn (identisch zu den drei Kapitel-Guards).
 *
 * Schalter (Default AN, #717):
 *   ACADEMIC_RESEARCH_NLI_PREFILTER=0  → Hook tut nichts (auch kein Drain)
 *   config/parallel_agents.json → "nli_prefilter_enabled": false
 *   Vorrang: Env > Configdatei > Default true — dieselbe Reihenfolge wie
 *   academic_vault/nli_prefilter.py::resolve_nli_prefilter_enabled.
 *
 * Weitere Umgebungsvariablen:
 *   VAULT_DB_PATH             — Vault-DB (Default siehe hooks/lib/vault-bridge.mjs)
 *   ACADEMIC_PYTHON           — Interpreter fuer den Worker
 *   ACADEMIC_NLI_SCAN_SPOOL   — Spool-Verzeichnis (Default
 *                               ~/.academic-research/nli-scan-spool)
 *   ACADEMIC_CHAPTER_DIR      — Kapitelverzeichnis (siehe protected-path.mjs)
 *   NLI_SCAN_DEBUG            — '1' aktiviert Diagnosezeilen auf stderr
 */

import { spawn } from 'node:child_process';
import {
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { createHash } from 'node:crypto';
import { join, sep } from 'node:path';
import * as os from 'node:os';

import { isProtectedPath } from './lib/protected-path.mjs';
import { resolveVaultDb, VAULT_SRC, pythonCandidates } from './lib/vault-bridge.mjs';

const WRITE_LIKE_TOOLS = new Set(['Write', 'Edit', 'MultiEdit']);
const BYPASS_MARKER = '<!-- vault-guard: skip -->';
const DEBUG = process.env.NLI_SCAN_DEBUG === '1';

/** Schema-Version der Spool-Datensaetze (academic_vault/nli_scan_worker.py). */
const SCHEMA_VERSION = 1;

/** Obergrenze gemeldeter Fundstellen je Meldung — ein Kapitel mit 50
 *  auffaelligen Zitaten soll die Sitzung nicht zuschuetten. */
const MAX_REPORTED = 10;

const TRUTHY = new Set(['1', 'true', 'yes', 'on']);
const FALSY = new Set(['0', 'false', 'no', 'off']);

function debug(message) {
  if (DEBUG) process.stderr.write(`[NLI-Zitatscan-Diagnose] ${message}\n`);
}

// ---------------------------------------------------------------------------
// Schalter — dieselbe Vorrangfolge wie resolve_nli_prefilter_enabled (Python)
// ---------------------------------------------------------------------------

function scanEnabled(env = process.env) {
  const raw = env.ACADEMIC_RESEARCH_NLI_PREFILTER;
  if (raw !== undefined) {
    const value = String(raw).trim().toLowerCase();
    if (TRUTHY.has(value)) return true;
    if (FALSY.has(value)) return false;
  }
  try {
    const configPath = join(VAULT_SRC, 'config', 'parallel_agents.json');
    const data = JSON.parse(readFileSync(configPath, 'utf-8'));
    if (typeof data.nli_prefilter_enabled === 'boolean') return data.nli_prefilter_enabled;
  } catch {
    // Keine/kaputte Config — Default gilt.
  }
  return true;
}

function spoolDir(env = process.env) {
  return env.ACADEMIC_NLI_SCAN_SPOOL
    || join(os.homedir(), '.academic-research', 'nli-scan-spool');
}

// ---------------------------------------------------------------------------
// Stdin
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

function authoredContent(toolName, toolInput) {
  if (toolName === 'MultiEdit' && Array.isArray(toolInput.edits)) {
    return toolInput.edits.map((e) => (e && e.new_string) || '').join('\n');
  }
  if (toolName === 'Edit') return toolInput.new_string || '';
  return toolInput.content || '';
}

// ---------------------------------------------------------------------------
// Phase 1: Spawn (abgekoppelt)
// ---------------------------------------------------------------------------

/** Erster tatsaechlich vorhandener Interpreter. Anders als runVaultPython()
 *  gibt es hier keine Kaskade: der Worker laeuft abgekoppelt, sein Scheitern
 *  ist erst im naechsten Drain sichtbar (als error-Datensatz des Workers) —
 *  ein zweiter Startversuch waere ein zweiter Modell-Ladevorgang. */
function firstUsablePython() {
  for (const candidate of pythonCandidates()) {
    if (!candidate.includes(sep) || existsSync(candidate)) return candidate;
  }
  return null;
}

function spawnWorker(filePath) {
  const dbPath = resolveVaultDb();
  if (!existsSync(dbPath)) {
    // Kein Vault, nichts zu belegen — und der Hook legt bewusst keine DB an
    // (identische Regel wie post-tool-use-decisions.mjs).
    debug(`Vault-DB fehlt (${dbPath}) — kein Scan.`);
    return false;
  }
  const python = firstUsablePython();
  if (!python) {
    debug('Kein Python-Interpreter gefunden — kein Scan.');
    return false;
  }
  try {
    const child = spawn(
      python,
      ['-m', 'academic_vault.nli_scan_worker', dbPath, filePath, spoolDir()],
      {
        cwd: VAULT_SRC,
        detached: true,
        stdio: 'ignore',
        env: { ...process.env, PYTHONPATH: VAULT_SRC },
      },
    );
    // spawn() ist asynchron: ENOENT/EACCES/EAGAIN/EMFILE kommen nicht
    // synchron aus diesem try/catch, sondern per process.nextTick als
    // 'error'-Event auf dem ChildProcess. Ohne Listener wirft der
    // EventEmitter das als uncaughtException -- der Hook wuerde entgegen
    // seiner fail-open-Zusage (Exit-Code IMMER 0) mit Stacktrace sterben.
    child.on('error', (err) => {
      debug(`Worker-Start fehlgeschlagen: ${err.message}`);
    });
    child.unref();
    debug(`Worker gestartet: ${python} fuer ${filePath}`);
    return true;
  } catch (err) {
    debug(`Worker-Start fehlgeschlagen: ${err.message}`);
    return false;
  }
}

// ---------------------------------------------------------------------------
// Phase 2: Drain
// ---------------------------------------------------------------------------

/** Marker der bereits gemeldeten Fehler. AC5 verlangt "einmal sichtbar" —
 *  ohne diese Datei wuerde derselbe fehlende Modell-Download bei jedem
 *  Kapitel-Write erneut gemeldet. */
function reportedErrorsFile() {
  return join(spoolDir(), '.reported-errors.json');
}

function loadReportedErrors() {
  try {
    const parsed = JSON.parse(readFileSync(reportedErrorsFile(), 'utf-8'));
    return Array.isArray(parsed) ? new Set(parsed) : new Set();
  } catch {
    return new Set();
  }
}

function saveReportedErrors(hashes) {
  try {
    const dir = spoolDir();
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true, mode: 0o700 });
    // Nur die letzten 50 Hashes behalten — der Marker ist ein Gedaechtnis,
    // kein Archiv.
    const kept = [...hashes].slice(-50);
    writeFileSync(reportedErrorsFile(), JSON.stringify(kept), 'utf-8');
    chmodSync(reportedErrorsFile(), 0o600);
  } catch (err) {
    debug(`Fehler-Marker nicht schreibbar: ${err.message}`);
  }
}

function readSpool() {
  const dir = spoolDir();
  let names = [];
  try {
    names = readdirSync(dir).filter((n) => n.endsWith('.json') && !n.startsWith('.'));
  } catch {
    return [];
  }
  const records = [];
  for (const name of names) {
    const full = join(dir, name);
    try {
      const record = JSON.parse(readFileSync(full, 'utf-8'));
      if (record && record.schema === SCHEMA_VERSION) records.push(record);
      else debug(`Unbekanntes Spool-Schema in ${name} — verworfen.`);
    } catch (err) {
      debug(`Spool-Datei ${name} unlesbar: ${err.message}`);
    }
    try {
      rmSync(full, { force: true });
    } catch {
      // Nicht loeschbar: die naechste Runde meldet es erneut. Kein Abbruch.
    }
  }
  return records;
}

function truncate(text, max = 160) {
  const flat = String(text ?? '').replace(/\s+/g, ' ').trim();
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
}

/** Baut die Meldezeilen. AC3: Zitat, Beleg und Kapitelsatz stehen in der
 *  Meldung selbst — nachvollziehbar ohne Nachschlagen im Vault. */
function formatRecords(records, alreadyReported = new Set()) {
  const lines = [];
  const newErrorHashes = [];

  for (const record of records) {
    const chapter = record.chapter || '(unbekanntes Kapitel)';
    if (record.error) {
      const hash = createHash('sha256').update(String(record.error), 'utf-8').digest('hex');
      if (alreadyReported.has(hash)) {
        debug(`Fehler bereits gemeldet, uebersprungen: ${record.error}`);
        continue;
      }
      newErrorHashes.push(hash);
      lines.push(`[NLI-Zitatscan] Scan fuer ${chapter} nicht moeglich: ${truncate(record.error, 300)}`);
      lines.push('  Die Sitzung laeuft normal weiter; die uebrigen Zitat-Guards sind unberuehrt.');
      lines.push('  Dauerhaft abschalten: ACADEMIC_RESEARCH_NLI_PREFILTER=0 oder '
        + '"nli_prefilter_enabled": false in config/parallel_agents.json.');
      continue;
    }

    const findings = Array.isArray(record.findings) ? record.findings : [];
    if (findings.length === 0) continue;

    const scanned = Number.isFinite(record.scanned) ? record.scanned : findings.length;
    lines.push(
      `[NLI-Zitatscan] ${findings.length} von ${scanned} belegten Zitat(en) in ${chapter} `
      + 'werden von ihrer Quelle moeglicherweise nicht getragen:',
    );
    for (const finding of findings.slice(0, MAX_REPORTED)) {
      lines.push(`  Zitat: "${truncate(finding.verbatim)}"`);
      lines.push(`  Beleg: ${truncate(finding.paper_ref || finding.paper_id, 120)} `
        + `[${finding.paper_id}, quote_id ${finding.quote_id}]`);
      lines.push(`  Kapitelsatz: ${truncate(finding.chapter_claim)}`);
      if (typeof finding.raw_score === 'number') {
        lines.push(`  Entailment-Score: ${finding.raw_score.toFixed(2)}`);
      }
    }
    if (findings.length > MAX_REPORTED) {
      lines.push(`  … und ${findings.length - MAX_REPORTED} weitere Fundstelle(n).`);
    }
    lines.push(
      '  Das ist ein Verdacht, kein Urteil: den quote-fidelity-auditor-Agenten mit der '
      + 'quote_id aufrufen oder selbst gegen die Quelle pruefen. Kein Zitat wurde aus dem '
      + 'Pruefpfad entfernt.',
    );
  }

  return { message: lines.join('\n'), newErrorHashes };
}

function emit(message, eventName) {
  if (!message) return;
  process.stderr.write(`${message}\n`);
  // Exit 0 + JSON auf stdout, bewusst ohne permissionDecision: der Hook
  // informiert, er entscheidet nichts. Plain stdout landet laut
  // Claude-Code-Hook-Doku nur im Debug-Log — additionalContext ist der Weg,
  // auf dem die Meldung das Modell tatsaechlich erreicht.
  console.log(JSON.stringify({
    systemMessage: message,
    hookSpecificOutput: {
      hookEventName: eventName,
      additionalContext: message,
    },
  }));
}

// ---------------------------------------------------------------------------
// Haupt-Logik
// ---------------------------------------------------------------------------

async function main() {
  let input = {};
  try {
    const raw = await readStdin();
    input = raw.trim() ? JSON.parse(raw) : {};
  } catch {
    process.exit(0); // Malformed stdin — stumm
  }

  if (!scanEnabled()) {
    debug('Schalter aus — weder Scan noch Drain.');
    process.exit(0);
  }

  const eventName = input?.hook_event_name || 'PostToolUse';
  const toolName = input?.tool_name || '';

  // Phase 1: Spawn — ausschliesslich beim PostToolUse eines Kapitel-Writes.
  if (eventName === 'PostToolUse' && WRITE_LIKE_TOOLS.has(toolName)) {
    const toolInput = input?.tool_input || {};
    const filePath = toolInput.file_path || '';
    if (!isProtectedPath(filePath)) {
      debug(`${filePath || '(kein Pfad)'} ist kein Kapitelpfad — kein Scan.`);
    } else if (authoredContent(toolName, toolInput).includes(BYPASS_MARKER)) {
      debug('Bypass-Marker gesetzt — kein Scan.');
    } else {
      spawnWorker(filePath);
    }
  }

  // Phase 2: Drain — bei jedem Aufruf, auch dem des UserPromptSubmit-Events.
  const reported = loadReportedErrors();
  const { message, newErrorHashes } = formatRecords(readSpool(), reported);
  if (newErrorHashes.length) {
    for (const hash of newErrorHashes) reported.add(hash);
    saveReportedErrors(reported);
  }
  // Kein process.exit() nach dem Schreiben: stdout ist bei einer Pipe
  // asynchron, ein sofortiges exit() koennte die Meldung abschneiden. Der
  // Prozess endet hier ohnehin mit 0.
  emit(message, eventName);
}

main().catch((err) => {
  process.stderr.write(`[NLI-Zitatscan] Unerwarteter Fehler: ${err.message}\n`);
  process.exit(0); // fail-open
});
