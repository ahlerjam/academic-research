#!/usr/bin/env node
/**
 * hooks/context-fidelity-guard.mjs — PreToolUse Kontexttreue-Warnung (Issue #522)
 *
 * Prueft beim Kapitel-Write jedes im Vault verifizierte Zitat gegen seinen
 * ECHTEN Quellkontext (`quotes.context_before/context_after` mit
 * `context_source = 'fulltext'`, #520) und markiert Fundstellen mit
 * `[KONTEXT-PRUEFEN]`. Typischer Fall: das Original schraenkt unmittelbar nach
 * dem zitierten Satz ein ("Allerdings gilt das nur fuer ..."), das Kapitel
 * uebernimmt nur den ersten Teil — Quote-Mining.
 *
 * Abgrenzung:
 *   - `verbatim-guard.mjs` prueft deterministisch, OB ein Zitat im Vault steht,
 *     und blockiert. Das bleibt die harte Linie.
 *   - `claim-drift-guard.mjs` prueft die KAPITEL-Umgebung eines Zitats bei
 *     Ueberarbeitungen und warnt.
 *   - Dieser Hook prueft die QUELL-Umgebung desselben Zitats und markiert.
 *     Die Signale sind lexikalisch bzw. probabilistisch, deshalb blockt er NIE
 *     — probabilistische Urteile werden nicht zur harten Linie gemacht.
 *
 * Protokoll:
 *   - Eingabe: JSON via stdin (Claude-Code-PreToolUse-Format)
 *   - Ausgabe: JSON via stdout (systemMessage + hookSpecificOutput.additionalContext)
 *   - Exit-Code: IMMER 0. Es wird bewusst KEIN `permissionDecision` gesetzt.
 *
 * Abdeckung statt Stille: sobald ueberhaupt ein Zitat im geschriebenen Text
 * steht, meldet der Hook `Abdeckung: x von y Zitaten pruefbar` und begruendet
 * jedes nicht pruefbare Zitat namentlich (kein Vault-Treffer / kein
 * aufgeloester Quellkontext / Vault nicht erreichbar). Ein stilles Ueberspringen
 * waere ein lautloses Loch.
 *
 * Bypass: Der geschriebene Inhalt enthaelt <!-- vault-guard: skip --> → stumm,
 * die Nutzung wird geloggt wie in verbatim-guard.mjs (#381), mit eigenem Label
 * `context-fidelity-guard: skip`.
 *
 * Konfiguration via Umgebungsvariablen:
 *   VAULT_DB_PATH                 — Pfad zur Vault-DB
 *   VAULT_GUARD_BYPASS_LOG        — Bypass-Log (identisch zu verbatim-guard.mjs)
 *   CONTEXT_FIDELITY_WINDOW       — Kapitelfenster um das Zitat (default 300)
 *   CONTEXT_FIDELITY_MAX_QUOTES   — geprueftes Kontingent je Write (default 20)
 *   CONTEXT_FIDELITY_SIM_MIN      — Kosinus-Schwelle (default 0.35, UNGEEICHT)
 *   CONTEXT_FIDELITY_DEBUG        — '1' aktiviert Diagnose-Ausgaben auf stderr
 *   ACADEMIC_PYTHON               — Interpreter-Override fuer den Vault-Lookup
 */

