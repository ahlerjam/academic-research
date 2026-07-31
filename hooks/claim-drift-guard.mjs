#!/usr/bin/env node
/**
 * hooks/claim-drift-guard.mjs — PreToolUse Claim-Drift-Warnung (Issue #397)
 *
 * Erkennt, wenn eine Kapitel-Ueberarbeitung die Prosa unmittelbar um ein
 * bereits im Vault belegtes Zitat inhaltlich veraendert, ohne den zugehoerigen
 * Beleg anzupassen. Typischer Fall: aus "moderater Effekt" wird "starker
 * Effekt", das woertliche Zitat und die Quellenangabe bleiben unveraendert
 * stehen — die Aussage ist damit nicht mehr durch den Beleg gedeckt.
 *
 * Abgrenzung: ergaenzt hooks/verbatim-guard.mjs, ersetzt nichts davon. Der
 * verbatim-guard prueft, ob ein Zitat ueberhaupt im Vault existiert (und
 * blockiert). Dieser Hook prueft die UMGEBUNG eines existierenden Zitats und
 * warnt nur.
 *
 * Protokoll:
 *   - Eingabe: JSON via stdin (Claude Code PreToolUse-Format)
 *   - Ausgabe: JSON via stdout (systemMessage + hookSpecificOutput.additionalContext)
 *   - Exit-Code: IMMER 0. Laut Claude-Code-Hook-Doku wird stdout-JSON nur bei
 *     Exit 0 ausgewertet; Exit 2 waere ein Hard-Block und ist hier nie gewollt.
 *   - Es wird bewusst KEIN permissionDecision gesetzt: der Hook informiert,
 *     er entscheidet nicht ueber die Berechtigung.
 *
 * Bypass: Der neue Inhalt enthaelt <!-- vault-guard: skip --> → stumm.
 *
 * Stumm (kein False Positive) ist der Hook insbesondere, wenn
 *   - der Pfad keine Kapitel-/LaTeX-Datei ist,
 *   - die Aenderung nur Markup/Whitespace betrifft,
 *   - kein unveraendertes, im Vault belegtes Zitat im Fenster um die
 *     Aenderung liegt,
 *   - die Quellenangabe im selben Fenster mitgeaendert wurde (bewusste
 *     Anpassung),
 *   - der Vault nicht erreichbar ist (kein Raten ohne Datenbasis).
 *
 * Konfiguration via Umgebungsvariablen:
 *   VAULT_DB_PATH             — Pfad zur Vault-DB
 *   CLAIM_DRIFT_WINDOW        — Zeichenfenster um die Aenderung (default 300)
 *   CLAIM_DRIFT_MAX_LOOKUPS   — Budget an Vault-Lookups pro Aufruf (default 10)
 *   CLAIM_DRIFT_DEBUG         — '1' aktiviert Diagnose-Ausgaben auf stderr
 *   ACADEMIC_PYTHON           — Interpreter-Override fuer den Vault-Lookup
 */

