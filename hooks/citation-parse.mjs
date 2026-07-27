/**
 * hooks/citation-parse.mjs — Extraktion von Klammer-/Paraphrase-Belegen (Issue #378)
 *
 * Reine Funktionen ohne Seiteneffekte: Kapiteltext rein, normalisierte
 * Beleg-Objekte raus. Wird von hooks/verbatim-guard.mjs importiert.
 *
 * Erkannte Formen:
 *   (Müller 2021, S. 45)      (Müller/Schmidt 2019)     (Müller u. a. 2021, S. 45–47)
 *   (vgl. Müller 2021: 45)    vgl. Schmidt 2019         zit. nach Weber 2018, S. 7
 *
 * Bewusst NICHT erkannt (False-Positive-Schutz, siehe SKIP-Regeln unten):
 *   Code-Fences und Inline-Code, LaTeX-Makros (\cite{...}, \ref{...}),
 *   nackte Jahresklammern "(2021)", Verweise wie "(siehe Kapitel 2)" oder
 *   "(vgl. Abb. 3)", "ebd."/"a.a.O." (kein eigener Autor/Jahr-Beleg) und
 *   der Literaturverzeichnis-Abschnitt.
 */

// Deutsche Umlaut-/Ligatur-Faltung — muss mit academic_vault/db.py::_UMLAUT_FOLD
// uebereinstimmen, damit Hook und Vault denselben Namensvergleich anstellen.
const UMLAUT_FOLD = {
  ä: 'ae', ö: 'oe', ü: 'ue', ß: 'ss', æ: 'ae', ø: 'oe', å: 'aa',
};

/**
 * Normalisiert einen Familiennamen zu einer Menge von Vergleichsvarianten
 * (Umlaut-Faltung UND Diakritika-Strip). Zwei Namen gelten als gleich, wenn
 * sich ihre Variantenmengen schneiden.
 */
export function normalizeFamily(name) {
  const lowered = (name || '').trim().toLowerCase();
  if (!lowered) return new Set();
  const folded = [...lowered].map((ch) => UMLAUT_FOLD[ch] ?? ch).join('');
  const stripped = lowered.normalize('NFD').replace(/\p{M}/gu, '');
  const variants = new Set();
  for (const variant of [folded, stripped]) {
    const cleaned = variant.replace(/[^a-z]/g, '');
    if (cleaned) variants.add(cleaned);
  }
  return variants;
}

