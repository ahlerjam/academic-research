/**
 * hooks/lib/citation-parse.mjs — Extraktion von Klammer-/Paraphrase-Belegen (Issue #378)
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
 * Signalwort, Co-Autoren-Marker — oder wenn derselbe Familienname im Dokument
 * schon in einer dieser eindeutigen Formen auftaucht (siehe
 * upgradeCorroborated). Sonst "weak": die nackte Form "(Wort Jahr)" ist von
 * Prosa wie "(Fukushima 2011)" nicht zu unterscheiden.
 *
 * Das Feld KLASSIFIZIERT nur — was daraus folgt, entscheidet der Aufrufer
 * (verbatim-guard.mjs::ambiguousPolicy). Default ist auch fuer "weak" der
 * Block bei sauberem Negativ; "(Fantasius 2087)" ist genau der
 * Halluzinationsfall, gegen den der Guard antritt. Wer prosa-lastig schreibt,
 * setzt ACADEMIC_CITATION_AMBIGUOUS=mark.
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

// "und andere"-Marker: stehen fuer sich, ohne folgenden Namen.
const ET_AL = String.raw`(?:u\.\s?a\.|et\s+al\.)`;

// Co-Autoren-Kette: "/Schmidt", " & Schmidt", ", Schmidt", " und Schmidt" —
// nach einem Trennzeichen MUSS ein Name folgen. Ohne diese Pflicht verschluckt
// die Kette das Komma vor der Jahreszahl ("(Paris, 2015)"), und der leere
// Zweitautor liest sich anschliessend wie ein Co-Autoren-Marker: die Klammer
// gilt als eindeutiger Beleg und wird hart geblockt, obwohl sie Prosa ist.
// Standardformen wie "(Müller, 2021)" bleiben erkannt — das Komma faengt das
// optionale ",?" vor dem Jahr (siehe PAREN_CITATION).
const COAUTHORS = String.raw`(?:\s*(?:(?:\/|&|,|und)\s*(?:${NAME})|${ET_AL}))*`;

// Signalwoerter, die einem Beleg vorangehen duerfen.
const SIGNAL = String.raw`(?:vgl\.|vergleiche|siehe|s\.|cf\.|zit\.\s*nach|nach)`;

// Seitenangabe: ", S. 45" | ": 45" | ", pp. 12-14" | " S. 45"
const PAGE = String.raw`(?:\s*[,:]?\s*(?:S\.|Seite|p\.|pp\.)\s*(\d{1,4})|\s*:\s*(\d{1,4}))?`;

const PAREN_CITATION = new RegExp(
  String.raw`^(?:${SIGNAL}\s*)?(${NAME})(${COAUTHORS})\s*,?\s*(\d{4})[a-z]?${PAGE}`,
  'u',
);

// Signalwoerter fuer den Narrativ-Pass, case-insensitiv OHNE pauschales
// 'i'-Flag auf dem Gesamtmuster (Issue #740, Plan-Risiko 1): ein 'i'-Flag
// wuerde ``\p{Lu}`` im NAME-Baustein auch fuer Kleinbuchstaben wahr werden
// lassen (verifiziert: ``/\p{Lu}/iu.test('a')`` -> true) und damit die
// Grossschreibungs-Heuristik fuer Familiennamen aufweichen. Deshalb hier eine
// explizite Gross/Klein-Alternation je Signalwort statt des Flags.
const NARRATIVE_SIGNAL_CI = String.raw`(?:[Vv]gl\.|[Ss]iehe|[Zz]it\.\s*nach)`;

// Narrativ mit Signalwort (ausserhalb von Klammern) — "vgl. Schmidt 2019".
const NARRATIVE_CITATION = new RegExp(
  String.raw`\b${NARRATIVE_SIGNAL_CI}\s+(${NAME})(${COAUTHORS})\s*,?\s*(\d{4})[a-z]?${PAGE}`,
  'gu',
);

// Narrativ mit Jahresklammer (ausserhalb von Klammern, Jahr selbst in
// Klammern) — "Müller (2021, S. 45) zeigt", "Müller et al. (2021) belegen".
// Ohne Seite/Co-Autor/Signalwort ist die Form von Prosa wie
// "Die DSGVO (2016) trat in Kraft" nicht zu unterscheiden — dafuer
// REPORTING_VERBS unten (Gate in extractCitations).
const NARRATIVE_PAREN_YEAR = new RegExp(
  String.raw`\b(${NAME})(${COAUTHORS})\s*\(\s*(\d{4})[a-z]?${PAGE}\s*\)`,
  'gu',
);

// Berichtsverben, die eine Autoren-Zuschreibung anzeigen, wenn sie direkt
// hinter "Name (Jahr)" folgen — noetig, um die bare Form ohne Seite/Co-Autor
// ("Müller (2021) belegt …") von einer blossen Datums-/Struktur-Klammer wie
// "Die DSGVO (2016) trat in Kraft" zu unterscheiden (siehe docs/reference/hooks.md).
const REPORTING_VERBS = new Set([
  'zeigt', 'zeigen', 'belegt', 'belegen', 'schreibt', 'schreiben',
  'argumentiert', 'argumentieren', 'betont', 'betonen', 'konstatiert',
  'konstatieren', 'erklaert', 'erklaeren', 'folgert', 'folgern', 'meint',
  'meinen', 'kritisiert', 'kritisieren', 'resuemiert', 'resuemieren',
  'sieht', 'sehen', 'beschreibt', 'beschreiben', 'analysiert', 'analysieren',
  'untersucht', 'untersuchen', 'formuliert', 'formulieren',
]);

/** Vergleichsform fuer REPORTING_VERBS (klein, umlautgefaltet wie UMLAUT_FOLD). */
function reportingVerbToken(token) {
  return [...token.toLowerCase()].map((ch) => UMLAUT_FOLD[ch] ?? ch).join('');
}