import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { join, dirname, basename, isAbsolute, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as os from 'node:os';

// ---------------------------------------------------------------------------
// Konfiguration
// ---------------------------------------------------------------------------

const HOOK_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = dirname(HOOK_DIR);
const VAULT_SRC = REPO_ROOT;

// Kanonischer DB-Default (Single Source of Truth, Issue #190) — identisch zu
// verbatim-guard.mjs und mid-session-reinforcement.mjs.
const SLUG = basename(process.env.CLAUDE_PROJECT_DIR || process.cwd()) || 'default';
const VAULT_DB = process.env.VAULT_DB_PATH
  || join(os.homedir(), '.academic-research', 'projects', SLUG, 'vault.db');

const WINDOW = positiveInt(process.env.CLAIM_DRIFT_WINDOW, 300);
const MAX_LOOKUPS = positiveInt(process.env.CLAIM_DRIFT_MAX_LOOKUPS, 10);
const DEBUG = process.env.CLAIM_DRIFT_DEBUG === '1';

// Mindestlaenge eines Zitat-Spans (Zeichen) — analog verbatim-guard.mjs.
const MIN_QUOTE_LEN = 10;
const WRITE_LIKE_TOOLS = new Set(['Write', 'Edit', 'MultiEdit']);
const BYPASS_MARKER = '<!-- vault-guard: skip -->';

function positiveInt(raw, fallback) {
  const parsed = parseInt(raw ?? '', 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function debug(message) {
  if (DEBUG) process.stderr.write(`[Claim-Drift-Diagnose] ${message}\n`);
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
// Pfad-Match (bewusst identisch zu verbatim-guard.mjs: kapitel/**/*.md und *.tex)
// ---------------------------------------------------------------------------

function isProtectedPath(filePath) {
  if (!filePath) return false;
  const normalized = filePath.replace(/\\/g, '/');
  if (normalized.endsWith('.tex')) return true;
  if (/(?:^|\/)kapitel\/(?:[^/]+\/)*[^/]+\.md$/.test(normalized)) return true;
  return false;
}

/** Loest einen relativen Tool-Pfad gegen CLAUDE_PROJECT_DIR bzw. das CWD auf. */
function resolveFilePath(filePath) {
  if (!filePath) return '';
  if (isAbsolute(filePath)) return filePath;
  return join(process.env.CLAUDE_PROJECT_DIR || process.cwd(), filePath);
}

// ---------------------------------------------------------------------------
// Alt/Neu-Paare je Tool-Shape
// ---------------------------------------------------------------------------

/** Liest den aktuellen Dateistand, oder null wenn es keinen gibt. */
function readDiskState(filePath) {
  const diskPath = resolveFilePath(filePath);
  if (!diskPath || !existsSync(diskPath)) {
    debug(`Kein Vorgaengerstand auf Platte: ${diskPath || '(kein Pfad)'}`);
    return null;
  }
  try {
    return readFileSync(diskPath, 'utf-8');
  } catch (err) {
    debug(`Datei nicht lesbar (${diskPath}): ${err.message}`);
    return null;
  }
}

/**
 * Wendet eine Edit-Ersetzung literal an (bewusst KEIN String.replace: dort
 * waeren `$&`, `$'` & Co. im Ersatztext Sonderzeichen und wuerden den
 * rekonstruierten Text verschieben).
 *
 * @returns {string|null} null, wenn `oldStr` im Text nicht vorkommt.
 */
function applyEdit(text, oldStr, newStr, replaceAll) {
  if (!oldStr || !text.includes(oldStr)) return null;
  if (replaceAll) return text.split(oldStr).join(newStr);
  const index = text.indexOf(oldStr);
  return text.slice(0, index) + newStr + text.slice(index + oldStr.length);
}

/**
 * Liefert die zu vergleichenden Textpaare — jeweils GANZE Dateistaende, nicht
 * nur die Tool-Strings.
 *
 * Das ist fuer Edit/MultiEdit wesentlich: ein realistischer Edit traegt in
 * `old_string`/`new_string` nur die geaenderte Textstelle ("moderaten Effekt"
 * → "starken Effekt"). Zitat und Quellenangabe stehen dann ausschliesslich in
 * der Datei. Wuerde der Guard nur die beiden Tool-Strings vergleichen, laege im
 * Fenster um die Aenderung nie ein Zitat und er bliebe stumm — genau der Fall,
 * den Issue #397 abdecken soll. Deshalb wird der neue Dateistand aus dem
 * Dateistand auf Platte rekonstruiert.
 *
 *   - Edit:      [{Platte, Platte mit angewandtem Edit}]
 *   - MultiEdit: ein Paar je edits[]-Eintrag, kumulativ angewandt. Pro Paar
 *                bleibt so genau EINE zusammenhaengende Aenderung uebrig, was
 *                Voraussetzung fuer computeChangeRegion() ist.
 *   - Write:     Dateiinhalt von Platte als "alt", content als "neu".
 *
 * Jedes Paar traegt zusaetzlich den Gesamtstand des Dokuments vor und nach dem
 * KOMPLETTEN Tool-Aufruf (`docBefore`/`docAfter`) — den braucht die
 * Beleg-Pruefung, siehe citationChangedAroundQuote().
 *
 * Ohne lesbaren Vorgaengerstand auf Platte faellt der Hook auf den alten,
 * schwaecheren Vergleich der reinen Tool-Strings zurueck: besser als blind.
 * Fuer Write gibt es diesen Rueckfall nicht — dort ist "kein Dateistand"
 * gleichbedeutend mit "neue Datei", und ohne Vorgaengertext gibt es nichts zu
 * vergleichen. Passt ein `old_string` nicht auf den Dateistand, wuerde auch das
 * echte Tool scheitern; der betroffene Edit wird uebersprungen, statt einen nie
 * entstehenden Dateistand zu konstruieren.
 */
function collectPairs(toolName, toolInput) {
  const disk = readDiskState(toolInput.file_path);

  if (toolName === 'Edit') {
    const oldStr = toolInput.old_string || '';
    const newStr = toolInput.new_string || '';
    if (disk === null) return [withDoc({ before: oldStr, after: newStr })];
    const reconstructed = applyEdit(disk, oldStr, newStr, toolInput.replace_all);
    if (reconstructed === null) {
      debug('old_string kommt im Dateistand nicht vor — Edit wird uebersprungen.');
      return [];
    }
    return [withDoc({ before: disk, after: reconstructed })];
  }

  if (toolName === 'MultiEdit') {
    if (!Array.isArray(toolInput.edits)) return [];
    if (disk === null) {
      return toolInput.edits.map((e) => withDoc({
        before: e?.old_string || '',
        after: e?.new_string || '',
      }));
    }
    const staged = [];
    let current = disk;
    for (const edit of toolInput.edits) {
      const next = applyEdit(current, edit?.old_string, edit?.new_string || '', edit?.replace_all);
      if (next === null) {
        debug('old_string kommt im Dateistand nicht vor — Edit wird uebersprungen.');
        continue;
      }
      staged.push({ before: current, after: next });
      current = next;
    }
    // docAfter ist der Stand NACH allen Teil-Edits: eine Quellenangabe, die ein
    // spaeterer Teil-Edit anpasst, gilt auch fuer die frueheren Paare als
    // mitgeaendert.
    return staged.map((p) => ({ ...p, docBefore: disk, docAfter: current }));
  }

  // Write
  if (disk === null) return [];
  return [withDoc({ before: disk, after: toolInput.content || '' })];
}

/** Paar ohne eigenen Dokumentkontext: der Paartext IST der Kontext. */
function withDoc(pair) {
  return { ...pair, docBefore: pair.before, docAfter: pair.after };
}

/**
 * Der vom Modell tatsaechlich geschriebene Text — nur fuer die
 * Bypass-Marker-Erkennung. Bewusst die Tool-Eingabe und nicht der
 * rekonstruierte Dateistand: der Marker soll die konkrete Schreiboperation
 * abwaehlen, exakt wie in verbatim-guard.mjs, und nicht eine Datei dauerhaft
 * aus der Pruefung nehmen, weil er irgendwo darin steht.
 */
function authoredContent(toolName, toolInput) {
  if (toolName === 'MultiEdit' && Array.isArray(toolInput.edits)) {
    return toolInput.edits.map((e) => e?.new_string || '').join('\n');
  }
  if (toolName === 'Edit') return toolInput.new_string || '';
  return toolInput.content || '';
}

// ---------------------------------------------------------------------------
// Aenderungsregion
// ---------------------------------------------------------------------------

/**
 * Grenzt die Aenderung ueber gemeinsamen Praefix/Suffix ein.
 * Gibt {start, beforeEnd, afterEnd} zurueck — Indizes im jeweiligen Text.
 */
function computeChangeRegion(before, after) {
  const maxPrefix = Math.min(before.length, after.length);
  let start = 0;
  while (start < maxPrefix && before[start] === after[start]) start += 1;

  const maxSuffix = maxPrefix - start;
  let suffix = 0;
  while (
    suffix < maxSuffix
    && before[before.length - 1 - suffix] === after[after.length - 1 - suffix]
  ) {
    suffix += 1;
  }
  return { start, beforeEnd: before.length - suffix, afterEnd: after.length - suffix };
}

/**
 * Normalisiert Prosa fuer den Signifikanz-Vergleich: Markdown-Emphase und
 * LaTeX-Zeilenumbrueche raus, Whitespace kollabiert. Damit zaehlen reine
 * Formatierungsaenderungen (z. B. **fett** entfernen, Zeilenumbruch
 * verschieben) nicht als Aussagenaenderung.
 */
function normalizeProse(text) {
  return text
    .replace(/[*_`~]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

// ---------------------------------------------------------------------------
// Zitat-Spans (mit Position) und Beleg-Marker
// ---------------------------------------------------------------------------

/**
 * Extrahiert Anfuehrungszeichen-Spans inklusive Position im Text.
 * Unterstuetzte Typen wie im verbatim-guard: "…", „…“, «…», ``…''.
 */
function extractQuoteSpans(content) {
  const q = MIN_QUOTE_LEN;
  const patterns = [
    new RegExp(`"([^"]{${q},})"`, 'g'),
    new RegExp(`„([^“]{${q},})“`, 'g'),
    new RegExp(`«([^»]{${q},})»`, 'g'),
    new RegExp(`\`\`([^']{${q},})''`, 'g'),
  ];
  const spans = [];
  for (const r of patterns) {
    let match;
    while ((match = r.exec(content)) !== null) {
      if (!match[1]) continue;
      spans.push({ text: match[1], start: match.index, end: match.index + match[0].length });
    }
  }
  return spans;
}

// Beleg-Marker: Autor-Jahr-Klammer, LaTeX-\cite-Varianten, Fussnoten-Referenz,
// Pandoc-Citekeys.
const CITATION_PATTERNS = [
  /\([^)]*\b(?:1[5-9]\d{2}|20\d{2})[a-z]?\b[^)]*\)/g,
  /\\[a-zA-Z]*cite[a-zA-Z]*\s*(?:\[[^\]]*\]\s*)*\{[^}]*\}/g,
  /\[\^[^\]]+\]/g,
  /\[@[^\]]+\]/g,
];

