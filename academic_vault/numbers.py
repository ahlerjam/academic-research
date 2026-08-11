"""Toleranter Zahlenvergleich fuer Kennzahl-Belege aus Tabellenzellen (Issue #741).

``vault.add_table_value`` vergleicht eine behauptete Kennzahl gegen den
tatsaechlichen Zellinhalt (``VaultDB.get_table_cell``). Ein stures
String-Vergleich wuerde ueblichste Schreibweisenunterschiede faelschlich als
Abweichung werten -- Dezimalkomma statt -punkt, Tausendertrennzeichen,
fuehrende Nullen, ein angehaengtes Prozentzeichen. Dieses Modul normalisiert
beide Seiten auf eine kanonische Dezimaldarstellung, bevor verglichen wird.

Bewusst KEINE Einheiten- oder Prozent-Umrechnung (Issue #741 Scope-Out): ein
Prozentzeichen wird nur ABGESTREIFT, nicht durch 100 geteilt -- "46%" und "46"
gelten als dieselbe Schreibweise, nicht als Bruch und Ganzzahl. Eine echte
Werteabweichung (z. B. Tabellenzelle "45.8" gegen behauptet "46", eine
Rundungsdifferenz) bleibt eine Abweichung: beide normalisieren auf
verschiedene kanonische Werte und werden korrekt als Mismatch erkannt.

Gerechnet wird ausschliesslich mit :class:`decimal.Decimal`, nie mit ``float``.
Ein Zwischenschritt ueber ``float64`` (bzw. ein Format mit fester
Nachkommastellen-Zahl) wuerde Praezision vernichten und dadurch
VERSCHIEDENE Zahlen auf dieselbe kanonische Form abbilden -- ein p-Wert von
1e-11 wuerde als Beleg fuer eine Zelle mit 2e-11 durchgehen. Der Check ist
fail-closed gedacht; er darf nichts durchwinken, was er nicht exakt geprueft
hat.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, localcontext

# Zeichen, die als Minuszeichen akzeptiert werden. U+2212 MINUS SIGN ist das
# Zeichen, das LaTeX-gesetzte PDFs liefern und pdfplumber woertlich
# durchreicht; U+2010/U+2011 sind reine Bindestrich-Varianten.
_MINUS_CHARS = "−‐‑"

# BEWUSST NICHT akzeptiert: U+2013 EN DASH und U+2014 EM DASH. In Tabellen
# stehen sie regelmaessig fuer "kein Wert" oder fuer eine Bereichsangabe
# ("5–10") und nicht fuer ein Minus. Sie als Vorzeichen zu raten koennte einen
# falschen Wert stillschweigend als belegt ausweisen; ein lautes Reject
# (``None`` -> Mismatch-Fehler) ist hier die sichere Seite.

# Zeichen, die als Tausender-Gruppierung ersatzlos entfernt werden: normales
# Leerzeichen, NO-BREAK SPACE, NARROW NO-BREAK SPACE, THIN SPACE, FIGURE SPACE
# sowie der gerade und der typografische Apostroph (Schweizer Satz "1'234").
_GROUPING_CHARS = "     '’ʼ"

# Nach der Separator-Aufloesung erlaubte Restform. Bewusst strenger als
# ``Decimal()``: kein "NaN"/"Infinity", keine Unterstriche, keine Klammern.
_DECIMAL_RE = re.compile(r"^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")

# Groessenordnungs-Schranke gegen Eingaben wie "1e999999999": eine solche
# Zelle ist keine Kennzahl, und die Fixpunkt-Ausgabe waere hunderte Megabyte.
_MAX_ADJUSTED_EXPONENT = 1000


def normalize_number(raw: str | None) -> str | None:
    """Normalisiert eine Zahlen-Schreibweise auf eine kanonische Dezimalform.

    Toleriert (Issue #741 AC3):
      * Dezimalkomma vs. Dezimalpunkt ("45,8" == "45.8")
      * Tausendertrennzeichen per Punkt, Komma, Leerzeichen (auch NBSP, NNBSP,
        Thin Space) oder Apostroph ("1.234,56" == "1234.56" == "1,234.56")
      * Fuehrende Nullen und Nachkomma-Nullen ("046" == "46", "1.50" == "1.5")
      * Ein angehaengtes Prozentzeichen ("46 %" == "46")
      * Unicode-Minus U+2212 sowie U+2010/U+2011 ("−0.5" == "-0.5")
      * Exponentialschreibweise ("1e-11" == "0.00000000001")

    Args:
        raw: Roher Zahlen-String, z. B. aus einer Tabellenzelle oder einer
            behaupteten Kennzahl. ``None`` oder Leerstring liefern ``None``.

    Returns:
        Kanonische Dezimaldarstellung als ``str`` (z. B. ``"1234.56"``,
        ``"46"``, ``"-0.5"``) oder ``None``, wenn ``raw`` keine erkennbare
        oder eine mehrdeutige Zahl enthaelt. Die Darstellung ist exakt: es
        gehen keine Stellen verloren, verschiedene Zahlen liefern immer
        verschiedene Strings.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None

    if text.endswith("%"):
        text = text[:-1].strip()
        if not text:
            return None

    for char in _MINUS_CHARS:
        text = text.replace(char, "-")

    # Tausendertrennzeichen als Leerzeichen/Apostroph entfernen -- die
    # Punkt/Komma-Varianten werden weiter unten kontextabhaengig behandelt.
    for char in _GROUPING_CHARS:
        text = text.replace(char, "")
    if not text:
        return None

    negative = text.startswith("-")
    if negative or text.startswith("+"):
        text = text[1:]
    if not text:
        return None

    has_comma = "," in text
    has_dot = "." in text

    if has_comma and has_dot:
        # Der zuletzt stehende Separator ist der Dezimaltrenner, der andere
        # (ggf. mehrfach) der Tausendertrenner.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif has_comma:
        text = _resolve_single_separator(text, ",")
    elif has_dot:
        text = _resolve_single_separator(text, ".")

    if not _DECIMAL_RE.match(text):
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:  # pragma: no cover -- durch _DECIMAL_RE abgedeckt
        return None
    if not value.is_finite() or abs(value.adjusted()) > _MAX_ADJUSTED_EXPONENT:
        return None
    if negative:
        # ``copy_negate()`` statt unaerem ``-value``: Letzteres ist eine
        # arithmetische Operation und unterliegt der Kontext-Praezision (28
        # Stellen per Default) samt Rundung -- fuer eine lange negative Zahl
        # genau der Praezisionsverlust, den dieses Modul verhindern soll.
        # ``copy_negate()`` ist laut decimal-Doku eine reine Vorzeichen-Kopie:
        # "unaffected by context [...] no rounding is performed".
        value = value.copy_negate()

    # ``normalize()`` streicht bedeutungslose Nachkomma-Nullen ("1.50" ->
    # "1.5"). Die Kontext-Praezision muss dafuer gross genug sein, sonst
    # rundet der Default-Kontext (28 Stellen) lange Zahlen weg -- genau der
    # Praezisionsverlust, den dieses Modul vermeiden soll.
    with localcontext() as ctx:
        ctx.prec = max(len(value.as_tuple().digits) + 1, 28)
        canonical = format(value.normalize(), "f")
    if canonical in ("", "-0"):
        canonical = "0"
    return canonical


def _resolve_single_separator(text: str, sep: str) -> str:
    """Entscheidet bei genau EINER Separator-Art zwischen Dezimal- und Tausendertrenner.

    Mehrere Gruppen von je genau drei Ziffern nach dem ersten Segment
    ("1,234,567" bzw. "1.234.567") gelten als Tausendertrennung und werden
    entfernt. Alles andere (ein einzelnes Vorkommen, insbesondere mit
    abweichender Nachkommastellen-Zahl wie "45,8" oder "1.234") gilt als
    Dezimaltrenner.
    """
    parts = text.split(sep)
    if len(parts) > 2 and all(len(p) == 3 for p in parts[1:]) and len(parts[0]) <= 3:
        return "".join(parts)
    if sep == ",":
        return text.replace(",", ".")
    return text


def numbers_equivalent(claimed: str | None, actual: str | None) -> bool:
    """``True``, wenn beide Werte nach Normalisierung dieselbe Zahl sind.

    Reine Schreibweisenunterschiede (siehe :func:`normalize_number`) machen
    keinen Unterschied; jede echte Werteabweichung (auch eine
    Rundungsdifferenz oder eine Abweichung erst in der 20. Stelle) bleibt ein
    Unterschied. Was nicht eindeutig als Zahl lesbar ist, gilt nie als
    gleichwertig -- der Aufrufer soll lieber laut ablehnen als raten.
    """
    left = normalize_number(claimed)
    right = normalize_number(actual)
    return left is not None and left == right
