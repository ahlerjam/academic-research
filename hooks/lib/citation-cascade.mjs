/**
 * hooks/lib/citation-cascade.mjs — externe Beleg-Aufloesung (Issue #378)
 *
 * Dreistufige Kaskade als FALLBACK, wenn ein Klammer-Beleg im Vault nicht
 * gefunden wurde:
 *   1. arXiv        — eine gebatchte Anfrage fuer alle offenen Belege
 *   2. CrossRef     — DOI-Metadaten, je offenem Beleg eine Anfrage
 *   3. Semantic Scholar — Fuzzy-Match, Gate: Autoren-Ueberlapp >= S2_MIN_OVERLAP
 *
 * Score-Modell (0-100, siehe README "Klammer-Zitat-Validierung"):
 *   Familienname trifft            40
 *   Jahr exakt                     40   (Abweichung von genau 1 Jahr: 20)
 *   Autoren-Ueberlapp (Jaccard)  0-20
 *
 * Ergebnis-Status je Beleg:
 *   confirmed   Score >= ACADEMIC_CITATION_CONFIRMED_MIN (Default 80) -> allow
 *   probable    Score >= ACADEMIC_CITATION_PROBABLE_MIN  (Default 65) -> [UNVERIFIED]
 *   unavailable mindestens eine Stufe technisch nicht erreichbar      -> [UNVERIFIED]
 *   no-match    alle Stufen haben sauber geantwortet, kein Treffer    -> Block
 *
 * Der Unterschied zwischen "no-match" und "unavailable" ist der Kern von AC3:
 * ein Netzausfall darf niemals wie ein Halluzinations-Nachweis wirken. Als
 * "sauber beantwortet" gilt deshalb ausschliesslich ein 2xx mit vollstaendig
 * gelesenem, im erwarteten Format parsbarem Body. Alles andere — Timeout,
 * ECONNREFUSED, jeder Nicht-2xx-Status (5xx, 429, aber ebenso 403-Drosselung
 * und 404), abgebrochener Body-Stream, HTML-Fehlerseite mit Status 200 — ist
 * "unavailable".
 */

import { familiesMatch, normalizeFamily } from './citation-parse.mjs';

// ---------------------------------------------------------------------------
// Konfiguration (alle Werte per Env ueberschreibbar, siehe README)
// ---------------------------------------------------------------------------

const DEFAULTS = {
  arxivUrl: 'https://export.arxiv.org/api/query',
  crossrefUrl: 'https://api.crossref.org/works',
  s2Url: 'https://api.semanticscholar.org/graph/v1/paper/search',
  confirmedMin: 80,
  probableMin: 65,
  s2MinOverlap: 0.6,
  requestTimeoutMs: 2000,
  budgetMs: 6000,
};

function envNumber(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined || raw === '') return fallback;
  const value = Number(raw);
  return Number.isFinite(value) ? value : fallback;
}

export function loadConfig(env = process.env) {
  return {
    enabled: (env.ACADEMIC_CITATION_CASCADE || 'on').toLowerCase() !== 'off',
    arxivUrl: env.ACADEMIC_CITATION_ARXIV_URL || DEFAULTS.arxivUrl,
    crossrefUrl: env.ACADEMIC_CITATION_CROSSREF_URL || DEFAULTS.crossrefUrl,
    s2Url: env.ACADEMIC_CITATION_S2_URL || DEFAULTS.s2Url,
    confirmedMin: envNumber('ACADEMIC_CITATION_CONFIRMED_MIN', DEFAULTS.confirmedMin),
    probableMin: envNumber('ACADEMIC_CITATION_PROBABLE_MIN', DEFAULTS.probableMin),
    s2MinOverlap: envNumber('ACADEMIC_CITATION_S2_MIN_OVERLAP', DEFAULTS.s2MinOverlap),
    requestTimeoutMs: envNumber('ACADEMIC_CITATION_TIMEOUT_MS', DEFAULTS.requestTimeoutMs),
    budgetMs: envNumber('ACADEMIC_CITATION_BUDGET_MS', DEFAULTS.budgetMs),
  };
}

// ---------------------------------------------------------------------------
// Score-Modell
// ---------------------------------------------------------------------------

/** Jaccard-Ueberlapp zweier Autorenlisten ueber normalisierte Familiennamen. */
export function authorOverlap(citationAuthors, candidateAuthors) {
  const left = (citationAuthors || []).filter((n) => normalizeFamily(n).size > 0);
  const right = (candidateAuthors || []).filter((n) => normalizeFamily(n).size > 0);
  if (left.length === 0 || right.length === 0) return 0;
  let intersection = 0;
  for (const name of left) {
    if (right.some((other) => familiesMatch(name, other))) intersection += 1;
  }
  const union = left.length + right.length - intersection;
  return union === 0 ? 0 : intersection / union;
}

