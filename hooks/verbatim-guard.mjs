#!/usr/bin/env node
/**
 * hooks/verbatim-guard.mjs — PreToolUse Verbatim-Validation
 *
 * Blockiert Write-Calls auf kapitel/*.md und *.tex, wenn der Content
 * Anführungszeichen-Spans enthält, die nicht im Vault verifiziert sind.
 *
 * Drei additive Prüfstufen (jede läuft erst, wenn die vorige durch ist):
 *   1. Wörtliche Zitate  — Anführungszeichen-Spans gegen quotes.verbatim,
 *      seit Issue #846 samt WORTLAUT (nicht nur Vorkommen): ein verändertes
 *      Wort blockiert mit Fundstelle und Abweichung, reine Darstellungs-
 *      varianten (Typografie, Whitespace, Ligaturen, Trennstrich, [...])
 *      passieren. Siehe academic_vault/quote_match.py.
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
 * Fail-open vs. fail-closed (drei unterschiedliche, bewusst getrennt
 * formulierte Faelle, Issue #381 + #846-Folgefix — Vermischung war Ursache
 * des ursprünglichen Bugs UND des Folgefunds):
 *   1. "DB fehlt" — erwartbar bei einem frischen Projekt ohne Vault-DB.
 *      Wortlaut: "Vault-DB nicht gefunden ... Bypass aktiv." Bleibt fail-open.
 *   2. "Lookup-Fehler bei vorhandener DB" — die DB existiert, ist aber
 *      selbst das Problem (korrupte Datei, kaputte Query). Bleibt fail-open
 *      (kein Regressionsverlust für Scope "Out", Issue #381 AC2) — ein
 *      Befund UEBER die DB, sichtbar anderer Wortlaut als Fall 1.
 *   3. "Lookup-APPARAT kaputt trotz vorhandener DB" — fehlendes Python-Modul
 *      (z. B. rapidfuzz fehlt im aktiven venv) oder kein lauffaehiger
 *      Interpreter. Das ist KEIN Befund ueber die DB, sondern "nicht
 *      prüfbar" — anders als Fall 1/2 bleibt dieser Fall NICHT fail-open,
 *      sonst wuerde ein fehlendes Paket jedes erfundene Zitat durchwinken
 *      (#846-Folgefund, siehe tests/test_review_fix_verbatim_guard.py).
 */

import { existsSync, appendFileSync, mkdirSync, chmodSync, readFileSync } from 'node:fs';
import { join, dirname, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as os from 'node:os';
import {
  extractCitations, markSpans, detectUncheckedCitationForms, maskSkipRegions,
} from './lib/citation-parse.mjs';
import { loadConfig, resolveCitations } from './lib/citation-cascade.mjs';
import { isProtectedPath, isMarkdownOrTexFile, chapterDirLabel } from './lib/protected-path.mjs';
import { runVaultPython } from './lib/vault-bridge.mjs';

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
  'ACADEMIC_CITATION_UNCHECKED_NOTICE',
  'ACADEMIC_VERBATIM_WORDING',
];
// Mindestlänge eines Zitat-Spans (in Zeichen). Muss mit den Regex-Quantifizierern übereinstimmen.
const MIN_QUOTE_LEN = 10;
// Zeitbudget je Vault-Aufruf. hooks.json gibt dem Hook insgesamt 30 s, und ein
// Write loest hoechstens ZWEI Aufrufe aus: einen gebuendelten fuer alle
// Quote-Spans und Figure-Referenzen (lookupBatch) und einen fuer alle
// Klammer-Belege (verifyCitationsInVault). 2 x 10 s = 20 s lassen dem
// Node-Start und der externen Beleg-Kaskade noch Luft unter den 30 s.
// Vorher lief ein eigener Subprozess JE Span — vier Zitate plus zwei
// Abbildungsverweise kamen so auf bis zu 48 s und wurden vom Hook-Timeout
// abgeschossen.
const VAULT_LOOKUP_BUDGET_MS = 10000;
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
 * Sucht sequenziell Delimiter-PAARE (nicht Vorkommen) eines einzelnen
 * Anfuehrungszeichen-Typs: ab ``pos`` das naechste oeffnende Delimiter, dann
 * ab dessen Ende das naechste SCHLIESSENDE Delimiter — nie umgekehrt gesucht,
 * nie ueber ein zu kurzes Paar hinweg weitergesucht. Erst NACH der Paarung
 * wird auf ``minLen`` gefiltert (Post-Filter, nicht Teil der Suche selbst),
 * und in JEDEM Fall (Paar zu kurz oder nicht) geht es ab dem Ende des
 * gefundenen Paares weiter.
 *
 * Das ist der Kern des Issue-#900-Fixes: die fruehere gierige Regex
 * (`/"([^"]{10,})"/g`) sprang bei einem zu kurzen Paar einfach zum naechsten
 * "-Zeichen weiter und paarte damit das SCHLIESSENDE Zeichen des einen mit
 * dem OEFFNENDEN des naechsten kurzen Begriffs — der Fliesstext dazwischen
 * wurde dann faelschlich als Zitat gelesen. Der sequenzielle Scanner bindet
 * jedes Oeffnen an genau das naechste Schliessen danach, unabhaengig von der
 * Laenge, und verwirft nur zu kurze PAARE — nie eine falsche Paarung.
 *
 * Wenn nach einem oeffnenden Delimiter kein schliessendes mehr folgt, gibt es
 * fuer diesen Typ keine weiteren Paare mehr (das schliessende Delimiter kommt
 * im restlichen Text nicht mehr vor) — der Scan bricht dann ab.
 */