/** Sortierte Liste aller Beleg-Marker eines Textausschnitts. */
function extractCitationMarkers(text) {
  const markers = [];
  for (const pattern of CITATION_PATTERNS) {
    const re = new RegExp(pattern.source, pattern.flags);
    let match;
    while ((match = re.exec(text)) !== null) markers.push(match[0]);
  }
  return markers.map(normalizeProse).sort();
}

/** Abstand eines Spans zur Aenderungsregion (0 = ueberlappend). */
function distanceToRegion(span, regionStart, regionEnd) {
  if (span.end < regionStart) return regionStart - span.end;
  if (span.start > regionEnd) return span.start - regionEnd;
  return 0;
}

// ---------------------------------------------------------------------------
// Kandidaten-Ermittlung
// ---------------------------------------------------------------------------

/** Beleg-Marker im Fenster um das Zitat, oder null wenn es dort nicht steht. */
function markersAroundQuote(quoteText, doc) {
  const index = doc.indexOf(quoteText);
  if (index === -1) return null;
  const from = Math.max(0, index - WINDOW);
  const to = Math.min(doc.length, index + quoteText.length + WINDOW);
  return extractCitationMarkers(doc.slice(from, to));
}

/**
 * Wurde die Quellenangabe RUND UM DIESES ZITAT mitgeaendert? Dann ist die
 * Ueberarbeitung eine bewusste Anpassung und keine Drift.
 *
 * Der Vergleich haengt bewusst am Zitat und nicht an der Aenderungsregion:
 * bei einem MultiEdit stecken "Aussage aendern" und "Quelle nachziehen" in
 * zwei getrennten Teil-Edits. Eine regionsbezogene Pruefung saehe im ersten
 * Teil-Edit eine unveraenderte Quellenangabe und wuerde falsch warnen.
 */
