#!/usr/bin/env node
/**
 * hooks/session-snapshot.mjs — Session-Ende-Snapshot des Vaults (#625)
 *
 * Der einzige automatische Vault-Snapshot hing bislang am `PreCompact`-Event,
 * das nur in langen Sitzungen feuert. Wer in kurzen Sitzungen arbeitet,
 * erzeugte über Wochen keinen einzigen Snapshot. Dieser Hook läuft
 * ZUSÄTZLICH unter dem bestehenden `Stop`-Event und sichert den Vault auch
 * am Ende jeder Sitzung — als eigenständiger Snapshot-Pfad, ohne den
 * Compaction-Snapshot zu importieren oder aufzurufen (AC6).
 *
 * DROSSELUNG PRO SITZUNG (Audit P1, PR #650): Der `Stop`-Event feuert nach
 * JEDEM Turn, nicht nur am Sitzungsende. Um Perf-Regression und Retention-
 * Kollaps zu vermeiden, trackt der Hook die session_id aus dem Stop-Payload:
 * Pro Sitzung wird maximal einmal exportiert, nachfolgende Turns in derselben
 * Sitzung überspringen den Export. Neue Sitzung (neue session_id) triggert
 * erneut einen Export.
 *
 * Ablauf:
 *   1. session_id aus dem Stop-Payload extrahieren. Ist sie identisch mit
 *      der im Marker gespeicherten (und beide non-null), überspringen wir
 *      Punkte 2–4 und beenden mit Meldung (P1-Audit-Fix).
 *   2. Fingerprint der Vault-DB (size + mtimeMs) gegen den Marker aus dem
 *      letzten Lauf vergleichen (<snapshotsDir>/<slug>/.last-session-snapshot.json).
 *   3. Unveraendert -> kein neuer Snapshot, aber Stderr-Meldung mit dem
 *      Zeitpunkt der letzten Sicherung (AC2, AC4).
 *   4. Veraendert (oder Marker fehlt/kaputt) -> Export ueber die vorhandene
 *      Python-Funktion academic_vault.server.export_snapshot(), aufgerufen
 *      via runVaultPython() aus hooks/lib/vault-bridge.mjs (dieselbe
 *      Interpreter-Kaskade wie die anderen Vault-Hooks, #382).
 *   5. Erfolg -> Export-Datei mit dem Suffix `.session.tgz` kennzeichnen
 *      (Herkunftsmarkierung, siehe OWN_SNAPSHOT_SUFFIX unten), Marker
 *      aktualisieren (session_id speichern), eigene alte `*.session.tgz` im
 *      Slug-Verzeichnis auf ACADEMIC_SNAPSHOTS_KEEP (Default 20)
 *      zurückschneiden (AC3). Das Slug-Verzeichnis wird mit dem Compaction-
 *      Snapshot geteilt, dessen eigene .tgz-Dateien vom Pruning dieses Hooks
 *      unangetastet bleiben (Audit-Finding P1, PR #650: blindes Pruning nach
 *      reinem .tgz-Count konnte fremde, potenziell vault-haltige Snapshots
 *      verdrängen).
 *   6. Fehlschlag -> sichtbare ⚠️-Meldung auf stderr, Marker NICHT
 *      aktualisiert, trotzdem exit 0 (AC5, fail-open).
 *
 * Bekannte Grenzen (im Plan-Kommentar zu #625 dokumentiert, akzeptiert fuer
 * Umfang size/S):
 *   - Fingerprint statt Vollhash: (size, mtimeMs) statt SHA-256 ueber die
 *     komplette DB — billig, aber theoretisches False-Negative bei
 *     gleich grosser Aenderung binnen derselben Millisekunde.
 *   - Kein Locking zwischen parallelen Sitzungen auf demselben Projekt.
 *   - session_id abhängig von Claude-Code-Implementierung: Wenn das System
 *     die session_id nicht im Stop-Payload mitteilt (oder null), fällt die
 *     Pro-Sitzungs-Drosselung weg und der Hook exportiert wie in Punkt 3–5.
 *
 * Konfiguration via Umgebungsvariablen (analog zu den anderen Vault-Hooks, #382):
 *   ACADEMIC_SNAPSHOTS_DIR   — Zielverzeichnis (default: ~/.academic-research/snapshots)
 *   ACADEMIC_PROJECT_SLUG    — Projekt-Slug (default: basename(CLAUDE_PROJECT_DIR))
 *   CLAUDE_PROJECT_DIR       — Projekt-Verzeichnis (default: cwd)
 *   VAULT_DB_PATH            — Pfad zur Vault-DB
 *   ACADEMIC_SNAPSHOTS_KEEP  — Anzahl aufbewahrter .tgz je Slug (default: 20)
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync, statSync, unlinkSync, readdirSync, renameSync } from 'node:fs';
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

// Kennzeichnungs-Suffix fuer von DIESEM Hook erzeugte Tarballs. Das
// Slug-Verzeichnis wird mit dem PreCompact-Snapshot-Hook geteilt, der eigene
// .tgz-Dateien nach demselben `YYYYMMDD-HHMM.tgz`-Schema ablegt, ohne
// Herkunftskennzeichen.
// Ohne diesen Suffix koennte pruneOldSnapshots() nicht zwischen eigenen und
// fremden Dateien unterscheiden und faelschlich fremde (potenziell
// vault-haltige) Snapshots loeschen (Audit-Finding P1, PR #650).
const OWN_SNAPSHOT_SUFFIX = '.session.tgz';

// (isOwnSnapshotFilename filtert genau die eigenen, oben markierten Dateien;
// fremde .tgz-Dateien — z. B. vom PreCompact-Snapshot-Hook — matchen nicht.)
function isOwnSnapshotFilename(name) {
  return name.endsWith(OWN_SNAPSHOT_SUFFIX);
}

/**
 * Haengt OWN_SNAPSHOT_SUFFIX an den von export_snapshot() gelieferten Pfad an
 * (z. B. `20260803-1230.tgz` -> `20260803-1230.session.tgz`) und benennt die
 * Datei entsprechend um. Damit bleibt die Namensordnung chronologisch
 * sortierbar, ist aber eindeutig diesem Hook zuordenbar.
 */
