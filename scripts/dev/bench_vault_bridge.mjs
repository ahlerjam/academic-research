#!/usr/bin/env node
/**
 * scripts/dev/bench_vault_bridge.mjs — Mikrobenchmark fuer Issue #600.
 *
 * Vergleicht den Zugriffsweg der Node-Hooks (`runVaultPython`, ein
 * Python-Subprozess pro Aufruf) mit einem direkten `node:sqlite`-Zugriff auf
 * dieselbe SQLite-Datei, fuer den billigstmoeglichen Lesefall (eine leere,
 * initialisierte Vault-DB, `SELECT count(*) FROM decisions`).
 *
 * Das misst NUR die Zugriffsweg-Kosten (Prozessstart + Interpreter-Import vs.
 * In-Process-Treiberaufruf) — nicht, ob die Geschaeftslogik der drei
 * Hook-Aufrufer (`post-tool-use-decisions.mjs`, `mid-session-reinforcement.mjs`,
 * `context-fidelity-guard.mjs`) 1:1 in JavaScript nachgebaut werden koennte.
 * Diese Logik lebt heute ausschliesslich in `academic_vault` (Python) —
 * Dedup/Supersede in `decision_log.record_file_change`, Sortierung/Filterung
 * in `VaultDB.list_decisions`, FTS5-Suche + Fuzzy-Matching in
 * `search_quote_text`/`get_quote`/`resolve_quote_context`. Eine Migration
 * muesste diese Logik duplizieren statt nur den Treiber zu tauschen — genau
 * die Divergenz, derentwegen die Bruecke ueberhaupt existiert (#527).
 *
 * Ausgabe: ein JSON-Objekt auf stdout mit Median-ms UND allen Einzelwerten
 * (Rohzahlen, kein Einzelwert-Beleg) fuer beide Wege.
 *
 * Nutzung:
 *   node scripts/dev/bench_vault_bridge.mjs [--reps N] [--out-dir DIR]
 */

import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';
import { DatabaseSync } from 'node:sqlite';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = dirname(dirname(SCRIPT_DIR));

function parseArgs(argv) {
  const opts = { reps: 15, outDir: null };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--reps') opts.reps = Number(argv[++i]);
    else if (argv[i] === '--out-dir') opts.outDir = argv[++i];
  }
  return opts;
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

function pythonForBenchmark() {
  return process.env.ACADEMIC_PYTHON || 'python3';
}

/** Legt eine leere, per academic_vault initialisierte Vault-DB an. */
function initVault(pyExe, dbPath) {
  const pyCode = [
    'import sys',
    `sys.path.insert(0, ${JSON.stringify(REPO_ROOT)})`,
    'from academic_vault.db import VaultDB',
    'VaultDB(sys.argv[1]).init_schema()',
  ].join('; ');
  execFileSync(pyExe, ['-c', pyCode, dbPath], { encoding: 'utf-8' });
}

/** Ein Lesevorgang ueber den heutigen Bridge-Weg (Python-Subprozess). */
function timePythonSubprocessRead(pyExe, dbPath) {
  const pyCode = [
    'import sys, sqlite3',
    'con = sqlite3.connect(sys.argv[1])',
    "print(con.execute('SELECT count(*) FROM decisions').fetchone()[0])",
    'con.close()',
  ].join('; ');
  const start = process.hrtime.bigint();
  execFileSync(pyExe, ['-c', pyCode, dbPath], { encoding: 'utf-8' });
  const end = process.hrtime.bigint();
  return Number(end - start) / 1e6;
}

/** Derselbe Lesevorgang direkt in-process ueber node:sqlite. */
function timeNodeSqliteRead(dbPath) {
  const start = process.hrtime.bigint();
  const db = new DatabaseSync(dbPath, { readOnly: true });
  const row = db.prepare('SELECT count(*) AS n FROM decisions').get();
  db.close();
  const end = process.hrtime.bigint();
  void row;
  return Number(end - start) / 1e6;
}

function main() {
  const { reps, outDir } = parseArgs(process.argv.slice(2));
  if (!Number.isFinite(reps) || reps < 1) {
    throw new Error(`--reps muss eine positive Zahl sein, erhalten: ${reps}`);
  }

  const workDir = outDir ?? mkdtempSync(join(tmpdir(), 'bench-vault-bridge-'));
  const dbPath = join(workDir, 'bench-vault.db');
  const pyExe = pythonForBenchmark();

  initVault(pyExe, dbPath);

  // Ein Aufwaerm-Durchlauf je Weg (Datei-Cache, JIT) zaehlt nicht in die Messung.
  timePythonSubprocessRead(pyExe, dbPath);
  timeNodeSqliteRead(dbPath);

  const pythonSamples = [];
  const sqliteSamples = [];
  for (let i = 0; i < reps; i++) {
    pythonSamples.push(timePythonSubprocessRead(pyExe, dbPath));
    sqliteSamples.push(timeNodeSqliteRead(dbPath));
  }

  if (!outDir) {
    rmSync(workDir, { recursive: true, force: true });
  }

  const result = {
    reps,
    pythonSubprocessSamplesMs: pythonSamples,
    nodeSqliteSamplesMs: sqliteSamples,
    pythonSubprocessMedianMs: median(pythonSamples),
    nodeSqliteMedianMs: median(sqliteSamples),
  };
  console.log(JSON.stringify(result));
}

main();
