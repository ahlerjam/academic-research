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

import {
  appendFileSync,
  mkdirSync,
  existsSync,
  chmodSync,
  statSync,
  renameSync,
  createReadStream,
} from 'node:fs';
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
 * NOTLOESUNG, nicht die primaere Hash-Quelle (siehe hashFileFromDisk unten):
 * extrahiert den Text aus tool_input, den das jeweilige Tool geschrieben hat —
 * abhaengig vom Tool:
 *   - Write:     tool_input.content (= kompletter Datei-Inhalt)
 *   - Edit:      tool_input.new_string (= NUR das eingefuegte Fragment)
 *   - MultiEdit: alle edits[].new_string (zusammengefuegt, ebenfalls Fragmente)
 *
 * Fuer Edit/MultiEdit ist das ausdruecklich NICHT der resultierende
 * Datei-Inhalt — zwei verschiedene Aenderungen an derselben Datei koennen
 * zufaellig dasselbe new_string-Fragment einfuegen (z.B. dieselbe Ueberschrift
 * an zwei Stellen) und haetten dann identische Hashes, obwohl der
 * Datei-Zustand unterschiedlich ist. Nur als Fallback verwendet, wenn die
 * Datei nach dem Tool-Aufruf nicht von der Platte gelesen werden kann.
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

/**
 * Hasht den RESULTIERENDEN Datei-Inhalt von der Platte (SHA-256 ueber die
 * Rohbytes, kein Encoding) — das ist die einzige Quelle, die fuer Write,
 * Edit UND MultiEdit denselben Idempotenz-Vertrag erfuellt, den
 * academic_vault/decision_log.py::content_hash dokumentiert: "dieselbe Datei
 * mit demselben Inhalt einmal per Write und einmal per Edit geschrieben ist
 * eine Aenderung, keine zwei" (#644 / Finding 12).
 *
 * PostToolUse feuert NACHDEM Write/Edit/MultiEdit die Datei bereits
 * geschrieben haben — der Lesezugriff hier ist also kein Race gegen das
 * ausloesende Tool selbst, sondern nur gegen (seltene) externe Eingriffe.
 *
 * Gestreamt statt per readFileSync komplett eingelesen, damit auch grosse
 * Dateien keinen Speicherdruck erzeugen ("large files"-Fall). Der Hash laeuft
 * ueber die rohen Bytes (Buffer-Chunks, kein 'utf-8'-Decoding), damit auch
 * binaerer oder kaputter UTF-8-Inhalt deterministisch gehasht wird, statt
 * still durch Ersatzzeichen verfaelscht zu werden ("binary content"-Fall).
 *
 * Rueckgabe: { ok: true, hash } bei Erfolg, sonst { ok: false, error } — der
 * Fehler wird NICHT verschluckt, der Aufrufer schreibt ihn auf stderr, bevor
 * er auf den Fragment-/Content-Fallback ausweicht ("file missing/unreadable
 * after the tool ran"-Fall, z.B. geloescht, keine Leserechte, ist ein
 * Verzeichnis).
 */
function hashFileFromDisk(filePath) {
  return new Promise((resolve) => {
    let stream;
    try {
      stream = createReadStream(filePath);
    } catch (err) {
      resolve({ ok: false, error: err.message });
      return;
    }
    const hash = createHash('sha256');
    stream.on('data', (chunk) => hash.update(chunk));
    stream.on('end', () => resolve({ ok: true, hash: hash.digest('hex') }));
    stream.on('error', (err) => resolve({ ok: false, error: err.message }));
  });
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

  // Nur .md-Dateien im Projekt
  if (!isMdInProject(filePath)) {
    process.exit(0);
  }

  const relPath = toRelPath(filePath);

  // SHA-256-Hash des RESULTIERENDEN Datei-Inhalts (Finding 12) — nicht des
  // Edit-Fragments. PostToolUse feuert nach dem Schreiben, die Datei liegt
  // also bereits im Ziel-Zustand vor; das ist fuer Write, Edit und MultiEdit
  // gleichermassen die korrekte Idempotenz-Quelle. Klartext landet nirgends
  // im Log — nur der Hash.
  const diskResult = await hashFileFromDisk(filePath);
  let hash;
  if (diskResult.ok) {
    hash = diskResult.hash;
  } else {
    // Nicht stillschweigend uebergehen: Diagnosezeile auf stderr, dann
    // Fallback auf den Fragment-/Content-Text aus tool_input, damit der Hook
    // fail-open bleibt. In Produktion ein seltener Rand-/Race-Fall (Datei
    // zwischen Tool-Aufruf und Hook geloescht o.ae.); die Idempotenz-Garantie
    // ist fuer DIESEN einen Eintrag dann eingeschraenkt.
    process.stderr.write(
      `[Decisions-Log] Datei nach ${toolName} nicht von Platte lesbar (${filePath}): ` +
        `${diskResult.error}. Fallback auf Fragment-Hash.\n`
    );
    const fallbackContent = extractContent(toolName, toolInput);
    hash = createHash('sha256').update(fallbackContent || '', 'utf-8').digest('hex');
  }

  recordInVault(toolName, relPath, hash);
  writeLogLine(toolName, relPath, hash);
  process.exit(0);
}

main().catch((err) => {
  process.stderr.write(`[Decisions-Log] Unerwarteter Fehler: ${err.message}\n`);
  process.exit(0); // fail-open
});
