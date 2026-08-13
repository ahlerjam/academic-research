#!/usr/bin/env node
/**
 * scripts/dev/bench_hook_guards_batch.mjs — Latenz-Nachweis fuer Issue #844.
 *
 * Misst den ECHTEN Codepfad (drei reale Hook-Prozesse, echter
 * `academic_vault`-Import ueber runVaultPython — kein Mikrobenchmark, Muster
 * aus #600/bench_vault_bridge.mjs) fuer denselben Kapitel-Write, EINMAL "vorher"
 * (jeder Guard bekommt sein EIGENES, isoliertes Cache-Verzeichnis — das
 * erzwingt fuer jeden Guard einen eigenen Cache-Miss und reproduziert damit
 * exakt das Verhalten vor #844: drei unabhaengige Python-Subprozess-Starts)
 * und EINMAL "nachher" (alle drei Guards teilen sich EIN Cache-Verzeichnis —
 * das tatsaechliche Verhalten seit #844: ein Python-Subprozess-Start fuer alle
 * drei zusammen).
 *
 * Ausgabe: ein JSON-Objekt auf stdout mit Median-ms UND allen Einzelwerten je
 * Pfad, sowie der jeweils gezaehlten Python-Subprozess-Starts (ueber einen
 * zaehlenden Interpreter-Wrapper).
 *
 * Nutzung:
 *   node scripts/dev/bench_hook_guards_batch.mjs [--reps N]
 *
 * Voraussetzung: ein Python-Interpreter mit importierbarem `academic_vault`
 * (ACADEMIC_PYTHON-Override wie bei den Hooks selbst, sonst `python3`).
 */

