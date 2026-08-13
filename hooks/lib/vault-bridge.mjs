/**
 * hooks/lib/vault-bridge.mjs — gemeinsame Vault-Bruecke der Node-Hooks (#527)
 *
 * KEIN Hook: diese Datei wird von hooks/hooks.json nicht aufgerufen, sondern
 * von den Hooks importiert. Sie liegt deshalb in hooks/lib/, wo alle
 * importierten Module dieses Plugins liegen (#542). Der CI-Syntax-Gate erfasst
 * sie dort mit: er iteriert seit #542 ueber alle getrackten *.mjs
 * (`scripts/dev/check-mjs-syntax.sh`) statt ueber den nicht-rekursiven Glob
 * `hooks/*.mjs`.
 *
 * Hintergrund: `post-tool-use-decisions.mjs` schrieb bis #527 in eine Textdatei,
 * `mid-session-reinforcement.mjs` las die SQLite-Tabelle `decisions` — zwei
 * Speicherorte, die nie zusammenfanden. Damit dieselbe Divergenz nicht ueber
 * unterschiedliche DB-Pfade oder Interpreter zurueckkehrt, loesen beide Hooks
 * beides hier auf, an genau einer Stelle.
 *
 * Warum weiterhin ein Python-Subprozess und kein `node:sqlite` (#600, geprueft
 * nach dem CI-Bump auf Node 22):
 *
 * Ein Mikrobenchmark (scripts/dev/bench_vault_bridge.mjs, billigstmoeglicher
 * Lesefall) bestaetigt den erwarteten Unterschied im reinen Zugriffsweg —
 * Median ueber 20 Wiederholungen: Python-Subprozess ~22,7 ms,
 * `node:sqlite` in-process ~0,9 ms (~25x). Das allein rechtfertigt die
 * Umstellung aber nicht: die drei Aufrufer dieser Bruecke rufen keine rohen
 * SELECTs auf, sondern Geschaeftslogik, die ausschliesslich in
 * `academic_vault` (Python) existiert — Dedup/Supersede in
 * `decision_log.record_file_change`, Sortierung/Filterung in
 * `VaultDB.list_decisions`, FTS5-Suche + Fuzzy-Matching in
 * `search_quote_text`/`get_quote`/`resolve_quote_context`. Eine Migration
 * muesste diese Logik in JavaScript duplizieren statt nur den SQLite-Treiber
 * zu tauschen — exakt die Divergenz zwischen zwei Speicherorten, derentwegen
 * diese Bruecke ueberhaupt existiert (#527, siehe oben). Solange die Bruecke
 * nur duenne Wrapper um `academic_vault`-Funktionen ist, bleibt der
 * Python-Subprozess trotz seines Overheads der sicherere Weg.
 */

