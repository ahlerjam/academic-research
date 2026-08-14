"""Reine Text-, Namens- und Pfad-Helfer des Vaults — ohne DB-Zugriff.

Reiner Move aus der frueheren ``academic_vault/db.py`` (Issue #841): die
Funktionen sind unveraendert. Sie liegen hier statt in ``db.py``, damit die
Repository-Module sie nutzen koennen, ohne die Fassade zu importieren
(Zirkularimport).
"""

import os
import re
import unicodedata
from pathlib import Path

# Typ-Alias-Map fuer Figure-Referenzen (Issue #379): alle Schreibweisen
# normalisieren auf "figure" bzw. "table", damit In-Text-Label
# ("Abb. 3.4") und Caption ("Abbildung 3.4: ...") strukturiert statt per
# Freitext-Teilstring verglichen werden koennen.
_FIGURE_REF_TYPE_ALIASES = {
    "abb": "figure",
    "abbildung": "figure",
    "fig": "figure",
    "figure": "figure",
    "tab": "table",
    "tabelle": "table",
}

_FIGURE_REF_RE = re.compile(
    r"\b(Abb|Abbildung|Fig|Figure|Tab|Tabelle)\.?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _parse_figure_reference(text: str) -> tuple[str, str] | None:
    """Parst Referenz-/Caption-Text in ``(kind, number)``.

    ``kind`` ist ``"figure"`` oder ``"table"`` (normalisiert ueber die
    Typ-Alias-Map), ``number`` das Nummern-Label als String (z. B. ``"3.4"``).
    Gibt ``None`` zurueck, wenn kein Typ+Nummer-Muster gefunden wird.
    """
    match = _FIGURE_REF_RE.search(text)
    if match is None:
        return None
    kind = _FIGURE_REF_TYPE_ALIASES[match.group(1).lower()]
    number = match.group(2)
    return (kind, number)


# ---------------------------------------------------------------------------
# Autorennamen-Normalisierung (Issue #378)
# ---------------------------------------------------------------------------

# Deutsche Umlaut-/Ligatur-Faltung. Muss identisch in hooks/lib/citation-parse.mjs
# gepflegt werden, damit Hook und Vault denselben Vergleich anstellen.
_UMLAUT_FOLD = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ß": "ss",
    "æ": "ae",
    "ø": "oe",
    "å": "aa",
}


# Namenspartikel. Muss mit hooks/lib/citation-parse.mjs::NAME_PARTICLES uebereinstimmen.
_NAME_PARTICLES = frozenset(
    {"von", "van", "de", "del", "della", "di", "du", "da", "le", "la", "ten", "ter"}
)


def _strip_leading_particles(lowered: str) -> str:
    """Entfernt fuehrende Namenspartikel; der letzte Token bleibt immer stehen."""
    tokens = lowered.split()
    while len(tokens) > 1 and "".join(c for c in tokens[0] if c.isalpha()) in _NAME_PARTICLES:
        tokens = tokens[1:]
    return " ".join(tokens)


def normalize_family_name(name: str) -> set[str]:
    """Normalisiert einen Familiennamen zu einer Menge von Vergleichsvarianten.

    Zwei Varianten sind noetig, weil beide Schreibkonventionen real vorkommen:
      * Umlaut-Faltung  ("Müller" -> "mueller")
      * Diakritika-Strip ("Müller" -> "muller", "Sørensen" -> "sorensen")

    Beide werden zusaetzlich OHNE fuehrendes Namenspartikel gebildet: im
    Kapiteltext steht ``(von Neumann 1945)``, CSL-JSON fuehrt das Partikel
    dagegen in ``non-dropping-particle`` und laesst ``family`` auf ``Neumann``.
    Ohne diese Variante fand der Lookup ein eingepflegtes Paper nicht wieder.

    Zwei Namen gelten als gleich, wenn sich ihre Variantenmengen schneiden.
    Die Partikel-Variante macht den Vergleich bewusst etwas weiter (``De
    Angelis`` trifft ``Angelis``) — ein zu weiter Vergleich laesst durch, ein zu
    enger blockt korrekte Belege.
    """
    lowered = (name or "").strip().lower()
    if not lowered:
        return set()
    variants: set[str] = set()
    for form in {lowered, _strip_leading_particles(lowered)}:
        folded = "".join(_UMLAUT_FOLD.get(ch, ch) for ch in form)
        stripped = "".join(
            ch for ch in unicodedata.normalize("NFD", form) if not unicodedata.combining(ch)
        )
        variants |= {re.sub(r"[^a-z]", "", v) for v in (folded, stripped)}
    return variants - {""}


