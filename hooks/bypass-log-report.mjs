#!/usr/bin/env node
/**
 * hooks/bypass-log-report.mjs — SessionStart-Bypass-/Env-Switch-Report
 * (Issue #517, erweitert um Issue #519)
 *
 * Rein LESENDER SessionStart-Hook: meldet Anzahl und betroffene Dateien
 * NEUER Eintraege seit dem letzten SessionStart in zwei unabhaengigen Logs:
 *
 *   1. vault-guard-Bypass-Log (`<!-- vault-guard: skip -->`, geschrieben von
 *      `verbatim-guard.mjs`, Issue #381) — Abschnitt "Bypass-Report".
 *   2. Env-Switch-Log (guard-schwaechende Schalter ACADEMIC_CITATION_*,
 *      geschrieben von `verbatim-guard.mjs`, Issue #519) — Abschnitt
 *      "Env-Switch-Report".
 *
 * Beide Logs waren bisher unsichtbar — nichts las sie (Audit-Risiken R8/R7).
 *
 * Scope (Issue #517 fuer den Bypass-Teil, #519 fuer den Env-Switch-Teil):
 *   In:  dieser Hook (Leseseite), je ein Merkposten "zuletzt gemeldet".
 *   Out: das Blockieren des Bypass bzw. der Schalter (bleibt erlaubt), die
 *        Schreibseite (bleibt wie in verbatim-guard.mjs — unangetastet).
 *
 * Log-Formate (unveraendert, siehe verbatim-guard.mjs::logBypassUsage /
 * ::logEnvSwitchUsage):
 *   <ISO-Timestamp> | vault-guard: skip | <Dateipfad>
 *   <ISO-Timestamp> | <SCHALTER-NAME>=<Wert> | <Dateipfad>
 *
 * Merkposten: je eine State-Datei haelt die Byte-Groesse des jeweiligen Logs
 * zum Zeitpunkt des letzten Reports. Die Schreibseite rotiert die Logs nie
 * (Scope "Out"), ein reiner Byte-Offset genuegt daher. Schrumpft eine
 * Logdatei unerwartet unter den gespeicherten Offset (extern
 * geloescht/rotiert), wird der Offset auf 0 zurueckgesetzt statt zu crashen.
 *
 * Protokoll:
 *   - Eingabe: JSON via stdin (Claude Code SessionStart-Format), wird nicht
 *     ausgewertet — der Hook ist fuer jeden SessionStart-Aufruf gleich.
 *   - Ausgabe: pro Log mit >=1 neuem Eintrag ein Report-Abschnitt auf stdout
 *     (wird bei SessionStart laut Doku als Modell-Kontext injiziert); ohne
 *     neue Eintraege in beiden Logs keine Ausgabe (kein Rauschen).
 *   - Exit 0: immer (fail-open, nie blockierend — AC3).
 *
 * Konfiguration via Umgebungsvariablen:
 *   VAULT_GUARD_BYPASS_LOG          — Pfad zum Bypass-Log (Env-Override,
 *                                     sonst identische Aufloesung wie in
 *                                     verbatim-guard.mjs:
 *                                     ~/.academic-research/vault-guard-bypass.log)
 *   VAULT_GUARD_BYPASS_REPORT_STATE — Pfad zur Bypass-State-Datei (Env-Override,
 *                                     sonst
 *                                     ~/.academic-research/vault-guard-bypass-report-state.json)
 *   VAULT_GUARD_ENV_SWITCH_LOG          — Pfad zum Env-Switch-Log (Env-Override,
 *                                         sonst identische Aufloesung wie in
 *                                         verbatim-guard.mjs:
 *                                         ~/.academic-research/vault-guard-env-switch.log)
 *   VAULT_GUARD_ENV_SWITCH_REPORT_STATE — Pfad zur Env-Switch-State-Datei
 *                                         (Env-Override, sonst
 *                                         ~/.academic-research/vault-guard-env-switch-report-state.json)
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

const BYPASS_STATE_FILE = process.env.VAULT_GUARD_BYPASS_REPORT_STATE
  || join(os.homedir(), '.academic-research', 'vault-guard-bypass-report-state.json');

// Identische Pfadauflösung wie verbatim-guard.mjs::VAULT_GUARD_ENV_SWITCH_LOG.
const VAULT_GUARD_ENV_SWITCH_LOG = process.env.VAULT_GUARD_ENV_SWITCH_LOG
  || join(os.homedir(), '.academic-research', 'vault-guard-env-switch.log');

const ENV_SWITCH_STATE_FILE = process.env.VAULT_GUARD_ENV_SWITCH_REPORT_STATE
  || join(os.homedir(), '.academic-research', 'vault-guard-env-switch-report-state.json');

// Deckel fuer die im Report genannten Zeilen (dedupliziert) — verhindert eine
// ausufernde Meldung bei sehr vielen Nutzungen auf einmal. Gilt fuer beide
// Abschnitte.
const MAX_ENTRIES_IN_REPORT = 5;

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
// State-Verwaltung (parametrisiert auf eine State-Datei, Issue #519)
// ---------------------------------------------------------------------------

/**
 * Laedt den gespeicherten Offset (Byte-Groesse des Logs beim letzten Report).
 * Fehlt die State-Datei oder ist sie korrupt (kaputtes JSON): Offset 0 —
 * der Hook verhaelt sich dann wie beim allerersten Lauf (AC3).
 */
