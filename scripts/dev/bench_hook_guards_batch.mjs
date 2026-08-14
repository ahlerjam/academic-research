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
 * Gefahren wird das fuer ZWEI Kapitelgroessen: ein kleines Kapitel (1 Zitat,
 * der urspruengliche Messfall) und ein grosses (>= 50 Zitate). Das grosse
 * Kapitel ist der Fall, in dem die vorgeladene Obermenge frueher mit der
 * ganzen Datei skalierte statt mit den Guard-Kontingenten
 * (`hooks/lib/vault-bridge.mjs::prefetchLimit()`).
 *
 * Ausgabe: ein JSON-Objekt auf stdout mit Median-ms UND allen Einzelwerten je
 * Pfad und Kapitelgroesse, sowie der jeweils gezaehlten
 * Python-Subprozess-Starts (ueber einen zaehlenden Interpreter-Wrapper).
 *
 * Nutzung:
 *   node scripts/dev/bench_hook_guards_batch.mjs [--reps N] [--large-quotes N]
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
  const opts = { reps: 10, largeQuotes: 60 };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--reps') opts.reps = Number(argv[++i]);
    if (argv[i] === '--large-quotes') opts.largeQuotes = Number(argv[++i]);
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

/**
 * Legt den Bench-Vault an und traegt ALLE uebergebenen Zitate ein. Alle Zitate
 * muessen im Vault stehen: Negativ-Treffer werden seit dem Deep-Review zu #844
 * bewusst NICHT aus dem Batch-Cache bedient (ein Block loest den Retry aus, bei
 * dem der Nutzer die Ursache gerade behoben hat) — ein Bench mit fehlenden
 * Zitaten wuerde also den Blockfall messen statt den Normalfall.
 */