/**
 * True, wenn direkt nach [end] (ueberspringt optionales ":"/"," und
 * Leerraum) ein Berichtsverb steht. Nur fuer die bare Narrativ-Form ohne
 * Seite/Co-Autor relevant (siehe NARRATIVE_PAREN_YEAR-Docstring).
 */
function followedByReportingVerb(text, end) {
  const rest = text.slice(end, end + 40);
  const m = /^\s*[:,]?\s*(\p{L}+)/u.exec(rest);
  if (!m) return false;
  return REPORTING_VERBS.has(reportingVerbToken(m[1]));
}

// Trennstueck des Sekundaerbelegs "X, Jahr, zitiert nach Y, Jahr[, S. X]" —
// case-insensitiv nur fuer "zitiert", nicht fuer die Namen (Risiko 1).
const SECONDARY_SEPARATOR = /,\s*[Zz]itiert\s+nach\s+/u;

/**
 * Sekundaerbeleg-Erkennung innerhalb eines Klammerinhalts: "Schmidt, 2015,
 * zitiert nach Müller, 2021, S. 45" wird zu ZWEI Citation-Objekten — dem
 * nicht gelesenen Original (Schmidt) und dem tatsaechlich vorliegenden Werk
 * (Müller, ``viaSecondary: true``). Gibt ``null`` zurueck, wenn keine der
 * beiden Haelften ein gueltiger Beleg ist.
 *
 * @param {string} innerRaw  Klammerinhalt, UNGETRIMMT (fuer Offset-Treue)
 * @param {number} innerAbsStart  Position von innerRaw[0] im Originaltext
 * @param {string} content  Originaltext (fuer content.slice in buildCitation)
 */
function trySecondaryCitation(innerRaw, innerAbsStart, content) {
  const sep = SECONDARY_SEPARATOR.exec(innerRaw);
  if (!sep) return null;
  const leftRaw = innerRaw.slice(0, sep.index);
  const rightRaw = innerRaw.slice(sep.index + sep[0].length);
  const leftMatch = PAREN_CITATION.exec(leftRaw);
  const rightMatch = PAREN_CITATION.exec(rightRaw);
  if (!leftMatch || !rightMatch) return null;
  const leftStart = innerAbsStart + leftMatch.index;
  const rightStart = innerAbsStart + sep.index + sep[0].length + rightMatch.index;
  const first = buildCitation(
    leftMatch, content.slice(leftStart, leftStart + leftMatch[0].length), leftStart,
  );
  const second = buildCitation(
    rightMatch, content.slice(rightStart, rightStart + rightMatch[0].length), rightStart,
  );
  if (second) second.viaSecondary = true;
  return { first, second };
}

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
// 'i'-Flag hier unbedenklich (anders als bei NARRATIVE_CITATION): SIGNAL
// enthaelt kein \p{Lu} aus NAME, also keine Kollision mit Risiko 1. Deckt
// u. a. "Vgl." am Satzanfang ab (Issue #740).
const SIGNAL_PREFIX = new RegExp(String.raw`^\(?\s*(?:${SIGNAL})`, 'iu');