def family_names_match(left: str, right: str) -> bool:
    """True, wenn zwei Familiennamen nach Normalisierung als gleich gelten."""
    left_variants = normalize_family_name(left)
    return bool(left_variants and left_variants & normalize_family_name(right))


def csl_families(csl: dict) -> list[str]:
    """Extrahiert alle Autoren-Familiennamen aus einem CSL-JSON-Objekt."""
    families: list[str] = []
    for author in csl.get("author") or []:
        if not isinstance(author, dict):
            continue
        family = author.get("family") or author.get("literal") or author.get("name")
        if family:
            families.append(str(family))
    return families


def csl_title(csl: dict) -> str | None:
    """Extrahiert den Titel aus einem CSL-JSON-Objekt (#701, Kontextsatz-Metadaten)."""
    title = csl.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return None


def csl_year(csl: dict) -> int | None:
    """Extrahiert das Erscheinungsjahr aus ``issued`` (date-parts, literal, raw)."""
    issued = csl.get("issued")
    if not isinstance(issued, dict):
        return None
    parts = issued.get("date-parts")
    if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
        try:
            return int(str(parts[0][0])[:4])
        except (TypeError, ValueError):
            pass
    for key in ("literal", "raw"):
        value = issued.get(key)
        if isinstance(value, str):
            match = re.search(r"\b(1[0-9]{3}|2[0-9]{3})\b", value)
            if match:
                return int(match.group(1))
    return None


_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _normalized_words(text: str) -> set[str]:
    """Tokenisiert Text und faltet jedes Wort wie ``normalize_family_name()``.

    Baustein der Kapitelzitat-Heuristik (Issue #604, AC5): dieselbe
    Umlaut-/Diakritika-Faltung wie bei Autorennamen wird auf jedes Wort des
    Kapiteltexts angewendet, damit ``family_names_match``-kompatible
    Varianten (``Müller``/``Mueller``/``Muller``) als Wort-Treffer erkannt
    werden -- ohne Namenspartikel-Behandlung, die ist bei Fliesstext nicht
    sinnvoll (kein "von"/"van" isoliert am Satzanfang zu erwarten).
    """
    variants: set[str] = set()
    for token in _WORD_RE.findall(text):
        lowered = token.lower()
        folded = "".join(_UMLAUT_FOLD.get(ch, ch) for ch in lowered)
        stripped = "".join(
            ch for ch in unicodedata.normalize("NFD", lowered) if not unicodedata.combining(ch)
        )
        variants |= {re.sub(r"[^a-z]", "", v) for v in (folded, stripped)}
    return variants - {""}