import { execFileSync } from 'node:child_process';
import {
  mkdtempSync, rmSync, mkdirSync, writeFileSync, chmodSync, readFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = dirname(dirname(SCRIPT_DIR));
const HOOKS = [
  join(REPO_ROOT, 'hooks', 'verbatim-guard.mjs'),
  join(REPO_ROOT, 'hooks', 'claim-drift-guard.mjs'),
  join(REPO_ROOT, 'hooks', 'context-fidelity-guard.mjs'),
];

function parseArgs(argv) {
  const opts = { reps: 10 };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--reps') opts.reps = Number(argv[++i]);
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

function initVault(pyExe, dbPath) {
  const pyCode = [
    'import sys, json',
    `sys.path.insert(0, ${JSON.stringify(REPO_ROOT)})`,
    'from academic_vault.db import VaultDB',
    'from academic_vault.server import add_paper, add_quote',
    'db_path = sys.argv[1]',
    'VaultDB(db_path).init_schema()',
    'add_paper(db_path=db_path, paper_id="bench-844", '
      + 'csl_json=json.dumps({"title": "Bench", "type": "article-journal"}))',
    'add_quote(db_path=db_path, paper_id="bench-844", '
      + 'verbatim="Der Effekt war in allen Kohorten nachweisbar und stabil.", '
      + 'extraction_method="manual", printed_page=45, '
      + 'context_before="Davor.", context_after="Danach.")',
  ].join('\n');
  execFileSync(pyExe, ['-c', pyCode, dbPath], { encoding: 'utf-8' });
}

/** Zaehlender Interpreter-Wrapper: protokolliert jeden Aufruf, reicht ihn dann durch. */
function writeCountingWrapper(path, markerFile, realPython) {
  writeFileSync(
    path,
    '#!/bin/sh\n'
    + `echo call >> "${markerFile}"\n`
    + `exec "${realPython}" "$@"\n`,
  );
  chmodSync(path, 0o755);
}

function countCalls(markerFile) {
  try {
    return readFileSync(markerFile, 'utf-8').split('\n').filter(Boolean).length;
  } catch {
    return 0;
  }
}

const CHAPTER_OLD = (
  '## Ergebnisse\n\n'
  + 'Die Studie zeigt einen moderaten Effekt auf die Lesekompetenz. '
  + '"Der Effekt war in allen Kohorten nachweisbar und stabil."\n'
);
const CHAPTER_NEW = CHAPTER_OLD.replace('moderaten', 'starken');

/**
 * Fuehrt alle drei Guards sequenziell (hooks.json-Reihenfolge) gegen denselben
 * Write aus. `sharedCache: false` gibt jedem Guard sein EIGENES
 * Cache-Verzeichnis (simuliert den Vor-#844-Zustand: drei Subprozess-Starts).
 * `sharedCache: true` ist der tatsaechliche Zustand seit #844.
 */
function runOneWrite(vaultDb, wrapper, markerFile, workDir, sharedCache) {
  const filePath = join(workDir, 'kapitel', `kap-${Date.now()}-${Math.random()}.md`);
  const payload = JSON.stringify({
    tool_name: 'Edit',
    tool_input: { file_path: filePath, old_string: CHAPTER_OLD, new_string: CHAPTER_NEW },
  });

  const sharedCacheDir = join(workDir, 'shared-cache');
  const start = process.hrtime.bigint();
  HOOKS.forEach((hook, i) => {
    const cacheDir = sharedCache ? sharedCacheDir : join(workDir, `isolated-cache-${i}`);
    mkdirSync(cacheDir, { recursive: true });
    execFileSync('node', [hook], {
      input: payload,
      encoding: 'utf-8',
      env: {
        ...process.env,
        VAULT_DB_PATH: vaultDb,
        ACADEMIC_PYTHON: wrapper,
        HOOK_BATCH_CACHE_DIR: cacheDir,
        VAULT_GUARD_BYPASS_LOG: join(workDir, 'bypass.log'),
        VAULT_GUARD_ENV_SWITCH_LOG: join(workDir, 'env-switch.log'),
      },
    });
  });
  const end = process.hrtime.bigint();
  return Number(end - start) / 1e6;
}

function main() {
  const { reps } = parseArgs(process.argv.slice(2));
  if (!Number.isFinite(reps) || reps < 1) {
    throw new Error(`--reps muss eine positive Zahl sein, erhalten: ${reps}`);
  }

  const workDir = mkdtempSync(join(tmpdir(), 'bench-hook-guards-batch-'));
  const pyExe = pythonForBenchmark();
  const vaultDb = join(workDir, 'bench-vault.db');
  initVault(pyExe, vaultDb);

  const wrapper = join(workDir, 'counting-python');
  const markerFile = join(workDir, 'python-calls.log');

  // Aufwaerm-Durchlauf je Pfad (Node-Start-JIT, Datei-Cache) zaehlt nicht in die Messung.
  writeFileSync(markerFile, '');
  writeCountingWrapper(wrapper, markerFile, pyExe);
  runOneWrite(vaultDb, wrapper, markerFile, workDir, false);
  writeFileSync(markerFile, '');
  runOneWrite(vaultDb, wrapper, markerFile, workDir, true);

  const beforeSamples = [];
  let beforeCalls = 0;
  for (let i = 0; i < reps; i++) {
    writeFileSync(markerFile, '');
    beforeSamples.push(runOneWrite(vaultDb, wrapper, markerFile, workDir, false));
    beforeCalls += countCalls(markerFile);
  }

  const afterSamples = [];
  let afterCalls = 0;
  for (let i = 0; i < reps; i++) {
    writeFileSync(markerFile, '');
    afterSamples.push(runOneWrite(vaultDb, wrapper, markerFile, workDir, true));
    afterCalls += countCalls(markerFile);
  }

  rmSync(workDir, { recursive: true, force: true });

  const result = {
    reps,
    beforeIsolatedCache: {
      description: 'Vor #844 (simuliert): je Guard ein eigenes Cache-Verzeichnis -> 3 Subprozess-Starts je Write',
      samplesMs: beforeSamples,
      medianMs: median(beforeSamples),
      pythonSubprocessStartsTotal: beforeCalls,
      pythonSubprocessStartsPerWrite: beforeCalls / reps,
    },
    afterSharedCache: {
      description: 'Seit #844: ein geteiltes Cache-Verzeichnis -> 1 Subprozess-Start je Write',
      samplesMs: afterSamples,
      medianMs: median(afterSamples),
      pythonSubprocessStartsTotal: afterCalls,
      pythonSubprocessStartsPerWrite: afterCalls / reps,
    },
  };
  console.log(JSON.stringify(result, null, 2));
}

main();
