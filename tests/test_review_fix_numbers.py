"""Regressionstests fuer den Zahlenvergleich in ``academic_vault.numbers``.

Zwei Review-Befunde am Fail-closed-Check von ``vault.add_table_value``:

* Befund 6 -- ``float64`` + ``f"{value:.10f}"`` zerstoerte Praezision, sodass
  VERSCHIEDENE Zahlen dieselbe kanonische Form bekamen (1e-11 vs. 2e-11,
  9007199254740993 vs. ...92). Der Check winkte eine falsch abgeschriebene
  Kennzahl durch und legte dafuer eine Beleg-Kette an.
* Befund 7 -- nur ASCII-``-`` galt als Vorzeichen, deshalb scheiterte eine
  KORREKTE Kennzahl mit U+2212 MINUS SIGN (so setzt LaTeX Minus, pdfplumber
  liefert das Zeichen woertlich) an einem Mismatch-Fehler.

Runde-2-Regression -- die Vorzeichen-Anwendung (``value = -value``) lief
ausserhalb des erweiterten ``localcontext`` und damit unter der
Default-Praezision von 28 Stellen: fuer negative Zahlen kehrte Befund 6 exakt
zurueck, nur eben nur fuer das Vorzeichen ``-``. Die Tests unten spiegeln
deshalb die Praezisions-Faelle aus Befund 6 zusaetzlich mit negativem
Vorzeichen.
"""

from __future__ import annotations

import pytest
from academic_vault.numbers import normalize_number, numbers_equivalent

# ---------------------------------------------------------------------------
# Befund 6 -- Praezision darf nicht stillschweigend verlorengehen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claimed,actual",
    [
        ("0,00000000001", "0,00000000002"),  # unterhalb der alten 10-Nachkommastellen
        ("1e-11", "2e-11"),  # dieselbe Differenz in Exponentialschreibweise
        ("9007199254740993", "9007199254740992"),  # jenseits von 2**53 (float64)
        ("1234567890123456789", "1234567890123456788"),  # 19 Stellen
        ("0.12345678901", "0.12345678902"),  # 11. Nachkommastelle
        ("-0,00000000001", "-0,00000000002"),  # dieselben Faelle negativ (Runde-2-Regression)
        ("-1e-11", "-2e-11"),
        ("-9007199254740993", "-9007199254740992"),
        ("-1234567890123456789", "-1234567890123456788"),
        ("-0.12345678901", "-0.12345678902"),
        (
            "-1.000000000000000000000000000001",  # 30 signifikante Stellen, negativ
            "-1",
        ),
    ],
)
def test_verschiedene_zahlen_gelten_nicht_als_gleich(claimed, actual):
    """Jede echte Werteabweichung bleibt eine Abweichung -- auch weit hinten."""
    assert not numbers_equivalent(claimed, actual)
    assert normalize_number(claimed) != normalize_number(actual)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1234567890123456789", "1234567890123456789"),
        ("9007199254740993", "9007199254740993"),
        ("0,00000000001", "0.00000000001"),
        ("1e-11", "0.00000000001"),
        ("123456789012345678901234567890.5", "123456789012345678901234567890.5"),
        # Negative Gegenstuecke (Runde-2-Regression: Negation ausserhalb des
        # erweiterten Kontexts rundete lange negative Zahlen weg).
        ("-1234567890123456789", "-1234567890123456789"),
        ("-9007199254740993", "-9007199254740993"),
        ("-0,00000000001", "-0.00000000001"),
        ("-1e-11", "-0.00000000001"),
        ("-123456789012345678901234567890.5", "-123456789012345678901234567890.5"),
        ("-1.000000000000000000000000000001", "-1.000000000000000000000000000001"),
    ],
)
def test_kanonische_form_haelt_alle_stellen(raw, expected):
    assert normalize_number(raw) == expected


@pytest.mark.parametrize(
    "claimed,actual",
    [
        ("1.50", "1.5"),  # Nachkomma-Nullen bleiben irrelevant
        ("1,5", "1.5"),  # Dezimalkomma vs. -punkt
        ("046", "46"),  # fuehrende Null
        ("1.234,56", "1234.56"),  # deutsche Schreibweise
        ("46 %", "46"),  # Prozentzeichen wird nur abgestreift
        ("1e3", "1000"),  # Exponentialschreibweise
        ("-0", "0"),  # negative Null
        ("0.0", "0"),
    ],
)
def test_reine_schreibweisenunterschiede_bleiben_gleich(claimed, actual):
    assert numbers_equivalent(claimed, actual)


# ---------------------------------------------------------------------------
# Befund 7 -- Unicode-Vorzeichen und -Trennzeichen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "−0.5",  # MINUS SIGN (LaTeX-Standard)
        "‐0.5",  # HYPHEN
        "‑0.5",  # NON-BREAKING HYPHEN
        "-0.5",
    ],
)
def test_unicode_minus_wird_erkannt(raw):
    assert normalize_number(raw) == "-0.5"
    assert numbers_equivalent(raw, "-0.5")
    assert numbers_equivalent("-0,5", raw)


@pytest.mark.parametrize(
    "claimed,actual",
    [
        ("1 234,56", "1234.56"),  # NARROW NO-BREAK SPACE (frz./CH-Satz)
        ("1 234,56", "1234.56"),  # THIN SPACE
        ("1’234", "1234"),  # typografischer Apostroph (CH-Satz)
        ("1 234", "1234"),  # NO-BREAK SPACE (schon vorher toleriert)
    ],
)
def test_unicode_tausendertrennzeichen(claimed, actual):
    assert numbers_equivalent(claimed, actual)


@pytest.mark.parametrize(
    "raw",
    [
        "–0.5",  # EN DASH -- in Tabellen auch "kein Wert"/Bereich
        "—0.5",  # EM DASH
        "–",  # blanker Gedankenstrich als Leerwert
        "5–10",  # Bereichsangabe
    ],
)
def test_mehrdeutige_gedankenstriche_werden_abgelehnt(raw):
    """Fail-closed: lieber ablehnen als einen Bereich/Leerwert als Zahl raten."""
    assert normalize_number(raw) is None


@pytest.mark.parametrize("raw", ["nan", "NaN", "inf", "-Infinity", "keine Zahl", "1_0", "--5"])
def test_nichtzahlen_bleiben_none(raw):
    assert normalize_number(raw) is None


def test_none_und_leerstring():
    assert normalize_number(None) is None
    assert normalize_number("") is None
    assert normalize_number("   ") is None
    assert not numbers_equivalent(None, None)


def test_absurde_exponenten_werden_abgelehnt():
    """Kein Speicher-Blowup durch ``1e999999999`` in einer Zelle."""
    assert normalize_number("1e999999999") is None
    assert normalize_number("1e-999999999") is None
