#!/usr/bin/env node
/**
 * hooks/bypass-log-report.mjs — SessionStart-Bypass-Report (Issue #517)
 *
 * Rein LESENDER SessionStart-Hook: meldet Anzahl und betroffene Dateien
 * NEUER Eintraege im vault-guard-Bypass-Log (`<!-- vault-guard: skip -->`,
 * geschrieben von `verbatim-guard.mjs`, Issue #381) seit dem letzten
 * SessionStart. Der Bypass-Marker ist fuer Ausnahmefaelle legitim, blieb
 * bisher aber vollstaendig unsichtbar — nichts las das Log (Audit-Risiko R8).
 *
 * Scope (Issue #517):
 *   In:  dieser Hook (Leseseite), Merkposten "zuletzt gemeldet".
 *   Out: das Blockieren des Bypass (bleibt erlaubt), die Schreibseite
 *        (bleibt wie in verbatim-guard.mjs — unangetastet).
 *
 * Log-Format (unveraendert, siehe verbatim-guard.mjs::logBypassUsage):
 *   <ISO-Timestamp> | vault-guard: skip | <Dateipfad>
 *
 * Merkposten: eine State-Datei haelt die Byte-Groesse des Logs zum Zeitpunkt
 * des letzten Reports. Die Schreibseite rotiert das Log nie (Scope "Out"),
 * ein reiner Byte-Offset genuegt daher. Schrumpft die Logdatei unerwartet
 * unter den gespeicherten Offset (extern geloescht/rotiert), wird der Offset
 * auf 0 zurueckgesetzt statt zu crashen.
 *
 * Protokoll:
 *   - Eingabe: JSON via stdin (Claude Code SessionStart-Format), wird nicht
 *     ausgewertet — der Hook ist fuer jeden SessionStart-Aufruf gleich.
 *   - Ausgabe: bei >=1 neuem Eintrag ein Report-Text auf stdout (wird bei
 *     SessionStart laut Doku als Modell-Kontext injiziert); bei 0 neuen
 *     Eintraegen keine Ausgabe (kein Rauschen).
 *   - Exit 0: immer (fail-open, nie blockierend — AC3).
 *
 * Konfiguration via Umgebungsvariablen:
 *   VAULT_GUARD_BYPASS_LOG          — Pfad zum Bypass-Log (Env-Override,
 *                                     sonst identische Aufloesung wie in
 *                                     verbatim-guard.mjs:
 *                                     ~/.academic-research/vault-guard-bypass.log)
 *   VAULT_GUARD_BYPASS_REPORT_STATE — Pfad zur State-Datei (Env-Override,
 *                                     sonst
 *                                     ~/.academic-research/vault-guard-bypass-report-state.json)
 */

import { existsSync, readFileSync, writeFileSync, mkdirSync, chmodSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import * as os from 'node:os';

// ---------------------------------------------------------------------------
// Konfiguration
// ---------------------------------------------------------------------------

// Identische Pfadauflösung wie verbatim-guard.mjs::VAULT_GUARD_BYPASS_LOG.
const VAULT_GUARD_BYPASS_LOG = process.env.VAULT_GUARD_BYPASS_LOG
  || join(os.homedir(), '.academic-research', 'vault-guard-bypass.log');

const STATE_FILE = process.env.VAULT_GUARD_BYPASS_REPORT_STATE
  || join(os.homedir(), '.academic-research', 'vault-guard-bypass-report-state.json');

// Deckel fuer die im Report genannten Dateien (dedupliziert) — verhindert
// eine ausufernde Meldung bei sehr vielen Bypass-Nutzungen auf einmal.
const MAX_FILES_IN_REPORT = 5;

// ---------------------------------------------------------------------------
// Stdin lesen (Payload wird nicht ausgewertet, siehe Dateikopf)
// ---------------------------------------------------------------------------

async function readStdin() {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.setEncoding('utf-8');
    process.stdin.on('data', (chunk) => { data += chunk; });
    process.stdin.on('end', () => resolve(data));
    // Malformed/kein stdin ist hier nie fatal — der Hook wertet den Payload
    // nicht aus.
    process.stdin.on('error', () => resolve(''));
    process.stdin.resume();
  });
}

// ---------------------------------------------------------------------------
// State-Verwaltung
// ---------------------------------------------------------------------------

/**
 * Laedt den gespeicherten Offset (Byte-Groesse des Logs beim letzten Report).
 * Fehlt die State-Datei oder ist sie korrupt (kaputtes JSON): Offset 0 —
 * der Hook verhaelt sich dann wie beim allerersten Lauf (AC3).
 */
function loadOffset() {
  if (!existsSync(STATE_FILE)) {
    return 0;
  }
  try {
    const parsed = JSON.parse(readFileSync(STATE_FILE, 'utf-8'));
    const offset = Number(parsed?.offset);
    return Number.isFinite(offset) && offset >= 0 ? offset : 0;
  } catch (err) {
    process.stderr.write(
      `[Bypass-Report] State-Datei nicht lesbar (${err.message}) — Offset auf 0 zurueckgesetzt.\n`
    );
    return 0;
  }
}

