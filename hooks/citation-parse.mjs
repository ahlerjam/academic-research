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
 *   "(vgl. Abb. 3)", Datums- und Standangaben ("(Januar 2021)", "(Stand 2021)"),
 *   "ebd."/"a.a.O." (kein eigener Autor/Jahr-Beleg) und der
 *   Literaturverzeichnis-Abschnitt.
 *
 * Jeder Beleg traegt ein Feld ``confidence``: "strong" bei Seitenangabe,
 * Signalwort oder Co-Autoren-Marker, sonst "weak". Die nackte Form
 * "(Wort Jahr)" ist von Prosa wie "(Fukushima 2011)" nicht zu unterscheiden
 * und darf deshalb nie zu einem Hard-Block fuehren.
 */

// Deutsche Umlaut-/Ligatur-Faltung — muss mit academic_vault/db.py::_UMLAUT_FOLD
// uebereinstimmen, damit Hook und Vault denselben Namensvergleich anstellen.
const UMLAUT_FOLD = {
  ä: 'ae', ö: 'oe', ü: 'ue', ß: 'ss', æ: 'ae', ø: 'oe', å: 'aa',
};

// Namenspartikel. Muss mit academic_vault/db.py::_NAME_PARTICLES uebereinstimmen.
// Doppelrolle: Baustein des NAME-Musters (unten) UND Strip-Liste in
// normalizeFamily. Beides aus derselben Quelle, damit das Muster nie ein
// Partikel liest, das der Vergleich anschliessend nicht kennt.
export const NAME_PARTICLES = [
  'von', 'van', 'de', 'del', 'della', 'di', 'du', 'da', 'le', 'la', 'ten', 'ter',
];

/** Entfernt fuehrende Namenspartikel; der letzte Token bleibt immer stehen. */
function stripLeadingParticles(lowered) {
  let tokens = lowered.split(/\s+/).filter(Boolean);
  while (tokens.length > 1 && NAME_PARTICLES.includes(tokens[0].replace(/[^\p{L}]/gu, ''))) {
    tokens = tokens.slice(1);
  }
  return tokens.join(' ');
}

/**
 * Normalisiert einen Familiennamen zu einer Menge von Vergleichsvarianten
 * (Umlaut-Faltung UND Diakritika-Strip), jeweils mit UND ohne fuehrendes
 * Namenspartikel. Zwei Namen gelten als gleich, wenn sich ihre Variantenmengen
 * schneiden.
 *
 * Die Partikel-Variante ist noetig, weil beide Seiten des Vergleichs das
 * Partikel unterschiedlich fuehren: im Kapiteltext steht ``(von Neumann 1945)``,
 * CSL-JSON und die externen APIs liefern ``family: "Neumann"`` mit dem Partikel
 * in ``non-dropping-particle`` oder gar nicht. Ohne diese Variante blockte der
 * Guard Belege, deren Paper im Vault liegt.
 *
 * Die zusaetzliche Variante kann einen Treffer erzeugen, wo strenggenommen zwei
 * verschiedene Namen vorliegen (``De Angelis``/``Angelis``). Das ist die
 * gewollte Richtung: ein zu weiter Vergleich laesst durch, ein zu enger blockt.
 */