// "u. a."/"et al." im Co-Autoren-Teil — eindeutiger Marker auch ohne Namen.
const ET_AL_TEST = new RegExp(ET_AL, 'u');

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

function buildCitation(match, raw, start) {
  const family = match[1].trim();
  if (NON_AUTHOR_TOKENS.has(nonAuthorToken(family.split(/\s+/).pop()))) return null;
  const year = Number.parseInt(match[3], 10);
  if (!Number.isFinite(year) || year < 1400 || year > 2200) return null;
  const coauthorText = (match[2] || '').trim();
  const coauthors = coauthorText
    .split(/\/|&|,|\bund\b|u\.\s?a\.|et\s+al\./u)
    .map((part) => part.trim())
    .filter(Boolean);
  const page = parsePage(match);
  // Belegstaerke: Seitenangabe, Signalwort, ein wirklich gelesener Zweitautor
  // oder ein "u. a."/"et al."-Marker kommen in Fliesstext nicht versehentlich
  // vor — dort ist die Zitierabsicht eindeutig. Bewusst NICHT aus dem rohen
  // Treffertext abgeleitet: ein Trennzeichen ohne folgenden Namen ist kein
  // Co-Autor (siehe COAUTHORS). Die nackte Form "(Wort Jahr)" ist lexikalisch
  // nicht von Prosa zu trennen ("(Fukushima 2011)", "(Corona 2020)") — was der
  // Aufrufer daraus macht, steuert ACADEMIC_CITATION_AMBIGUOUS (siehe
  // verbatim-guard.mjs::ambiguousPolicy).
  const strong =
    page !== null
    || SIGNAL_PREFIX.test(raw)
    || coauthors.length > 0
    || ET_AL_TEST.test(coauthorText);
  return {
    raw,
    start,
    end: start + raw.length,
    // Stabiler Identitaetsschluessel des BELEGS (nicht der Fundstelle): zwei
    // Vorkommen desselben Belegs teilen ihn, damit Vault-Lookup und Kaskade
    // je Beleg einmal laufen — waehrend start/end jede Fundstelle einzeln
    // adressierbar halten. ``raw`` taugt dafuer nicht mehr als Schluessel.
    key: `${family.toLowerCase()}|${year}|${page}`,
    family,
    authors: [family, ...coauthors],
    year,
    page,
    confidence: strong ? 'strong' : 'weak',
  };
}

/**
 * Extrahiert alle Klammer-/Paraphrase-Belege aus einem Kapiteltext.
 *
 * Gibt **eine Fundstelle pro Vorkommen** zurueck — bewusst ohne Deduplizierung:
 * {raw, start, end, key, family, authors, year, page, confidence}. Es gilt die
 * Invariante ``content.slice(start, end) === raw``; die Maskierung in
 * :func:`maskSkipRegions` ist laengenerhaltend, deshalb sind die Offsets aus
 * dem maskierten Text im Originaltext gueltig. ``raw`` wird trotzdem aus dem
 * ORIGINAL geschnitten, damit ein teilweise maskierter Beleg (etwa mit einem
 * ``\cite{...}`` in derselben Klammer) nicht die maskierte Fassung mitschleppt.
 *
 * Ohne die Offsets muesste der Aufrufer den Beleg zum Markieren per Textsuche
 * wiederfinden — und traefe dabei auch Vorkommen, die hier gerade uebergangen
 * wurden (Code-Fence, LaTeX, Literaturverzeichnis). Fuer die Kostenkontrolle
 * dedupliziert der Aufrufer stattdessen ueber ``key``.
 *
 * ``confidence`` ist ``"strong"`` oder ``"weak"`` (siehe buildCitation).
 */
/**
 * True, wenn der Bereich [start, end) im maskierten Text ueber Zeichen laeuft,
 * die im Original kein Whitespace sind — also ueber eine ausgeblendete Region
 * (Klammerinhalt, Code, LaTeX-Makro, Kommentar, Literaturverzeichnis).
 *
 * Der Zeichenvergleich ist Absicht: eine blosse Whitespace-Obergrenze wuerde
 * auch legitime Belege ueber einen Zeilenumbruch hinweg verwerfen
 * (``vgl.\n  Schmidt 2019, S. 7``).
 */