def paper_cited_in_chapters(csl: dict, kapitel_dir: str | Path) -> bool:
    """Heuristische Pruefung: taucht das Paper in einem Kapiteltext auf? (#604, AC5)

    Ein Paper gilt als "im Kapiteltext zitiert", wenn mindestens eine
    ``*.md``-Datei unter ``kapitel_dir`` (Unterordner eingeschlossen, Ordner-
    konvention aus ``scripts/bootstrap/CLAUDE.md``) sowohl das Erscheinungs-
    jahr des Papers als String ENTHAELT als auch mindestens einen seiner
    Autoren-Familiennamen als Wort-Treffer aufweist.

    Bewusst approximativ (Autor-Familienname + Jahr statt echtem
    Zitat-Parsing): False Negatives bei reiner Paraphrase ohne Klammerbeleg,
    False Positives bei Namensgleichheit unterschiedlicher Autoren. Das ist
    fuer diesen Anwendungsfall tragbar, weil das Ergebnis dem Nutzer nur
    vorgelegt wird (AC4) -- keine automatische Aktion haengt daran; der
    Aufrufer kennzeichnet das Ergebnis entsprechend als heuristisch.

    Gibt ``False`` zurueck, wenn das Paper keine Autoren/kein Jahr im
    CSL-JSON traegt oder ``kapitel_dir`` nicht existiert -- kein Fehler, denn
    ohne Kapitelordner ist "ungenutzter Vault-Eintrag" die korrekte Auskunft.
    """
    year = csl_year(csl)
    families = csl_families(csl)
    if not families or year is None:
        return False

    kapitel_path = Path(kapitel_dir)
    if not kapitel_path.is_dir():
        return False

    year_str = str(year)
    family_variant_sets = [normalize_family_name(family) for family in families]

    for md_file in sorted(kapitel_path.glob("**/*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if year_str not in text:
            continue
        words = _normalized_words(text)
        if any(variants & words for variants in family_variant_sets):
            return True
    return False


def format_table_evidence(
    paper_id: str,
    page: int,
    table_index: int,
    row: int,
    col: int,
) -> str:
    """Formatiert den Beleg zu einer Tabellenzelle (Issue #630 AC2).

    Intern sind ``table_index``, ``row`` und ``col`` 0-basiert; im Beleg stehen
    sie 1-basiert, weil ihn ein Mensch gegen das PDF haelt. ``page`` ist die
    PDF-Seite und bereits 1-basiert.
    """
    return f"{paper_id}, S. {page}, Tabelle {table_index + 1}, Zeile {row + 1}, Spalte {col + 1}"


# Escape-Zeichen fuer LIKE-Patterns (siehe escape_like / ESCAPE-Klauseln unten).
_LIKE_ESCAPE_CHAR = "\\"


def escape_like(value: str) -> str:
    """Escaped LIKE-Wildcards (``%`` und ``_``) sowie das Escape-Zeichen selbst.

    SQLite-LIKE behandelt ``%`` und ``_`` als Wildcards. Ohne Escaping veraendert
    User-Input mit diesen Zeichen das Suchverhalten still. Mit dem Rueckgabewert
    laesst sich ein literales LIKE-Pattern bauen, das per ``ESCAPE '\\'`` an die
    Query gebunden wird. Backslash muss zuerst escaped werden, damit die spaeter
    eingefuegten Escape-Backslashes nicht doppelt escaped werden.
    """
    return (
        value.replace(_LIKE_ESCAPE_CHAR, _LIKE_ESCAPE_CHAR * 2)
        .replace("%", _LIKE_ESCAPE_CHAR + "%")
        .replace("_", _LIKE_ESCAPE_CHAR + "_")
    )


_FTS5_OPERATOR_KEYWORDS = re.compile(r"\b(?:NEAR|AND|OR|NOT)\b")


# Wort-Token fuer FTS5-Queries: ``\w`` deckt unter Unicode ASCII-Alnum,
# Unterstrich UND alle Unicode-Wortzeichen ab (Umlaute, ss, Akzente) -- jedes
# andere Zeichen (Bindestrich, Slash, Klammer, Doppelpunkt, Satzzeichen, Stern,
# Anfuehrungszeichen) TRENNT. Damit ist jedes erzeugte Token per Konstruktion
# ein legales FTS5-Bareword: laut SQLite-FTS5-Doku (``https://devdocs.io/sqlite/fts5``,
# Abschnitt "FTS5 Strings", per context7 verifiziert) bestehen Barewords
# ausschliesslich aus ASCII-Buchstaben/-Ziffern, Unterstrich und Zeichen
# >= 0x80 -- eine echte Obermenge von ``\w``.
_FTS5_WORD_TOKEN = re.compile(r"\w+", re.UNICODE)


def _sanitize_fts5_query(query: str) -> str:
    """Bereinigt Query fuer sichere FTS5-MATCH-Ausfuehrung.

    Eine Blacklist einzelner Sonderzeichen verliert strukturell immer wieder
    gegen die Menge an Zeichen, die in einem FTS5-Bareword illegal sind (u.a.
    ``. , ? ' ! % ; = [ @ # & | ~ \\ < >`` -- Issue #841 zeigt das an
    ``"Was ist DevOps-Governance?"``, ``"Web 2.0"``, ``"Governance, Praxis"``
    und ``"it's governance"``, die alle mit ``sqlite3.OperationalError: fts5:
    syntax error`` abstuerzten, obwohl die alte Blacklist bereits ``-^/*():"``
    entfernte). Strategie daher nicht "verbotene Zeichen raus", sondern
    "an allem zerlegen, was kein Wortzeichen ist" (:data:`_FTS5_WORD_TOKEN`):
    uebrig bleiben ausschliesslich legale Barewords, die per Leerzeichen
    verbunden werden. Die Query ist damit fuer beliebigen User-Input
    syntaktisch immer gueltig, und kein Zeichen mit Operator-Bedeutung
    (``: * ^ ( ) " -``) ueberlebt -- die Schutzabsicht aus Issue #196 bleibt
    ohne Zeichen-Blacklist erhalten.

    Bewusst NICHT gewaehlt: das ganze Whitespace-Token als FTS5-Stringliteral
    quoten (``DevOps-Governance`` -> ``"DevOps-Governance"``). Ein
    Stringliteral mit mehreren Tokens ist in FTS5 eine PHRASE mit
    Adjazenz-Zwang; sie faende nur noch Text, in dem die Woerter unmittelbar
    hintereinander stehen. ``Governance von DevOps in KMU`` fiele damit aus
    der Trefferliste (die alte Blacklist fand es, weil sie den Bindestrich zu
    Whitespace machte), ``Mueller/Schmidt`` faende kein ``Schmidt und
    Mueller``, und ``Governance, Praxis`` machte im Trigram-Zweig das Komma
    zum Pflicht-Substring. Das Zerlegen liefert stattdessen ``DevOps
    Governance`` -- implizites UND und damit derselbe Recall wie vor #841.

    Kurze Tokens bleiben unquotiert und damit bytegleich zum Verhalten vor
    #841 -- wichtig, weil ``server._trigram_match_expression()`` die
    Tokenlaenge der sanitisierten Query auswertet (Issue #703, AK5): ein
    gequotetes ``"KMU"`` waere 2 Zeichen laenger als das Bareword ``KMU`` und
    haette die dortige Laengenschwelle falsch ausgeloest.

    Die booleschen Operator-Keywords NEAR/AND/OR/NOT werden VOR dem Zerlegen
    entfernt (nur in Grossschreibung operatorwirksam) -- so bleibt das
    bisherige Verhalten erhalten, dass usergenerierte Grossschreib-Operatoren
    nicht als literale Suchbegriffe landen. Kleingeschriebene Woerter wie
    'android' oder 'and' bleiben unangetastet.

    Gemeinsam genutzt von server.search_papers() und VaultDB.search_notes()
    (Issue #462) -- lebt hier statt in server.py, weil VaultDB (db.py) nicht
    von server.py importieren darf (Zirkularimport).
    """
    # Boolesche Operator-Keywords (Grossschreibung) neutralisieren, BEVOR
    # tokenisiert wird -- sonst landeten sie als literale Suchbegriffe im
    # Ergebnis, statt zu verschwinden.
    without_operators = _FTS5_OPERATOR_KEYWORDS.sub(" ", query)
    return " ".join(_FTS5_WORD_TOKEN.findall(without_operators))


def project_slug(cwd: str | None = None) -> str:
    """Kanonischer Projekt-Slug fuer den DB-Pfad: basename(CLAUDE_PROJECT_DIR || CWD).

    Eine einzige Quelle der Wahrheit (Issue #190). Hooks (hooks/verbatim-guard.mjs)
    und MCP-Server muessen denselben Algorithmus verwenden, damit alle
    Komponenten gegen dieselbe vault.db schreiben.

    Praezedenz (Issue #365 -- muss mit hooks/verbatim-guard.mjs:34 uebereinstimmen):
      1. Expliziter ``cwd``-Parameter (Escape-Hatch fuer bestehende Aufrufer/Tests).
      2. ``CLAUDE_PROJECT_DIR``-Umgebungsvariable, falls gesetzt.
      3. ``Path.cwd()``.
    """
    if cwd is not None:
        base = Path(cwd)
    else:
        env_project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        base = Path(env_project_dir) if env_project_dir else Path.cwd()
    return base.name or "default"


def default_db_path() -> str:
    """Kanonischer Default-Pfad zur vault.db (Single Source of Truth, Issue #190).

    Reihenfolge:
      1. Falls ``VAULT_DB_PATH`` gesetzt ist, wird dieser Pfad verwendet.
      2. Sonst ``~/.academic-research/projects/<slug>/vault.db`` mit
         ``slug = basename(CWD)``.

    Bewusst NICHT das CWD direkt ("vault.db") und NICHT das Plugin-Verzeichnis
    (``CLAUDE_PLUGIN_ROOT``/``REPO_ROOT``), um Datenverlust bei Plugin-Updates
    und das versehentliche Committen von Forschungs-PII zu vermeiden (CWE-538).
    """
    env = os.environ.get("VAULT_DB_PATH")
    if env:
        return env
    return str(Path.home() / ".academic-research" / "projects" / project_slug() / "vault.db")
