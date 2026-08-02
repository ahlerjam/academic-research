/**
 * hooks/lib/protected-path.mjs — gemeinsame Pfadpruefung fuer die drei
 * Kapitel-Guards (Issue #615)
 *
 * Vorher definierten verbatim-guard.mjs, claim-drift-guard.mjs und
 * context-fidelity-guard.mjs je eine eigene Kopie von isProtectedPath() mit
 * derselben case-sensitiven Regex. Case-Sensitivitaet bedeutete:
 * "Kapitel/03.md" (korrekte deutsche Grossschreibung) lief an allen drei
 * Guards ungeprueft vorbei, obwohl macOS' Standard-Dateisystem
 * Gross-/Kleinschreibung ignoriert und Dateien trotzdem am richtigen Ort
 * landeten — der Nutzer sah alles funktionieren, ohne Signal, dass der
 * Schutz aus war.
 *
 * isProtectedPath() ist jetzt case-insensitiv fuer Verzeichnisname UND
 * Dateiendung, und das Kapitelverzeichnis ist ueber ACADEMIC_CHAPTER_DIR
 * konfigurierbar (Default weiterhin "kapitel" — identisch zum bisherigen
 * Verhalten ohne Override).
 */

const DEFAULT_CHAPTER_DIR = 'kapitel';

/** Escaped Regex-Sonderzeichen, damit ein konfigurierter Ordnername (z. B.
 * "kapitel.neu" oder "kapitel(alt)") keine ungewollte Regex-Syntax
 * einschleust. */
function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function chapterDirFrom(env) {
  const raw = (env && env.ACADEMIC_CHAPTER_DIR) || '';
  const trimmed = raw.trim();
  return trimmed || DEFAULT_CHAPTER_DIR;
}

/**
 * Prueft, ob ein Pfad zur geschuetzten Menge gehoert: jede *.tex-Datei
 * (ueberall, ordnerunabhaengig — bewusst beibehaltenes Verhalten aus der
 * alten Implementierung) oder eine *.md-Datei unterhalb des
 * Kapitelverzeichnisses (beliebig tief verschachtelt, #516). Beides
 * case-insensitiv (#615): Verzeichnisname UND Dateiendung.
 *
 * @param {string} filePath - roher Tool-Pfad (relativ oder absolut)
 * @param {object} [env] - Umgebung fuer ACADEMIC_CHAPTER_DIR-Override
 *   (Default: process.env)
 * @returns {boolean}
 */
export function isProtectedPath(filePath, env = process.env) {
  if (!filePath) return false;
  const normalized = filePath.replace(/\\/g, '/');
  if (/\.tex$/i.test(normalized)) return true;
  const chapterDir = escapeRegExp(chapterDirFrom(env));
  const pattern = new RegExp(`(?:^|/)${chapterDir}/(?:[^/]+/)*[^/]+\\.md$`, 'i');
  return pattern.test(normalized);
}

/**
 * Prueft, ob ein Pfad ueberhaupt ein Kapiteltext-Kandidat ist (.md oder
 * .tex, case-insensitiv) — unabhaengig davon, ob er in der geschuetzten
 * Menge liegt. Dient AC3: die sichtbare Meldung soll nur bei Kapiteltexten
 * ausserhalb der Schutzzone erscheinen, nicht bei jeder beliebigen Datei
 * (kein Rauschen fuer .py/.json/etc.).
 *
 * @param {string} filePath
 * @returns {boolean}
 */
export function isMarkdownOrTexFile(filePath) {
  if (!filePath) return false;
  const normalized = filePath.replace(/\\/g, '/');
  return /\.(md|tex)$/i.test(normalized);
}

/** Menschlich lesbares Label des aktiven Kapitelverzeichnisses, fuer
 * Meldungen (AC3). */
export function chapterDirLabel(env = process.env) {
  return chapterDirFrom(env);
}