import { appendFileSync, chmodSync, existsSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import * as os from 'node:os';
import { join } from 'node:path';

import { VAULT_SRC, resolveVaultDb, runVaultPython } from './lib/vault-bridge.mjs';

// ---------------------------------------------------------------------------
// Konfiguration
// ---------------------------------------------------------------------------

const VAULT_DB = resolveVaultDb();

// Identische Pfadaufloesung wie verbatim-guard.mjs::VAULT_GUARD_BYPASS_LOG.
const VAULT_GUARD_BYPASS_LOG = process.env.VAULT_GUARD_BYPASS_LOG
  || join(os.homedir(), '.academic-research', 'vault-guard-bypass.log');

const WINDOW = positiveInt(process.env.CONTEXT_FIDELITY_WINDOW, 300);
const MAX_QUOTES = positiveInt(process.env.CONTEXT_FIDELITY_MAX_QUOTES, 20);
const DEBUG = process.env.CONTEXT_FIDELITY_DEBUG === '1';

/**
 * Kosinus-Schwelle, unterhalb derer Signal 4 anschlaegt.
 *
 * UNGEEICHT: e5-Aehnlichkeiten liegen eng beieinander, 0.35 ist eine bewusst
 * defensive Vermutung und kein Messergebnis. Die Eichung ist ein evals-Thema;
 * bis dahin ist der Wert per Env justierbar und liegt tief genug, dass Signal 4
 * eher schweigt als falsch anschlaegt.
 */
const SIM_MIN = finiteFloat(process.env.CONTEXT_FIDELITY_SIM_MIN, 0.35);

// Zeitbudget des gesamten Vault-Lookups. hooks.json gibt dem Hook 30 s; der
// Lookup muss deutlich darunter bleiben, damit die Meldung noch geschrieben wird.
const LOOKUP_BUDGET_MS = 20000;

const MIN_QUOTE_LEN = 10;
const WRITE_LIKE_TOOLS = new Set(['Write', 'Edit', 'MultiEdit']);
const BYPASS_MARKER = '<!-- vault-guard: skip -->';
const BYPASS_LABEL = 'context-fidelity-guard: skip';

const MARKER = '[KONTEXT-PRÜFEN]';
// Fundstellen-Formulierung. Bewusst verschieden von der Abdeckungszeile: die
// erscheint auch dann, wenn NICHTS gefunden wurde.
const FINDING_PHRASE = 'Kapitelzitat weicht vom Quellkontext ab';

function positiveInt(raw, fallback) {
  const parsed = parseInt(raw ?? '', 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function finiteFloat(raw, fallback) {
  const parsed = Number.parseFloat(raw ?? '');
  return Number.isFinite(parsed) ? parsed : fallback;
}

function debug(message) {
  if (DEBUG) process.stderr.write(`[Kontexttreue-Diagnose] ${message}\n`);
}

// ---------------------------------------------------------------------------
// Lexikalische Signalwoerter
// ---------------------------------------------------------------------------

/**
 * Kontrastmarker (Signal 1) und zugleich das Signal, mit dem ein Kapitel die
 * Einschraenkung selbst offenlegt (Unterdrueckung, AC2).
 */
const CONTRAST_MARKERS = [
  'however', 'but', 'yet', 'nevertheless', 'nonetheless',
  'in contrast', 'on the other hand',
  'allerdings', 'jedoch', 'aber', 'dennoch', 'hingegen', 'gleichwohl',
  'demgegenüber', 'einschränkend',
];

/** Zusaetzliche Offenlegungs-Signale des Kapitels (nur fuer die Unterdrueckung). */
const DISCLOSURE_MARKERS = [
  'relativiert', 'kritisch', 'im gegensatz', 'einschränkung', 'einschränkt',
];

/** Rahmen-Marker (Signal 2): das Zitat referiert eine FREMDE Position. */
const FRAMING_MARKERS = [
  'critics argue', 'it is often claimed', 'proponents claim', 'opponents argue',
  'kritiker behaupten', 'gegner behaupten', 'befürworter behaupten',
  'vielfach wird behauptet', 'es wird oft angenommen', 'man könnte einwenden',
];

/** Relativierungen in der Quelle (Signal 3, Quellseite). */
const HEDGE_MARKERS = [
  'may', 'might', 'suggests', 'appears', 'tends to',
  'könnte', 'könnten', 'deutet darauf hin', 'deuten darauf hin',
  'scheint', 'möglicherweise', 'tendenziell', 'legt nahe', 'legen nahe',
  'dürfte', 'vermutlich',
];

/** Absolutheitsmarker im Kapitel (Signal 3, Kapitelseite). */
const ABSOLUTE_MARKERS = [
  'beweist', 'belegt eindeutig', 'durchweg', 'immer', 'ausnahmslos',
  'generell', 'zweifelsfrei', 'proves', 'always', 'invariably',
];

/** Escaped Wortgrenzen-Regex ueber eine Markerliste (case-insensitive). */
function markerRegex(markers) {
  const escaped = markers.map((m) => m.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  return new RegExp(`(?<![\\p{L}])(${escaped.join('|')})(?![\\p{L}])`, 'iu');
}

const CONTRAST_RE = markerRegex(CONTRAST_MARKERS);
const SUPPRESSION_RE = markerRegex([...CONTRAST_MARKERS, ...DISCLOSURE_MARKERS]);
const FRAMING_RE = markerRegex(FRAMING_MARKERS);
const HEDGE_RE = markerRegex(HEDGE_MARKERS);
const ABSOLUTE_RE = markerRegex(ABSOLUTE_MARKERS);

/** Gefundenes Markerwort oder null. */
function findMarker(regex, text) {
  const match = regex.exec(String(text ?? ''));
  return match ? match[1] : null;
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
// Pfad-Match (identisch zu verbatim-guard.mjs / claim-drift-guard.mjs)
// ---------------------------------------------------------------------------

function isProtectedPath(filePath) {
  if (!filePath) return false;
  const normalized = filePath.replace(/\\/g, '/');
  if (normalized.endsWith('.tex')) return true;
  // Unterordner unter kapitel/ zaehlen mit (#516)
  return /(?:^|\/)kapitel\/(?:[^/]+\/)*[^/]+\.md$/.test(normalized);
}

// ---------------------------------------------------------------------------
// Geschriebener Text
// ---------------------------------------------------------------------------

/**
 * Der vom Modell in DIESEM Tool-Aufruf geschriebene Text.
 *
 * Bewusst nur die Tool-Eingabe und nicht der rekonstruierte Dateistand:
 * geprueft werden soll die aktuelle Schreiboperation, nicht bei jedem Edit
 * erneut das ganze Kapitel — sonst meldete derselbe Befund bei jeder
 * Folgeaenderung wieder. Fuer die Kapitel-Umgebung (Unterdrueckung, Signal 3)
 * reicht dieser Text: der Kontext, in den das Zitat gestellt wird, wird mit dem
 * Zitat zusammen geschrieben.
 */
function authoredContent(toolName, toolInput) {
  if (toolName === 'MultiEdit' && Array.isArray(toolInput.edits)) {
    return toolInput.edits.map((e) => e?.new_string || '').join('\n');
  }
  if (toolName === 'Edit') return toolInput.new_string || '';
  return toolInput.content || '';
}

/**
 * Extrahiert Anfuehrungszeichen-Spans inklusive Position.
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
  return spans.sort((a, b) => a.start - b.start);
}

/** Kapitelfenster um einen Span (Prosa vor und nach dem Zitat, ohne das Zitat). */
function chapterWindow(content, span) {
  const before = content.slice(Math.max(0, span.start - WINDOW), span.start);
  const after = content.slice(span.end, Math.min(content.length, span.end + WINDOW));
  return { before, after, combined: `${before} ${after}` };
}

// ---------------------------------------------------------------------------
// Bypass-Nutzung loggen (Muster verbatim-guard.mjs, Issue #381)
// ---------------------------------------------------------------------------

/**
 * Protokolliert die Nutzung des Bypass-Markers. Best-effort: ein Schreibfehler
 * darf den Hook nie blockierend machen. Das Format bleibt dreispaltig
 * (`<ISO> | <Label> | <Pfad>`), damit bypass-log-report.mjs unveraendert
 * parsen kann; nur das Label unterscheidet die Quelle.
 */
function logBypassUsage(filePath) {
  const line = `${new Date().toISOString()} | ${BYPASS_LABEL} | ${filePath || '(unbekannter Pfad)'}\n`;
  try {
    const logDir = dirname(VAULT_GUARD_BYPASS_LOG);
    if (!existsSync(logDir)) mkdirSync(logDir, { recursive: true, mode: 0o700 });
    appendFileSync(VAULT_GUARD_BYPASS_LOG, line, 'utf-8');
    chmodSync(VAULT_GUARD_BYPASS_LOG, 0o600);
  } catch (err) {
    process.stderr.write(`[Kontexttreue] Bypass-Log-Fehler (ignoriert): ${err.message}\n`);
  }
}

// ---------------------------------------------------------------------------
// Vault-Lookup (ein Subprozess fuer alle Kandidaten)
// ---------------------------------------------------------------------------

const PY_LOOKUP = [
  'import sys, json',
  `sys.path.insert(0, ${JSON.stringify(VAULT_SRC)})`,
  'from academic_vault.server import search_quote_text, get_quote, quote_context_similarity',
  'db_path = sys.argv[1]',
  'out = []',
  'for item in json.loads(sys.argv[2]):',
  '    hits = search_quote_text(db_path, item["span"], 1)',
  '    if not hits:',
  '        out.append({"found": False})',
  '        continue',
  '    quote_id = hits[0]["quote_id"]',
  '    record = get_quote(db_path, quote_id) or {}',
  '    try:',
  '        similarity = quote_context_similarity(db_path, quote_id, item["window"])',
  '    except Exception:',
  '        similarity = None',
  '    out.append({',
  '        "found": True,',
  '        "quote_id": quote_id,',
  '        "paper_id": record.get("paper_id") or hits[0].get("paper_id"),',
  '        "context_before": record.get("context_before"),',
  '        "context_after": record.get("context_after"),',
  '        "context_source": record.get("context_source"),',
  '        "printed_page": record.get("printed_page"),',
  '        "verbatim": record.get("verbatim"),',
  '        "similarity": similarity,',
  '    })',
  'print(json.dumps(out))',
].join('\n');

/**
 * Schlaegt alle Kandidaten in EINEM Python-Subprozess nach.
 *
 * @returns {{status: 'ok', results: object[]} | {status: 'unavailable'}}
 */
function lookupQuotes(candidates) {
  if (candidates.length === 0) return { status: 'ok', results: [] };
  if (!existsSync(VAULT_DB)) {
    debug(`Vault-DB nicht gefunden (${VAULT_DB}).`);
    return { status: 'unavailable' };
  }

  // Kein Modell-Download im PreToolUse-Pfad: HF_HUB_OFFLINE zwingt
  // huggingface_hub auf den lokalen Cache (dokumentierte Offline-Variable).
  // Ohne Cache scheitert der Modell-Load sauber, quote_context_similarity gibt
  // dann None zurueck und der Hook weist "Aehnlichkeit nicht geprueft" aus,
  // statt in das Hook-Timeout zu laufen.
  process.env.HF_HUB_OFFLINE = process.env.HF_HUB_OFFLINE ?? '1';
  process.env.HF_HUB_DISABLE_TELEMETRY = process.env.HF_HUB_DISABLE_TELEMETRY ?? '1';

  const payload = JSON.stringify(
    candidates.map((c) => ({ span: c.text, window: c.window.combined }))
  );
  const output = runVaultPython(PY_LOOKUP, [VAULT_DB, payload], {
    timeout: LOOKUP_BUDGET_MS,
    budget: LOOKUP_BUDGET_MS,
    label: 'Kontexttreue',
  });
  if (output === null) return { status: 'unavailable' };

  try {
    const parsed = JSON.parse(output.trim());
    if (Array.isArray(parsed)) return { status: 'ok', results: parsed };
  } catch (err) {
    debug(`Vault-Antwort nicht lesbar: ${err.message}`);
  }
  return { status: 'unavailable' };
}

// ---------------------------------------------------------------------------
// Signale
// ---------------------------------------------------------------------------

/** Erster Satz (max. 80 Zeichen) eines Textes — der "Anfang" von context_after. */
function leadingSentence(text) {
  const flat = String(text ?? '').replace(/\s+/g, ' ').trim();
  const cut = flat.search(/[.!?]/);
  const head = cut === -1 ? flat : flat.slice(0, cut);
  return head.slice(0, 80);
}

/** Letzte 80 Zeichen eines Textes — das "Ende" von context_before. */
function trailingFragment(text) {
  const flat = String(text ?? '').replace(/\s+/g, ' ').trim();
  return flat.slice(Math.max(0, flat.length - 80));
}

/**
 * Bewertet ein pruefbares Zitat und gibt die ausgeloesten Signale zurueck.
 *
 * `suppressed` = das Kapitel legt die Kontrastivitaet selbst offen. Dann sind
 * die Signale 1 und 2 gegenstandslos (AC2) — Signal 3 und 4 bleiben aktiv:
 * ein offengelegter Kontrast heilt weder einen Hedge-Verlust noch eine
 * semantische Verschiebung.
 */
function evaluateSignals(record, window) {
  const signals = [];
  const disclosure = findMarker(SUPPRESSION_RE, window.combined);

  if (!disclosure) {
    const contrast = findMarker(CONTRAST_RE, leadingSentence(record.context_after));
    if (contrast) {
      signals.push(
        `Kontrastmarker am Anfang des Quellkontexts danach: "${contrast}" — `
        + 'die Quelle schraenkt unmittelbar nach dem zitierten Satz ein.'
      );
    }
    const framing = findMarker(FRAMING_RE, trailingFragment(record.context_before));
    if (framing) {
      signals.push(
        `Rahmen-Marker am Ende des Quellkontexts davor: "${framing}" — `
        + 'das Zitat referiert im Original moeglicherweise eine fremde Position.'
      );
    }
  }

  const sourceText = `${record.context_before || ''} ${record.verbatim || ''} ${record.context_after || ''}`;
  const sourceHedge = findMarker(HEDGE_RE, sourceText);
  const chapterHedge = findMarker(HEDGE_RE, window.combined);
  const chapterAbsolute = findMarker(ABSOLUTE_RE, window.combined);
  if (sourceHedge && !chapterHedge && chapterAbsolute) {
    signals.push(
      `Hedge-Verlust: die Quelle relativiert ("${sourceHedge}"), das Kapitel `
      + `formuliert absolut ("${chapterAbsolute}").`
    );
  }

  if (typeof record.similarity === 'number' && record.similarity < SIM_MIN) {
    signals.push(
      `Semantische Distanz: Kosinus ${record.similarity.toFixed(2)} < ${SIM_MIN} `
      + '(ungeeichte Schwelle, CONTEXT_FIDELITY_SIM_MIN).'
    );
  }

  return { signals, suppressed: Boolean(disclosure) };
}

// ---------------------------------------------------------------------------
// Ausgabe
// ---------------------------------------------------------------------------

function truncate(text, max = 160) {
  const flat = String(text ?? '').replace(/\s+/g, ' ').trim();
  return flat.length > max ? `${flat.slice(0, max - 3)}...` : flat;
}

function buildMessage(filePath, findings, unverifiable, checkable, total, similarityMissing) {
  const lines = [];

  if (findings.length > 0) {
    lines.push(`${MARKER} ${FINDING_PHRASE} (${filePath || '(unbekannter Pfad)'}).`);
    for (const finding of findings) {
      lines.push(`  Zitat: "${truncate(finding.span)}"`);
      if (finding.record.paper_id) {
        const page = finding.record.printed_page ? `, S. ${finding.record.printed_page}` : '';
        lines.push(`  Beleg im Vault: ${finding.record.paper_id}${page}`);
      }
      for (const signal of finding.signals) lines.push(`  Signal: ${signal}`);
      if (finding.record.context_before) {
        lines.push(`  Quellkontext davor:  ${truncate(finding.record.context_before)}`);
      }
      if (finding.record.context_after) {
        lines.push(`  Quellkontext danach: ${truncate(finding.record.context_after)}`);
      }
    }
    lines.push(
      '  Bitte pruefen: Traegt der Quellkontext die Verwendung im Kapitel noch? '
      + 'Sonst Einschraenkung mit aufnehmen, Zitat erweitern oder die Aussage zuruecknehmen.'
    );
    lines.push(
      '  Zur Klaerung: den quote-fidelity-auditor-Agenten mit der betroffenen '
      + 'quote_id aufrufen. Dieser Hook urteilt nicht, er markiert nur.'
    );
  }

  lines.push(`${MARKER} Abdeckung: ${checkable} von ${total} Zitaten prüfbar`);
  for (const item of unverifiable) {
    lines.push(`  Nicht prüfbar: "${truncate(item.span, 80)}" — ${item.reason}`);
  }
  if (similarityMissing) {
    lines.push(
      '  Ähnlichkeit nicht geprüft: kein gespeichertes Quote-Embedding oder kein '
      + 'Embedding-Backend — Signal 4 blieb aus (keine geratene Zahl).'
    );
  }

  return lines.join('\n');
}

function emit(message) {
  process.stderr.write(`${message}\n`);
  // Exit 0 + JSON auf stdout — bewusst ohne permissionDecision (reine Markierung).
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

  const content = authoredContent(toolName, toolInput);
  if (content.includes(BYPASS_MARKER)) {
    debug('Bypass-Marker gesetzt — Kontexttreue-Pruefung uebersprungen.');
    logBypassUsage(filePath);
    process.exit(0);
  }

  // Kandidaten: deduplizierte Zitat-Spans mit ihrem Kapitelfenster.
  const candidates = [];
  const seen = new Set();
  for (const span of extractQuoteSpans(content)) {
    if (seen.has(span.text)) continue;
    seen.add(span.text);
    candidates.push({ text: span.text, window: chapterWindow(content, span) });
    if (candidates.length >= MAX_QUOTES) break;
  }
  if (candidates.length === 0) process.exit(0); // Kein Zitat — nichts zu melden.

  const lookup = lookupQuotes(candidates);

  const findings = [];
  const unverifiable = [];
  let checkable = 0;
  let similarityMissing = false;

  candidates.forEach((candidate, index) => {
    if (lookup.status !== 'ok') {
      unverifiable.push({ span: candidate.text, reason: `Vault nicht erreichbar (${VAULT_DB})` });
      return;
    }
    const record = lookup.results[index];
    if (!record?.found) {
      unverifiable.push({ span: candidate.text, reason: 'kein Eintrag im Vault' });
      return;
    }
    if (record.context_source !== 'fulltext') {
      // Nichtleerer Kontext ist KEIN Beleg fuer echten Quellkontext: der
      // No-Op-Pfad von resolve_quote_context laesst modellgenerierte Felder
      // stehen (#520).
      unverifiable.push({
        span: candidate.text,
        reason: 'kein aufgelöster Quellkontext (context_source fehlt)',
      });
      return;
    }

    checkable += 1;
    if (typeof record.similarity !== 'number') similarityMissing = true;
    const { signals } = evaluateSignals(record, candidate.window);
    if (signals.length > 0) findings.push({ span: candidate.text, record, signals });
  });

  emit(buildMessage(
    filePath, findings, unverifiable, checkable, candidates.length, similarityMissing,
  ));

  // Kein process.exit(0) hier: stdout ist bei einer Pipe asynchron, ein
  // sofortiger exit koennte die JSON-Ausgabe abschneiden.
}

main().catch((err) => {
  debug(`Unerwarteter Fehler (ignoriert): ${err.message}`);
  process.exit(0); // Ein Warn-Hook darf nie zum Blocker werden.
});
