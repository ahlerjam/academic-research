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
// Negativ-Treffer werden NIE aus dem Cache bedient (siehe usableCacheEntry()
// unten): genau sie fuehren zum Block — und damit zum Retry des Nutzers, der
// die Ursache zwischenzeitlich behebt.
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
 * Prueft, ob ein Cache-Eintrag fuer die angefragten Schluessel BEDIENBAR ist.
 *
 * Zwei Gruende, warum er es nicht ist:
 *   1. Ein Schluessel fehlt — die Naeherung in quote-span-extract.mjs hat den
 *      Text nicht vorhergesagt (bekannter Fall, siehe dortiger Kopfkommentar).
 *   2. Der Eintrag ist ein NEGATIV-Treffer (`null` bei Zitaten, `false` bei
 *      Figures). Nur diese Eintraege loesen einen Block aus — und ein Block
 *      loest den Retry aus, bei dem der Nutzer die Ursache bereits behoben
 *      hat (Zitat nachgetragen, Abbildung eingepflegt). Ein aus dem Cache
 *      bedienter Negativ-Treffer wuerde denselben Write fuer die volle TTL
 *      weiter blockieren, obwohl der Vault die Antwort inzwischen kennt: der
 *      Cache-Schluessel haengt nur an Pfad + tool_input, die beim Retry
 *      identisch sind.
 *
 * Bewusst NICHT ueber die Vault-DB-Mtime im Cache-Schluessel geloest: die
 * Vault-DB laeuft im WAL-Modus (`PRAGMA journal_mode=WAL`,
 * academic_vault/db.py), ein Commit landet also in `vault.db-wal` und laesst
 * die Mtime von `vault.db` bis zum Checkpoint unveraendert — die Invalidierung
 * wuerde genau im Retry-Fall lautlos ausbleiben. Zusaetzlich zur ohnehin
 * grenzwertigen Zeitstempel-Granularitaet. Positiv-Treffer bleiben cachebar
 * und tragen den Performance-Gewinn aus #844; nur der (seltenere) Blockfall
 * faellt auf das Verhalten vor #844 zurueck: ein Lookup je Guard.
 *
 * `{error: ...}`-Eintraege gelten (fuer die STANDARD-``isNegative``, s.u.) als
 * bedienbar — sie sind fail-open (Warnung statt Block) und erzeugen deshalb
 * keinen klebrigen Blocker. ``isNegative`` ist ein Parameter, kein fester
 * Test: verbatim-guard.mjs uebergibt fuer Zitate eine EIGENE, strengere
 * Fassung (siehe dortiges ``isCachedQuoteNegative``), weil der Wortlaut-Status
 * aus Issue #846 (``deviation``/``absent``/Apparat-Fehler) BLOCKIERT, nicht
 * nur warnt — genau die Klasse, die hier nicht klebrig bleiben darf.
 */
function usableCacheEntry(obj, keys, isNegative) {
  return keys.every((key) => {
    if (!Object.prototype.hasOwnProperty.call(obj || {}, key)) return false;
    return !isNegative(obj[key]);
  });
}

/**
 * Deckel fuer die vorgeladene Zitat-Obermenge: die Kontingente der Guards, die
 * ueberhaupt aus dem Cache bedient werden koennen, plus der eigene Bedarf des
 * Aufrufers (der darf nie wegfallen — sonst faellt der Aufrufer sofort in
 * seinen eigenen Lookup zurueck und der Prefetch war umsonst).
 *
 * Ohne Deckel skalierte der Prefetch mit der GANZEN Datei statt mit dem, was
 * die Guards ueberhaupt pruefen duerfen: ein Kapitel mit 80 Zitaten schickte
 * 80 Texte in den Vault, obwohl context-fidelity-guard hoechstens
 * CONTEXT_FIDELITY_MAX_QUOTES und claim-drift-guard hoechstens
 * CLAIM_DRIFT_MAX_LOOKUPS davon nachschlaegt.
 *
 * Die Env-Namen/Defaults sind absichtlich die der Guards (dort dokumentiert);
 * ein Import waere ein Zyklus (die Guards importieren diese Datei).
 */
