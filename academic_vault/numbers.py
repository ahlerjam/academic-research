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
"""

from __future__ import annotations


def normalize_number(raw: str | None) -> str | None:
    """Normalisiert eine Zahlen-Schreibweise auf eine kanonische Dezimalform.

    Toleriert (Issue #741 AC3):
      * Dezimalkomma vs. Dezimalpunkt ("45,8" == "45.8")
      * Tausendertrennzeichen per Punkt, Komma, Leerzeichen oder Apostroph
        ("1.234,56" == "1234.56" == "1,234.56")
      * Fuehrende Nullen ("046" == "46")
      * Ein angehaengtes Prozentzeichen ("46 %" == "46")

    Args:
        raw: Roher Zahlen-String, z. B. aus einer Tabellenzelle oder einer
            behaupteten Kennzahl. ``None`` oder Leerstring liefern ``None``.

    Returns:
        Kanonische Dezimaldarstellung als ``str`` (z. B. ``"1234.56"``,
        ``"46"``, ``"-0.5"``) oder ``None``, wenn ``raw`` keine erkennbare
        Zahl enthaelt.
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

    # Tausendertrennzeichen als Leerzeichen/NBSP/Apostroph entfernen -- die
    # Punkt/Komma-Varianten werden weiter unten kontextabhaengig behandelt.
    text = text.replace(" ", "").replace(" ", "").replace("'", "")
    if not text:
        return None

    negative = text.startswith("-")
    if negative:
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

    try:
        value = float(text)
    except ValueError:
        return None
    if negative:
        value = -value

    canonical = f"{value:.10f}".rstrip("0").rstrip(".")
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
    Rundungsdifferenz) bleibt ein Unterschied.
    """
    left = normalize_number(claimed)
    right = normalize_number(actual)
    return left is not None and left == right
