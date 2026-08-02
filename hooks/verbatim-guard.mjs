#!/usr/bin/env node
/**
 * hooks/verbatim-guard.mjs — PreToolUse Verbatim-Validation
 *
 * Blockiert Write-Calls auf kapitel/*.md und *.tex, wenn der Content
 * Anführungszeichen-Spans enthält, die nicht im Vault verifiziert sind.
 *
 * Drei additive Prüfstufen (jede läuft erst, wenn die vorige durch ist):
 *   1. Wörtliche Zitate  — Anführungszeichen-Spans gegen quotes.verbatim
 *   2. Figure-Referenzen — "Abb. 3.4" gegen figures.caption
 *   3. Klammer-Belege    — "(Müller 2021, S. 45)" gegen papers.csl_json,
 *      mit externer Kaskade als Fallback (Issue #378)
 *
 * Protokoll:
 *   - Eingabe: JSON via stdin (Claude Code PreToolUse-Format)
 *   - Ausgabe: JSON via stdout (hookSpecificOutput für Block-Hinweis)
 *   - Exit 0: allow (kein Block)
 *   - Exit 2: block (Zitat nicht verifiziert)
 *
 * Bypass: Content enthält <!-- vault-guard: skip --> → immer allow.
 * Jede Bypass-Nutzung wird nach stderr gewarnt UND in eine Logdatei
 * angehängt (siehe VAULT_GUARD_BYPASS_LOG, Issue #381).
 *
 * Fail-open (zwei unterschiedliche, bewusst getrennt formulierte Fälle,
 * Issue #381 — Vermischung war Ursache des ursprünglichen Bugs):
 *   1. "DB fehlt" — erwartbar bei einem frischen Projekt ohne Vault-DB.
 *      Wortlaut: "Vault-DB nicht gefunden ... Bypass aktiv."
 *   2. "Lookup-Fehler bei vorhandener DB" — unerwartet (z. B. korrupte
 *      Datei, kaputte Query). Bleibt fail-open (kein Regressionsverlust
 *      für Scope "Out"), aber sichtbar anderer Wortlaut, damit ein
 *      stiller Bypass bei kaputter DB nicht mit dem harmlosen
 *      "frisches Projekt"-Fall verwechselt wird.
 */