function citationChangedAroundQuote(quoteText, docBefore, docAfter) {
  const markersBefore = markersAroundQuote(quoteText, docBefore);
  const markersAfter = markersAroundQuote(quoteText, docAfter);
  if (markersBefore === null || markersAfter === null) return false;
  return JSON.stringify(markersBefore) !== JSON.stringify(markersAfter);
}

/**
 * Sucht Zitat-Spans, die
 *   1. im neuen Text im Fenster um die Aenderung liegen,
 *   2. woertlich unveraendert auch im alten Text vorkommen (der Beleg selbst
 *      wurde also nicht angefasst),
 *   3. deren Beleg-Marker im Fenster um das Zitat unveraendert sind.
 * Gibt [] zurueck, sobald einer der Ausschlussgruende greift.
 */
function findAnchoredQuotes(pair) {
  const { before, after, docBefore, docAfter } = pair;
  if (before === after || !before) return [];

  const region = computeChangeRegion(before, after);
  const changedBefore = normalizeProse(before.slice(region.start, region.beforeEnd));
  const changedAfter = normalizeProse(after.slice(region.start, region.afterEnd));
  if (changedBefore === changedAfter) {
    debug('Aenderung ist rein formatierend — keine Aussagenaenderung.');
    return [];
  }

  return extractQuoteSpans(after).filter((span) => {
    if (distanceToRegion(span, region.start, region.afterEnd) > WINDOW) return false;
    if (!before.includes(span.text)) return false;
    if (citationChangedAroundQuote(span.text, docBefore, docAfter)) {
      debug('Beleg-Marker am Zitat wurden mitgeaendert — bewusste Anpassung.');
      return false;
    }
    return true;
  });
}