import { execFileSync } from 'node:child_process';
import {
  existsSync, mkdirSync, readFileSync, writeFileSync, chmodSync, statSync,
} from 'node:fs';
import { dirname, join, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import * as os from 'node:os';
import * as path from 'node:path';
import { unionQuoteTexts } from './quote-span-extract.mjs';

const LIB_DIR = dirname(fileURLToPath(import.meta.url));

/**
 * Repo-/Plugin-Wurzel — Import-Pfad fuer das Paket `academic_vault`.
 *
 * Zwei Ebenen hoch, nicht eine: diese Datei liegt seit #542 in `hooks/lib/`.
 * Der Wert landet zur Laufzeit in `sys.path` des Vault-Subprozesses; zeigt er
 * auf `hooks/`, schlaegt der Import von `academic_vault` lautlos fehl.
 * Abgesichert durch tests/test_issue_542_hooks_layout.py.
 */
export const VAULT_SRC = dirname(dirname(LIB_DIR));

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

// ---------------------------------------------------------------------------
// Batch-Cache fuer die drei Kapitel-Guards (Issue #844)
// ---------------------------------------------------------------------------
//
// Hintergrund: verbatim-guard.mjs, claim-drift-guard.mjs und
// context-fidelity-guard.mjs laufen als DREI SEPARATE OS-Prozesse (hooks.json,
// PreToolUse Write|Edit|MultiEdit) und schlagen fuer denselben Write
// grossteils DIESELBEN Zitat-Texte im Vault nach — jeder mit einem eigenen
// Python-Subprozess (~23 ms statt ~1 ms nativ, siehe Kommentar oben). Ein
// gemeinsamer Hook wuerde die Blockier-/Warn-Semantik der drei unabhaengigen
// Guards vermischen (Out-of-Scope, Issue #844) — stattdessen teilen sie sich
// einen dateibasierten Cache: der erste Guard, der fuer einen gegebenen Write
// KEINEN frischen Cache-Eintrag findet, holt die Zitat-Obermenge ALLER DREI
// Guards (hooks/lib/quote-span-extract.mjs::unionQuoteTexts) in EINEM
// runVaultPython-Aufruf und schreibt das Ergebnis in eine Cache-Datei. Die
// beiden anderen Guards lesen bei Cache-Hit nur noch die Datei — kein
// Subprozess. Producer-Rolle ist NICHT an "verbatim-guard laeuft zuerst"
// gekoppelt, sondern an "wer zuerst einen Cache-Miss sieht" — robust gegen
// kuenftige hooks.json-Reihenfolge-Aenderungen.
//
// Fail-open (durchgaengig): jeder Fehler auf diesem Pfad (Cache-Verzeichnis
// nicht schreibbar, korrupte Cache-Datei, Python-Aufruf schlaegt fehl) gibt
// `null` zurueck. Die Aufrufer (die drei Guards) behandeln `null` exakt wie
// "kein Cache vorhanden" und fallen auf ihren EIGENEN, unveraenderten
// runVaultPython-Call zurueck — der Cache ist eine reine Optimierung, nie
// eine zusaetzliche Fehlerquelle fuer die Blockier-Entscheidung.

const BATCH_CACHE_TTL_MS = 20000;

/** Cache-Verzeichnis; per Env override-bar (Tests, `HOOK_BATCH_CACHE_DIR`). */
function batchCacheDir() {
  return process.env.HOOK_BATCH_CACHE_DIR
    || join(os.homedir(), '.academic-research', 'hook-batch-cache');
}

/**
 * Cache-Schluessel fuer EINEN Write: sha256(Pfad + rohes tool_input-JSON).
 * Alle drei Guards erhalten dasselbe `tool_input`-Objekt desselben
 * PreToolUse-Events — `JSON.stringify` liefert deshalb fuer denselben Write
 * bei allen dreien dieselbe Zeichenkette.
 */
export function batchCacheKey(filePath, toolInput) {
  const raw = `${filePath || ''} ${JSON.stringify(toolInput ?? {})}`;
  return createHash('sha256').update(raw, 'utf-8').digest('hex');
}

/**
 * Liest einen Cache-Eintrag, oder `null` bei Fehlen/Ablauf/Fehler
 * (fail-open — siehe Abschnittskommentar oben).
 */
function readBatchCache(key) {
  try {
    const file = join(batchCacheDir(), `${key}.json`);
    if (!existsSync(file)) return null;
    const stat = statSync(file);
    if (Date.now() - stat.mtimeMs > BATCH_CACHE_TTL_MS) return null;
    return JSON.parse(readFileSync(file, 'utf-8'));
  } catch {
    return null;
  }
}

/**
 * Schreibt einen Cache-Eintrag, best-effort (0600-Rechte, analog
 * VAULT_GUARD_BYPASS_LOG in verbatim-guard.mjs). Schreibfehler werden
 * verschluckt — der Aufrufer hat sein frisch berechnetes Ergebnis bereits in
 * der Hand und braucht den Cache nur fuer die ANDEREN Guards.
 */
function writeBatchCache(key, data) {
  try {
    const dir = batchCacheDir();
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true, mode: 0o700 });
    const file = join(dir, `${key}.json`);
    writeFileSync(file, JSON.stringify(data), { mode: 0o600 });
    chmodSync(file, 0o600);
  } catch {
    // best-effort — ein Cache-Schreibfehler darf keinen Guard blockieren.
  }
}

/**
 * EIN Python-Snippet, das ALLE uebergebenen Zitat-Texte (volle Records:
 * quote_id/paper_id/context_before/context_after/context_source/
 * printed_page/verbatim, Muster aus claim-drift-guard.mjs/
 * context-fidelity-guard.mjs::PY_LOOKUP) UND ALLE uebergebenen Figure-Referenzen
 * (bool, Muster aus verbatim-guard.mjs::PY_BATCH_LOOKUP) in EINEM Aufruf
 * nachschlaegt. Jeder Eintrag einzeln try/except-gekapselt — ein einzelner
 * kaputter Lookup faellt nur fuer sich selbst aus (`{"error": ...}`).
 */