/**
 * Speichert den neuen Offset. Best-effort: ein Schreibfehler darf den Hook
 * nie blockierend machen (AC3), er wird nur auf stderr sichtbar.
 */
function saveOffset(offset) {
  try {
    const dir = dirname(STATE_FILE);
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true, mode: 0o700 });
    }
    writeFileSync(STATE_FILE, JSON.stringify({ offset }, null, 2), {
      encoding: 'utf-8',
      mode: 0o600,
    });
    chmodSync(STATE_FILE, 0o600);
  } catch (err) {
    process.stderr.write(`[Bypass-Report] State-Datei konnte nicht gespeichert werden: ${err.message}\n`);
  }
}

// ---------------------------------------------------------------------------
// Log-Zeilen ab Offset lesen
// ---------------------------------------------------------------------------

/**
 * Parst eine Log-Zeile im Format
 * "<ISO-Timestamp> | vault-guard: skip | <Dateipfad>" und gibt den Dateipfad
 * zurueck (oder null bei unerwartetem Format — wird dann nicht in der
 * Dateiliste gefuehrt, zaehlt aber weiter zum Gesamtzaehler).
 */
function parseFilePath(line) {
  const parts = line.split(' | ');
  if (parts.length < 3) return null;
  const path = parts.slice(2).join(' | ').trim();
  return path || null;
}

/**
 * Liest neue Zeilen aus dem Bypass-Log seit dem gespeicherten Offset.
 *
 * Fail-open an jeder Stelle:
 *   - Logdatei existiert nicht: das ist der Normalfall ohne je genutzten
 *     Bypass — kein Report, kein stderr-Rauschen, Offset bleibt 0.
 *   - Logdatei ist kuerzer als der gespeicherte Offset (externe Rotation/
 *     Loeschung): Offset wird auf 0 zurueckgesetzt statt eine negative
 *     Leselaenge zu erzeugen.
 *   - Lesefehler (z. B. Permissions): stderr-Warnung, keine neuen Zeilen.
 *
 * Gibt { newLines, currentSize } zurueck. currentSize ist die tatsaechliche
 * Dateigroesse (0, wenn die Datei fehlt) — Basis fuer den naechsten Offset.
 */
function readNewLines(offset) {
  if (!existsSync(VAULT_GUARD_BYPASS_LOG)) {
    return { newLines: [], currentSize: 0 };
  }

  let currentSize;
  try {
    currentSize = statSync(VAULT_GUARD_BYPASS_LOG).size;
  } catch (err) {
    process.stderr.write(`[Bypass-Report] Log-Datei nicht lesbar (${err.message}).\n`);
    return { newLines: [], currentSize: offset };
  }

  // Externe Rotation/Kuerzung: Datei ist kleiner als der gespeicherte Offset.
  const effectiveOffset = currentSize < offset ? 0 : offset;

  try {
    const full = readFileSync(VAULT_GUARD_BYPASS_LOG, 'utf-8');
    // Byte-Offset auf den utf-8-Puffer anwenden, nicht auf den dekodierten
    // String — die Datei enthaelt aber nur ASCII/Unicode-Timestamps und
    // -Pfade, ein Slice auf dem Buffer ist daher unkritisch.
    const buffer = Buffer.from(full, 'utf-8');
    const tail = buffer.subarray(Math.min(effectiveOffset, buffer.length)).toString('utf-8');
    const newLines = tail.split('\n').map((l) => l.trim()).filter((l) => l.length > 0);
    return { newLines, currentSize };
  } catch (err) {
    process.stderr.write(`[Bypass-Report] Log-Datei nicht lesbar (${err.message}).\n`);
    return { newLines: [], currentSize: offset };
  }
}

// ---------------------------------------------------------------------------
// Report ausgeben
// ---------------------------------------------------------------------------

function printReport(newLines) {
  const files = [];
  for (const line of newLines) {
    const path = parseFilePath(line);
    if (path && !files.includes(path)) {
      files.push(path);
    }
  }
  const shown = files.slice(0, MAX_FILES_IN_REPORT);
  const overflow = files.length - shown.length;

  const lines = [
    `[Bypass-Report] ${newLines.length} neue Nutzung(en) von <!-- vault-guard: skip --> seit der letzten Session.`,
  ];
  if (shown.length > 0) {
    lines.push('Betroffene Dateien:');
    for (const f of shown) {
      lines.push(`  - ${f}`);
    }
    if (overflow > 0) {
      lines.push(`  … und ${overflow} weitere`);
    }
  }
  process.stdout.write(lines.join('\n') + '\n');
}

// ---------------------------------------------------------------------------
// Haupt-Logik
// ---------------------------------------------------------------------------

async function main() {
  // Stdin wird nur konsumiert, damit der Prozess nicht auf offenem stdin
  // haengt — der Payload selbst ist fuer diesen Hook irrelevant.
  await readStdin();

  const offset = loadOffset();
  const { newLines, currentSize } = readNewLines(offset);

  if (newLines.length > 0) {
    printReport(newLines);
  }

  saveOffset(currentSize);
  process.exit(0);
}

main().catch((err) => {
  process.stderr.write(`[Bypass-Report] Unerwarteter Fehler: ${err.message}\n`);
  process.exit(0); // fail-open (AC3)
});