// ---------------------------------------------------------------------------
// Vault-Lookup (Tri-State: found | not-found | unavailable)
// ---------------------------------------------------------------------------

/**
 * Interpreter-Kaskade wie in mid-session-reinforcement.mjs (#382): das
 * System-Python auf macOS (3.9) kann academic_vault nicht importieren.
 */
function pythonCandidates() {
  const candidates = [];
  if (process.env.ACADEMIC_PYTHON) candidates.push(process.env.ACADEMIC_PYTHON);
  if (process.env.VIRTUAL_ENV) candidates.push(join(process.env.VIRTUAL_ENV, 'bin', 'python'));
  candidates.push(join(os.homedir(), '.academic-research', 'venv', 'bin', 'python'));
  candidates.push('python3');
  return [...new Set(candidates)];
}

const PY_LOOKUP = [
  'import sys, json',
  `sys.path.insert(0, ${JSON.stringify(VAULT_SRC)})`,
  'from academic_vault.server import search_quote_text, get_quote',
  'db_path = sys.argv[1]',
  'out = []',
  'for span in json.loads(sys.argv[2]):',
  '    hits = search_quote_text(db_path, span, 1)',
  '    if not hits:',
  '        out.append({"found": False})',
  '        continue',
  '    record = get_quote(db_path, hits[0]["quote_id"]) or {}',
  '    out.append({',
  '        "found": True,',
  '        "quote_id": hits[0]["quote_id"],',
  '        "paper_id": record.get("paper_id") or hits[0].get("paper_id"),',
  '        "context_before": record.get("context_before"),',
  '        "context_after": record.get("context_after"),',
  '        "printed_page": record.get("printed_page"),',
  '    })',
  'print(json.dumps(out))',
].join('\n');

/**
 * Schlaegt mehrere Spans in EINEM Subprozess nach (ein Python-Start pro
 * Hook-Aufruf statt einem pro Zitat — das 15-s-Timeout in hooks.json haelt).
 *
 * @returns {{status: 'ok', results: object[]} | {status: 'unavailable'}}
 */
function lookupQuotes(spanTexts) {
  if (spanTexts.length === 0) return { status: 'ok', results: [] };
  if (!existsSync(VAULT_DB)) {
    debug(`Vault-DB nicht gefunden (${VAULT_DB}) — Claim-Drift-Pruefung uebersprungen.`);
    return { status: 'unavailable' };
  }

  const failures = [];
  for (const python of pythonCandidates()) {
    if (python.includes(sep) && !existsSync(python)) {
      failures.push(`${python}: nicht vorhanden`);
      continue;
    }
    try {
      const output = execFileSync(python, ['-c', PY_LOOKUP, VAULT_DB, JSON.stringify(spanTexts)], {
        encoding: 'utf-8',
        timeout: 10000,
        stdio: ['pipe', 'pipe', 'pipe'],
      });
      const parsed = JSON.parse(output.trim());
      if (Array.isArray(parsed)) return { status: 'ok', results: parsed };
      failures.push(`${python}: unerwartete Antwort`);
    } catch (err) {
      failures.push(`${python}: ${err.message.split('\n')[0]}`);
    }
  }
  debug(`Vault-Lookup mit keinem Interpreter moeglich: ${failures.join(' | ')}`);
  return { status: 'unavailable' };
}