/** Score eines Kandidaten fuer einen Beleg, 0-100. */
export function scoreCandidate(citation, candidate) {
  const families = candidate.authors || [];
  const familyHit = families.some((name) => familiesMatch(citation.family, name));
  if (!familyHit) return 0;
  let score = 40;
  const diff = Number.isFinite(candidate.year) ? Math.abs(candidate.year - citation.year) : null;
  if (diff === 0) score += 40;
  else if (diff === 1) score += 20;
  score += Math.round(20 * authorOverlap(citation.authors, families));
  return score;
}

// ---------------------------------------------------------------------------
// HTTP-Zugriff
// ---------------------------------------------------------------------------

class UnavailableError extends Error {}

async function fetchText(url, config, deadline) {
  const remaining = deadline - Date.now();
  if (remaining <= 0) throw new UnavailableError('Kaskaden-Budget aufgebraucht');
  const timeout = Math.min(config.requestTimeoutMs, remaining);
  let response;
  try {
    response = await fetch(url, {
      signal: AbortSignal.timeout(timeout),
      headers: { 'User-Agent': 'academic-research-citation-guard/1.0' },
    });
  } catch (err) {
    throw new UnavailableError(`Netzfehler: ${err.message}`);
  }
  // Nur ein 2xx zaehlt als beantwortete Anfrage. Jeder andere Status heisst
  // "wir haben keine Auskunft bekommen" — 5xx/429 ohnehin, aber genauso 403
  // (Semantic Scholar drosselt ohne API-Key, Proxys blocken den Egress) und
  // 404 (Endpunkt verlegt). Als "kein Treffer" gewertet, wuerde ausgerechnet
  // der Netzausfall wie ein Halluzinations-Nachweis wirken — das verbietet AC3.
  if (!response.ok) {
    throw new UnavailableError(`HTTP ${response.status}`);
  }
  try {
    return await response.text();
  } catch (err) {
    // Abbruch beim Body-Lesen (Timeout, Socket-Reset nach den Headern).
    throw new UnavailableError(`Body unvollstaendig: ${err.message}`);
  }
}

/**
 * JSON-Body einer Stufe parsen. Ein unlesbarer oder unerwartet geformter Body
 * (HTML-Fehlerseite eines Captive Portals, abgeschnittene Antwort, Fehler-JSON
 * ohne Ergebnisfeld) ist KEIN sauberes Negativ — "Antwort nicht verstanden"
 * darf nicht auf "Beleg existiert nicht" abgebildet werden.
 */
function parseJsonBody(body, stage, pick) {
  let data;
  try {
    data = JSON.parse(body);
  } catch {
    throw new UnavailableError(`${stage}: unlesbare Antwort`);
  }
  const items = pick(data);
  if (!Array.isArray(items)) {
    throw new UnavailableError(`${stage}: unerwartetes Antwortformat`);
  }
  return items;
}

// ---------------------------------------------------------------------------
// Stufe 1 — arXiv (gebatcht: eine Anfrage fuer alle offenen Belege)
// ---------------------------------------------------------------------------

/** Parst eine arXiv-Atom-Antwort zu [{title, year, authors}]. */
export function parseArxivFeed(xml) {
  const entries = [];
  const chunks = String(xml).split('<entry>').slice(1);
  for (const chunk of chunks) {
    const body = chunk.split('</entry>')[0];
    const title = (/<title>([\s\S]*?)<\/title>/.exec(body) || [, ''])[1].trim();
    const published = /<published>(\d{4})/.exec(body);
    const authors = [...body.matchAll(/<name>([\s\S]*?)<\/name>/g)].map((m) =>
      m[1].trim().split(/\s+/).pop(),
    );
    entries.push({ title, year: published ? Number(published[1]) : null, authors });
  }
  return entries;
}

async function stageArxiv(citations, config, deadline) {
  const url = new URL(config.arxivUrl);
  const query = [...new Set(citations.map((c) => c.family))]
    .map((family) => `au:"${family}"`)
    .join(' OR ');
  url.searchParams.set('search_query', query);
  url.searchParams.set('max_results', '50');
  const xml = await fetchText(url.toString(), config, deadline);
  // Ein leerer Atom-Feed hat kein <entry>, aber immer ein <feed>. Fehlt das,
  // war die Antwort kein arXiv-Feed und damit kein "kein Treffer".
  if (!/<feed[\s>]/.test(xml)) {
    throw new UnavailableError('arXiv: keine Atom-Antwort');
  }
  return parseArxivFeed(xml);
}