const PY_QUOTE_FIGURE_BATCH = [
  'import sys, json',
  `sys.path.insert(0, ${JSON.stringify(VAULT_SRC)})`,
  'from academic_vault.server import search_quote_text, get_quote, find_figure_by_caption',
  'db_path = sys.argv[1]',
  'payload = json.loads(sys.argv[2])',
  'quotes_out = {}',
  'for text in payload["quotes"]:',
  '    try:',
  '        hits = search_quote_text(db_path, text, 1)',
  '        if not hits:',
  '            quotes_out[text] = None',
  '            continue',
  '        quote_id = hits[0]["quote_id"]',
  '        record = get_quote(db_path, quote_id) or {}',
  '        quotes_out[text] = {',
  '            "found": True,',
  '            "quote_id": quote_id,',
  '            "paper_id": record.get("paper_id") or hits[0].get("paper_id"),',
  '            "context_before": record.get("context_before"),',
  '            "context_after": record.get("context_after"),',
  '            "context_source": record.get("context_source"),',
  '            "printed_page": record.get("printed_page"),',
  '            "verbatim": record.get("verbatim"),',
  '        }',
  '    except Exception as exc:',
  '        quotes_out[text] = {"error": "%s: %s" % (type(exc).__name__, exc)}',
  'figures_out = {}',
  'for text in payload["figures"]:',
  '    try:',
  '        figures_out[text] = bool(find_figure_by_caption(db_path, text))',
  '    except Exception as exc:',
  '        figures_out[text] = {"error": "%s: %s" % (type(exc).__name__, exc)}',
  'print(json.dumps({"quotes": quotes_out, "figures": figures_out}))',
].join('\n');

/**
 * Stellt einen Batch-Cache-Eintrag fuer einen Write sicher und gibt ihn
 * zurueck — oder `null`, wenn weder ein frischer Eintrag existiert noch einer
 * berechnet werden konnte (fail-open, siehe Abschnittskommentar oben).
 *
 * Bei Cache-Hit: kein Subprozess. Bei Cache-Miss (oder wenn der vorhandene
 * Eintrag nicht ALLE `quoteTexts`/`figureTexts` des Aufrufers als Schluessel
 * enthaelt — z. B. weil die Naeherung in quote-span-extract.mjs einen Text
 * anders paart als die exakte Guard-Logik): EIN runVaultPython-Aufruf ueber
 * die Obermenge aus `unionQuoteTexts()` (alle drei Guard-Bedarfe) PLUS die
 * `figureTexts` DIESES Aufrufers (Figures sind ausschliesslich
 * verbatim-guard-spezifisch, kein Cross-Guard-Bedarf).
 *
 * @param {{filePath: string, toolName: string, toolInput: object,
 *   vaultDb: string, quoteTexts: string[], figureTexts?: string[],
 *   budget?: number, label?: string}} params
 * @returns {{quotes: Record<string, object|null>,
 *   figures: Record<string, boolean|{error:string}>}|null}
 */
export function ensureQuoteBatch(params) {
  const {
    filePath, toolName, toolInput, vaultDb,
    quoteTexts = [], figureTexts = [],
    budget = 10000, label = 'Vault-Batch-Cache',
  } = params;

  const key = batchCacheKey(filePath, toolInput);
  const cached = readBatchCache(key);
  const hasAllKeys = (obj, keys) => keys.every(
    (k) => Object.prototype.hasOwnProperty.call(obj || {}, k),
  );
  if (
    cached
    && hasAllKeys(cached.quotes, quoteTexts)
    && hasAllKeys(cached.figures, figureTexts)
  ) {
    return cached;
  }

  // Miss (oder unvollstaendiger Treffer): dieser Aufrufer wird Producer.
  // Obermenge = Vereinigung aller drei Guard-Bedarfe (quote-span-extract.mjs)
  // UND der eigenen Zitat-/Figure-Texte (garantiert deren Abdeckung, auch
  // wenn die Naeherung sie verfehlt haette).
  let unionQuotes;
  try {
    unionQuotes = unionQuoteTexts(toolName, toolInput);
  } catch {
    unionQuotes = [];
  }
  const allQuotes = [...new Set([...unionQuotes, ...quoteTexts])];
  const allFigures = [...new Set(figureTexts)];

  if (!existsSync(vaultDb)) return null;

  const payload = JSON.stringify({ quotes: allQuotes, figures: allFigures });
  const output = runVaultPython(PY_QUOTE_FIGURE_BATCH, [vaultDb, payload], {
    timeout: budget,
    budget,
    label,
  });
  if (output === null) return null;

  let result;
  try {
    result = JSON.parse(output.trim());
  } catch {
    return null;
  }
  if (!result || typeof result !== 'object' || !result.quotes || !result.figures) return null;

  writeBatchCache(key, result);
  return result;
}