function spansMaskedRegion(content, maskedText, start, end) {
  for (let i = start; i < end; i += 1) {
    if (maskedText[i] === ' ' && content[i] !== undefined && !/\s/u.test(content[i])) return true;
  }
  return false;
}

export function extractCitations(content) {
  if (!content) return [];
  const masked = maskSkipRegions(content);
  const citations = [];

  const push = (citation) => {
    if (citation) citations.push(citation);
  };

  // 1) Klammer-Belege (inkl. Sekundaerbeleg "X, Jahr, zitiert nach Y, Jahr").
  //    Nur ERFOLGREICH geparste Klammer-Spans werden fuer Pass 2 maskiert
  //    (Issue #740, Plan-Risiko 2) — eine Struktur-Klammer wie
  //    "(siehe Kapitel 2)" oder eine blosse Jahresklammer "(2021)" bleibt
  //    sichtbar, weil NARRATIVE_PAREN_YEAR (Pass 2) genau diese Klammerform
  //    hinter einem vorangehenden Namen braucht.
  const parens = /\(([^()\n]{1,200})\)/g;
  let match;
  const parsedSpans = [];
  while ((match = parens.exec(masked)) !== null) {
    const start = match.index;
    const end = start + match[0].length;
    const innerRaw = match[1];
    const secondary = trySecondaryCitation(innerRaw, start + 1, content);
    if (secondary) {
      if (secondary.first || secondary.second) {
        push(secondary.first);
        push(secondary.second);
        parsedSpans.push({ start, end });
      }
      continue;
    }
    const parsed = PAREN_CITATION.exec(innerRaw.trim());
    if (parsed) {
      push(buildCitation(parsed, content.slice(start, end), start));
      parsedSpans.push({ start, end });
    }
  }

  // 2) Narrative Belege — nur die von Pass 1 erfolgreich geparsten Klammern
  //    werden ausgeblendet (laengenerhaltend), alle anderen Klammern bleiben
  //    fuer NARRATIVE_PAREN_YEAR sichtbar.
  let narrativeSource = masked;
  for (const span of [...parsedSpans].sort((a, b) => b.start - a.start)) {
    narrativeSource =
      narrativeSource.slice(0, span.start)
      + ' '.repeat(span.end - span.start)
      + narrativeSource.slice(span.end);
  }

  // 2a) Narrativ mit Signalwort ("vgl. Schmidt 2019").
  NARRATIVE_CITATION.lastIndex = 0;
  while ((match = NARRATIVE_CITATION.exec(narrativeSource)) !== null) {
    const start = match.index;
    const end = start + match[0].length;
    if (spansMaskedRegion(content, narrativeSource, start, end)) {
      NARRATIVE_CITATION.lastIndex = start + 1;
      continue;
    }
    push(buildCitation(match, content.slice(start, end), start));
  }

  // 2b) Narrativ mit Jahresklammer ("Müller (2021, S. 45) zeigt",
  //     "Müller et al. (2021) belegen"). Ohne Seite/Co-Autor/et-al. ist ein
  //     REPORTING_VERB direkt nach der Klammer Pflicht (Gate gegen
  //     "Die DSGVO (2016) trat in Kraft").
  NARRATIVE_PAREN_YEAR.lastIndex = 0;
  while ((match = NARRATIVE_PAREN_YEAR.exec(narrativeSource)) !== null) {
    const start = match.index;
    const end = start + match[0].length;
    if (spansMaskedRegion(content, narrativeSource, start, end)) {
      NARRATIVE_PAREN_YEAR.lastIndex = start + 1;
      continue;
    }
    const page = parsePage(match);
    const coauthorText = (match[2] || '').trim();
    if (page === null && coauthorText.length === 0 && !followedByReportingVerb(content, end)) {
      continue;
    }
    push(buildCitation(match, content.slice(start, end), start));
  }

  upgradeCorroborated(citations);
  citations.sort((a, b) => a.start - b.start);
  return citations;
}