// ---------------------------------------------------------------------------
// Warn-Ausgabe
// ---------------------------------------------------------------------------

function truncate(text, max = 120) {
  const flat = String(text ?? '').replace(/\s+/g, ' ').trim();
  return flat.length > max ? `${flat.slice(0, max - 3)}...` : flat;
}

function emitWarning(filePath, findings) {
  const header = `[Claim-Drift] Warnung: belegte Aussage geaendert, Beleg unveraendert (${filePath || '(unbekannter Pfad)'}).`;
  const lines = [header];
  for (const { span, record } of findings) {
    lines.push(`  Zitat: "${truncate(span)}"`);
    if (record.paper_id) {
      const page = record.printed_page ? `, S. ${record.printed_page}` : '';
      lines.push(`  Beleg im Vault: ${record.paper_id}${page}`);
    }
    if (record.context_before) lines.push(`  Kontext davor:  ${truncate(record.context_before)}`);
    if (record.context_after) lines.push(`  Kontext danach: ${truncate(record.context_after)}`);
  }
  lines.push(
    '  Bitte pruefen: Deckt der Beleg die geaenderte Aussage noch? '
    + 'Sonst Quelle anpassen, Zitat austauschen oder die Aussage zuruecknehmen.'
  );

  const message = lines.join('\n');
  process.stderr.write(`${message}\n`);
  // Exit 0 + JSON auf stdout — bewusst ohne permissionDecision (reine Warnung).
  console.log(JSON.stringify({
    systemMessage: message,
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      additionalContext: message,
    },
  }));
}

// ---------------------------------------------------------------------------
// Haupt-Logik
// ---------------------------------------------------------------------------

async function main() {
  let input;
  try {
    const raw = await readStdin();
    input = raw ? JSON.parse(raw) : {};
  } catch {
    process.exit(0); // Malformed stdin — stumm
  }

  const toolName = input?.tool_name || '';
  if (!WRITE_LIKE_TOOLS.has(toolName)) process.exit(0);

  const toolInput = input?.tool_input || {};
  const filePath = toolInput.file_path || '';
  if (!isProtectedPath(filePath)) process.exit(0);

  if (authoredContent(toolName, toolInput).includes(BYPASS_MARKER)) {
    debug('Bypass-Marker gesetzt — Claim-Drift-Pruefung uebersprungen.');
    process.exit(0);
  }

  const pairs = collectPairs(toolName, toolInput);
  if (pairs.length === 0) process.exit(0);

  // Kandidaten sammeln (dedupliziert, Lookup-Budget begrenzt die Laufzeit).
  const candidates = [];
  const seen = new Set();
  for (const pair of pairs) {
    for (const span of findAnchoredQuotes(pair)) {
      if (seen.has(span.text)) continue;
      seen.add(span.text);
      candidates.push(span.text);
      if (candidates.length >= MAX_LOOKUPS) break;
    }
    if (candidates.length >= MAX_LOOKUPS) break;
  }
  if (candidates.length === 0) process.exit(0);

  const lookup = lookupQuotes(candidates);
  if (lookup.status !== 'ok') process.exit(0); // Ohne Datenbasis wird nicht geraten.

  const findings = [];
  lookup.results.forEach((record, index) => {
    if (record?.found) findings.push({ span: candidates[index], record });
  });
  if (findings.length > 0) emitWarning(filePath, findings);

  // Kein process.exit(0) hier: stdout ist bei einer Pipe asynchron, ein
  // sofortiger exit koennte die JSON-Ausgabe abschneiden. Node beendet sich
  // nach dem Leerlaufen der Event-Loop ohnehin mit Exit-Code 0.
}

main().catch((err) => {
  debug(`Unerwarteter Fehler (ignoriert): ${err.message}`);
  process.exit(0); // Ein Warn-Hook darf nie zum Blocker werden.
});
