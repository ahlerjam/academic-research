#!/usr/bin/env node
/**
 * hooks/pre-compact.mjs — PreCompact Snapshot Hook
 *
 * Schreibt vor jeder Compaction einen Snapshot:
 *   - academic_context.md, literature_state.md, writing_state.md
 *   - vault.export_snapshot() als Tarball nach
 *     ACADEMIC_SNAPSHOTS_DIR/<slug>/<ts>.tgz
 *
 * Protokoll:
 *   - Eingabe: JSON via stdin (Claude Code PreCompact/Notification-Format)
 *   - Exit 0: immer (fail-open, nie blockierend)
 *
 * Konfiguration via Umgebungsvariablen:
 *   ACADEMIC_SNAPSHOTS_DIR  — Zielverzeichnis für Snapshots (default: ~/.academic-research/snapshots)
 *   ACADEMIC_PROJECT_SLUG   — Projekt-Slug (default: basename(CLAUDE_PROJECT_DIR), Issue #382)
 *   CLAUDE_PROJECT_DIR      — Projekt-Verzeichnis (default: cwd)
 *   VAULT_DB_PATH           — Pfad zur Vault-DB
 */

import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, createWriteStream } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { join, dirname, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createGzip } from 'node:zlib';
import { pipeline } from 'node:stream/promises';
import { Readable } from 'node:stream';
import * as path from 'node:path';
import * as fs from 'node:fs';
import * as os from 'node:os';

import { runVaultPython } from './lib/vault-bridge.mjs';

const HOOK_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = dirname(HOOK_DIR);

// ---------------------------------------------------------------------------
// Konfiguration
// ---------------------------------------------------------------------------

const SNAPSHOTS_DIR = process.env.ACADEMIC_SNAPSHOTS_DIR
  || join(os.homedir(), '.academic-research', 'snapshots');
const PROJECT_DIR = process.env.CLAUDE_PROJECT_DIR || process.cwd();
// Kanonischer Slug-Default (Single Source of Truth, Issue #190 + #382):
// ACADEMIC_PROJECT_SLUG aus Env, sonst basename(PROJECT_DIR) — identisch zu
// DB_SLUG und den anderen Hooks. Vorher hatte SLUG hartkodiert 'default' als
// Default, wodurch Snapshots verschiedener Projekte im selben Ordner landeten.
const SLUG = process.env.ACADEMIC_PROJECT_SLUG || basename(PROJECT_DIR) || 'default';
const DB_SLUG = basename(PROJECT_DIR) || 'default';
const VAULT_DB = process.env.VAULT_DB_PATH
  || join(os.homedir(), '.academic-research', 'projects', DB_SLUG, 'vault.db');
const VAULT_SRC = REPO_ROOT;

// Zeitbudget fuer den Vault-Export (siehe exportVaultSnapshot()). Der
// PreCompact-Hook selbst laeuft unter einem harten Timeout von 30s
// (hooks/hooks.json). 18s Gesamtbudget fuer den Vault-Export lassen dem
// Markdown-Fallback (createTarball(), max. 10s Tar-Aufruf) und sonstigem
// Overhead ausreichend Luft, damit ein haengender/langsamer Vault-Export die
// Compaction nicht zum Scheitern bringt (fail-open).
const VAULT_EXPORT_TIMEOUT_MS = 15000;
const VAULT_EXPORT_BUDGET_MS = 18000;

// Zu sichernde State-Dateien (relativ zu PROJECT_DIR)
const STATE_FILES = [
  'academic_context.md',
  'literature_state.md',
  'writing_state.md',
];

// ---------------------------------------------------------------------------
// Herkunftskennzeichnung + Retention (Regression A, Runde 2)
// ---------------------------------------------------------------------------
//
// hooks/session-snapshot.mjs teilt sich das Slug-Verzeichnis mit diesem Hook
// und kennzeichnet seine eigenen Exporte mit dem Suffix `.session.tgz`, um
// sein Pruning ausschliesslich auf eigene Dateien zu beschraenken
// (isOwnSnapshotFilename() dort, Zeile ~95) — fremde .tgz-Dateien (also die
// dieses Hooks) lässt es unangetastet. Das ist korrekt fuer session-snapshot
// selbst, bedeutet aber im Umkehrschluss: die von DIESEM Hook erzeugten
// Tarballs (inkl. vollstaendiger vault.db-Kopie bei jeder Auto-Compaction)
// wurden bislang von NIEMANDEM geprunt und wuchsen unbegrenzt.
//
// Fix: dieselbe Konvention hier spiegeln (eigenes Suffix + eigenes,
// analoges Pruning) statt einen fremden Mechanismus zu kapern oder einen
// strukturell anderen zweiten Mechanismus zu erfinden. session-snapshot.mjs
// bleibt unangetastet (nicht meine Datei) und braucht keine Aenderung, damit
// dieser Hook seine eigene Retention durchsetzt.
const OWN_SNAPSHOT_SUFFIX = '.precompact.tgz';