/**
 * Haengt ``marker`` hinter jede angegebene Fundstelle an — positionsbasiert,
 * nie per Textsuche.
 *
 * Wird von hinten nach vorne gespleisst, damit jedes Einfuegen die noch
 * offenen Offsets unberuehrt laesst. Der Waechter ``text.slice(start, end)
 * === raw`` ist Absicht: passt der Span nicht (fremder Text, verschobene
 * Segmentgrenze), wird die Fundstelle uebersprungen und gewarnt, statt zu
 * raten. Ein fehlender Marker ist harmlos, ein Marker an falscher Stelle
 * veraendert den Text des Nutzers.
 *
 * Die Rueckwaerts-Invariante haelt nur fuer DISJUNKTE Spans: ueberlappt ein
 * Span einen bereits markierten, sind die Offsets im mutierten Text um die
 * Marker-Laenge verschoben und das Einfuegen traefe mitten in ein Wort. Solche
 * Spans werden deshalb ebenfalls verworfen und gemeldet — der Waechter oben
 * kann das nicht sehen, weil er gegen den unveraenderten Text prueft.
 * Der Sortier-Tie-Break auf ``end`` sorgt dafuer, dass bei gleichem Start der
 * kuerzere (innere, praezisere) Span gewinnt.
 *
 * @param {string} text
 * @param {Array<{raw: string, start: number, end: number}>} citations
 * @param {string} marker
 * @param {(msg: string) => void} [warn]
 */
export function markSpans(text, citations, marker, warn = () => {}) {
  const source = text || '';
  const spans = [...citations]
    .filter((c) => Number.isInteger(c.start) && Number.isInteger(c.end))
    .sort((a, b) => b.start - a.start || a.end - b.end);
  let out = source;
  // Start der zuletzt markierten Fundstelle; alles Folgende muss davor enden.
  let lastStart = Number.POSITIVE_INFINITY;
  for (const span of spans) {
    if (source.slice(span.start, span.end) !== span.raw) {
      warn(`Span ${span.start}-${span.end} passt nicht zu ${JSON.stringify(span.raw)}`);
      continue;
    }
    if (span.end > lastStart) {
      warn(`Span ${span.start}-${span.end} ueberlappt eine bereits markierte Fundstelle`);
      continue;
    }
    out = `${out.slice(0, span.end)}${marker}${out.slice(span.end)}`;
    lastStart = span.start;
  }
  return out;
}

/**
 * Hebt mehrdeutige Belege an, deren Familienname im selben Dokument bereits in
 * einer eindeutigen Beleg-Form vorkommt.
 *
 * ``(Müller 2099)`` allein ist lexikalisch nicht von Prosa zu trennen. Steht im
 * selben Text aber ``(Müller 2021, S. 45)`` oder ``vgl. Müller 2018``, dann
 * weist das Dokument ``Müller`` selbst als zitierten Autor aus — die Klammer
 * ist dann ein Beleg und ein erfundenes Jahr wieder blockierbar. Die
 * Prosa-Faelle bleiben unberuehrt, weil ``Fukushima``, ``Corona`` oder
 * ``Bologna`` in keiner eindeutigen Beleg-Form auftauchen.
 *
 * Mutiert ``citations`` in-place (``confidence`` ``weak`` -> ``strong``).
 */