// ---------------------------------------------------------------------------
// Stufe 2 — CrossRef (je Beleg eine Anfrage)
// ---------------------------------------------------------------------------

async function stageCrossref(citation, config, deadline) {
  const url = new URL(config.crossrefUrl);
  url.searchParams.set('query.bibliographic', `${citation.family} ${citation.year}`);
  url.searchParams.set('rows', '5');
  const body = await fetchText(url.toString(), config, deadline);
  const items = parseJsonBody(body, 'CrossRef', (data) => data?.message?.items);
  return items.map((item) => ({
    title: Array.isArray(item.title) ? item.title[0] : item.title || '',
    year: item?.issued?.['date-parts']?.[0]?.[0] ?? null,
    authors: (item.author || []).map((a) => a.family || a.literal || a.name || '').filter(Boolean),
  }));
}

// ---------------------------------------------------------------------------
// Stufe 3 — Semantic Scholar (Fuzzy, mit Ueberlapp-Gate)
// ---------------------------------------------------------------------------

async function stageSemanticScholar(citation, config, deadline) {
  const url = new URL(config.s2Url);
  url.searchParams.set('query', `${citation.family} ${citation.year}`);
  url.searchParams.set('fields', 'title,year,authors');
  url.searchParams.set('limit', '5');
  const body = await fetchText(url.toString(), config, deadline);
  const items = parseJsonBody(body, 'Semantic Scholar', (data) => data?.data);
  return items.map((item) => ({
    title: item.title || '',
    year: Number.isFinite(item.year) ? item.year : null,
    authors: (item.authors || []).map((a) => (a.name || '').trim().split(/\s+/).pop()).filter(Boolean),
  }));
}

// ---------------------------------------------------------------------------
// Orchestrierung
// ---------------------------------------------------------------------------

function classify(score, unavailable, config) {
  if (score >= config.confirmedMin) return 'confirmed';
  if (score >= config.probableMin) return 'probable';
  return unavailable ? 'unavailable' : 'no-match';
}

/**
 * Loest offene Belege ueber die Kaskade auf.
 *
 * @param {Array} citations  Belege aus extractCitations()
 * @param {object} config    Ergebnis von loadConfig()
 * @returns {Promise<Map>}   citation.key -> {status, score}
 */
export async function resolveCitations(citations, config = loadConfig()) {
  const results = new Map();
  if (citations.length === 0) return results;

  // Kill-Switch: Vault-only. Kein Netzzugriff, kein Soft-Fail.
  if (!config.enabled) {
    for (const citation of citations) {
      results.set(citation.key, { status: 'no-match', score: 0 });
    }
    return results;
  }

  const deadline = Date.now() + config.budgetMs;
  const state = new Map(
    citations.map((c) => [c.key, { citation: c, best: 0, unavailable: false }]),
  );

  const open = () =>
    [...state.values()].filter((s) => s.best < config.confirmedMin).map((s) => s.citation);

  const apply = (citation, candidates) => {
    const entry = state.get(citation.key);
    for (const candidate of candidates) {
      entry.best = Math.max(entry.best, scoreCandidate(citation, candidate));
    }
  };

  // Stufe 1: eine Anfrage fuer alle offenen Belege.
  let pending = open();
  if (pending.length > 0) {
    try {
      const candidates = await stageArxiv(pending, config, deadline);
      for (const citation of pending) apply(citation, candidates);
    } catch (err) {
      if (!(err instanceof UnavailableError)) throw err;
      for (const citation of pending) state.get(citation.key).unavailable = true;
    }
  }

  // Stufen 2 und 3: je offenem Beleg eine Anfrage, mit Fruehausstieg.
  for (const stage of [stageCrossref, stageSemanticScholar]) {
    pending = open();
    if (pending.length === 0) break;
    for (const citation of pending) {
      const entry = state.get(citation.key);
      try {
        let candidates = await stage(citation, config, deadline);
        if (stage === stageSemanticScholar) {
          candidates = candidates.filter(
            (c) => authorOverlap(citation.authors, c.authors) >= config.s2MinOverlap,
          );
        }
        apply(citation, candidates);
      } catch (err) {
        if (!(err instanceof UnavailableError)) throw err;
        entry.unavailable = true;
      }
    }
  }

  for (const [key, entry] of state) {
    results.set(key, {
      status: classify(entry.best, entry.unavailable, config),
      score: entry.best,
    });
  }
  return results;
}
