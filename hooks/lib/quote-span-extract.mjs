/**
 * hooks/lib/quote-span-extract.mjs — Zitat-Text-NAEHERUNGEN fuer den Batch-
 * Vault-Cache (Issue #844).
 *
 * KEIN Hook, keine Pruef-/Blockier-Logik: diese Datei liefert ausschliesslich
 * die Zitat-TEXTE, die ein Guard fuer einen Write voraussichtlich braucht —
 * nichts davon entscheidet ueber block/warn/mark. Die drei Guards behalten
 * ihre jeweils EIGENE, unveraenderte Extraktions-/Filterlogik (verbatim-guard:
 * sequenzielle Delimiter-Paarung + Skip-Region-Maskierung, Issue #900;
 * claim-drift-guard/context-fidelity-guard: einfache Regex-Paarung) fuer die
 * tatsaechliche Pruefung. Diese Datei existiert nur, damit
 * `hooks/lib/vault-bridge.mjs::ensureQuoteBatch()` beim ERSTEN Cache-Miss eine
 * Obermenge aller drei Bedarfe in EINEM Vault-Aufruf vorladen kann, statt
 * dass jeder Guard seinen eigenen Subprozess startet.
 *
 * Bewusst eine NAEHERUNG statt einer exakten Kopie jeder Guard-Logik: die
 * Regex-Extraktion hier ist eine sichere Obermenge fuer den Normalfall (sie
 * filtert nicht auf Skip-Regionen, Aenderungsfenster oder Beleg-Kontingente —
 * sie liefert eher zu viele Texte als zu wenige). Trifft ein Guard beim
 * Cache-Lesen einen Text, den diese Naeherung NICHT vorhergesagt hat (z. B.
 * weil die sequenzielle Paarung im verbatim-guard eine andere Paarung liefert
 * als die gierige Regex hier), fehlt genau dieser Schluessel im Cache-Eintrag
 * — der Aufrufer erkennt das (fehlender Key) und faellt fuer den GESAMTEN
 * eigenen Bedarf auf seinen eigenen `runVaultPython`-Call zurueck (siehe
 * vault-bridge.mjs::ensureQuoteBatch). Ein Fehltreffer hier kostet also
 * hoechstens die Optimierung, nie Korrektheit.
 */

import { existsSync, readFileSync } from 'node:fs';
import { isAbsolute, join } from 'node:path';

const MIN_QUOTE_LEN = 10;

/**
 * Grobe Regex-Paarung von Anfuehrungszeichen-Spans — dasselbe Muster wie
 * (unveraendert) in claim-drift-guard.mjs und context-fidelity-guard.mjs.
 * Liefert nur die inneren Texte, keine Positionen (fuer den Cache-Bedarf
 * irrelevant).
 */
export function extractQuoteTextsApprox(content) {
  const q = MIN_QUOTE_LEN;
  const patterns = [
    new RegExp(`"([^"]{${q},})"`, 'g'),
    new RegExp(`„([^“]{${q},})“`, 'g'),
    new RegExp(`«([^»]{${q},})»`, 'g'),
    new RegExp(`\`\`([^']{${q},})''`, 'g'),
  ];
  const texts = [];
  for (const r of patterns) {
    let match;
    while ((match = r.exec(content)) !== null) {
      if (match[1]) texts.push(match[1]);
    }
  }
  return texts;
}

function dedupe(arr) {
  return [...new Set(arr)];
}

function resolveFilePath(filePath) {
  if (!filePath) return '';
  if (isAbsolute(filePath)) return filePath;
  return join(process.env.CLAUDE_PROJECT_DIR || process.cwd(), filePath);
}

function readDiskContent(filePath) {
  const resolved = resolveFilePath(filePath);
  if (!resolved || !existsSync(resolved)) return null;
  try {
    return readFileSync(resolved, 'utf-8');
  } catch {
    return null;
  }
}

/** Wendet eine alt->neu-Ersetzung literal an (analog claim-drift-guard.mjs). */
function applyEditApprox(text, oldStr, newStr, replaceAll) {
  if (!oldStr || !text.includes(oldStr)) return null;
  if (replaceAll) return text.split(oldStr).join(newStr);
  const index = text.indexOf(oldStr);
  return text.slice(0, index) + newStr + text.slice(index + oldStr.length);
}

/**
 * Der vom Tool-Aufruf geschriebene Text, segmentweise zusammengefuegt —
 * dieselbe Zuordnung wie collectSegments()/authoredContent() in den drei
 * Guards (Write: content, Edit: new_string, MultiEdit: alle new_string).
 */
function writtenContent(toolName, toolInput) {
  if (toolName === 'MultiEdit' && Array.isArray(toolInput.edits)) {
    return toolInput.edits.map((e) => e?.new_string || '').join('\n');
  }
  if (toolName === 'Edit') return toolInput.new_string || '';
  return toolInput.content || '';
}

/**
 * Naeherungsweise Obermenge fuer verbatim-guard.mjs UND
 * context-fidelity-guard.mjs: beide pruefen (im Kern) Zitat-Spans aus dem
 * geschriebenen Text. context-fidelity-guard prueft exakt diese Menge (bis
 * CONTEXT_FIDELITY_MAX_QUOTES); verbatim-guard prueft eine Teilmenge davon
 * (nach Skip-Region-Maskierung).
 */
export function writtenQuoteTexts(toolName, toolInput) {
  return dedupe(extractQuoteTextsApprox(writtenContent(toolName, toolInput)));
}

/**
 * Naeherungsweise Obermenge fuer claim-drift-guard.mjs: alle Zitat-Spans im
 * rekonstruierten NEUEN Dateistand, die woertlich auch im ALTEN Dateistand
 * (auf Platte) vorkommen — ohne Aenderungsfenster- oder Beleg-Filter (das
 * grenzt claim-drift-guard.mjs selbst danach weiter ein, hier bewusst
 * grosszuegiger fuer eine sichere Obermenge).
 */
export function claimDriftQuoteTexts(toolName, toolInput) {
  const disk = readDiskContent(toolInput.file_path);
  if (disk === null) return [];

  let after;
  if (toolName === 'Write') {
    after = toolInput.content || '';
  } else if (toolName === 'Edit') {
    after = applyEditApprox(disk, toolInput.old_string, toolInput.new_string || '', toolInput.replace_all);
    if (after === null) return [];
  } else if (toolName === 'MultiEdit' && Array.isArray(toolInput.edits)) {
    after = disk;
    for (const edit of toolInput.edits) {
      const next = applyEditApprox(after, edit?.old_string, edit?.new_string || '', edit?.replace_all);
      if (next !== null) after = next;
    }
  } else {
    return [];
  }

  return dedupe(extractQuoteTextsApprox(after).filter((text) => disk.includes(text)));
}

/**
 * Vereinigt die Bedarfe aller drei Guards zu EINER deduplizierten
 * Zitat-Textmenge — das ist die Obermenge, die
 * `vault-bridge.mjs::ensureQuoteBatch()` beim ersten Cache-Miss in EINEM
 * Vault-Aufruf vorlaedt.
 */
export function unionQuoteTexts(toolName, toolInput) {
  return dedupe([
    ...writtenQuoteTexts(toolName, toolInput),
    ...claimDriftQuoteTexts(toolName, toolInput),
  ]);
}