function upgradeCorroborated(citations) {
  // Vereinigung aller Vergleichsvarianten der eindeutigen Belege. Der Test
  // "schneiden sich die Variantenmengen?" (= familiesMatch) wird damit zu
  // einem Set-Lookup, statt jeden schwachen gegen jeden starken Beleg zu
  // fahren — bei einem Kapitel mit hunderten Klammern der Unterschied
  // zwischen linear und quadratisch.
  const strongVariants = new Set();
  for (const citation of citations) {
    if (citation.confidence !== 'strong') continue;
    for (const variant of normalizeFamily(citation.family)) strongVariants.add(variant);
  }
  if (strongVariants.size === 0) return;
  for (const citation of citations) {
    if (citation.confidence !== 'weak') continue;
    for (const variant of normalizeFamily(citation.family)) {
      if (strongVariants.has(variant)) {
        citation.confidence = 'strong';
        break;
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Ungeprüfte Belegformen (Issue #740, AC6/AC7) — grobe Erkennung ohne
// Vault-Prüfung
// ---------------------------------------------------------------------------

// Nur Code/Kommentare ausblenden — bewusst NICHT die generelle
// LaTeX-Makro-Maskierung aus MASKED_REGIONS: die verschluckt \footnote{...}
// vollständig, bevor irgendein Zitat-Regex läuft (Plan-Risiko 6), und genau
// das \footnote{...} mit Autor/Jahr-Payload ist der Fall, den dieser
// Detektor sichtbar machen soll.
const CODE_ONLY_SKIP_REGIONS = [
  /```[\s\S]*?```/g,
  /~~~[\s\S]*?~~~/g,
  /`[^`\n]*`/g,
  /<!--[\s\S]*?-->/g,
];

function maskCodeOnly(text) {
  let masked = text;
  for (const pattern of CODE_ONLY_SKIP_REGIONS) {
    masked = masked.replace(pattern, (m) => ' '.repeat(m.length));
  }
  return masked;
}

const UNCHECKED_YEAR = String.raw`(?:1[4-9]\d{2}|2[0-2]\d{2})`;

// \footnote{...} mit Autor+Jahr-Payload — grob (kein PAREN_CITATION-Parse,
// nur "steht dort ein Name UND eine Jahreszahl").
const LATEX_FOOTNOTE_CITE = new RegExp(
  String.raw`\\footnote\{[^{}]*\p{Lu}[\p{L}'’-]+[^{}]*\b${UNCHECKED_YEAR}\b[^{}]*\}`,
  'gu',
);

// Markdown-Fussnotendefinition am Zeilenanfang: "[^1]: Vgl. Müller 2021."
const MARKDOWN_FOOTNOTE_DEF = /^[ \t]*\[\^[^\]\s]+\]:.*$/gmu;

// Markdown-Fussnotenmarker im Fliesstext: "[^1]" (nicht die Definitionszeile
// selbst — die hat MARKDOWN_FOOTNOTE_DEF bereits erfasst).
const MARKDOWN_FOOTNOTE_REF = /\[\^[^\]\s]+\]/gu;

// Numerischer Verweis IEEE-Stil: "[12]". Bewusst grob (AC6) — Aufzählungen
// und Schrittnummern sind lexikalisch nicht auszuschliessen; der Detektor
// meldet nur eine Fundstelle, prüft nichts.
const NUMERIC_REFERENCE = /\[(\d{1,3})\]/gu;

/**
 * Grobe, VAULT-UNGEPRÜFTE Erkennung von Belegformen, die
 * :func:`extractCitations` bewusst nicht abdeckt: LaTeX-Fussnoten mit
 * Autor/Jahr-Payload, Markdown-Fussnotenmarker/-Definitionen, numerische
 * Klammerverweise. Löst KEINE Vault-Prüfung aus — liefert nur Fundstellen,
 * damit der Aufrufer (verbatim-guard.mjs) einmal je Write auf stderr
 * hinweisen kann, dass diese Form ungeprüft bleibt (Issue #740, AC6/AC7).
 *
 * @param {string} content
 * @returns {Array<{kind: string, raw: string, start: number, end: number}>}
 */
export function detectUncheckedCitationForms(content) {
  if (!content) return [];
  const masked = maskCodeOnly(content);
  const findings = [];
  let m;

  LATEX_FOOTNOTE_CITE.lastIndex = 0;
  while ((m = LATEX_FOOTNOTE_CITE.exec(masked)) !== null) {
    findings.push({ kind: 'latex-footnote', raw: m[0], start: m.index, end: m.index + m[0].length });
  }

  MARKDOWN_FOOTNOTE_DEF.lastIndex = 0;
  while ((m = MARKDOWN_FOOTNOTE_DEF.exec(masked)) !== null) {
    const raw = m[0].trim();
    const start = m.index + (m[0].length - m[0].trimStart().length);
    findings.push({ kind: 'markdown-footnote', raw, start, end: start + raw.length });
  }

  MARKDOWN_FOOTNOTE_REF.lastIndex = 0;
  while ((m = MARKDOWN_FOOTNOTE_REF.exec(masked)) !== null) {
    // Definitionszeilen ("[^1]: ...") wurden oben bereits erfasst.
    if (masked[m.index + m[0].length] === ':') continue;
    findings.push({
      kind: 'markdown-footnote', raw: m[0], start: m.index, end: m.index + m[0].length,
    });
  }

  NUMERIC_REFERENCE.lastIndex = 0;
  while ((m = NUMERIC_REFERENCE.exec(masked)) !== null) {
    findings.push({
      kind: 'numeric-reference', raw: m[0], start: m.index, end: m.index + m[0].length,
    });
  }

  findings.sort((a, b) => a.start - b.start);
  return findings;
}