/** True, wenn zwei Familiennamen nach Normalisierung als gleich gelten. */
export function familiesMatch(left, right) {
  const a = normalizeFamily(left);
  if (a.size === 0) return false;
  for (const variant of normalizeFamily(right)) {
    if (a.has(variant)) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// SKIP-Regeln: Regionen, in denen gar nicht erst gesucht wird
// ---------------------------------------------------------------------------

// Ueberschrift eines Literaturverzeichnisses (Markdown oder LaTeX). Ab hier
// bis Dateiende wird nichts mehr geprueft — dort stehen Vollbelege, keine
// In-Text-Zitate.
const BIBLIOGRAPHY_HEADING =
  /^\s*(?:#{1,6}\s*|\\(?:section|chapter|addsec)\*?\{)\s*(?:Literatur(?:verzeichnis)?|Quellen(?:verzeichnis)?|Bibliograf\p{L}*|Bibliograph\p{L}*|References|Works\s+Cited)\b/imu;

// Regionen, die durch Leerzeichen ersetzt werden (Laenge bleibt erhalten,
// damit Positionen im Originaltext gueltig bleiben).
const MASKED_REGIONS = [
  /```[\s\S]*?```/g,          // Fenced Code (Markdown)
  /~~~[\s\S]*?~~~/g,          // Fenced Code (alternativ)
  /`[^`\n]*`/g,               // Inline-Code
  /\\begin\{(verbatim|lstlisting|minted)\}[\s\S]*?\\end\{\1\}/g,
  /\\[a-zA-Z@]+\*?(?:\[[^\]]*\])*\{[^{}]*\}/g, // LaTeX-Makros inkl. \cite{...}
  /<!--[\s\S]*?-->/g,         // HTML-/Markdown-Kommentare
];

/**
 * Maskiert Code, LaTeX-Makros, Kommentare und das Literaturverzeichnis.
 * Ersetzt sie durch Leerzeichen gleicher Laenge, damit Offsets stabil bleiben.
 */
export function maskSkipRegions(text) {
  let masked = text;
  const biblio = BIBLIOGRAPHY_HEADING.exec(masked);
  if (biblio) {
    masked = masked.slice(0, biblio.index) + ' '.repeat(masked.length - biblio.index);
  }
  for (const pattern of MASKED_REGIONS) {
    masked = masked.replace(pattern, (match) => ' '.repeat(match.length));
  }
  return masked;
}

// ---------------------------------------------------------------------------
// Beleg-Muster
// ---------------------------------------------------------------------------

// Ein Familienname: beginnt mit Grossbuchstabe, danach Buchstaben/Bindestrich/
// Apostroph. Namenspartikel ("von", "van", "de") duerfen vorangehen.
const NAME = String.raw`(?:(?:von|van|de|del|della|di|du|da|le|la|ten|ter)\s+)?\p{Lu}[\p{L}'’-]+`;

// Co-Autoren-Kette: "/Schmidt", " & Schmidt", ", Schmidt", " und Schmidt",
// " u. a.", " et al." — der Name ist optional, damit "u. a." allein greift.
const COAUTHORS = String.raw`(?:\s*(?:\/|&|,|und|u\.\s?a\.|et\s+al\.)\s*(?:${NAME})?)*`;

// Signalwoerter, die einem Beleg vorangehen duerfen.
const SIGNAL = String.raw`(?:vgl\.|vergleiche|siehe|s\.|cf\.|zit\.\s*nach|nach)`;

// Seitenangabe: ", S. 45" | ": 45" | ", pp. 12-14" | " S. 45"
const PAGE = String.raw`(?:\s*[,:]?\s*(?:S\.|Seite|p\.|pp\.)\s*(\d{1,4})|\s*:\s*(\d{1,4}))?`;

const PAREN_CITATION = new RegExp(
  String.raw`^(?:${SIGNAL}\s*)?(${NAME})(${COAUTHORS})\s*,?\s*(\d{4})[a-z]?${PAGE}`,
  'u',
);

// Narrativ (ausserhalb von Klammern) — hier ist ein Signalwort Pflicht, sonst
// wuerde jeder Satz mit "Name Jahreszahl" als Beleg gelten.
const NARRATIVE_CITATION = new RegExp(
  String.raw`\b(?:vgl\.|siehe|zit\.\s*nach)\s+(${NAME})(${COAUTHORS})\s*,?\s*(\d{4})[a-z]?${PAGE}`,
  'gu',
);

// Woerter, die zwar gross geschrieben sind, aber nie ein Autorname eines
// Belegs sind (Struktur-Verweise). "Abb."/"Tab." deckt bereits der
// Figure-Check im verbatim-guard ab.
const NON_AUTHOR_TOKENS = new Set([
  'kapitel', 'abschnitt', 'anhang', 'tabelle', 'abbildung', 'abb', 'tab',
  'gleichung', 'formel', 'seite', 'fig', 'figure', 'table', 'chapter',
  'section', 'appendix', 'equation', 'ebd', 'ebenda', 'ibid', 'ders', 'dies',
]);

function parsePage(match) {
  const raw = match[4] ?? match[5];
  if (raw === undefined) return null;
  const page = Number.parseInt(raw, 10);
  if (!Number.isFinite(page) || page <= 0) return null;
  // Vierstellige "Seiten" im Jahresbereich sind fast immer ein zweites Jahr
  // ("(Müller 2021, 2022)"), keine Seitenzahl — lieber ignorieren als blocken.
  if (page >= 1400 && page <= 2100) return null;
  return page;
}

function buildCitation(match, raw) {
  const family = match[1].trim();
  const lastToken = family.split(/\s+/).pop().toLowerCase();
  if (NON_AUTHOR_TOKENS.has(lastToken.replace(/[^\p{L}]/gu, ''))) return null;
  const year = Number.parseInt(match[3], 10);
  if (!Number.isFinite(year) || year < 1400 || year > 2200) return null;
  const coauthors = (match[2] || '')
    .split(/\/|&|,|\bund\b|u\.\s?a\.|et\s+al\./u)
    .map((part) => part.trim())
    .filter(Boolean);
  return {
    raw,
    family,
    authors: [family, ...coauthors],
    year,
    page: parsePage(match),
  };
}

/**
 * Extrahiert alle Klammer-/Paraphrase-Belege aus einem Kapiteltext.
 * Gibt ein Array von {raw, family, authors, year, page} zurueck; ``raw`` ist
 * der Originaltext des Belegs (fuer die [UNVERIFIED]-Markierung).
 */
export function extractCitations(content) {
  if (!content) return [];
  const masked = maskSkipRegions(content);
  const citations = [];
  const seen = new Set();

  const push = (citation) => {
    if (!citation) return;
    const key = `${citation.raw}|${citation.family}|${citation.year}|${citation.page}`;
    if (seen.has(key)) return;
    seen.add(key);
    citations.push(citation);
  };

  // 1) Klammer-Belege
  const parens = /\(([^()\n]{1,200})\)/g;
  let match;
  while ((match = parens.exec(masked)) !== null) {
    const inner = match[1].trim();
    const parsed = PAREN_CITATION.exec(inner);
    if (parsed) push(buildCitation(parsed, match[0]));
  }

  // 2) Narrative Belege — Klammerinhalte vorher ausblenden, damit sie nicht
  //    doppelt (und mit falschem raw-Text) erfasst werden.
  const withoutParens = masked.replace(parens, (m) => ' '.repeat(m.length));
  NARRATIVE_CITATION.lastIndex = 0;
  while ((match = NARRATIVE_CITATION.exec(withoutParens)) !== null) {
    push(buildCitation(match, match[0]));
  }

  return citations;
}
