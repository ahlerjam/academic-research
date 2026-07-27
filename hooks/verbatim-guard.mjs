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
 * Fail-open: Bei fehlender Python/Vault-Umgebung → Warnung + allow.
 */

import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join, dirname, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as os from 'node:os';
import { extractCitations } from './citation-parse.mjs';
import { loadConfig, resolveCitations } from './citation-cascade.mjs';

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
// Pfad-Match
// ---------------------------------------------------------------------------

/**
 * Gibt true zurueck wenn der Pfad einer Kapitel-MD- oder LaTeX-Datei entspricht.
 * Patterns: kapitel/*.md | *.tex
 */
function isProtectedPath(filePath) {
  if (!filePath) return false;
  const normalized = filePath.replace(/\\/g, '/');
  if (normalized.endsWith('.tex')) return true;
  // kapitel/<datei>.md — auch bei fuehrendem Slash oder relativen Pfaden
  if (/(?:^|\/)kapitel\/[^/]+\.md$/.test(normalized)) return true;
  return false;
}

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
function extractContent(toolName, toolInput) {
  if (toolName === 'MultiEdit' && Array.isArray(toolInput.edits)) {
    return toolInput.edits.map((e) => e?.new_string || '').join('\n');
  }
  if (toolName === 'Edit') {
    return toolInput.new_string || '';
  }
  // Write (und Fallback)
  return toolInput.content || '';
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
// Vault-Lookup via Python-Subprocess
// ---------------------------------------------------------------------------

/**
 * Sucht verbatim im Vault. Gibt true zurueck wenn ein Treffer gefunden wurde.
 * Bei fehlender Python/Vault-Umgebung: Warnung + true (fail-open).
 */
function lookupInVault(verbatim) {
  // Vault-DB muss existieren (sonst fail-open)
  if (!existsSync(VAULT_DB)) {
    process.stderr.write(
      `[Vault-Guard] Warnung: Vault-DB nicht gefunden (${VAULT_DB}). Bypass aktiv.\n`
    );
    return true; // fail-open
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
    process.stderr.write(
      `[Vault-Guard] Warnung: Vault-Lookup fehlgeschlagen (${err.message}). Bypass aktiv.\n`
    );
    return true; // fail-open
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
    process.stderr.write(
      `[Figure-Guard] Warnung: Vault-DB nicht gefunden (${VAULT_DB}). Bypass aktiv.\n`
    );
    return true; // fail-open
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
    process.stderr.write(
      `[Figure-Guard] Warnung: Figure-Lookup fehlgeschlagen (${err.message}). Bypass aktiv.\n`
    );
    return true; // fail-open
  }
}

// ---------------------------------------------------------------------------
// Klammer-Zitat-Verifikation (Issue #378)
// ---------------------------------------------------------------------------

// Obergrenze pro Write. Verhindert, dass ein sehr grosses Kapitel den
// Hook-Timeout sprengt; darüber hinausgehende Belege werden nicht geprüft.
const MAX_CITATIONS_PER_WRITE = 100;

/**
 * Prüft alle Belege in EINEM Python-Subprozess (nicht einer pro Beleg —
 * sonst dominieren Interpreter-Starts das Hook-Timeout).
 * Gibt Map raw -> "verified" | "page-mismatch" | "no-match" | "unavailable"
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
    citations.forEach((c, i) => statuses.set(c.raw, parsed[i] || 'unavailable'));
  } catch (err) {
    process.stderr.write(
      `[Citation-Guard] Warnung: Vault-Lookup fehlgeschlagen (${err.message}). Bypass aktiv.\n`
    );
    for (const c of citations) statuses.set(c.raw, 'unavailable');
  }
  return statuses;
}

/** Hängt " [UNVERIFIED]" an jeden noch unmarkierten Beleg im Text an. */
function markUnverified(text, citations) {
  let out = text || '';
  for (const citation of citations) {
    const idx = out.indexOf(citation.raw);
    if (idx === -1) continue;
    const end = idx + citation.raw.length;
    if (out.slice(end).startsWith(' [UNVERIFIED]')) continue;
    out = `${out.slice(0, end)} [UNVERIFIED]${out.slice(end)}`;
  }
  return out;
}

/**
 * Baut das vollständige updatedInput-Objekt für den Soft-Fail — je nach Tool
 * wird content (Write), new_string (Edit) oder edits[].new_string (MultiEdit)
 * markiert. Alle übrigen Felder bleiben unverändert erhalten.
 */
function buildUpdatedInput(toolName, toolInput, citations) {
  if (toolName === 'MultiEdit' && Array.isArray(toolInput.edits)) {
    return {
      ...toolInput,
      edits: toolInput.edits.map((edit) => ({
        ...edit,
        new_string: markUnverified(edit?.new_string || '', citations),
      })),
    };
  }
  if (toolName === 'Edit') {
    return { ...toolInput, new_string: markUnverified(toolInput.new_string || '', citations) };
  }
  return { ...toolInput, content: markUnverified(toolInput.content || '', citations) };
}

function blockCitation(citation, reasonLine) {
  const pageInfo = citation.page == null ? '' : `, S. ${citation.page}`;
  const msg = [
    '[Citation-Guard] BLOCKIERT: Klammer-Beleg nicht verifiziert.',
    `Beleg: ${citation.raw}`,
    `Grund: ${reasonLine}`,
    `Erwartet: Paper von ${citation.family} (${citation.year}${pageInfo}) im Vault.`,
    'Bitte Quelle über vault.add_paper() einpflegen oder den Beleg korrigieren.',
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
  const citations = extractCitations(content).slice(0, MAX_CITATIONS_PER_WRITE);
  if (citations.length === 0) return;

  if (!existsSync(VAULT_DB)) {
    process.stderr.write(
      `[Citation-Guard] Warnung: Vault-DB nicht gefunden (${VAULT_DB}). Bypass aktiv.\n`
    );
    return;
  }

  const vaultStatus = verifyCitationsInVault(citations);
  const unresolved = [];
  for (const citation of citations) {
    const status = vaultStatus.get(citation.raw);
    // "unavailable" = Python/Vault-Fehler → fail-open wie beim Quote-Check.
    if (status === 'verified' || status === 'unavailable') continue;
    if (status === 'page-mismatch') {
      blockCitation(
        citation,
        `Seite ${citation.page} liegt außerhalb der im Vault hinterlegten Seiten.`,
      );
    }
    unresolved.push(citation);
  }
  if (unresolved.length === 0) return;

  const config = loadConfig();
  const cascade = await resolveCitations(unresolved, config);
  const toMark = [];
  for (const citation of unresolved) {
    const result = cascade.get(citation.raw) || { status: 'no-match', score: 0 };
    if (result.status === 'confirmed') continue;
    if (result.status === 'no-match') {
      blockCitation(
        citation,
        config.enabled
          ? `Weder im Vault noch über arXiv/CrossRef/Semantic Scholar auffindbar `
            + `(bester Score ${result.score} < ${config.probableMin}).`
          : 'Nicht im Vault (externe Kaskade per ACADEMIC_CITATION_CASCADE=off deaktiviert).',
      );
    }
    toMark.push(citation);
  }
  if (toMark.length === 0) return;

  const reason = [
    '[Citation-Guard] Belege konnten nicht abschließend verifiziert werden und '
      + 'wurden mit [UNVERIFIED] markiert:',
    ...toMark.map((c) => `  ${c.raw} — ${cascade.get(c.raw).status} `
      + `(Score ${cascade.get(c.raw).score})`),
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
    process.exit(0);
  }

  // Bypass-Flag
  if (content.includes('<!-- vault-guard: skip -->')) {
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
        `Bypass: <!-- vault-guard: skip --> im Content ergänzen (nur für Ausnahmefälle).`,
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
        `Bypass: <!-- vault-guard: skip --> im Content ergaenzen (nur fuer Ausnahmefaelle).`,
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