export function prefetchLimit(ownCount = 0) {
  const positiveInt = (raw, fallback) => {
    const parsed = parseInt(raw ?? '', 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
  };
  return Math.max(
    positiveInt(process.env.CLAIM_DRIFT_MAX_LOOKUPS, 10),
    positiveInt(process.env.CONTEXT_FIDELITY_MAX_QUOTES, 20),
    ownCount,
  );
}

/**
 * EIN Python-Snippet, das ALLE uebergebenen Zitat-Texte (volle Records:
 * quote_id/paper_id/context_before/context_after/context_source/
 * printed_page/verbatim, Muster aus claim-drift-guard.mjs/
 * context-fidelity-guard.mjs::PY_LOOKUP) UND ALLE uebergebenen Figure-Referenzen
 * (bool, Muster aus verbatim-guard.mjs::PY_BATCH_LOOKUP) in EINEM Aufruf
 * nachschlaegt. Jeder Eintrag einzeln try/except-gekapselt — ein einzelner
 * kaputter Lookup faellt nur fuer sich selbst aus (`{"error": ...}`).
 *
 * Zusaetzlich (Issue #846, nach #844 ergaenzt): jeder Zitat-Eintrag traegt
 * unter ``"wording"`` den vollen Wortlaut-Status aus ``match_quote_wording()``
 * (exact/normalized/ellipsis/deviation/absent, ``{"error": ...}`` bei Fehlern
 * je Kandidat) — NUR verbatim-guard.mjs liest dieses Feld, claim-drift-guard.mjs
 * und context-fidelity-guard.mjs bleiben bei ``found``/Kontext unveraendert.
 * Ohne dieses Feld muesste verbatim-guard.mjs einen ZWEITEN, eigenen
 * Subprozess starten — genau das haette #844s AC1 (hoechstens EIN
 * Subprozess fuer alle drei Guards) wieder aufgeweicht. ``quotes_out[text]``
 * ist deshalb IMMER ein Dict (nie mehr bloss ``None`` bei Nicht-Fund) —
 * ``found: False`` traegt denselben Sinn wie vorher ``None``, jetzt aber mit
 * Platz fuer ``wording`` daneben; ``usableCacheEntry()`` unten kennt das neue
 * Negativ-Kriterium.
 */
const PY_QUOTE_FIGURE_BATCH = [
  'import sys, json',
  `sys.path.insert(0, ${JSON.stringify(VAULT_SRC)})`,
  'from academic_vault.server import (',
  '    search_quote_text, get_quote, find_figure_by_caption, match_quote_wording,',
  ')',
  'db_path = sys.argv[1]',
  'payload = json.loads(sys.argv[2])',
  'quote_texts = payload["quotes"]',
  'quotes_out = {}',
  'for text in quote_texts:',
  '    try:',
  '        hits = search_quote_text(db_path, text, 1)',
  '        if not hits:',
  '            quotes_out[text] = {"found": False}',
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
  'try:',
  '    wording_results = match_quote_wording(',
  '        db_path, quote_texts, wording_limit=payload.get("wording_limit")',
  '    )',
  'except Exception as exc:',
  '    detail = "%s: %s" % (type(exc).__name__, exc)',
  '    wording_results = [{"error": detail} for _ in quote_texts]',
  'for text, wording in zip(quote_texts, wording_results):',
  '    entry = quotes_out.get(text)',
  '    if not isinstance(entry, dict):',
  '        entry = {}',
  '        quotes_out[text] = entry',
  '    entry["wording"] = wording',
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
 *   wordingLimit?: number|null, isQuoteNegative?: (v: object) => boolean,
 *   budget?: number, label?: string}} params
 *   `wordingLimit` (Issue #846): Pruefkontingent fuer die teure
 *     Wortlaut-Zuordnung, an ``match_quote_wording()`` durchgereicht —
 *     `null`/weggelassen heisst unbegrenzt (claim-drift-guard.mjs/
 *     context-fidelity-guard.mjs kennen kein eigenes Kontingent und lassen es
 *     weg; die Obermenge bleibt ohnehin durch `prefetchLimit()` gedeckelt).
 *   `isQuoteNegative` (Issue #846): welche Zitat-Eintraege als NICHT
 *     bedienbar gelten (siehe `usableCacheEntry()`) — Default deckt nur die
 *     alte Boolean-Semantik (`found === false`/`null`) ab. verbatim-guard.mjs
 *     uebergibt eine striktere Fassung, die zusaetzlich einen blockierenden
 *     Wortlaut-Status erkennt (sonst bliebe ein Block nach #846 im Cache
 *     klebrig — Retry-Bruch, siehe Docstring von `usableCacheEntry()`).
 * @returns {{quotes: Record<string, object>,
 *   figures: Record<string, boolean|{error:string}>}|null}
 */
export function ensureQuoteBatch(params) {
  const {
    filePath, toolName, toolInput, vaultDb,
    quoteTexts = [], figureTexts = [], wordingLimit = null,
    isQuoteNegative = (v) => v === null || v?.found === false,
    budget = 10000, label = 'Vault-Batch-Cache',
  } = params;

  const key = batchCacheKey(filePath, toolInput);
  const cached = readBatchCache(key);
  if (
    cached
    && usableCacheEntry(cached.quotes, quoteTexts, isQuoteNegative)
    && usableCacheEntry(cached.figures, figureTexts, (v) => v === false)
  ) {
    return cached;
  }

  // Miss (unvollstaendiger Treffer oder Negativ-Treffer): dieser Aufrufer wird
  // Producer. Obermenge = eigene Zitat-Texte (zuerst — der Deckel unten darf
  // sie nie verdraengen) plus die Vereinigung aller drei Guard-Bedarfe
  // (quote-span-extract.mjs), gedeckelt auf die Guard-Kontingente.
  const ownQuotes = [...new Set(quoteTexts)];
  const limit = prefetchLimit(ownQuotes.length);
  let unionQuotes;
  try {
    unionQuotes = unionQuoteTexts(toolName, toolInput, limit);
  } catch {
    unionQuotes = [];
  }
  const allQuotes = [...new Set([...ownQuotes, ...unionQuotes])].slice(0, limit);
  const allFigures = [...new Set(figureTexts)];

  if (!existsSync(vaultDb)) return null;

  const payload = JSON.stringify({
    quotes: allQuotes, figures: allFigures, wording_limit: wordingLimit,
  });
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