function markAsOwnSnapshot(outPath) {
  const markedPath = outPath.endsWith('.tgz')
    ? outPath.slice(0, -'.tgz'.length) + OWN_SNAPSHOT_SUFFIX
    : outPath + OWN_SNAPSHOT_SUFFIX;
  try {
    renameSync(outPath, markedPath);
    return markedPath;
  } catch (err) {
    // Umbenennen fehlgeschlagen -> Original-Pfad weiterverwenden statt
    // abzubrechen (fail-open); der Snapshot existiert bereits und ist gueltig,
    // nur die Herkunftskennzeichnung fehlt fuer diesen einen Lauf.
    process.stderr.write(`[Session-Snapshot] Konnte Snapshot nicht kennzeichnen (${err.message}), verwende Originalpfad.\n`);
    return outPath;
  }
}

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

function writeMarker(markerPath, { fingerprint, snapshotPath, lastSnapshotAt, sessionId }) {
  const payload = { fingerprint, snapshotPath, lastSnapshotAt, session_id: sessionId };
  writeFileSync(markerPath, JSON.stringify(payload, null, 2) + '\n', 'utf-8');
}

// ---------------------------------------------------------------------------
// Retention-Pruning: nur die EIGENEN *.session.tgz im (geteilten)
// Slug-Verzeichnis, nie die Marker-Datei und nie fremde .tgz-Dateien (z. B.
// vom PreCompact-Snapshot-Hook) — siehe OWN_SNAPSHOT_SUFFIX oben.
// ---------------------------------------------------------------------------

function pruneOldSnapshots(slugDir, keep) {
  let entries;
  try {
    entries = readdirSync(slugDir);
  } catch {
    return;
  }
  const tarballs = entries
    .filter(isOwnSnapshotFilename)
    .sort(); // Dateinamen sind YYYYMMDD-HHMM.session.tgz -> lexikographisch == chronologisch

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
  let stopPayload = null;
  try {
    const raw = await readStdin();
    if (raw.trim()) {
      stopPayload = JSON.parse(raw);
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
  // Claude-Code-Hook-Payloads verwenden snake_case, nicht camelCase
  const currentSessionId = stopPayload?.session_id || null;

  // Drosseln pro Sitzung: schon in dieser Sitzung exportiert?
  if (marker && marker.sessionId === currentSessionId && currentSessionId !== null) {
    const lastAt = marker.lastSnapshotAt || 'unbekannt';
    process.stderr.write(`[Session-Snapshot] Snapshot bereits in dieser Sitzung erstellt (${lastAt}). Uebersprungen.\n`);
    process.exit(0);
  }

  if (marker && fingerprintsEqual(marker.fingerprint, currentFingerprint)) {
    const lastAt = marker.lastSnapshotAt || 'unbekannt';
    process.stderr.write(`[Session-Snapshot] Vault unveraendert seit letzter Sicherung (${lastAt}). Kein neuer Snapshot.\n`);
    process.exit(0);
  }

  const exportedPath = exportVaultSnapshot();

  if (!exportedPath) {
    process.stderr.write('[Session-Snapshot] ⚠️ Vault-Sicherung fehlgeschlagen — Sitzung wird trotzdem fortgesetzt.\n');
    process.exit(0);
  }

  const outPath = markAsOwnSnapshot(exportedPath);

  const now = new Date().toISOString();
  writeMarker(markerPath, {
    fingerprint: currentFingerprint,
    snapshotPath: outPath,
    lastSnapshotAt: now,
    sessionId: currentSessionId,
  });
  pruneOldSnapshots(slugDir, KEEP);

  process.stderr.write(`[Session-Snapshot] Snapshot erstellt: ${outPath} (zuletzt gesichert: ${now})\n`);
  process.exit(0);
}

main().catch((err) => {
  process.stderr.write(`[Session-Snapshot] Unerwarteter Fehler: ${err.message}\n`);
  process.exit(0); // fail-open
});
