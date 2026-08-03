#!/usr/bin/env node
/**
 * hooks/session-snapshot.mjs — Session-Ende-Snapshot des Vaults (#625)
 *
 * Der einzige automatische Vault-Snapshot hing bislang am `PreCompact`-Event,
 * das nur in langen Sitzungen feuert. Wer in kurzen Sitzungen arbeitet,
 * erzeugte über Wochen keinen einzigen Snapshot. Dieser Hook laeuft
 * ZUSAETZLICH unter dem bestehenden `Stop`-Event und sichert den Vault auch
 * am Ende jeder Sitzung — als eigenstaendiger Snapshot-Pfad, ohne den
 * Compaction-Snapshot zu importieren oder aufzurufen (AC6).
 *
 * Ablauf:
 *   1. Fingerprint der Vault-DB (size + mtimeMs) gegen den Marker aus dem
 *      letzten Lauf vergleichen (<snapshotsDir>/<slug>/.last-session-snapshot.json).
 *   2. Unveraendert -> kein neuer Snapshot, aber Stderr-Meldung mit dem
 *      Zeitpunkt der letzten Sicherung (AC2, AC4).
 *   3. Veraendert (oder Marker fehlt/kaputt) -> Export ueber die vorhandene
 *      Python-Funktion academic_vault.server.export_snapshot(), aufgerufen
 *      via runVaultPython() aus hooks/lib/vault-bridge.mjs (dieselbe
 *      Interpreter-Kaskade wie die anderen Vault-Hooks, #382).
 *   4. Erfolg -> Marker aktualisieren, alte .tgz im Slug-Verzeichnis auf
 *      ACADEMIC_SNAPSHOTS_KEEP (Default 20) zurueckschneiden (AC3).
 *   5. Fehlschlag -> sichtbare ⚠️-Meldung auf stderr, Marker NICHT
 *      aktualisiert, trotzdem exit 0 (AC5, fail-open).
 *
 * Bekannte Grenzen (im Plan-Kommentar zu #625 dokumentiert, akzeptiert fuer
 * Umfang size/S):
 *   - Fingerprint statt Vollhash: (size, mtimeMs) statt SHA-256 ueber die
 *     komplette DB — billig, aber theoretisches False-Negative bei
 *     gleich grosser Aenderung binnen derselben Millisekunde.
 *   - Kein Locking zwischen parallelen Sitzungen auf demselben Projekt.
 *
 * Konfiguration via Umgebungsvariablen (analog zu den anderen Vault-Hooks, #382):
 *   ACADEMIC_SNAPSHOTS_DIR   — Zielverzeichnis (default: ~/.academic-research/snapshots)
 *   ACADEMIC_PROJECT_SLUG    — Projekt-Slug (default: basename(CLAUDE_PROJECT_DIR))
 *   CLAUDE_PROJECT_DIR       — Projekt-Verzeichnis (default: cwd)
 *   VAULT_DB_PATH            — Pfad zur Vault-DB
 *   ACADEMIC_SNAPSHOTS_KEEP  — Anzahl aufbewahrter .tgz je Slug (default: 20)
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync, statSync, unlinkSync, readdirSync } from 'node:fs';
import { join, basename } from 'node:path';
import * as os from 'node:os';

import { resolveVaultDb, runVaultPython, VAULT_SRC } from './lib/vault-bridge.mjs';

// ---------------------------------------------------------------------------
// Konfiguration
// ---------------------------------------------------------------------------

const SNAPSHOTS_DIR = process.env.ACADEMIC_SNAPSHOTS_DIR
  || join(os.homedir(), '.academic-research', 'snapshots');
const PROJECT_DIR = process.env.CLAUDE_PROJECT_DIR || process.cwd();
const SLUG = process.env.ACADEMIC_PROJECT_SLUG || basename(PROJECT_DIR) || 'default';
const VAULT_DB = resolveVaultDb();
const DEFAULT_KEEP = 20;
const KEEP = (() => {
  const raw = Number.parseInt(process.env.ACADEMIC_SNAPSHOTS_KEEP ?? '', 10);
  return Number.isFinite(raw) && raw > 0 ? raw : DEFAULT_KEEP;
})();

const MARKER_NAME = '.last-session-snapshot.json';

// ---------------------------------------------------------------------------
// Stdin lesen (tolerant, malformte Eingaben brechen den Hook nicht ab)
// ---------------------------------------------------------------------------

async function readStdin() {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.setEncoding('utf-8');
    process.stdin.on('data', (chunk) => { data += chunk; });
    process.stdin.on('end', () => resolve(data.replace(/^﻿/, '')));
    process.stdin.on('error', () => resolve(''));
    process.stdin.resume();
  });
}

// ---------------------------------------------------------------------------
// Fingerprint / Marker
// ---------------------------------------------------------------------------

function vaultFingerprint() {
  if (!existsSync(VAULT_DB)) {
    return null;
  }
  const st = statSync(VAULT_DB);
  return { size: st.size, mtimeMs: st.mtimeMs };
}

function readMarker(markerPath) {
  if (!existsSync(markerPath)) {
    return null;
  }
  try {
    const raw = readFileSync(markerPath, 'utf-8');
    return JSON.parse(raw);
  } catch {
    // Kaputter Marker -> wie "geaendert" behandeln, kein Crash
    return null;
  }
}

function fingerprintsEqual(a, b) {
  if (!a || !b) return false;
  return a.size === b.size && a.mtimeMs === b.mtimeMs;
}

function writeMarker(markerPath, { fingerprint, snapshotPath, lastSnapshotAt }) {
  const payload = { fingerprint, snapshotPath, lastSnapshotAt };
  writeFileSync(markerPath, JSON.stringify(payload, null, 2) + '\n', 'utf-8');
}

// ---------------------------------------------------------------------------
// Retention-Pruning: nur *.tgz im Slug-Verzeichnis, nie die Marker-Datei
// ---------------------------------------------------------------------------

function pruneOldSnapshots(slugDir, keep) {
  let entries;
  try {
    entries = readdirSync(slugDir);
  } catch {
    return;
  }
  const tarballs = entries
    .filter((name) => name.endsWith('.tgz'))
    .sort(); // Dateinamen sind YYYYMMDD-HHMM.tgz -> lexikographisch == chronologisch

  const excess = tarballs.length - keep;
  if (excess <= 0) return;

  for (const name of tarballs.slice(0, excess)) {
    try {
      unlinkSync(join(slugDir, name));
    } catch (err) {
      process.stderr.write(`[Session-Snapshot] Konnte alten Snapshot nicht loeschen (${name}): ${err.message}\n`);
    }
  }
}

// ---------------------------------------------------------------------------
// Vault-Export via vault-bridge.mjs
// ---------------------------------------------------------------------------

function exportVaultSnapshot() {
  const pyCode = [
    'import sys',
    `sys.path.insert(0, ${JSON.stringify(VAULT_SRC)})`,
    'from academic_vault.server import export_snapshot',
    'result = export_snapshot(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])',
    'print(result or "")',
  ].join('; ');

  const stdout = runVaultPython(
    pyCode,
    [VAULT_DB, SLUG, PROJECT_DIR, SNAPSHOTS_DIR],
    { timeout: 20000, budget: 25000, label: 'Session-Snapshot' },
  );

  if (stdout === null) {
    return null;
  }
  const outPath = stdout.trim();
  return outPath || null;
}

// ---------------------------------------------------------------------------
// Haupt-Logik
// ---------------------------------------------------------------------------

async function main() {
  try {
    const raw = await readStdin();
    if (raw.trim()) {
      JSON.parse(raw);
    }
  } catch {
    // Malformed stdin — trotzdem weitermachen (fail-open)
  }

  if (!existsSync(PROJECT_DIR)) {
    process.stderr.write(`[Session-Snapshot] Warnung: PROJECT_DIR nicht gefunden: ${PROJECT_DIR}\n`);
    process.exit(0);
  }

  const slugDir = join(SNAPSHOTS_DIR, SLUG);
  if (!existsSync(slugDir)) {
    mkdirSync(slugDir, { recursive: true });
  }
  const markerPath = join(slugDir, MARKER_NAME);

  const currentFingerprint = vaultFingerprint();
  if (currentFingerprint === null) {
    process.stderr.write(`[Session-Snapshot] Vault-DB nicht gefunden (${VAULT_DB}). Snapshot übersprungen.\n`);
    process.exit(0);
  }

  const marker = readMarker(markerPath);

  if (marker && fingerprintsEqual(marker.fingerprint, currentFingerprint)) {
    const lastAt = marker.lastSnapshotAt || 'unbekannt';
    process.stderr.write(`[Session-Snapshot] Vault unveraendert seit letzter Sicherung (${lastAt}). Kein neuer Snapshot.\n`);
    process.exit(0);
  }

  const outPath = exportVaultSnapshot();

  if (!outPath) {
    process.stderr.write('[Session-Snapshot] ⚠️ Vault-Sicherung fehlgeschlagen — Sitzung wird trotzdem fortgesetzt.\n');
    process.exit(0);
  }

  const now = new Date().toISOString();
  writeMarker(markerPath, {
    fingerprint: currentFingerprint,
    snapshotPath: outPath,
    lastSnapshotAt: now,
  });
  pruneOldSnapshots(slugDir, KEEP);

  process.stderr.write(`[Session-Snapshot] Snapshot erstellt: ${outPath} (zuletzt gesichert: ${now})\n`);
  process.exit(0);
}

main().catch((err) => {
  process.stderr.write(`[Session-Snapshot] Unerwarteter Fehler: ${err.message}\n`);
  process.exit(0); // fail-open
});