function scanDelimiterPairs(content, open, close, minLen) {
  const spans = [];
  let pos = 0;
  while (true) {
    const openIdx = content.indexOf(open, pos);
    if (openIdx === -1) break;
    const innerStart = openIdx + open.length;
    const closeIdx = content.indexOf(close, innerStart);
    if (closeIdx === -1) break;
    const text = content.slice(innerStart, closeIdx);
    if (text.length >= minLen) {
      spans.push({ start: innerStart, end: closeIdx, text });
    }
    pos = closeIdx + close.length;
  }
  return spans;
}

/**
 * Extrahiert Anführungszeichen-Spans aus dem Content.
 * Unterstuetzte Typen:
 *   "…"   — ASCII double quotes
 *   „…"   — Deutsche Anführungszeichen
 *   «…»   — Guillemets
 *   ``…'' — LaTeX
 *
 * Mindestlänge: MIN_QUOTE_LEN Zeichen (innerer Text). Jeder Delimiter-Typ wird
 * unabhaengig von den anderen sequenziell gepaart (scanDelimiterPairs), nicht
 * per gieriger Regex — siehe dort fuer den Grund (Issue #900).
 * Gibt Array von ``{start, end, text}`` zurueck — ``text`` ist der innere Text,
 * ``start``/``end`` seine Offsets IM UEBERGEBENEN Content.
 *
 * Gelesen wird immer der ORIGINALINHALT, nie eine maskierte Fassung: der
 * nachzuschlagende Text muss der echte sein (ein Zitat mit Inline-Code oder
 * LaTeX-Makro ginge sonst mit Leerzeichen an der Makro-Stelle in den Vault und
 * traefe nicht), und die Maskierung frisst sonst auch die Zitat-Grenzen selbst
 * — ``\`\`…''`` beginnt mit zwei Backticks, die als leerer Inline-Code
 * maskiert werden. Welche Spans uebersprungen werden, entscheidet stattdessen
 * spanIsMasked() weiter unten.
 */
function extractQuoteSpans(content) {
  const q = MIN_QUOTE_LEN;
  const delimiters = [
    { open: '"', close: '"' },   // ASCII "…"
    { open: '„', close: '“' },  // Deutsche „…" (U+201E…U+201C)
    { open: '«', close: '»' },  // Guillemets «…» (U+00AB…U+00BB)
    { open: '``', close: "''" }, // LaTeX ``…''
  ];
  const spans = [];
  for (const { open, close } of delimiters) {
    spans.push(...scanDelimiterPairs(content, open, close, q));
  }
  return spans;
}

/**
 * True, wenn ``span`` mit MINDESTENS einem der ``quoteSpans`` ueberlappt
 * (halboffenes Intervall [start, end)). Jede Ueberlappung genuegt — auch eine
 * Teilueberlappung, denn ein Marker, der nur an EINER Stelle innerhalb des
 * Zitats landet, zerreisst den geprueften Wortlaut trotzdem (Issue #900).
 */
function overlapsAnyQuoteSpan(span, quoteSpans) {
  return quoteSpans.some((q) => span.start < q.end && span.end > q.start);
}

/**
 * True, wenn im Bereich [start, end) KEIN sichtbares Zeichen die Maskierung
 * ueberlebt hat — der Span liegt also vollstaendig in einer Skip-Region
 * (Code-Fence, Inline-Code, LaTeX-Makro, Kommentar, Literaturverzeichnis).
 *
 * ``maskSkipRegions()`` ist laengenerhaltend (ersetzt jede Region durch
 * Leerzeichen gleicher Laenge), deshalb sind die Offsets aus dem Original im
 * maskierten Text gueltig — dieselbe Annahme wie in
 * citation-parse.mjs::spansMaskedRegion().
 *
 * Bewusst "vollstaendig" statt "ueberlappend": ein Zitat, das ein Makro oder
 * Inline-Code ENTHAELT, bleibt ein Zitat und muss geprueft werden. Nur was
 * ganz in einer Skip-Region steht (Quellentitel im Literaturverzeichnis,
 * Beispiel-String im Code-Fence), wird uebersprungen.
 */