import { execFileSync } from 'node:child_process';
import { existsSync, appendFileSync, mkdirSync, chmodSync, readFileSync } from 'node:fs';
import { join, dirname, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as os from 'node:os';
import { extractCitations, markSpans } from './lib/citation-parse.mjs';
import { loadConfig, resolveCitations } from './lib/citation-cascade.mjs';
import { isProtectedPath, isMarkdownOrTexFile, chapterDirLabel } from './lib/protected-path.mjs';

// ---------------------------------------------------------------------------
// Konfiguration
// ---------------------------------------------------------------------------

const HOOK_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = dirname(HOOK_DIR);
const VAULT_SRC = REPO_ROOT;
// Kanonischer DB-Default (Single Source of Truth, Issue #190):
// VAULT_DB_PATH aus Env, sonst ~/.academic-research/projects/<slug>/vault.db
// mit slug=basename(CWD). NICHT mehr REPO_ROOT/vault.db (= Plugin-Verzeichnis).
const SLUG = basename(process.env.CLAUDE_PROJECT_DIR || process.cwd()) || 'default';
const VAULT_DB = process.env.VAULT_DB_PATH
  || join(os.homedir(), '.academic-research', 'projects', SLUG, 'vault.db');
// Logdatei fuer Bypass-Marker-Nutzung (Issue #381). Env-Override, Default-Muster
// analog ACADEMIC_DECISIONS_LOG in post-tool-use-decisions.mjs.
const VAULT_GUARD_BYPASS_LOG = process.env.VAULT_GUARD_BYPASS_LOG
  || join(os.homedir(), '.academic-research', 'vault-guard-bypass.log');
// Logdatei fuer Nutzung guard-schwaechender Env-Schalter (Issue #519). Gleiches
// Muster wie VAULT_GUARD_BYPASS_LOG — eigene Datei, damit der Bypass-Report
// (#517) beide Quellen unabhaengig voneinander offset-verfolgen kann.
const VAULT_GUARD_ENV_SWITCH_LOG = process.env.VAULT_GUARD_ENV_SWITCH_LOG
  || join(os.homedir(), '.academic-research', 'vault-guard-env-switch.log');
// Namen der guard-schwaechenden Schalter (Issue #519, Audit-Risiko R7). Jeder
// GESETZTE (nicht-leere) Wert wird protokolliert — unabhaengig davon, ob er im
// konkreten Content-Check ueberhaupt greift (sichtbar machen der Nutzung, nicht
// Bewertung der Abschwaechung).
const ENV_SWITCH_NAMES = [
  'ACADEMIC_CITATION_AMBIGUOUS',
  'ACADEMIC_CITATION_CASCADE',
  'ACADEMIC_CITATION_MAX_PER_WRITE',
];
// Mindestlänge eines Zitat-Spans (in Zeichen). Muss mit den Regex-Quantifizierern übereinstimmen.
const MIN_QUOTE_LEN = 10;
// Pattern fuer Figure-Referenzen (Abb., Abbildung, Tab., Tabelle, Fig., Figure + Nummer)
const FIGURE_REF_PATTERN = /(Abb|Abbildung|Tab|Tabelle|Fig|Figure)\.?\s*\d+(\.\d+)?/gi;

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
// Pfad-Match: isProtectedPath() kommt aus ./lib/protected-path.mjs (#615) —
// gemeinsame Quelle fuer alle drei Kapitel-Guards.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Tool-Erkennung + Content-Extraktion
// ---------------------------------------------------------------------------

// Tools die Dateiinhalte schreiben und daher geprueft werden muessen (#220).
const WRITE_LIKE_TOOLS = new Set(['Write', 'Edit', 'MultiEdit']);

/**
 * Extrahiert den zu pruefenden Text aus tool_input — abhaengig vom Tool:
 *   - Write:     tool_input.content
 *   - Edit:      tool_input.new_string
 *   - MultiEdit: alle edits[].new_string (zusammengefuegt)
 */
/**
 * Die zu pruefenden Textstuecke eines Tool-Calls, in Reihenfolge.
 *
 * Einzige Quelle fuer BEIDE Richtungen: extractContent joint sie zum
 * Pruef-Text, buildUpdatedInput spleisst die Markierungen wieder hinein.
 * Liefen Join und Split auseinander, zeigten die Beleg-Offsets ins Leere.
 */
function collectSegments(toolName, toolInput) {
  if (toolName === 'MultiEdit' && Array.isArray(toolInput.edits)) {
    return toolInput.edits.map((e) => e?.new_string || '');
  }
  if (toolName === 'Edit') {
    return [toolInput.new_string || ''];
  }
  // Write (und Fallback)
  return [toolInput.content || ''];
}

// Trennzeichen zwischen zwei Segmenten im Pruef-Text. Genau ein Zeichen —
// die Offset-Rechnung in segmentBases() zaehlt es mit.
const SEGMENT_SEPARATOR = '\n';

/** Startoffset jedes Segments im gejointen Pruef-Text. */
function segmentBases(segments) {
  const bases = [];
  let offset = 0;
  for (const segment of segments) {
    bases.push(offset);
    offset += segment.length + SEGMENT_SEPARATOR.length;
  }
  return bases;
}

function extractContent(toolName, toolInput) {
  return collectSegments(toolName, toolInput).join(SEGMENT_SEPARATOR);
}

// ---------------------------------------------------------------------------
// Quote-Parser
// ---------------------------------------------------------------------------

/**
 * Extrahiert Anführungszeichen-Spans aus dem Content.
 * Unterstuetzte Typen:
 *   "…"   — ASCII double quotes
 *   „…"   — Deutsche Anführungszeichen
 *   «…»   — Guillemets
 *   ``…'' — LaTeX
 *
 * Mindestlänge: MIN_QUOTE_LEN Zeichen (innerer Text).
 * Gibt Array von Strings (innere Texte) zurueck.
 */
function extractQuoteSpans(content) {
  const spans = [];
  const q = MIN_QUOTE_LEN;
  // Jedes Pattern als Konstruktor — dadurch wird lastIndex isoliert pro Durchlauf.
  const patterns = [
    new RegExp(`"([^"]{${q},})"`, 'g'),           // ASCII "…"
    new RegExp(`„([^“]{${q},})“`, 'g'), // Deutsche „…" (U+201E…U+201C)
    new RegExp(`«([^»]{${q},})»`, 'g'), // Guillemets «…» (U+00AB…U+00BB)
    new RegExp(`\`\`([^']{${q},})''`, 'g'),        // LaTeX ``…''
  ];
  for (const r of patterns) {
    let match;
    while ((match = r.exec(content)) !== null) {
      if (match[1]) spans.push(match[1]);
    }
  }
  return spans;
}

// ---------------------------------------------------------------------------
// Fail-open-Warnung (gemeinsamer Helper, Issue #381)
// ---------------------------------------------------------------------------

/**
 * Schreibt eine fail-open-Warnung nach stderr und gibt true (Bypass) zurueck.
 * Zwei Faelle werden bewusst unterschiedlich formuliert, damit sie beim Lesen
 * von stderr nicht verwechselt werden koennen:
 *   - kind === 'missing-db'   → "DB fehlt" (erwartbar, frisches Projekt).
 *   - kind === 'lookup-error' → DB existiert, Python-Subprocess wirft trotzdem
 *                               (z. B. korrupte Datei) — unerwartet.
 *
 * @param {string} context - Label fuer die Ausgabe, z. B. 'Vault-Guard'/'Figure-Guard'.
 * @param {'missing-db'|'lookup-error'} kind
 * @param {string} detail - DB-Pfad (missing-db) oder Fehlermeldung (lookup-error).
 */
function warnFailOpen(context, kind, detail) {
  const message = kind === 'missing-db'
    ? `Vault-DB nicht gefunden (${detail}). Bypass aktiv.`
    : `Vault-Lookup-Fehler trotz vorhandener DB (${detail}). Bypass aktiv — bitte DB pruefen.`;
  process.stderr.write(`[${context}] Warnung: ${message}\n`);
  return true; // fail-open (Scope #381: Mechanismus selbst bleibt bestehen)
}

// ---------------------------------------------------------------------------
// Vault-Lookup via Python-Subprocess
// ---------------------------------------------------------------------------

/**
 * Sucht verbatim im Vault. Gibt true zurueck wenn ein Treffer gefunden wurde.
 * Bei fehlender Python/Vault-Umgebung: Warnung + true (fail-open).
 */
function lookupInVault(verbatim) {
  // Vault-DB muss existieren (sonst fail-open, Fall 1: "DB fehlt")
  if (!existsSync(VAULT_DB)) {
    return warnFailOpen('Vault-Guard', 'missing-db', VAULT_DB);
  }

  const pyCode = [
    'import sys, json',
    `sys.path.insert(0, ${JSON.stringify(VAULT_SRC)})`,
    'from academic_vault.server import search_quote_text',
    `hits = search_quote_text(sys.argv[1], sys.argv[2])`,
    'print(json.dumps(hits))',
  ].join('; ');

  try {
    const output = execFileSync('python3', ['-c', pyCode, VAULT_DB, verbatim], {
      encoding: 'utf-8',
      timeout: 10000,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const hits = JSON.parse(output.trim());
    return Array.isArray(hits) && hits.length > 0;
  } catch (err) {
    // Fall 2: DB vorhanden, aber Exception (z. B. korrupte Datei/Query) — unerwartet.
    return warnFailOpen('Vault-Guard', 'lookup-error', err.message);
  }
}

// ---------------------------------------------------------------------------
// Figure-Caption-Lookup via Python-Subprocess
// ---------------------------------------------------------------------------

/**
 * Sucht Caption-Fragment im Vault.
 * Gibt true wenn mindestens ein Eintrag gefunden oder Vault fehlt (fail-open).
 */
function lookupFigureInVault(captionFragment) {
  if (!existsSync(VAULT_DB)) {
    return warnFailOpen('Figure-Guard', 'missing-db', VAULT_DB);
  }

  const pyCode = [
    'import sys, json',
    `sys.path.insert(0, ${JSON.stringify(VAULT_SRC)})`,
    'from academic_vault.server import find_figure_by_caption',
    `hits = find_figure_by_caption(sys.argv[1], sys.argv[2])`,
    'print(json.dumps(hits))',
  ].join('; ');

  try {
    const output = execFileSync('python3', ['-c', pyCode, VAULT_DB, captionFragment], {
      encoding: 'utf-8',
      timeout: 10000,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const hits = JSON.parse(output.trim());
    return Array.isArray(hits) && hits.length > 0;
  } catch (err) {
    return warnFailOpen('Figure-Guard', 'lookup-error', err.message);
  }
}

// ---------------------------------------------------------------------------
// Bypass-Nutzung loggen (Issue #381)
// ---------------------------------------------------------------------------

/**
 * Protokolliert die Nutzung des Bypass-Markers <!-- vault-guard: skip -->.
 * Best-effort: Schreibfehler duerfen den Guard nie blockierend machen.
 * Analog zu writeLogLine() in post-tool-use-decisions.mjs (0600-Rechte,
 * Env-Var-Override der Logdatei).
 */
function logBypassUsage(filePath) {
  const ts = new Date().toISOString();
  const line = `${ts} | vault-guard: skip | ${filePath || '(unbekannter Pfad)'}\n`;
  try {
    const logDir = dirname(VAULT_GUARD_BYPASS_LOG);
    if (!existsSync(logDir)) {
      mkdirSync(logDir, { recursive: true, mode: 0o700 });
    }
    appendFileSync(VAULT_GUARD_BYPASS_LOG, line, 'utf-8');
    chmodSync(VAULT_GUARD_BYPASS_LOG, 0o600);
  } catch (err) {
    // Best-effort — das Loggen selbst darf keinen neuen Blocker erzeugen.
    process.stderr.write(`[Vault-Guard] Bypass-Log-Fehler (ignoriert): ${err.message}\n`);
  }
}

// ---------------------------------------------------------------------------
// Env-Schalter-Nutzung loggen (Issue #519)
// ---------------------------------------------------------------------------

/**
 * Protokolliert die Nutzung EINES guard-schwaechenden Env-Schalters.
 * Best-effort: Schreibfehler duerfen den Guard nie blockierend machen
 * (analog logBypassUsage, Issue #381).
 */
function writeEnvSwitchLines(payloads) {
  if (payloads.length === 0) return;
  const ts = new Date().toISOString();
  const block = payloads.map((p) => `${ts} | ${p}\n`).join('');
  try {
    const logDir = dirname(VAULT_GUARD_ENV_SWITCH_LOG);
    if (!existsSync(logDir)) {
      mkdirSync(logDir, { recursive: true, mode: 0o700 });
    }
    appendFileSync(VAULT_GUARD_ENV_SWITCH_LOG, block, 'utf-8');
    chmodSync(VAULT_GUARD_ENV_SWITCH_LOG, 0o600);
  } catch (err) {
    // Best-effort — das Loggen selbst darf keinen neuen Blocker erzeugen.
    process.stderr.write(`[Vault-Guard] Env-Switch-Log-Fehler (ignoriert): ${err.message}\n`);
  }
}

/**
 * Nutzlasten (alles ausser dem Zeitstempel) der letzten ``count`` Zeilen des
 * Env-Switch-Logs. Leeres Array, wenn das Log fehlt/leer/unlesbar ist —
 * fail-open: im Zweifel wird geschrieben statt verschluckt.
 */
function lastEnvSwitchPayloads(count) {
  try {
    if (count <= 0 || !existsSync(VAULT_GUARD_ENV_SWITCH_LOG)) return [];
    const lines = readFileSync(VAULT_GUARD_ENV_SWITCH_LOG, 'utf-8').trimEnd().split('\n');
    return lines
      .slice(-count)
      .map((l) => {
        const parts = l.split(' | ');
        return parts.length < 2 ? null : parts.slice(1).join(' | ');
      })
      .filter((p) => p !== null);
  } catch {
    return [];
  }
}

/**
 * Prueft alle drei guard-schwaechenden Schalter (ENV_SWITCH_NAMES) und
 * protokolliert jeden GESETZTEN (nicht-leeren) einzeln. "Gesetzt" heisst
 * process.env[NAME] vorhanden und nicht-leer — unabhaengig vom konkreten
 * Wert, auch ein explizit auf Default gesetzter Schalter zaehlt (AC1).
 */
function logActiveEnvSwitches(filePath, env = process.env) {
  const target = filePath || '(unbekannter Pfad)';
  const payloads = [];
  for (const name of ENV_SWITCH_NAMES) {
    const value = env[name];
    if (value !== undefined && value !== '') {
      payloads.push(`${name}=${value} | ${target}`);
    }
  }
  // Dedup ueber die GESAMTE Schalter-Kombination, nicht je Zeile: Anders als
  // der Bypass-Marker (#381) ist ein Env-Schalter eine dauerhaft gesetzte
  // Konfiguration — ohne Dedup haengt jeder geschuetzte Write denselben Block
  // erneut an, und der SessionStart-Report meldet dutzende "neue Nutzungen"
  // fuer eine einzige Einstellung. Der Vergleich muss den ganzen Block
  // umfassen: bei zwei oder drei gesetzten Schaltern ist die jeweils letzte
  // Zeile die eines ANDEREN Schalters, ein Zeilenvergleich traefe also nie zu.
  const previous = lastEnvSwitchPayloads(payloads.length);
  if (
    previous.length === payloads.length &&
    previous.every((p, i) => p === payloads[i])
  ) {
    return;
  }
  writeEnvSwitchLines(payloads);
}

// ---------------------------------------------------------------------------
// Klammer-Zitat-Verifikation (Issue #378)
// ---------------------------------------------------------------------------

// Obergrenze der pro Write GEPRÜFTEN Belege. Verhindert, dass ein sehr grosses
// Kapitel den Hook-Timeout sprengt. Überzählige Belege werden NICHT still
// übergangen — das wäre ein lautloses Loch im Guard: genug Belege vor einem
// erfundenen, und der erfundene läuft ungeprüft durch. Stattdessen zählen sie
// wie ein API-Ausfall als "ungeprüft" ([UNVERIFIED] statt Block) und der Hook
// meldet die Kappung auf stderr.
const DEFAULT_MAX_CITATIONS_PER_WRITE = 100;

/** Pruefkontingent pro Write; per Env übersteuerbar (Default 100). */
function maxCitationsPerWrite(env = process.env) {
  const raw = env.ACADEMIC_CITATION_MAX_PER_WRITE;
  if (raw === undefined || raw === '') return DEFAULT_MAX_CITATIONS_PER_WRITE;
  const value = Number(raw);
  return Number.isInteger(value) && value > 0 ? value : DEFAULT_MAX_CITATIONS_PER_WRITE;
}

/**
 * Reaktion auf ein sauberes Negativ bei der MEHRDEUTIGEN Beleg-Form
 * "(Wort Jahr)": ``"block"`` (Default) oder ``"mark"``.
 *
 * AC2 aus #378 nennt "erfundener Autor/Jahr" ohne Vorbehalt zur Form — und
 * genau die nackte Form ist der Halluzinationsfall, gegen den der Guard
 * antritt. Der frühere feste Deckel auf [UNVERIFIED] liess ihn durch.
 *
 * Das Gegenargument ("(Fukushima 2011) koennte Prosa sein") bleibt richtig,
 * traegt aber keinen Deckel mehr: derselbe Code schreibt diese Prosa im
 * Soft-Fail bereits um. Wer den Eingriff in moeglicherweise unbeteiligten Text
 * akzeptiert, kann ihn nicht als Grund gegen den sichtbaren, nichts
 * schreibenden Block anfuehren. Der Trade-off wird deshalb zur Politik des
 * Schreibenden statt zu einer stillen Entscheidung des Hooks:
 * ``ACADEMIC_CITATION_AMBIGUOUS=mark`` fuer prosa-lastige Texte.
 *
 * Unberuehrt bleibt in beiden Politiken die fehlende Evidenz: ``unavailable``
 * und "ungeprueft (Kontingent)" markieren weiter (AC3).
 */
function ambiguousPolicy(env = process.env) {
  return (env.ACADEMIC_CITATION_AMBIGUOUS || 'block').toLowerCase() === 'mark' ? 'mark' : 'block';
}

/**
 * Ein Eintrag je BELEG (nicht je Fundstelle), in Reihenfolge des ersten
 * Vorkommens. Der Parser liefert bewusst jede Fundstelle einzeln; Vault-Lookup
 * und Kaskade sollen trotzdem nur einmal je Beleg laufen.
 */
function uniqueByKey(citations) {
  const byKey = new Map();
  for (const citation of citations) {
    if (!byKey.has(citation.key)) byKey.set(citation.key, citation);
  }
  return [...byKey.values()];
}

/**
 * Prüft alle Belege in EINEM Python-Subprozess (nicht einer pro Beleg —
 * sonst dominieren Interpreter-Starts das Hook-Timeout).
 * Gibt Map key -> "verified" | "page-mismatch" | "no-match" | "unavailable"
 * zurück; "unavailable" bedeutet Python/Vault-Fehler (fail-open).
 */
function verifyCitationsInVault(citations) {
  const statuses = new Map();
  const pyCode = [
    'import sys, json',
    `sys.path.insert(0, ${JSON.stringify(VAULT_SRC)})`,
    'from academic_vault.server import verify_citation',
    'items = json.loads(sys.argv[2])',
    'print(json.dumps([verify_citation(sys.argv[1], i["family"], i["year"], i["page"])["status"] '
      + 'for i in items]))',
  ].join('; ');

  const payload = JSON.stringify(
    citations.map((c) => ({ family: c.family, year: c.year, page: c.page })),
  );

  try {
    const output = execFileSync('python3', ['-c', pyCode, VAULT_DB, payload], {
      encoding: 'utf-8',
      timeout: 10000,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const parsed = JSON.parse(output.trim());
    citations.forEach((c, i) => statuses.set(c.key, parsed[i] || 'unavailable'));
  } catch (err) {
    warnFailOpen('Citation-Guard', 'lookup-error', err.message);
    for (const c of citations) statuses.set(c.key, 'unavailable');
  }
  return statuses;
}

const UNVERIFIED_MARKER = ' [UNVERIFIED]';

/**
 * Baut das vollständige updatedInput-Objekt für den Soft-Fail — je nach Tool
 * wird content (Write), new_string (Edit) oder edits[].new_string (MultiEdit)
 * markiert. Alle übrigen Felder bleiben unverändert erhalten.
 *
 * Die Zuordnung Fundstelle → Segment läuft über die Basis-Offsets aus
 * segmentBases(), nicht über eine Textsuche. Nur so landet der Marker an genau
 * der Stelle, die geprüft wurde: ein identischer Beleg-String in einem
 * maskierten Bereich (Code-Fence, \cite{...}, Literaturverzeichnis) oder in
 * einem anderen Edit bleibt unangetastet, und mehrfach vorkommende Belege
 * werden alle markiert statt nur der erste.
 */
function buildUpdatedInput(toolName, toolInput, citations) {
  const segments = collectSegments(toolName, toolInput);
  const bases = segmentBases(segments);
  const marked = segments.map((segment, i) => {
    const base = bases[i];
    const local = citations
      .filter((c) => c.start >= base && c.end <= base + segment.length)
      .map((c) => ({ ...c, start: c.start - base, end: c.end - base }));
    if (local.length === 0) return segment;
    return markSpans(segment, local, UNVERIFIED_MARKER, (msg) => {
      process.stderr.write(`[Citation-Guard] Warnung: Markierung übersprungen — ${msg}\n`);
    });
  });

  if (toolName === 'MultiEdit' && Array.isArray(toolInput.edits)) {
    return {
      ...toolInput,
      edits: toolInput.edits.map((edit, i) => ({ ...edit, new_string: marked[i] })),
    };
  }
  if (toolName === 'Edit') {
    return { ...toolInput, new_string: marked[0] };
  }
  return { ...toolInput, content: marked[0] };
}

function blockCitation(citation, reasonLine) {
  const pageInfo = citation.page == null ? '' : `, S. ${citation.page}`;
  const msg = [
    '[Citation-Guard] BLOCKIERT: Klammer-Beleg nicht verifiziert.',
    `Beleg: ${citation.raw}`,
    `Grund: ${reasonLine}`,
    `Erwartet: Paper von ${citation.family} (${citation.year}${pageInfo}) im Vault.`,
    'Bitte Quelle über vault.add_paper() einpflegen oder den Beleg korrigieren.',
    // Der Block auf der mehrdeutigen Form kann echte Prosa treffen
    // ("(Rio 1992)"). Wer das regelmässig schreibt, braucht den Schalter — und
    // muss ihn aus der Meldung erfahren, sonst bleibt nur der Bypass, der den
    // Guard für die GANZE Datei abschaltet.
    ...(citation.confidence === 'weak'
      ? ['Mehrdeutige Form "(Wort Jahr)": ACADEMIC_CITATION_AMBIGUOUS=mark setzt '
        + 'sie auf [UNVERIFIED] herab, statt sie zu blockieren.']
      : []),
    'Bypass: <!-- vault-guard: skip --> im Content ergänzen (nur für Ausnahmefälle).',
  ].join('\n');
  process.stderr.write(`${msg}\n`);
  console.log(JSON.stringify({
    decision: 'block',
    reason: msg,
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'deny',
      permissionDecisionReason: msg,
    },
  }));
  process.exit(2);
}

/**
 * Führt den Klammer-Beleg-Check aus. Blockiert (exit 2) bei sauberem Negativ,
 * markiert bei probable/unavailable mit [UNVERIFIED] (exit 0) und gibt sonst
 * die Kontrolle zurück.
 */
async function runCitationCheck(toolName, toolInput, content) {
  const occurrences = extractCitations(content);
  if (occurrences.length === 0) return;

  if (!existsSync(VAULT_DB)) {
    warnFailOpen('Citation-Guard', 'missing-db', VAULT_DB);
    return;
  }

  // Geprüft wird jede erkannte Form. Ein sauberes Negativ blockt sie auch —
  // die eindeutige (Seite, Signalwort, Co-Autor) immer, die mehrdeutige
  // "(Wort Jahr)" abhängig von ACADEMIC_CITATION_AMBIGUOUS (Default block,
  // siehe ambiguousPolicy). Ein Vault- oder Kaskaden-Treffer schweigt in beiden
  // Fällen — das hält echte Prosa aus dem Block heraus, sobald der Name
  // überhaupt als Autor existiert ("(Fukushima 2011)", "(Bologna 1999)").
  const policy = ambiguousPolicy();
  const strongKeys = new Set(
    occurrences.filter((c) => c.confidence === 'strong').map((c) => c.key),
  );
  const mayBlock = (citation) => policy === 'block' || strongKeys.has(citation.key);

  // Geprüft wird je BELEG, markiert wird je FUNDSTELLE. Derselbe Beleg dreimal
  // im Kapitel kostet einen Lookup, bekommt aber drei Marker.
  // Eindeutige Belege zuerst: unter ACADEMIC_CITATION_AMBIGUOUS=mark sind sie
  // die einzigen, aus denen ein Block folgen kann, und dürfen deshalb nicht von
  // mehrdeutigen Klammern aus dem Prüfkontingent verdrängt werden (sonst genügt
  // genug harmlose Prosa vor einem erfundenen Beleg, um den Guard auszuhebeln).
  const distinct = uniqueByKey(occurrences)
    .map((citation, index) => ({ citation, index }))
    .sort((a, b) => {
      const byStrength = Number(strongKeys.has(b.citation.key))
        - Number(strongKeys.has(a.citation.key));
      return byStrength || a.index - b.index;
    })
    .map((entry) => entry.citation);

  // Kappung: was nicht mehr ins Kontingent passt, gilt als ungeprüft — nicht
  // als geprüft-und-in-Ordnung.
  const limit = maxCitationsPerWrite();
  const checked = distinct.slice(0, limit);
  const overflow = distinct.slice(limit);
  const reasons = new Map();
  const markKeys = new Set();
  for (const citation of overflow) {
    reasons.set(citation.key, `ungeprüft (Kontingent ${limit} erschöpft)`);
    markKeys.add(citation.key);
  }
  if (overflow.length > 0) {
    process.stderr.write(
      `[Citation-Guard] Warnung: ${distinct.length} Belege überschreiten das Prüfkontingent `
      + `von ${limit} (ACADEMIC_CITATION_MAX_PER_WRITE). Die überzähligen ${overflow.length} `
      + 'werden ungeprüft mit [UNVERIFIED] markiert.\n'
    );
  }

  const vaultStatus = verifyCitationsInVault(checked);
  const unresolved = [];
  for (const citation of checked) {
    const status = vaultStatus.get(citation.key);
    // "unavailable" = Python/Vault-Fehler → fail-open wie beim Quote-Check.
    if (status === 'verified' || status === 'unavailable') continue;
    if (status === 'page-mismatch') {
      if (mayBlock(citation)) {
        blockCitation(
          citation,
          `Seite ${citation.page} liegt außerhalb der im Vault hinterlegten Seiten.`,
        );
      }
      reasons.set(citation.key, 'Seite außerhalb der Vault-Seiten (mehrdeutige Form)');
      markKeys.add(citation.key);
      continue;
    }
    unresolved.push(citation);
  }

  if (unresolved.length > 0) {
    const config = loadConfig();
    const cascade = await resolveCitations(unresolved, config);
    for (const citation of unresolved) {
      const result = cascade.get(citation.key) || { status: 'no-match', score: 0 };
      if (result.status === 'confirmed') continue;
      // Sauberes Negativ = Halluzinations-Nachweis, und der gilt unabhängig von
      // der Form: "(Fantasius 2087)" ist genau der Fall, gegen den der Guard
      // antritt. "unavailable" dagegen ist fehlende Evidenz, kein Gegenbeweis —
      // deshalb steht die Politik NUR auf "no-match".
      if (result.status === 'no-match' && mayBlock(citation)) {
        blockCitation(
          citation,
          config.enabled
            ? `Weder im Vault noch über arXiv/CrossRef/Semantic Scholar auffindbar `
              + `(bester Score ${result.score} < ${config.probableMin}).`
            : 'Nicht im Vault (externe Kaskade per ACADEMIC_CITATION_CASCADE=off deaktiviert).',
        );
      }
      // Erreichbar nur unter ACADEMIC_CITATION_AMBIGUOUS=mark: mehrdeutige Form
      // mit sauberem Negativ — nicht geblockt, aber auch nicht durchgewunken.
      const ambiguousNote =
        result.status === 'no-match' ? ', mehrdeutige Form — nicht blockiert' : '';
      reasons.set(citation.key, `${result.status} (Score ${result.score})${ambiguousNote}`);
      markKeys.add(citation.key);
    }
  }
  if (markKeys.size === 0) return;

  // Markiert wird jede Fundstelle des betroffenen Belegs; die Begründung nennt
  // ihn einmal.
  const toMark = occurrences.filter((c) => markKeys.has(c.key));
  const reason = [
    '[Citation-Guard] Belege konnten nicht abschließend verifiziert werden und '
      + 'wurden mit [UNVERIFIED] markiert:',
    ...distinct
      .filter((c) => markKeys.has(c.key))
      .map((c) => `  ${c.raw} — ${reasons.get(c.key)}`),
  ].join('\n');
  process.stderr.write(`${reason}\n`);
  console.log(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'allow',
      permissionDecisionReason: reason,
      updatedInput: buildUpdatedInput(toolName, toolInput, toMark),
    },
  }));
  process.exit(0);
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
    // Malformed stdin — fail-open
    process.exit(0);
  }

  // Schreibende Tool-Calls pruefen: Write, Edit, MultiEdit (#220)
  const toolName = input?.tool_name || input?.hook_event_name || '';
  if (!WRITE_LIKE_TOOLS.has(toolName)) {
    process.exit(0);
  }

  const toolInput = input?.tool_input || {};
  const filePath = toolInput.file_path || '';
  const content = extractContent(toolName, toolInput);

  // Pfad-Match
  if (!isProtectedPath(filePath)) {
    // Sichtbare Meldung statt stillem Durchlass (#615): eine Regex deckt nie
    // jeden Ordnernamen ab, aber ein Nutzer, der die Zeile sieht, merkt es.
    // Beschraenkt auf .md/.tex, damit irrelevante Dateitypen (.py, .json, …)
    // kein Rauschen erzeugen.
    if (isMarkdownOrTexFile(filePath)) {
      process.stderr.write(
        `[Vault-Guard] Hinweis: ${filePath} liegt außerhalb des geschützten Kapitelverzeichnisses (${chapterDirLabel()}/) — Zitate/Figures werden NICHT geprüft.\n`
      );
    }
    process.exit(0);
  }

  // Guard-schwaechende Env-Schalter sichtbar machen (Issue #519, Audit R7) —
  // vor dem Bypass-Zweig, damit auch ein Lauf, der wegen des Bypass-Markers
  // direkt terminiert, die Schalter-Nutzung noch protokolliert.
  logActiveEnvSwitches(filePath);

  // Bypass-Flag — Nutzung wird sichtbar gemacht (Issue #381: kein stiller Bypass mehr).
  if (content.includes('<!-- vault-guard: skip -->')) {
    process.stderr.write(
      `[Vault-Guard] Warnung: Bypass-Marker verwendet (${filePath || '(unbekannter Pfad)'}) — Zitate/Figures werden NICHT geprueft.\n`
    );
    logBypassUsage(filePath);
    process.exit(0);
  }

  // Quote-Spans extrahieren und gegen Vault pruefen
  const spans = extractQuoteSpans(content);
  for (const span of spans) {
    const found = lookupInVault(span);
    if (!found) {
      const truncated = span.length > 80 ? span.slice(0, 77) + '...' : span;
      const msg = [
        `[Vault-Guard] BLOCKIERT: Zitat nicht im Vault verifiziert.`,
        `Zitat: "${truncated}"`,
        `Bitte Zitat über vault.add_quote() oder den quote-extractor einpflegen.`,
      ].join('\n');
      process.stderr.write(msg + '\n');

      // Claude Code PreToolUse Block-Protokoll: JSON auf stdout + exit 2
      console.log(JSON.stringify({
        decision: 'block',
        reason: msg,
      }));
      process.exit(2);
    }
  }

  // ---------------------------------------------------------------------------
  // Figure-Referenz-Check (additiv, nach Quote-Check)
  // ---------------------------------------------------------------------------
  const figureMatches = [...content.matchAll(FIGURE_REF_PATTERN)];
  for (const match of figureMatches) {
    const refText = match[0]; // z.B. "Abb. 3.4"
    const found = lookupFigureInVault(refText);
    if (!found) {
      const msg = [
        `[Figure-Guard] BLOCKIERT: Figure-Referenz nicht im Vault verifiziert.`,
        `Referenz: "${refText}"`,
        `Bitte Figure via figure-verifier oder vault.add_figure einpflegen.`,
      ].join('\n');
      process.stderr.write(msg + '\n');
      console.log(JSON.stringify({
        decision: 'block',
        reason: msg,
      }));
      process.exit(2);
    }
  }

  // ---------------------------------------------------------------------------
  // Klammer-Beleg-Check (additiv, nach Quote- und Figure-Check; Issue #378)
  // ---------------------------------------------------------------------------
  await runCitationCheck(toolName, toolInput, content);

  process.exit(0);
}

main().catch((err) => {
  process.stderr.write(`[Vault-Guard] Fehler: ${err.message}\n`);
  process.exit(0); // fail-open bei unerwartetem Fehler
});