// Gleicher Env-Var wie session-snapshot.mjs (ACADEMIC_SNAPSHOTS_KEEP,
// Default 20) — beide Hooks teilen sich das Slug-Verzeichnis und denselben
// Retention-Gedanken ("wie viele vollstaendige Vault-Sicherungen pro Slug
// aufbewahren"), pruned aber jeweils nur die eigene Teilmenge.
const DEFAULT_SNAPSHOTS_KEEP = 20;
const SNAPSHOTS_KEEP = (() => {
  const raw = Number.parseInt(process.env.ACADEMIC_SNAPSHOTS_KEEP ?? '', 10);
  return Number.isFinite(raw) && raw > 0 ? raw : DEFAULT_SNAPSHOTS_KEEP;
})();

function isOwnSnapshotFilename(name) {
  return name.endsWith(OWN_SNAPSHOT_SUFFIX);
}

/**
 * Prunt die eigenen (mit OWN_SNAPSHOT_SUFFIX gekennzeichneten) Tarballs im
 * Slug-Verzeichnis auf maximal `keep` Stueck (aelteste zuerst geloescht).
 * Fremde .tgz-Dateien (z. B. `*.session.tgz` von session-snapshot.mjs) und
 * die Marker-Datei bleiben unangetastet, weil der Filter ausschliesslich auf
 * OWN_SNAPSHOT_SUFFIX matcht — analog zu pruneOldSnapshots() in
 * session-snapshot.mjs.
 */
function pruneOldSnapshots(slugDir, keep) {
  let entries;
  try {
    entries = fs.readdirSync(slugDir);
  } catch {
    return;
  }
  const tarballs = entries
    .filter(isOwnSnapshotFilename)
    .sort(); // YYYYMMDD-HHMM[-N].precompact.tgz -> lexikographisch == chronologisch

  const excess = tarballs.length - keep;
  if (excess <= 0) return;

  for (const name of tarballs.slice(0, excess)) {
    try {
      fs.unlinkSync(join(slugDir, name));
    } catch (err) {
      process.stderr.write(`[Snapshot] Konnte alten Snapshot nicht loeschen (${name}): ${err.message}\n`);
    }
  }
}

/**
 * Liefert einen freien, mit OWN_SNAPSHOT_SUFFIX gekennzeichneten Zielpfad im
 * Slug-Verzeichnis (Regression B, Runde 2): `${ts}${OWN_SNAPSHOT_SUFFIX}`,
 * bei Kollision `${ts}-1${OWN_SNAPSHOT_SUFFIX}`, `${ts}-2...` usw. — exakt
 * dasselbe Kollisionsschema wie export_snapshot() in academic_vault/server.py
 * (dort fuer denselben Datenverlust-Vorfall vom 11.08.2026 eingefuehrt).
 *
 * Ohne diese Pruefung wuerde ein zweiter Compaction-Lauf in derselben Minute
 * (oder nach einem bereits erfolgreichen Export derselben Minute) den
 * vorhandenen — potenziell vault-haltigen — Tarball beim naechsten
 * `tar czf` blind ueberschreiben.
 */
function uniqueOwnTarPath(slugDir, ts) {
  let candidate = join(slugDir, `${ts}${OWN_SNAPSHOT_SUFFIX}`);
  let lauf = 1;
  while (existsSync(candidate)) {
    candidate = join(slugDir, `${ts}-${lauf}${OWN_SNAPSHOT_SUFFIX}`);
    lauf += 1;
  }
  return candidate;
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
// Timestamp-Generierung
// ---------------------------------------------------------------------------

/**
 * Gibt Timestamp im Format YYYYMMDD-HHMM zurueck.
 */
function makeTimestamp() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return [
    now.getFullYear(),
    pad(now.getMonth() + 1),
    pad(now.getDate()),
  ].join('') + '-' + [
    pad(now.getHours()),
    pad(now.getMinutes()),
  ].join('');
}