function initVault(pyExe, dbPath, quotes) {
  const pyCode = [
    'import sys, json',
    `sys.path.insert(0, ${JSON.stringify(REPO_ROOT)})`,
    'from academic_vault.db import VaultDB',
    'from academic_vault.server import add_paper, add_quote',
    'db_path = sys.argv[1]',
    'VaultDB(db_path).init_schema()',
    'add_paper(db_path=db_path, paper_id="bench-844", '
      + 'csl_json=json.dumps({"title": "Bench", "type": "article-journal"}))',
    'for verbatim in json.loads(sys.argv[2]):',
    '    add_quote(db_path=db_path, paper_id="bench-844", verbatim=verbatim, '
      + 'extraction_method="manual", printed_page=45, '
      + 'context_before="Davor.", context_after="Danach.")',
  ].join('\n');
  execFileSync(pyExe, ['-c', pyCode, dbPath, JSON.stringify(quotes)], {
    encoding: 'utf-8',
    // Reines Bench-SETUP, nicht der Messpfad: der Auto-Ingest der Embeddings
    // (#719) wuerde hier je Zitat das Modell laden — bei >= 50 Zitaten Minuten
    // Ladezeit, die mit den gemessenen Guard-Latenzen nichts zu tun hat.
    env: { ...process.env, ACADEMIC_RESEARCH_EMBEDDING_ENABLED: '0', VAULT_AUTO_EMBED: '0' },
  });
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

/**
 * Baut ein Kapitel mit `quoteCount` Zitaten und liefert Vorher-/Nachher-Stand
 * plus die Zitat-Texte (die in den Vault muessen).
 */
function buildChapter(quoteCount) {
  const quotes = [];
  const blocks = [
    '## Ergebnisse',
    'Die Studie zeigt einen moderaten Effekt auf die Lesekompetenz.',
  ];
  for (let i = 0; i < quoteCount; i++) {
    const text = i === 0
      ? 'Der Effekt war in allen Kohorten nachweisbar und stabil.'
      : `Teilbefund ${String(i).padStart(3, '0')} war in der Stichprobe klar nachweisbar.`;
    quotes.push(text);
    blocks.push(`Einordnender Satz ${i}. "${text}" Nachfolgender Satz ${i}.`);
  }
  const before = `${blocks.join('\n\n')}\n`;
  return { quotes, before, after: before.replace('moderaten', 'starken') };
}

/**
 * Fuehrt alle drei Guards sequenziell (hooks.json-Reihenfolge) gegen denselben
 * Write aus. `sharedCache: false` gibt jedem Guard sein EIGENES
 * Cache-Verzeichnis (simuliert den Vor-#844-Zustand: drei Subprozess-Starts).
 * `sharedCache: true` ist der tatsaechliche Zustand seit #844.
 *
 * Der Vorher-Stand wird tatsaechlich auf Platte gelegt: claim-drift-guard.mjs
 * vergleicht gegen den Dateistand: ohne Datei entfaellt sein Vault-Bedarf und
 * der Messfall waere unvollstaendig.
 */
function runOneWrite(vaultDb, wrapper, markerFile, workDir, sharedCache, chapter) {
  const filePath = join(workDir, 'kapitel', `kap-${Date.now()}-${Math.random()}.md`);
  mkdirSync(dirname(filePath), { recursive: true });
  writeFileSync(filePath, chapter.before);
  const payload = JSON.stringify({
    tool_name: 'Edit',
    tool_input: { file_path: filePath, old_string: chapter.before, new_string: chapter.after },
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

/** Misst EINE Kapitelgroesse ueber beide Pfade (isoliert vs. geteilt). */
function benchChapter(chapter, reps, ctx) {
  const {
    vaultDb, wrapper, markerFile, workDir,
  } = ctx;

  // Aufwaerm-Durchlauf je Pfad (Node-Start-JIT, Datei-Cache) zaehlt nicht in die Messung.
  writeFileSync(markerFile, '');
  runOneWrite(vaultDb, wrapper, markerFile, workDir, false, chapter);
  writeFileSync(markerFile, '');
  runOneWrite(vaultDb, wrapper, markerFile, workDir, true, chapter);

  const beforeSamples = [];
  let beforeCalls = 0;
  for (let i = 0; i < reps; i++) {
    writeFileSync(markerFile, '');
    beforeSamples.push(runOneWrite(vaultDb, wrapper, markerFile, workDir, false, chapter));
    beforeCalls += countCalls(markerFile);
  }

  const afterSamples = [];
  let afterCalls = 0;
  for (let i = 0; i < reps; i++) {
    writeFileSync(markerFile, '');
    afterSamples.push(runOneWrite(vaultDb, wrapper, markerFile, workDir, true, chapter));
    afterCalls += countCalls(markerFile);
  }

  return {
    quotesInChapter: chapter.quotes.length,
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
}

function main() {
  const { reps, largeQuotes } = parseArgs(process.argv.slice(2));
  if (!Number.isFinite(reps) || reps < 1) {
    throw new Error(`--reps muss eine positive Zahl sein, erhalten: ${reps}`);
  }
  if (!Number.isFinite(largeQuotes) || largeQuotes < 50) {
    throw new Error(`--large-quotes muss >= 50 sein (Review-Vorgabe), erhalten: ${largeQuotes}`);
  }

  const workDir = mkdtempSync(join(tmpdir(), 'bench-hook-guards-batch-'));
  const pyExe = pythonForBenchmark();
  const vaultDb = join(workDir, 'bench-vault.db');

  const smallChapter = buildChapter(1);
  const largeChapter = buildChapter(largeQuotes);
  initVault(pyExe, vaultDb, [...new Set([...smallChapter.quotes, ...largeChapter.quotes])]);

  const wrapper = join(workDir, 'counting-python');
  const markerFile = join(workDir, 'python-calls.log');
  writeFileSync(markerFile, '');
  writeCountingWrapper(wrapper, markerFile, pyExe);

  const ctx = {
    vaultDb, wrapper, markerFile, workDir,
  };
  const result = {
    reps,
    smallChapter: benchChapter(smallChapter, reps, ctx),
    largeChapter: benchChapter(largeChapter, reps, ctx),
  };

  rmSync(workDir, { recursive: true, force: true });
  console.log(JSON.stringify(result, null, 2));
}

main();