export function normalizeFamily(name) {
  const lowered = (name || '').trim().toLowerCase();
  if (!lowered) return new Set();
  const variants = new Set();
  for (const form of new Set([lowered, stripLeadingParticles(lowered)])) {
    const folded = [...form].map((ch) => UMLAUT_FOLD[ch] ?? ch).join('');
    const stripped = form.normalize('NFD').replace(/\p{M}/gu, '');
    for (const variant of [folded, stripped]) {
      const cleaned = variant.replace(/[^a-z]/g, '');
      if (cleaned) variants.add(cleaned);
    }
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
// Apostroph. Namenspartikel ("von", "van", "de") duerfen vorangehen — laengste
// Alternative zuerst, damit "della" nicht als "de" + "lla" zerfaellt.
const PARTICLE_ALT = [...NAME_PARTICLES].sort((a, b) => b.length - a.length).join('|');
const NAME = String.raw`(?:(?:${PARTICLE_ALT})\s+)?\p{Lu}[\p{L}'’-]+`;

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
// Belegs sind. Der Vergleich laeuft ueber die umlautgefaltete Kleinschreibung
// (siehe nonAuthorToken), deshalb steht hier "maerz" und nicht "März".
const NON_AUTHOR_TOKENS = new Set([
  // Struktur-Verweise. "Abb."/"Tab." deckt bereits der Figure-Check ab.
  'kapitel', 'abschnitt', 'anhang', 'tabelle', 'abbildung', 'abb', 'tab',
  'gleichung', 'formel', 'seite', 'fig', 'figure', 'table', 'chapter',
  'section', 'appendix', 'equation', 'ebd', 'ebenda', 'ibid', 'ders', 'dies',
  // Monate (de/en, inkl. Abkuerzungen): "(Januar 2021)" hat exakt die Form
  // eines Belegs, ist aber ein Datum.
  'januar', 'februar', 'maerz', 'april', 'mai', 'juni', 'juli', 'august',
  'september', 'oktober', 'november', 'dezember',
  'jan', 'feb', 'mrz', 'apr', 'jun', 'jul', 'aug', 'sep', 'sept', 'okt',
  'nov', 'dez',
  'january', 'february', 'march', 'may', 'june', 'july', 'october', 'december',
  'mar', 'oct', 'dec',
  // Jahreszeiten und Zeitraeume
  'fruehjahr', 'sommer', 'herbst', 'winter', 'quartal', 'stichtag',
  // Stand-/Ausgabe-Angaben: "(Stand 2021)", "(Fassung 2019)"
  'stand', 'fassung', 'version', 'ausgabe', 'auflage', 'jahrgang', 'band',
  'heft', 'nr', 'hrsg', 'zugriff', 'abgerufen',
]);

/** Vergleichsform eines Tokens fuer NON_AUTHOR_TOKENS (klein, umlautgefaltet). */
function nonAuthorToken(token) {
  return [...token.toLowerCase().replace(/[^\p{L}]/gu, '')]
    .map((ch) => UMLAUT_FOLD[ch] ?? ch)
    .join('');
}

// Ein Signalwort am Anfang des Belegs (mit oder ohne oeffnende Klammer).
const SIGNAL_PREFIX = new RegExp(String.raw`^\(?\s*(?:${SIGNAL})`, 'u');

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
  if (NON_AUTHOR_TOKENS.has(nonAuthorToken(family.split(/\s+/).pop()))) return null;
  const year = Number.parseInt(match[3], 10);
  if (!Number.isFinite(year) || year < 1400 || year > 2200) return null;
  const coauthors = (match[2] || '')
    .split(/\/|&|,|\bund\b|u\.\s?a\.|et\s+al\./u)
    .map((part) => part.trim())
    .filter(Boolean);
  const page = parsePage(match);
  // Belegstaerke: Seitenangabe, Signalwort oder Co-Autoren-Marker ("/", "&",
  // "u. a.", "et al.") kommen in Fliesstext nicht versehentlich vor — dort ist
  // die Zitierabsicht eindeutig. Die nackte Form "(Wort Jahr)" ist dagegen
  // lexikalisch nicht von Prosa zu trennen: "(Fukushima 2011)",
  // "(Corona 2020)". Der Aufrufer darf daraus deshalb keinen Hard-Block
  // ableiten (siehe verbatim-guard.mjs::runCitationCheck).
  const strong = page !== null || SIGNAL_PREFIX.test(raw) || (match[2] || '').trim().length > 0;
  return {
    raw,
    family,
    authors: [family, ...coauthors],
    year,
    page,
    confidence: strong ? 'strong' : 'weak',
  };
}

/**
 * Extrahiert alle Klammer-/Paraphrase-Belege aus einem Kapiteltext.
 * Gibt ein Array von {raw, family, authors, year, page, confidence} zurueck;
 * ``raw`` ist der Originaltext des Belegs (fuer die [UNVERIFIED]-Markierung),
 * ``confidence`` ist ``"strong"`` oder ``"weak"`` (siehe buildCitation).
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