function loadOffset(stateFile) {
  if (!existsSync(stateFile)) {
    return 0;
  }
  try {
    const parsed = JSON.parse(readFileSync(stateFile, 'utf-8'));
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
function saveOffset(stateFile, offset) {
  try {
    const dir = dirname(stateFile);
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true, mode: 0o700 });
    }
    writeFileSync(stateFile, JSON.stringify({ offset }, null, 2), {
      encoding: 'utf-8',
      mode: 0o600,
    });
    chmodSync(stateFile, 0o600);
  } catch (err) {
    process.stderr.write(`[Bypass-Report] State-Datei konnte nicht gespeichert werden: ${err.message}\n`);
  }
}

// ---------------------------------------------------------------------------
// Log-Zeilen ab Offset lesen (parametrisiert auf einen Log-Pfad, Issue #519)
// ---------------------------------------------------------------------------

/**
 * Parst eine Log-Zeile im Format
 * "<ISO-Timestamp> | <Mittelfeld> | <Dateipfad>" und gibt { middle, path }
 * zurueck (oder null bei unerwartetem Format — wird dann nicht im Report
 * gefuehrt, zaehlt aber weiter zum Gesamtzaehler). Das Mittelfeld ist beim
 * Bypass-Log der feste Text "vault-guard: skip", beim Env-Switch-Log
 * "<SCHALTER-NAME>=<Wert>" (defensiv slice-basiert statt striktem
 * Split-Count, siehe Plan-Risiko zu Trennzeichen-Kollisionen).
 */
function parseLine(line) {
  const parts = line.split(' | ');
  if (parts.length < 3) return null;
  const middle = parts[1];
  const path = parts.slice(2).join(' | ').trim();
  return path ? { middle, path } : null;
}

/**
 * Liest neue Zeilen aus einer Logdatei seit dem gespeicherten Offset.
 *
 * Fail-open an jeder Stelle:
 *   - Logdatei existiert nicht: das ist der Normalfall ohne je genutzten
 *     Bypass/Schalter — kein Report, kein stderr-Rauschen, Offset bleibt 0.
 *   - Logdatei ist kuerzer als der gespeicherte Offset (externe Rotation/
 *     Loeschung): Offset wird auf 0 zurueckgesetzt statt eine negative
 *     Leselaenge zu erzeugen.
 *   - Lesefehler (z. B. Permissions): stderr-Warnung, keine neuen Zeilen.
 *
 * Gibt { newLines, currentSize } zurueck. currentSize ist die tatsaechliche
 * Dateigroesse (0, wenn die Datei fehlt) — Basis fuer den naechsten Offset.
 */
function readNewLines(logPath, offset) {
  if (!existsSync(logPath)) {
    return { newLines: [], currentSize: 0 };
  }

  let currentSize;
  try {
    currentSize = statSync(logPath).size;
  } catch (err) {
    process.stderr.write(`[Bypass-Report] Log-Datei nicht lesbar (${err.message}).\n`);
    return { newLines: [], currentSize: offset };
  }

  // Externe Rotation/Kuerzung: Datei ist kleiner als der gespeicherte Offset.
  const effectiveOffset = currentSize < offset ? 0 : offset;

  try {
    const full = readFileSync(logPath, 'utf-8');
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

/** Bypass-Abschnitt (Issue #517, unveraendertes Verhalten): Zaehler + betroffene Dateien. */
function printBypassReport(newLines) {
  const files = [];
  for (const line of newLines) {
    const parsed = parseLine(line);
    if (parsed && !files.includes(parsed.path)) {
      files.push(parsed.path);
    }
  }
  const shown = files.slice(0, MAX_ENTRIES_IN_REPORT);
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

/**
 * Env-Switch-Abschnitt (Issue #519): Zaehler + Schalter-Name, Wert und
 * Zieldatei je Eintrag (dedupliziert auf die exakte Kombination, gedeckelt).
 */
function printEnvSwitchReport(newLines) {
  const entries = [];
  for (const line of newLines) {
    const parsed = parseLine(line);
    if (!parsed) continue;
    const label = `${parsed.middle} (${parsed.path})`;
    if (!entries.includes(label)) {
      entries.push(label);
    }
  }
  const shown = entries.slice(0, MAX_ENTRIES_IN_REPORT);
  const overflow = entries.length - shown.length;

  const lines = [
    `[Env-Switch-Report] ${newLines.length} neue Nutzung(en) guard-schwächender `
      + 'Env-Schalter (ACADEMIC_CITATION_*) seit der letzten Session.',
  ];
  if (shown.length > 0) {
    lines.push('Details (Schalter=Wert (Zieldatei)):');
    for (const e of shown) {
      lines.push(`  - ${e}`);
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

  const bypassOffset = loadOffset(BYPASS_STATE_FILE);
  const bypassResult = readNewLines(VAULT_GUARD_BYPASS_LOG, bypassOffset);
  if (bypassResult.newLines.length > 0) {
    printBypassReport(bypassResult.newLines);
  }
  saveOffset(BYPASS_STATE_FILE, bypassResult.currentSize);

  const envSwitchOffset = loadOffset(ENV_SWITCH_STATE_FILE);
  const envSwitchResult = readNewLines(VAULT_GUARD_ENV_SWITCH_LOG, envSwitchOffset);
  if (envSwitchResult.newLines.length > 0) {
    printEnvSwitchReport(envSwitchResult.newLines);
  }
  saveOffset(ENV_SWITCH_STATE_FILE, envSwitchResult.currentSize);

  process.exit(0);
}

main().catch((err) => {
  process.stderr.write(`[Bypass-Report] Unerwarteter Fehler: ${err.message}\n`);
  process.exit(0); // fail-open (AC3)
});