function spanIsMasked(content, masked, start, end) {
  for (let i = start; i < end; i += 1) {
    const ch = content[i];
    if (ch === undefined || /\s/u.test(ch)) continue;
    if (masked[i] !== ' ') return false;
  }
  return true;
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
// Fail-CLOSED bei kaputtem Lookup-APPARAT (#846-Folgefund)
// ---------------------------------------------------------------------------

/**
 * Erkennt, ob eine Fehlermeldung den Lookup-APPARAT selbst betrifft
 * (fehlendes Python-Modul, z. B. rapidfuzz, oder ein kompletter
 * Interpreter-Ausfall) statt eine Eigenschaft der Vault-DB (korrupte Datei,
 * kaputte Query). Nur diese Klasse darf NICHT fail-open behandelt werden:
 * ein fehlendes Paket bedeutet "nicht prüfbar", nicht "kein Befund" — sonst
 * würde z. B. ein venv ohne rapidfuzz jedes erfundene Zitat durchwinken
 * (CI-Regression aus PR #939, Issue #846).
 *
 * Bewusst eng gefasst (nur ModuleNotFoundError/ImportError): eine korrupte
 * DB wirft andere Exception-Typen (sqlite3.DatabaseError etc.) und bleibt
 * damit unveraendert im fail-open-Pfad (Issue #381 AC2,
 * tests/test_issue_381_verbatim_guard_failopen.py).
 */
function isApparatusError(detail) {
  return /^(ModuleNotFoundError|ImportError)\b/.test(String(detail ?? ''));
}

/**
 * Wie warnFailOpen(), aber fail-CLOSED: schreibt eine BLOCKIERT-Meldung
 * nach stderr und gibt false zurueck (kein Bypass). Fuer den Fall, dass der
 * Lookup-Apparat selbst kaputt ist (siehe isApparatusError) — die DB mag
 * vorhanden und intakt sein, aber der Prozess kann sie nicht befragen.
 */
function warnFailClosedApparatus(context, detail) {
  process.stderr.write(
    `[${context}] BLOCKIERT: Lookup-Apparat nicht einsatzbereit trotz vorhandener DB `
    + `(${detail}). Kein Bypass — gilt als NICHT geprueft (venv/Abhaengigkeiten pruefen).\n`
  );
  return false; // fail-closed
}

// ---------------------------------------------------------------------------
// Vault-/Figure-Lookup via EINEN Python-Subprozess (gebuendelt)
// ---------------------------------------------------------------------------

/**
 * Schlaegt ALLE Quote-Spans und ALLE Figure-Referenzen eines Writes in EINEM
 * Subprozess nach (Muster aus claim-drift-guard.mjs::PY_LOOKUP). Ein
 * Interpreterstart je Aufruf statt einem je Span — sonst summieren sich
 * Interpreterstart + academic_vault-Import ueber das Hook-Timeout hinaus.
 *
 * Jeder Eintrag wird EINZELN in try/except gekapselt: faellt ein Lookup aus,
 * betrifft das genau diesen Eintrag (``{"error": ...}``) und nicht den ganzen
 * Batch — das entspricht dem frueheren Verhalten, bei dem ein Subprozess je
 * Span lief und nur dieser eine fail-open wurde. Fuer die Zitate uebernimmt
 * ``match_quote_wording()`` diese Kapselung je Kandidat selbst; scheitert
 * schon der gemeinsame Snapshot (korrupte DB), traegt jeder Kandidat denselben
 * Fehler — derselbe fail-open-Ausgang wie zuvor.
 *
 * Zitate liefern seit Issue #846 KEIN Boolean mehr, sondern ein Statusobjekt
 * (exact/normalized/ellipsis/deviation/absent). Figuren bleiben Boolean —
 * ``find_figure_by_caption`` ist unveraendert.
 */
const PY_BATCH_LOOKUP = [
  'import sys, json',
  `sys.path.insert(0, ${JSON.stringify(VAULT_SRC)})`,
  'from academic_vault.server import match_quote_wording, find_figure_by_caption',
  'db_path = sys.argv[1]',
  'payload = json.loads(sys.argv[2])',
  'out = {"quotes": [], "figures": []}',
  'try:',
  '    out["quotes"] = match_quote_wording(',
  '        db_path, payload["quotes"], wording_limit=payload.get("wording_limit")',
  '    )',
  'except Exception as exc:',
  '    detail = "%s: %s" % (type(exc).__name__, exc)',
  '    out["quotes"] = [{"error": detail} for _ in payload["quotes"]]',
  'for needle in payload["figures"]:',
  '    try:',
  '        out["figures"].append(bool(find_figure_by_caption(db_path, needle)))',
  '    except Exception as exc:',
  '        out["figures"].append({"error": "%s: %s" % (type(exc).__name__, exc)})',
  'print(json.dumps(out))',
].join('\n');

/**
 * Deutet die Ergebnisliste EINER Sorte (Quotes oder Figures) aus dem Batch.
 * ``true`` heisst "nicht blockieren" — entweder Treffer im Vault oder
 * fail-open nach einem Fehler. Fehler werden je Eintrag gemeldet, damit ein
 * einzelner kaputter Lookup nicht die uebrigen Ergebnisse entwertet und
 * umgekehrt kein Eintrag stillschweigend als verifiziert gilt.
 */
function readBatchFlags(values, expected, context) {
  if (expected === 0) return [];
  if (!Array.isArray(values) || values.length !== expected) {
    warnFailOpen(context, 'lookup-error', `unerwartete Antwortform (erwartet ${expected} Ergebnisse)`);
    return Array.from({ length: expected }, () => true);
  }
  return values.map((value) => {
    if (typeof value === 'boolean') return value;
    const detail = value?.error || 'unerwarteter Ergebniswert';
    // Fall 3: Lookup-Apparat kaputt (fehlendes Modul) — fail-CLOSED, kein Bypass.
    if (isApparatusError(detail)) return warnFailClosedApparatus(context, detail);
    // Fall 2: DB vorhanden, aber Exception fuer GENAU diesen Eintrag.
    return warnFailOpen(context, 'lookup-error', detail);
  });
}

/**
 * Deutet die Zitat-Ergebnisse aus dem Batch (Issue #846).
 *
 * Anders als bei den Figuren ist ein Zitat-Ergebnis ein Statusobjekt, kein
 * Boolean. Nicht deutbare Eintraege (``{error}``, fehlende/kaputte Antwortform)
 * werden entweder zu ``{status: 'open'}`` (fail-open, Fall 2 — DB-seitiger
 * Fehler) oder zu ``{status: 'unverifiable'}`` (fail-CLOSED, Fall 3 —
 * Lookup-Apparat kaputt, siehe isApparatusError), je nach Fehlerart. Beide
 * Faelle loggen dieselbe Art Warnung wie bisher, damit ein kaputter Lookup
 * nie stillschweigend als "verifiziert" gilt und die uebrigen Ergebnisse
 * nicht entwertet.
 */
function readQuoteResults(values, expected, context) {
  if (expected === 0) return [];
  if (!Array.isArray(values) || values.length !== expected) {
    warnFailOpen(context, 'lookup-error', `unerwartete Antwortform (erwartet ${expected} Ergebnisse)`);
    return Array.from({ length: expected }, () => ({ status: 'open' }));
  }
  return values.map((value) => {
    if (value && typeof value === 'object' && typeof value.status === 'string') return value;
    const detail = value?.error || 'unerwarteter Ergebniswert';
    if (isApparatusError(detail)) {
      warnFailClosedApparatus(context, detail);
      return { status: 'unverifiable', detail };
    }
    warnFailOpen(context, 'lookup-error', detail);
    return { status: 'open' };
  });
}

/**
 * Sucht alle Zitat-Texte und Figure-Referenzen im Vault.
 * Rueckgabe: ``{quotes: object[], figures: boolean[]}`` in Eingabereihenfolge.
 * Bei den Figuren heisst ``true`` "kein Block" (Treffer oder fail-open), bei
 * den Zitaten entscheidet der Status (siehe readQuoteResults).
 *
 * ``wordingLimit`` ist das Pruefkontingent fuer die teure Wortlaut-Zuordnung
 * (Issue #846) — ueberzaehlige Spans laufen nur noch durch den billigen
 * Bestands-Abgleich und bleiben im Zweifel ``absent`` (Block), nie still
 * durchgewunken.
 */
function lookupBatch(spanTexts, figureRefs, wordingLimit) {
  const allOpen = () => ({
    quotes: spanTexts.map(() => ({ status: 'open' })),
    figures: figureRefs.map(() => true),
  });
  if (spanTexts.length === 0 && figureRefs.length === 0) return allOpen();

  // Vault-DB muss existieren (sonst fail-open, Fall 1: "DB fehlt").
  // Beide Kontexte melden getrennt — der Wortlaut je Guard ist gepinnt
  // (Issue #381, tests/test_verbatim_figure_guard.py).
  if (!existsSync(VAULT_DB)) {
    if (spanTexts.length > 0) warnFailOpen('Vault-Guard', 'missing-db', VAULT_DB);
    if (figureRefs.length > 0) warnFailOpen('Figure-Guard', 'missing-db', VAULT_DB);
    return allOpen();
  }

  const payload = JSON.stringify({
    quotes: spanTexts,
    figures: figureRefs,
    wording_limit: wordingLimit ?? null,
  });
  const output = runVaultPython(PY_BATCH_LOOKUP, [VAULT_DB, payload], {
    timeout: VAULT_LOOKUP_BUDGET_MS,
    budget: VAULT_LOOKUP_BUDGET_MS,
    label: 'Vault-Guard',
  });
  if (output === null) {
    // KEIN Interpreter der Kaskade (runVaultPython) konnte ueberhaupt
    // starten (Details bereits auf stderr protokolliert) — das ist der
    // Apparat-kaputt-Fall in Reinform ("kaputter Interpreter", Fall 3):
    // fail-CLOSED statt Bypass, sonst wuerde ein kaputtes PATH-python3
    // (o. ae.) jedes erfundene Zitat durchwinken (#846-Folgefund).
    const detail = 'kein Interpreter konnte den Vault oeffnen';
    if (spanTexts.length > 0) warnFailClosedApparatus('Vault-Guard', detail);
    if (figureRefs.length > 0) warnFailClosedApparatus('Figure-Guard', detail);
    return {
      quotes: spanTexts.map(() => ({ status: 'unverifiable', detail })),
      figures: figureRefs.map(() => false),
    };
  }

  let parsed;
  try {
    parsed = JSON.parse(output.trim());
  } catch (err) {
    if (spanTexts.length > 0) warnFailOpen('Vault-Guard', 'lookup-error', err.message);
    if (figureRefs.length > 0) warnFailOpen('Figure-Guard', 'lookup-error', err.message);
    return allOpen();
  }
  return {
    quotes: readQuoteResults(parsed?.quotes, spanTexts.length, 'Vault-Guard'),
    figures: readBatchFlags(parsed?.figures, figureRefs.length, 'Figure-Guard'),
  };
}

// ---------------------------------------------------------------------------
// Wortlaut-Pruefung woertlicher Zitate (Issue #846)
// ---------------------------------------------------------------------------

/**
 * Status, die den Zitat-Check passieren lassen:
 *   - ``exact``/``normalized``/``ellipsis`` — Wortlaut belegt (ggf. nur
 *     typografisch/durch Auslassung abweichend);
 *   - ``open`` — fail-open, weil DIE DB (nicht der Apparat) fuer diesen
 *     Eintrag scheiterte (Fall 1/2, siehe warnFailOpen).
 * ``deviation`` und ``absent`` fuehren zur Meldung (siehe main()).
 * ``unverifiable`` (Fall 3, Lookup-Apparat kaputt, #846-Folgefund) ist
 * BEWUSST NICHT hier drin — es blockiert wie ``absent``, aber mit eigener
 * Meldung (siehe main()).
 */
const PASSING_QUOTE_STATUSES = new Set(['exact', 'normalized', 'ellipsis', 'open']);

/**
 * Reaktion auf einen abweichenden Wortlaut: ``"block"`` (Default) oder
 * ``"report"``. ``report`` ist eine ABSCHWAECHUNG des Guards und deshalb in
 * ENV_SWITCH_NAMES protokolliert (Issue #519) — der Default bleibt
 * blockierend, damit aus #846 kein stiller Rueckschritt wird.
 */
function wordingPolicy(env = process.env) {
  return (env.ACADEMIC_VERBATIM_WORDING || 'block').toLowerCase() === 'report'
    ? 'report'
    : 'block';
}

/** 1-basierte Zeile/Spalte eines Zeichenoffsets im Pruef-Text. */
function locationOf(content, index) {
  const before = content.slice(0, Math.max(0, index));
  const line = before.split('\n').length;
  const column = before.length - (before.lastIndexOf('\n') + 1) + 1;
  return { line, column };
}

/** Kuerzt lange Wortlaute fuer die Meldung (identische Grenze wie beim Bestandsblock). */
function shorten(text, max = 120) {
  const value = String(text ?? '');
  return value.length > max ? `${value.slice(0, max - 3)}...` : value;
}

/**
 * Die abweichenden Woerter als lesbare Zeilen. ``kind`` kommt aus
 * academic_vault/quote_match.py::_word_diff.
 */
function formatWordDiff(diff) {
  return (diff || []).map((entry) => {
    const chapter = shorten(entry.chapter, 60);
    const vault = shorten(entry.vault, 60);
    if (entry.kind === 'missing') return `  im Kapitel ausgelassen: "${vault}"`;
    if (entry.kind === 'added') return `  im Kapitel ergaenzt: "${chapter}"`;
    return `  "${chapter}" statt "${vault}"`;
  });
}

/**
 * Meldung fuer einen abweichenden Wortlaut — mit Fundstelle (Datei + Zeile:Spalte),
 * beiden Wortlauten und den benannten Abweichungen (Issue #846, AC1).
 */
function wordingDeviationMessage(span, result, filePath, content, blocking) {
  const { line, column } = locationOf(content, span.start);
  const quoteRef = result.quote_id ? ` (Quote ${result.quote_id})` : '';
  return [
    blocking
      ? '[Vault-Guard] BLOCKIERT: Wortlaut weicht vom Vault-Snapshot ab.'
      : '[Vault-Guard] Warnung: Wortlaut weicht vom Vault-Snapshot ab (nicht blockiert).',
    `Fundstelle: ${filePath || '(unbekannter Pfad)'}:${line}:${column}`,
    `Kapitel: "${shorten(result.candidate || span.text)}"`,
    `Vault:   "${shorten(result.vault_verbatim)}"${quoteRef}`,
    'Abweichung:',
    ...formatWordDiff(result.diff),
    'Bitte den Wortlaut an den Vault-Snapshot angleichen — oder das Zitat neu '
      + 'einpflegen (vault.add_quote), wenn der Vault-Eintrag falsch ist.',
    ...(blocking
      ? ['Abschwaechung: ACADEMIC_VERBATIM_WORDING=report meldet die Abweichung, '
        + 'statt zu blockieren.']
      : []),
  ].join('\n');
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
 * sonst dominieren Interpreter-Starts das Hook-Timeout) über
 * `server.verify_citations()`, das sich innerhalb des Subprozesses zusätzlich
 * einen einzigen Papers-Tabellen-Scan für alle Belege teilt statt einen je
 * Beleg (Issue #501).
 * Gibt Map key -> Ergebnis-Objekt ``{status, paper_ids, vault_pages?,
 * vault_ranges?}`` zurück (``status`` eine von "verified" | "page-mismatch" |
 * "no-match" | "unavailable"; ``vault_pages``/``vault_ranges`` nur bei
 * "page-mismatch" gesetzt — die im Vault hinterlegten Seiten für die
 * Blockmeldung, Issue #724). "unavailable" bedeutet Python/Vault-Fehler
 * (fail-open).
 */
function verifyCitationsInVault(citations) {
  const statuses = new Map();
  const pyCode = [
    'import sys, json',
    `sys.path.insert(0, ${JSON.stringify(VAULT_SRC)})`,
    'from academic_vault.server import verify_citations',
    'items = json.loads(sys.argv[2])',
    'results = verify_citations(sys.argv[1], items)',
    'print(json.dumps(results))',
  ].join('; ');

  const payload = JSON.stringify(
    citations.map((c) => ({
      family: c.family, year: c.year, page: c.page, page_end: c.pageEnd ?? null,
    })),
  );

  const output = runVaultPython(pyCode, [VAULT_DB, payload], {
    budget: VAULT_LOOKUP_BUDGET_MS,
    label: 'Citation-Guard',
  });
  if (output === null) {
    warnFailOpen('Citation-Guard', 'lookup-error', 'kein Interpreter konnte den Vault oeffnen');
    for (const c of citations) statuses.set(c.key, { status: 'unavailable' });
    return statuses;
  }
  try {
    const parsed = JSON.parse(output.trim());
    citations.forEach((c, i) => statuses.set(c.key, parsed[i] || { status: 'unavailable' }));
  } catch (err) {
    warnFailOpen('Citation-Guard', 'lookup-error', err.message);
    for (const c of citations) statuses.set(c.key, { status: 'unavailable' });
  }
  return statuses;
}

const UNVERIFIED_MARKER = ' [UNVERIFIED]';

/** Beleg-Seite als Text: "45" oder bei Bereich "45–47". */
function pageInfoText(citation) {
  return citation.pageEnd != null ? `${citation.page}–${citation.pageEnd}` : `${citation.page}`;
}

/**
 * Die im Vault hinterlegten Seiten als lesbarer Text für die Blockmeldung
 * (Issue #724, AC1: "nennt beide Werte"). ``entry`` ist das Ergebnis-Objekt
 * aus :func:`verifyCitationsInVault` für den Status "page-mismatch".
 */
function formatVaultPagesText(entry) {
  const parts = [];
  for (const range of entry?.vault_ranges || []) {
    const [first, last] = range;
    parts.push(first === last ? `S. ${first}` : `S. ${first}–${last}`);
  }
  const samples = entry?.vault_pages || [];
  if (samples.length > 0) parts.push(`Zitat-Fundstelle(n) S. ${samples.join(', ')}`);
  return parts.length > 0 ? parts.join('; ') : 'keine bekannten Seiten';
}

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
  const pageInfo = citation.page == null ? '' : `, S. ${pageInfoText(citation)}`;
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

/** Schalter fuer den Ungeprueft-Hinweis (Issue #740, AC7); Default "on". */
function uncheckedNoticeEnabled(env = process.env) {
  return (env.ACADEMIC_CITATION_UNCHECKED_NOTICE || 'on').toLowerCase() !== 'off';
}

/**
 * Meldet Belege in nicht geprüften Formen (LaTeX-/Markdown-Fußnote,
 * numerischer Verweis) einmal je Write auf stderr — nicht blockierend,
 * unabhängig davon, ob ``extractCitations()`` überhaupt etwas findet
 * (Issue #740, AC6/AC7: „nicht unterstützt heißt nicht stillschweigend").
 */
function reportUncheckedCitationForms(content, filePath, env = process.env) {
  if (!uncheckedNoticeEnabled(env)) return;
  const findings = detectUncheckedCitationForms(content);
  if (findings.length === 0) return;
  const kinds = [...new Set(findings.map((f) => f.kind))].join(', ');
  process.stderr.write(
    `[Citation-Guard] Hinweis: ${findings.length} Beleg(e) in ungeprüfter Form `
    + `(${kinds}) in ${filePath || '(unbekannter Pfad)'} — werden NICHT gegen den Vault `
    + `geprüft. Beispiel: ${findings[0].raw}. Abstellen: `
    + 'ACADEMIC_CITATION_UNCHECKED_NOTICE=off.\n'
  );
}

/**
 * Führt den Klammer-Beleg-Check aus. Blockiert (exit 2) bei sauberem Negativ,
 * markiert bei probable/unavailable mit [UNVERIFIED] (exit 0) und gibt sonst
 * die Kontrolle zurück.
 *
 * ``quoteSpans`` (Issue #900): Anführungszeichen-Spans aus derselben
 * extractQuoteSpans()-Erkennung, die main() bereits für den Zitat-Check
 * gebildet hat. Ein Klammerbeleg, dessen Fundstelle in einem dieser Spans
 * liegt, wird weiterhin GEMELDET (stderr-Grund), aber NICHT markiert — der
 * Marker würde sonst mitten in geprüftem Wortlaut landen und ihn verändern.
 */
async function runCitationCheck(toolName, toolInput, content, quoteSpans = []) {
  // Unabhaengig vom occurrences.length === 0-Early-Return unten (Issue #740,
  // Plan Task 7): sonst bliebe ausgerechnet der Fall aus dem Issue-Text —
  // ein woertliches Zitat mit AUSSCHLIESSLICH einer ungeprueften Beleg-Form —
  // ohne jede Rueckmeldung.
  reportUncheckedCitationForms(content, toolInput.file_path);

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
    const entry = vaultStatus.get(citation.key);
    const status = entry?.status;
    // "unavailable" = Python/Vault-Fehler → fail-open wie beim Quote-Check.
    if (status === 'verified' || status === 'unavailable') continue;
    if (status === 'page-mismatch') {
      if (mayBlock(citation)) {
        blockCitation(
          citation,
          `Seite ${pageInfoText(citation)} liegt außerhalb der im Vault hinterlegten `
          + `Seite(n) (${formatVaultPagesText(entry)}).`,
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

  // Markiert wird jede Fundstelle des betroffenen Belegs — AUSSER sie liegt in
  // einem Anführungszeichen-Span (Issue #900): dort würde der Marker in
  // geprüften Wortlaut eingreifen. Die Begründung nennt den Beleg trotzdem
  // einmal (reason unten filtert nur auf markKeys, nicht auf Quote-Overlap).
  const toMark = occurrences.filter(
    (c) => markKeys.has(c.key) && !overlapsAnyQuoteSpan(c, quoteSpans),
  );
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

  // Gesucht wird im ORIGINALINHALT, uebersprungen werden nur ganze Fundstellen,
  // die in einer Skip-Region liegen. Die Maskierung entscheidet also, WELCHE
  // Fundstellen geprueft werden — nicht, WELCHER TEXT nachgeschlagen wird:
  //   - ohne den Skip blockte ein Quellentitel im eigenen Literaturverzeichnis
  //     ("Mueller, T. (2021). \"Digitalisierung ...\". Springer.") oder ein
  //     Beispiel-String im Code-Fence faelschlich (Finding 4);
  //   - wuerde umgekehrt auf dem maskierten Text GESUCHT, ginge ein Zitat mit
  //     Inline-Code oder LaTeX-Makro mit Leerzeichen an der Makro-Stelle in den
  //     Vault-Lookup und blockte ebenfalls faelschlich — und ein
  //     LaTeX-Zitat ``…'' waere gar nicht mehr auffindbar, weil seine beiden
  //     oeffnenden Backticks als leerer Inline-Code maskiert werden.
  // maskSkipRegions() ist laengenerhaltend, deshalb sind die Offsets aus dem
  // Original im maskierten Text gueltig (siehe spanIsMasked()).
  const maskedContent = maskSkipRegions(content);

  const spans = extractQuoteSpans(content)
    .filter((span) => !spanIsMasked(content, maskedContent, span.start, span.end));
  const figures = [...content.matchAll(FIGURE_REF_PATTERN)]
    .map((match) => ({
      text: match[0], // z.B. "Abb. 3.4"
      start: match.index,
      end: match.index + match[0].length,
    }))
    .filter((ref) => !spanIsMasked(content, maskedContent, ref.start, ref.end));

  // Pruefkontingent (Issue #846, AC4): dieselbe Obergrenze wie fuer die
  // Klammer-Belege. Ueberzaehlige Spans verlieren nur die teure
  // Wortlaut-Zuordnung, nicht die Pruefung selbst — sie bleiben im Zweifel
  // "nicht im Vault" und blocken. Ein stiller Durchlass waere ein Loch im
  // Guard (genug Zitate vor einem erfundenen, und das erfundene passiert).
  const wordingLimit = maxCitationsPerWrite();
  if (spans.length > wordingLimit) {
    process.stderr.write(
      `[Vault-Guard] Warnung: ${spans.length} Zitat-Spans überschreiten das Prüfkontingent `
      + `von ${wordingLimit} (ACADEMIC_CITATION_MAX_PER_WRITE). Für die überzähligen `
      + `${spans.length - wordingLimit} läuft nur der Bestands-Abgleich, keine `
      + 'Wortlaut-Zuordnung.\n'
    );
  }

  // EIN Subprozess fuer alle Spans und Referenzen zusammen (Regression aus dem
  // ersten Fix: je Span ein eigener Interpreterstart sprengte das 30-s-Timeout).
  const lookups = lookupBatch(
    spans.map((s) => s.text), figures.map((f) => f.text), wordingLimit,
  );

  const wordingMode = wordingPolicy();
  for (let i = 0; i < spans.length; i += 1) {
    const span = spans[i];
    const result = lookups.quotes[i] || { status: 'open' };

    if (PASSING_QUOTE_STATUSES.has(result.status)) {
      // Reiner Gross-/Kleinschreibungs-Unterschied: sichtbar, aber kein Block
      // (die alte LIKE-Suche war fuer ASCII ebenfalls case-insensitiv — ein
      // Block waere eine neue, unangekuendigte Blockklasse gewesen).
      if (result.case_only) {
        const { line, column } = locationOf(content, span.start);
        process.stderr.write(
          `[Vault-Guard] Hinweis: Zitat weicht nur in der Groß-/Kleinschreibung vom `
          + `Vault-Snapshot ab (${filePath || '(unbekannter Pfad)'}:${line}:${column}).\n`
        );
      }
      continue;
    }

    if (result.status === 'deviation') {
      const blocking = wordingMode === 'block';
      const msg = wordingDeviationMessage(span, result, filePath, content, blocking);
      process.stderr.write(`${msg}\n`);
      if (!blocking) continue;
      console.log(JSON.stringify({ decision: 'block', reason: msg }));
      process.exit(2);
    }

    if (result.status === 'unverifiable') {
      // Lookup-Apparat kaputt (Fall 3, #846-Folgefund) — KEIN Bestandsbefund
      // ("nicht im Vault"), sondern ein Werkzeugausfall. Blockiert IMMER,
      // unabhaengig von wordingMode: ACADEMIC_VERBATIM_WORDING=report
      // schwaecht nur die Wortlaut-STRENGE ab, nicht die Frage, ob ueberhaupt
      // geprueft werden konnte.
      const truncated = span.text.length > 80 ? span.text.slice(0, 77) + '...' : span.text;
      const msg = [
        `[Vault-Guard] BLOCKIERT: Zitat NICHT prüfbar — Lookup-Apparat kaputt trotz vorhandener Vault-DB.`,
        `Zitat: "${truncated}"`,
        `Ursache: ${result.detail || 'unbekannt'}`,
        `Kein Bestandsbefund — die Prüfumgebung (Python-venv/Abhängigkeiten) reparieren `
          + `und den Write erneut versuchen. Bypass: <!-- vault-guard: skip --> nur für Ausnahmefälle.`,
      ].join('\n');
      process.stderr.write(msg + '\n');
      console.log(JSON.stringify({ decision: 'block', reason: msg }));
      process.exit(2);
    }

    // status === 'absent' — Bestandsbefund, Wortlaut des Blocks unveraendert.
    const truncated = span.text.length > 80 ? span.text.slice(0, 77) + '...' : span.text;
    const msg = [
      `[Vault-Guard] BLOCKIERT: Zitat nicht im Vault verifiziert.`,
      `Zitat: "${truncated}"`,
      ...(result.quota_capped
        ? ['Hinweis: Der Wortlaut-Abgleich lief für dieses Zitat nicht — Prüfkontingent '
          + `${wordingLimit} erschöpft (ACADEMIC_CITATION_MAX_PER_WRITE).`]
        : []),
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

  // ---------------------------------------------------------------------------
  // Figure-Referenz-Check (additiv, nach Quote-Check)
  // ---------------------------------------------------------------------------
  figures.forEach((ref, i) => {
    if (lookups.figures[i]) return;
    const msg = [
      `[Figure-Guard] BLOCKIERT: Figure-Referenz nicht im Vault verifiziert.`,
      `Referenz: "${ref.text}"`,
      `Bitte Figure via figure-verifier oder vault.add_figure einpflegen.`,
    ].join('\n');
    process.stderr.write(msg + '\n');
    console.log(JSON.stringify({
      decision: 'block',
      reason: msg,
    }));
    process.exit(2);
  });

  // ---------------------------------------------------------------------------
  // Klammer-Beleg-Check (additiv, nach Quote- und Figure-Check; Issue #378)
  // ---------------------------------------------------------------------------
  await runCitationCheck(toolName, toolInput, content, spans);

  process.exit(0);
}

main().catch((err) => {
  process.stderr.write(`[Vault-Guard] Fehler: ${err.message}\n`);
  process.exit(0); // fail-open bei unerwartetem Fehler
});
