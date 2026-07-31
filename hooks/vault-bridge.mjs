/**
 * hooks/vault-bridge.mjs — gemeinsame Vault-Bruecke der Node-Hooks (Issue #527)
 *
 * KEIN Hook: diese Datei wird von hooks/hooks.json nicht aufgerufen, sondern
 * von den Hooks importiert (analog zu hooks/onboard-project-uni-prompt.sh, das
 * ebenfalls im Verzeichnis liegt, ohne verdrahtet zu sein). Sie liegt bewusst
 * flach in hooks/ und nicht in hooks/lib/, damit das CI-Syntax-Gate
 * (`for f in hooks/*.mjs; node --check "$f"`) sie mit erfasst.
 *
 * Hintergrund: `post-tool-use-decisions.mjs` schrieb bis #527 in eine Textdatei,
 * `mid-session-reinforcement.mjs` las die SQLite-Tabelle `decisions` — zwei
 * Speicherorte, die nie zusammenfanden. Damit dieselbe Divergenz nicht ueber
 * unterschiedliche DB-Pfade oder Interpreter zurueckkehrt, loesen beide Hooks
 * beides hier auf, an genau einer Stelle.
 *
 * Node hat vor 22.5 kein `node:sqlite`, die CI pinnt Node 20 — der DB-Zugriff
 * laeuft deshalb ueber einen Python-Subprozess.
 */

import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as os from 'node:os';
import * as path from 'node:path';

const HOOK_DIR = dirname(fileURLToPath(import.meta.url));

/** Repo-/Plugin-Wurzel — Import-Pfad fuer das Paket `academic_vault`. */
export const VAULT_SRC = dirname(HOOK_DIR);

/**
 * Kanonischer Vault-DB-Pfad (Single Source of Truth, Issue #190/#365):
 * `VAULT_DB_PATH` aus der Env, sonst
 * `~/.academic-research/projects/<slug>/vault.db` mit
 * `slug = basename(CLAUDE_PROJECT_DIR || cwd)`.
 *
 * Dieselbe Formel wie `academic_vault.db.project_slug()` (Paritaet per
 * tests/test_project_slug_hook_parity.py) und wie verbatim-guard.mjs.
 */
export function resolveVaultDb() {
  if (process.env.VAULT_DB_PATH) {
    return process.env.VAULT_DB_PATH;
  }
  const slug = basename(process.env.CLAUDE_PROJECT_DIR || process.cwd()) || 'default';
  return join(os.homedir(), '.academic-research', 'projects', slug, 'vault.db');
}

/**
 * Interpreter-Kandidaten fuer den Vault-Zugriff, in Prioritaetsreihenfolge und
 * dedupliziert.
 *
 * Hintergrund (#382, AC1): Hooks erben in einer echten Claude-Code-Session die
 * PATH des Nutzers — dort steht in aller Regel das System-Python (macOS:
 * /usr/bin/python3 == 3.9), das `academic_vault` mangels PEP-604-Syntax nicht
 * einmal importieren kann.
 *
 *   1. ACADEMIC_PYTHON        — expliziter Override (conda/pyenv/Systempakete)
 *   2. $VIRTUAL_ENV/bin/python — aktives venv (uv run, aktivierte Shell, CI)
 *   3. ~/.academic-research/venv/bin/python — kanonisches Setup-venv, dasselbe,
 *      das hooks.json im SessionStart-Block prueft (/academic-research:setup)
 *   4. python3                 — PATH-Fallback
 */
export function pythonCandidates() {
  const candidates = [];
  if (process.env.ACADEMIC_PYTHON) {
    candidates.push(process.env.ACADEMIC_PYTHON);
  }
  if (process.env.VIRTUAL_ENV) {
    candidates.push(join(process.env.VIRTUAL_ENV, 'bin', 'python'));
  }
  candidates.push(join(os.homedir(), '.academic-research', 'venv', 'bin', 'python'));
  candidates.push('python3');
  return [...new Set(candidates)];
}

/**
 * Fuehrt ein Python-Snippet gegen den Vault aus und gibt dessen stdout zurueck.
 *
 * Argumente werden ueber `argv` uebergeben (keine String-Interpolation in den
 * Code — Pfade koennen Anfuehrungszeichen enthalten). Scheitert ein Kandidat,
 * kommt der naechste dran; scheitern alle, ist das Ergebnis `null` (fail-open,
 * die Aufrufer sind nicht-blockierende Hooks).
 *
 * @param {string} pyCode  Snippet fuer `python -c`
 * @param {string[]} args  Argumente, ab sys.argv[1] sichtbar
 * @param {{timeout?: number, budget?: number, label?: string}} options
 *        timeout: Zeitlimit je Kandidat in ms (Default 10000)
 *        budget:  Gesamtbudget in ms; nach dessen Ablauf wird kein weiterer
 *                 Kandidat mehr probiert (Hook-Timeouts in hooks.json)
 *        label:   Praefix der Diagnose-Zeile auf stderr
 * @returns {string|null} stdout des ersten erfolgreichen Kandidaten
 */
export function runVaultPython(pyCode, args = [], options = {}) {
  const timeout = options.timeout ?? 10000;
  const budget = options.budget ?? Infinity;
  const label = options.label ?? 'Vault-Bridge';
  const startedAt = Date.now();

  const failures = [];
  for (const python of pythonCandidates()) {
    const elapsed = Date.now() - startedAt;
    if (elapsed >= budget) {
      failures.push(`${python}: Zeitbudget (${budget} ms) erschoepft`);
      break;
    }
    // Absolute Kandidaten vorab pruefen; 'python3' bleibt eine PATH-Aufloesung.
    if (python.includes(path.sep) && !existsSync(python)) {
      failures.push(`${python}: nicht vorhanden`);
      continue;
    }
    try {
      return execFileSync(python, ['-c', pyCode, ...args], {
        encoding: 'utf-8',
        timeout: Math.min(timeout, budget - elapsed),
        stdio: ['pipe', 'pipe', 'pipe'],
      });
    } catch (err) {
      failures.push(`${python}: ${String(err.message).split('\n')[0]}`);
    }
  }

  process.stderr.write(`[${label}] Kein Interpreter konnte den Vault oeffnen: ${failures.join(' | ')}\n`);
  return null;
}