// ---------------------------------------------------------------------------
// Tarball erstellen (einfache Implementierung ohne externe Deps)
// ---------------------------------------------------------------------------

/**
 * Erstellt einen .tgz-Tarball mit den angegebenen Dateien.
 * Verwendet das GNU-tar CLI.
 */
async function createTarball(outPath, files) {
  // Verzeichnis sicherstellen
  const dir = dirname(outPath);
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
  }

  // Existierende Dateien filtern
  const existing = files.filter((f) => existsSync(f.src));
  if (existing.length === 0) {
    process.stderr.write('[Snapshot] Warnung: Keine State-Dateien gefunden.\n');
    // Leeren Tarball mit Platzhalter erstellen
    const tmpDir = fs.mkdtempSync(join(os.tmpdir(), 'snapshot-'));
    const placeholder = join(tmpDir, 'snapshot-empty.txt');
    fs.writeFileSync(placeholder, 'Keine State-Dateien vorhanden.\n');
    execFileSync('tar', ['czf', outPath, '-C', tmpDir, 'snapshot-empty.txt'], { timeout: 10000 });
    fs.rmSync(tmpDir, { recursive: true, force: true });
    return;
  }

  // Temporaeres Verzeichnis als Staging
  const tmpDir = fs.mkdtempSync(join(os.tmpdir(), 'snapshot-'));
  try {
    for (const { src, name } of existing) {
      const dest = join(tmpDir, name);
      fs.copyFileSync(src, dest);
    }
    const fileNames = existing.map((f) => f.name);
    execFileSync('tar', ['czf', outPath, '-C', tmpDir, ...fileNames], { timeout: 10000 });
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

// ---------------------------------------------------------------------------
// Vault-Snapshot via Python-Subprocess
// ---------------------------------------------------------------------------

/**
 * Exportiert State-Dateien + Vault-DB als Tarball ueber
 * academic_vault.server.export_snapshot() (dieselbe Funktion, die auch
 * hooks/session-snapshot.mjs verwendet — siehe dort Zeile 208). Fail-open:
 * fehlt die Vault-DB oder scheitert der Export, liefert die Funktion `null`
 * zurueck und main() faellt auf den reinen Markdown-Tarball zurueck, statt
 * die Compaction zu blockieren.
 *
 * Nutzt runVaultPython() aus hooks/lib/vault-bridge.mjs fuer dieselbe
 * Interpreter-Kaskade wie die anderen Vault-Hooks (#382): das rohe
 * `python3` aus der Vorgaengerversion dieser Funktion scheitert auf macOS
 * typischerweise am System-Python (3.9, kein PEP-604), wodurch der
 * Vault-Export im Stillen nie griff.
 *
 * @returns {string|null} Pfad der erstellten .tgz-Datei oder null.
 */
function exportVaultSnapshot() {
  if (!existsSync(VAULT_DB)) {
    process.stderr.write(`[Snapshot] Vault-DB nicht gefunden (${VAULT_DB}). Vault-Snapshot übersprungen, Markdown-Snapshot folgt.\n`);
    return null;
  }

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
    { timeout: VAULT_EXPORT_TIMEOUT_MS, budget: VAULT_EXPORT_BUDGET_MS, label: 'Snapshot' },
  );

  if (stdout === null) {
    process.stderr.write('[Snapshot] ⚠️ Vault-Export fehlgeschlagen — Markdown-Snapshot wird trotzdem erstellt.\n');
    return null;
  }
  const outPath = stdout.trim();
  return outPath || null;
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
    // Malformed stdin — trotzdem weitermachen
  }

  // Sicherstellen dass PROJECT_DIR existiert
  if (!existsSync(PROJECT_DIR)) {
    process.stderr.write(`[Snapshot] Warnung: PROJECT_DIR nicht gefunden: ${PROJECT_DIR}\n`);
    process.exit(0);
  }

  const ts = makeTimestamp();
  const slugDir = join(SNAPSHOTS_DIR, SLUG);

  // Snapshot-Verzeichnis erstellen
  if (!existsSync(slugDir)) {
    mkdirSync(slugDir, { recursive: true });
  }

  // Vault-Snapshot zuerst versuchen: export_snapshot() buendelt State-Dateien
  // UND vault.db in einem einzigen Tarball (academic_vault/server.py,
  // export_snapshot()). Gelingt das, ist der reine Markdown-Fallback unten
  // ueberfluessig — ohne diesen Aufruf enthielt der PreCompact-Snapshot nie
  // die Vault-DB, obwohl das Modul-Docstring genau das verspricht.
  const vaultTarPath = exportVaultSnapshot();
  if (vaultTarPath) {
    // Eigenes Suffix + Kollisionsschema (Regression A + B, Runde 2): der von
    // export_snapshot() gelieferte Rohpfad traegt noch keine
    // Herkunftskennzeichnung. uniqueOwnTarPath() findet einen freien,
    // gekennzeichneten Zielnamen, statt blind auf ${ts}.precompact.tgz zu
    // schreiben, das durch einen vorherigen Compaction-Lauf in derselben
    // Minute schon belegt sein kann.
    const ownPath = uniqueOwnTarPath(slugDir, ts);
    try {
      fs.renameSync(vaultTarPath, ownPath);
      pruneOldSnapshots(slugDir, SNAPSHOTS_KEEP);
      process.stderr.write(`[Snapshot] Snapshot inkl. Vault-DB erstellt: ${ownPath}\n`);
    } catch (err) {
      // Umbenennen scheitert, wenn Quelle und Ziel in verschiedenen
      // Dateisystemen liegen (EXDEV) oder das Quellverzeichnis
      // schreibgeschuetzt ist (EACCES). Dann auf Kopieren ausweichen: der
      // Snapshot MUSS gekennzeichnet im Slug-Verzeichnis landen, sonst erfasst
      // ihn kein Pruning-Filter (weder pruneOldSnapshots() hier noch der in
      // hooks/session-snapshot.mjs) und er bleibt dort unbegrenzt liegen.
      try {
        fs.copyFileSync(vaultTarPath, ownPath);
        try {
          fs.unlinkSync(vaultTarPath);
        } catch {
          // Quelle nicht loeschbar (z.B. schreibgeschuetztes Verzeichnis).
          // Der gekennzeichnete Snapshot steht — das ist der Zweck hier.
        }
        pruneOldSnapshots(slugDir, SNAPSHOTS_KEEP);
        process.stderr.write(`[Snapshot] Snapshot inkl. Vault-DB erstellt (kopiert, Umbenennen scheiterte: ${err.message}): ${ownPath}\n`);
      } catch (kopierFehler) {
        // Auch das Kopieren scheitert -> fail-open: der Original-Pfad bleibt
        // gueltig und enthaelt die Vault-DB, nur ohne Kennzeichnung.
        process.stderr.write(`[Snapshot] Konnte Snapshot nicht kennzeichnen (${err.message}; Kopieren: ${kopierFehler.message}), Originalpfad bleibt: ${vaultTarPath}\n`);
      }
    }
    process.exit(0);
  }

  // Fallback: nur die State-Dateien sichern (keine Vault-DB vorhanden oder
  // Export fehlgeschlagen) — fail-open, der Markdown-Snapshot bleibt so in
  // jedem Fall erhalten.
  const files = STATE_FILES.map((name) => ({
    src: join(PROJECT_DIR, name),
    name,
  }));

  // Auch der Markdown-Fallback schreibt direkt auf einen kollisionssicheren,
  // gekennzeichneten Pfad (Regression B): ein fest aus dem Minuten-
  // Zeitstempel gebildeter Pfad wuerde bei einer zweiten Compaction in
  // derselben Minute einen vorherigen, potenziell vault-haltigen Tarball per
  // `tar czf` kuerzen statt daneben zu schreiben.
  const tarPath = uniqueOwnTarPath(slugDir, ts);

  try {
    await createTarball(tarPath, files);
    pruneOldSnapshots(slugDir, SNAPSHOTS_KEEP);
    process.stderr.write(`[Snapshot] Snapshot erstellt (ohne Vault-DB): ${tarPath}\n`);
  } catch (err) {
    process.stderr.write(`[Snapshot] Fehler beim Erstellen des Tarballs: ${err.message}\n`);
  }

  process.exit(0);
}

main().catch((err) => {
  process.stderr.write(`[Snapshot] Unerwarteter Fehler: ${err.message}\n`);
  process.exit(0); // fail-open
});
