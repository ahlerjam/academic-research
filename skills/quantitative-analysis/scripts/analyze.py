#!/usr/bin/env python3
"""Deterministischer Rechenkern des quantitative-analysis-Skills (Issue #610).

Drei Subkommandos:

``describe``
    Schneller Blick auf einen Rohdatensatz: Spalten, Fallzahl, fehlende Werte.
    Gedacht fuer den Dialog *vor* dem Analyseplan.

``run``
    Fuehrt einen Analyseplan (JSON) ueber eine CSV-Datei aus und schreibt drei
    Artefakte in das Zielverzeichnis: ``ergebnisse.json`` (der reproduzierbare
    Payload), ``lauf_meta.json`` (Zeitpunkt, Pfade, Versionen -- alles, was
    zwischen zwei Laeufen abweicht) und ``protokoll.md`` (der Bericht).

``report``
    Rendert ``protokoll.md`` erneut aus einem vorhandenen Ergebnis-Payload.

Die Trennung von ``ergebnisse.json`` und ``lauf_meta.json`` ist Absicht: nur so
laesst sich "zweimal gerechnet, dasselbe herausgekommen" ueberhaupt pruefen --
mit einem Zeitstempel im Payload waere jeder Vergleich immer verschieden.

Bewusst NICHT in diesem Skript: die Wahl des Verfahrens (Dialog, siehe
SKILL.md) und die Deutung des Ergebnisses (Sache der Autorin). Das Skript
rechnet, prueft Voraussetzungen und berichtet -- mehr nicht.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import shlex
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

STANDARD_FEHLWERTE = ["", "NA", "N/A", "na", ".", "-99"]
STANDARD_ALPHA = 0.05
STANDARD_NIVEAU = 0.95
STANDARD_BOOTSTRAP = 2000
STANDARD_SEED = 610

DEUTUNGS_PLATZHALTER = "Deutung: [vom Autor zu ergänzen]"


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _r(wert: Any, stellen: int = 6) -> float | None:
    """Rundet auf eine feste Stellenzahl -- Determinismus vor Scheingenauigkeit."""
    if wert is None:
        return None
    zahl = float(wert)
    if not math.isfinite(zahl):
        return None
    return round(zahl, stellen)


def _rp(wert: Any) -> float | None:
    """Rundet p-Werte auf 8 signifikante Stellen statt auf 8 Nachkommastellen.

    Feste Nachkommastellen machten aus p = 6.7e-10 eine Null -- und aus "so
    deutlich wie es die Zahl hergibt" ein "exakt null", das keine Software
    liefern kann. Signifikante Stellen halten die Groessenordnung fest und
    bleiben trotzdem zwischen zwei Laeufen identisch.
    """
    if wert is None:
        return None
    zahl = float(wert)
    if not math.isfinite(zahl):
        return None
    return float(f"{zahl:.8g}")


def datei_sha256(pfad: Path) -> str:
    """SHA-256 der Rohdatei -- die Bruecke zwischen Bericht und Datensatz."""
    hasher = hashlib.sha256()
    with open(pfad, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            hasher.update(block)
    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# Datensatz
# ---------------------------------------------------------------------------


class Datensatz:
    """Eine eingelesene CSV-Tabelle mit expliziter Fehlwert-Kodierung."""

    def __init__(self, spalten: dict[str, list[str]], fehlende: Sequence[str], quelle: Path):
        self.spalten = spalten
        self.fehlende = {f.strip() for f in fehlende}
        self.quelle = quelle

    # -- Rohzugriff ---------------------------------------------------------

    def _spalte(self, name: str) -> list[str]:
        if name not in self.spalten:
            raise ValueError(f"Spalte '{name}' existiert nicht. Vorhanden: {sorted(self.spalten)}")
        return self.spalten[name]

    def _fehlt(self, roh: str) -> bool:
        return roh.strip() in self.fehlende

    @property
    def n_zeilen(self) -> int:
        return len(next(iter(self.spalten.values()))) if self.spalten else 0

    # -- typisierter Zugriff ------------------------------------------------

    def metrisch(self, name: str) -> np.ndarray:
        """Numerische Werte einer Spalte ohne Fehlwerte (fallweiser Ausschluss)."""
        werte: list[float] = []
        for roh in self._spalte(name):
            if self._fehlt(roh):
                continue
            try:
                werte.append(float(roh.replace(",", ".")))
            except ValueError as exc:
                raise ValueError(
                    f"Spalte '{name}' ist als metrisch geplant, enthaelt aber '{roh}'."
                ) from exc
        return np.asarray(werte, dtype=float)

    def n_fehlend(self, name: str) -> int:
        return sum(1 for roh in self._spalte(name) if self._fehlt(roh))

    def kategorial(self, name: str) -> list[str]:
        return [roh.strip() for roh in self._spalte(name) if not self._fehlt(roh)]

    def gruppiert(self, messwert: str, gruppierung: str) -> dict[str, np.ndarray]:
        """Messwerte je Auspraegung der Gruppierungsvariable, listenweise bereinigt."""
        mess = self._spalte(messwert)
        grp = self._spalte(gruppierung)
        gesammelt: dict[str, list[float]] = {}
        for m_roh, g_roh in zip(mess, grp, strict=True):
            if self._fehlt(m_roh) or self._fehlt(g_roh):
                continue
            try:
                zahl = float(m_roh.replace(",", "."))
            except ValueError as exc:
                raise ValueError(
                    f"Spalte '{messwert}' ist als metrisch geplant, enthaelt aber '{m_roh}'."
                ) from exc
            gesammelt.setdefault(g_roh.strip(), []).append(zahl)
        return {
            schluessel: np.asarray(gesammelt[schluessel], dtype=float)
            for schluessel in sorted(gesammelt)
        }

    def paare(self, erste: str, zweite: str) -> tuple[np.ndarray, np.ndarray]:
        """Zwei metrische Spalten, fallweise komplett (listenweiser Ausschluss)."""
        a_roh = self._spalte(erste)
        b_roh = self._spalte(zweite)
        a_werte: list[float] = []
        b_werte: list[float] = []
        for a, b in zip(a_roh, b_roh, strict=True):
            if self._fehlt(a) or self._fehlt(b):
                continue
            try:
                a_werte.append(float(a.replace(",", ".")))
                b_werte.append(float(b.replace(",", ".")))
            except ValueError as exc:
                raise ValueError(
                    f"Spalten '{erste}'/'{zweite}' sind als metrisch geplant, "
                    f"enthalten aber nicht-numerische Werte."
                ) from exc
        return np.asarray(a_werte, dtype=float), np.asarray(b_werte, dtype=float)

    def kategorial_paare(self, erste: str, zweite: str) -> tuple[list[str], list[str]]:
        a_roh = self._spalte(erste)
        b_roh = self._spalte(zweite)
        a_werte: list[str] = []
        b_werte: list[str] = []
        for a, b in zip(a_roh, b_roh, strict=True):
            if self._fehlt(a) or self._fehlt(b):
                continue
            a_werte.append(a.strip())
            b_werte.append(b.strip())
        return a_werte, b_werte


def lade_datensatz(pfad: Path | str, fehlende_werte: Sequence[str] | None = None) -> Datensatz:
    """Liest eine CSV-Datei ein. Kein pandas -- die stdlib reicht und bleibt lesbar."""
    pfad = Path(pfad)
    with open(pfad, newline="", encoding="utf-8-sig") as fh:
        leser = csv.DictReader(fh)
        if not leser.fieldnames:
            raise ValueError(f"{pfad}: keine Kopfzeile gefunden.")
        spalten: dict[str, list[str]] = {name: [] for name in leser.fieldnames}
        for zeile in leser:
            for name in leser.fieldnames:
                spalten[name].append((zeile.get(name) or "").strip())
    return Datensatz(spalten, fehlende_werte or STANDARD_FEHLWERTE, pfad)


# ---------------------------------------------------------------------------
# Kreuztabelle
# ---------------------------------------------------------------------------


def kreuztabelle(a: Sequence[str], b: Sequence[str]) -> tuple[list[str], list[str], np.ndarray]:
    zeilen = sorted(set(a))
    spalten = sorted(set(b))
    tabelle = np.zeros((len(zeilen), len(spalten)), dtype=float)
    zeilen_index = {name: i for i, name in enumerate(zeilen)}
    spalten_index = {name: i for i, name in enumerate(spalten)}
    for links, rechts in zip(a, b, strict=True):
        tabelle[zeilen_index[links], spalten_index[rechts]] += 1
    return zeilen, spalten, tabelle


# ---------------------------------------------------------------------------
# Effektstaerken
# ---------------------------------------------------------------------------


def cohens_d(x: np.ndarray, y: np.ndarray) -> float:
    n1, n2 = len(x), len(y)
    s_pooled = math.sqrt(
        ((n1 - 1) * float(np.var(x, ddof=1)) + (n2 - 1) * float(np.var(y, ddof=1))) / (n1 + n2 - 2)
    )
    if s_pooled == 0:
        return 0.0
    return (float(np.mean(x)) - float(np.mean(y))) / s_pooled


def hedges_g(x: np.ndarray, y: np.ndarray) -> float:
    """Cohen's d mit Kleinstichproben-Korrektur (Hedges 1981)."""
    n1, n2 = len(x), len(y)
    korrektur = 1 - 3 / (4 * (n1 + n2) - 9)
    return cohens_d(x, y) * korrektur


def cohens_d_gepaart(vorher: np.ndarray, nachher: np.ndarray) -> float:
    """d_z: Mittelwert der Differenzen, standardisiert an deren Streuung."""
    differenz = nachher - vorher
    sd = float(np.std(differenz, ddof=1))
    if sd == 0:
        return 0.0
    return float(np.mean(differenz)) / sd


def _mann_whitney_u(x: np.ndarray, y: np.ndarray) -> float:
    gemeinsam = np.concatenate([x, y])
    raenge = stats.rankdata(gemeinsam)
    r1 = float(np.sum(raenge[: len(x)]))
    return r1 - len(x) * (len(x) + 1) / 2


def rang_biserial(x: np.ndarray, y: np.ndarray) -> float:
    """Rang-biseriale Korrelation aus U (Kerby 2014): 2U/(n1*n2) - 1."""
    u = _mann_whitney_u(x, y)
    return 2 * u / (len(x) * len(y)) - 1


def rang_biserial_gepaart(vorher: np.ndarray, nachher: np.ndarray) -> float:
    """Matched-pairs rank-biserial: (R+ - R-) / Summe aller Raenge."""
    differenz = nachher - vorher
    differenz = differenz[differenz != 0]
    if len(differenz) == 0:
        return 0.0
    raenge = stats.rankdata(np.abs(differenz))
    positiv = float(np.sum(raenge[differenz > 0]))
    negativ = float(np.sum(raenge[differenz < 0]))
    gesamt = positiv + negativ
    if gesamt == 0:
        return 0.0
    return (positiv - negativ) / gesamt


def eta_quadrat(gruppen: Sequence[np.ndarray]) -> float:
    alle = np.concatenate(list(gruppen))
    gesamtmittel = float(np.mean(alle))
    ss_zwischen = sum(len(g) * (float(np.mean(g)) - gesamtmittel) ** 2 for g in gruppen)
    ss_gesamt = float(np.sum((alle - gesamtmittel) ** 2))
    if ss_gesamt == 0:
        return 0.0
    return ss_zwischen / ss_gesamt


def epsilon_quadrat(gruppen: Sequence[np.ndarray]) -> float:
    """epsilon^2 zum Kruskal-Wallis-H (Tomczak & Tomczak 2014)."""
    h = float(stats.kruskal(*gruppen).statistic)
    n = sum(len(g) for g in gruppen)
    k = len(gruppen)
    if n - k <= 0:
        return 0.0
    return (h - k + 1) / (n - k)


def cramers_v(a: Sequence[str], b: Sequence[str]) -> float:
    _, _, tabelle = kreuztabelle(a, b)
    if min(tabelle.shape) < 2:
        return 0.0
    chi2 = float(stats.chi2_contingency(tabelle, correction=False).statistic)
    n = float(tabelle.sum())
    if n == 0:
        return 0.0
    return math.sqrt(chi2 / (n * (min(tabelle.shape) - 1)))


# ---------------------------------------------------------------------------
# Bootstrap-Konfidenzintervalle
# ---------------------------------------------------------------------------


def _resample_getrennt(stichproben: list[Any], rng: np.random.Generator) -> list[Any]:
    """Jede Gruppe fuer sich ziehen -- der Zwei-/Mehrstichproben-Fall."""
    gezogen = []
    for probe in stichproben:
        index = rng.integers(0, len(probe), len(probe))
        gezogen.append(np.asarray(probe)[index])
    return gezogen


def _resample_gepaart(stichproben: list[Any], rng: np.random.Generator) -> list[Any]:
    """Alle Vektoren mit demselben Index ziehen -- Paare bleiben Paare."""
    laenge = len(stichproben[0])
    index = rng.integers(0, laenge, laenge)
    return [np.asarray(probe)[index] for probe in stichproben]


def bootstrap_ci(
    effekt_fn: Callable[[list[Any]], float],
    stichproben: list[Any],
    *,
    gepaart: bool,
    seed: int,
    replikationen: int,
    niveau: float,
) -> tuple[float | None, float | None, str]:
    """Perzentil-Bootstrap. Deterministisch ueber Seed -- derselbe Lauf, dasselbe Intervall."""
    rng = np.random.default_rng(seed)
    ziehen = _resample_gepaart if gepaart else _resample_getrennt
    werte: list[float] = []
    for _ in range(replikationen):
        try:
            wert = effekt_fn(ziehen(stichproben, rng))
        except (ValueError, ZeroDivisionError, IndexError):
            continue
        if wert is not None and math.isfinite(wert):
            werte.append(float(wert))
    methode = (
        f"Perzentil-Bootstrap (B = {replikationen}, Seed = {seed}, "
        f"{len(werte)} verwertbare Replikationen)"
    )
    if len(werte) < 100:
        return None, None, methode + " — zu wenige verwertbare Replikationen"
    rest = 1 - niveau
    lo = float(np.quantile(werte, rest / 2))
    hi = float(np.quantile(werte, 1 - rest / 2))
    return lo, hi, methode


def _t_ci_differenz(
    differenz: float, standardfehler: float, df: float, niveau: float
) -> tuple[float, float]:
    kritisch = float(stats.t.ppf(1 - (1 - niveau) / 2, df))
    return differenz - kritisch * standardfehler, differenz + kritisch * standardfehler


# ---------------------------------------------------------------------------
# Voraussetzungspruefungen
# ---------------------------------------------------------------------------


def _voraussetzung(
    name: str,
    bezug: str,
    kennwert: float | None,
    p: float | None,
    schwelle: str,
    verletzt: bool,
    alternative: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "bezug": bezug,
        "kennwert": _r(kennwert),
        "p": _rp(p),
        "schwelle": schwelle,
        "verletzt": bool(verletzt),
        "alternative": alternative if verletzt else "",
    }


def _shapiro(werte: np.ndarray, bezug: str, alpha: float, alternative: str) -> dict[str, Any]:
    if len(werte) < 3:
        return _voraussetzung(
            "Normalverteilung (Shapiro-Wilk)",
            bezug,
            None,
            None,
            "n >= 3 für den Test",
            True,
            alternative,
        )
    ergebnis = stats.shapiro(werte)
    return _voraussetzung(
        "Normalverteilung (Shapiro-Wilk)",
        bezug,
        float(ergebnis.statistic),
        float(ergebnis.pvalue),
        f"p >= {alpha}",
        float(ergebnis.pvalue) < alpha,
        alternative,
    )


def _levene(gruppen: Sequence[np.ndarray], alpha: float, alternative: str) -> dict[str, Any]:
    ergebnis = stats.levene(*gruppen, center="median")
    return _voraussetzung(
        "Varianzhomogenität (Levene-Test, Median-zentriert)",
        "alle Gruppen",
        float(ergebnis.statistic),
        float(ergebnis.pvalue),
        f"p >= {alpha}",
        float(ergebnis.pvalue) < alpha,
        alternative,
    )


def _mindestbesetzung(
    gruppen: dict[str, np.ndarray], mindest: int, alternative: str
) -> dict[str, Any]:
    kleinste = min(len(g) for g in gruppen.values())
    return _voraussetzung(
        f"Mindestfallzahl je Gruppe (n >= {mindest})",
        min(gruppen, key=lambda k: len(gruppen[k])),
        float(kleinste),
        None,
        f"n >= {mindest}",
        kleinste < mindest,
        alternative,
    )


# ---------------------------------------------------------------------------
# Verfahren
# ---------------------------------------------------------------------------


def _zwei_gruppen(daten: Datensatz, analyse: dict) -> tuple[str, str, np.ndarray, np.ndarray]:
    messwert = analyse["messwert"]
    gruppierung = analyse["gruppierung"]
    gruppen = daten.gruppiert(messwert, gruppierung)
    if len(gruppen) != 2:
        raise ValueError(
            f"{analyse['id']}: '{gruppierung}' hat {len(gruppen)} Auspraegungen, "
            f"der Zweigruppenvergleich braucht genau 2."
        )
    (name_a, x), (name_b, y) = list(gruppen.items())
    return name_a, name_b, x, y


def _gruppen_kennwerte(gruppen: dict[str, np.ndarray]) -> dict[str, dict[str, float | None]]:
    return {
        name: {
            "n": float(len(werte)),
            "m": _r(np.mean(werte)),
            "sd": _r(np.std(werte, ddof=1)) if len(werte) > 1 else None,
        }
        for name, werte in gruppen.items()
    }


def verfahren_t_test_unabhaengig(daten: Datensatz, analyse: dict, konf: dict) -> dict[str, Any]:
    name_a, name_b, x, y = _zwei_gruppen(daten, analyse)
    alpha = konf["alpha"]
    ergebnis = stats.ttest_ind(x, y, equal_var=True)
    df = len(x) + len(y) - 2
    effekt = hedges_g(x, y)
    lo, hi, methode = bootstrap_ci(
        lambda proben: hedges_g(proben[0], proben[1]),
        [x, y],
        gepaart=False,
        seed=konf["seed"],
        replikationen=konf["replikationen"],
        niveau=konf["niveau"],
    )
    s_pooled = math.sqrt(
        ((len(x) - 1) * float(np.var(x, ddof=1)) + (len(y) - 1) * float(np.var(y, ddof=1))) / df
    )
    se = s_pooled * math.sqrt(1 / len(x) + 1 / len(y))
    diff = float(np.mean(x)) - float(np.mean(y))
    diff_lo, diff_hi = _t_ci_differenz(diff, se, df, konf["niveau"])
    return {
        "verfahren": "t_test_unabhaengig",
        "typ": "inferenz",
        "frage": f"{analyse['messwert']} nach {analyse['gruppierung']} ({name_a} vs. {name_b})",
        "n": len(x) + len(y),
        "gruppen": _gruppen_kennwerte({name_a: x, name_b: y}),
        "statistik": {"name": "t", "wert": _r(ergebnis.statistic), "df": float(df)},
        "p": _rp(ergebnis.pvalue),
        "effekt": {"name": "Hedges' g", "wert": _r(effekt)},
        "ci": {
            "bezug": "Hedges' g",
            "lo": _r(lo),
            "hi": _r(hi),
            "niveau": konf["niveau"],
            "methode": methode,
        },
        "zusatz": [
            {
                "name": "Mittelwertdifferenz",
                "wert": _r(diff),
                "ci": {
                    "lo": _r(diff_lo),
                    "hi": _r(diff_hi),
                    "niveau": konf["niveau"],
                    "methode": f"analytisch (t-Verteilung, df = {df})",
                },
            }
        ],
        "voraussetzungen": [
            _shapiro(x, f"Gruppe {name_a}", alpha, "Mann-Whitney-U-Test"),
            _shapiro(y, f"Gruppe {name_b}", alpha, "Mann-Whitney-U-Test"),
            _levene([x, y], alpha, "Welch-Test (t_test ohne Varianzhomogenitätsannahme)"),
        ],
        "hinweise": [],
    }


def verfahren_welch_test(daten: Datensatz, analyse: dict, konf: dict) -> dict[str, Any]:
    name_a, name_b, x, y = _zwei_gruppen(daten, analyse)
    alpha = konf["alpha"]
    ergebnis = stats.ttest_ind(x, y, equal_var=False)
    df = float(ergebnis.df)
    effekt = hedges_g(x, y)
    lo, hi, methode = bootstrap_ci(
        lambda proben: hedges_g(proben[0], proben[1]),
        [x, y],
        gepaart=False,
        seed=konf["seed"],
        replikationen=konf["replikationen"],
        niveau=konf["niveau"],
    )
    se = math.sqrt(float(np.var(x, ddof=1)) / len(x) + float(np.var(y, ddof=1)) / len(y))
    diff = float(np.mean(x)) - float(np.mean(y))
    diff_lo, diff_hi = _t_ci_differenz(diff, se, df, konf["niveau"])
    return {
        "verfahren": "welch_test",
        "typ": "inferenz",
        "frage": f"{analyse['messwert']} nach {analyse['gruppierung']} ({name_a} vs. {name_b})",
        "n": len(x) + len(y),
        "gruppen": _gruppen_kennwerte({name_a: x, name_b: y}),
        "statistik": {"name": "t", "wert": _r(ergebnis.statistic), "df": _r(df)},
        "p": _rp(ergebnis.pvalue),
        "effekt": {"name": "Hedges' g", "wert": _r(effekt)},
        "ci": {
            "bezug": "Hedges' g",
            "lo": _r(lo),
            "hi": _r(hi),
            "niveau": konf["niveau"],
            "methode": methode,
        },
        "zusatz": [
            {
                "name": "Mittelwertdifferenz",
                "wert": _r(diff),
                "ci": {
                    "lo": _r(diff_lo),
                    "hi": _r(diff_hi),
                    "niveau": konf["niveau"],
                    "methode": f"analytisch (Welch-Satterthwaite, df = {df:.2f})",
                },
            }
        ],
        "voraussetzungen": [
            _shapiro(x, f"Gruppe {name_a}", alpha, "Mann-Whitney-U-Test"),
            _shapiro(y, f"Gruppe {name_b}", alpha, "Mann-Whitney-U-Test"),
        ],
        "hinweise": [
            "Der Welch-Test setzt keine Varianzhomogenität voraus; ein Levene-Test "
            "entfällt hier bewusst."
        ],
    }


def _gepaarte_werte(daten: Datensatz, analyse: dict) -> tuple[str, str, np.ndarray, np.ndarray]:
    vorher = analyse["messwert_vorher"]
    nachher = analyse["messwert_nachher"]
    a, b = daten.paare(vorher, nachher)
    if len(a) < 3:
        raise ValueError(f"{analyse['id']}: zu wenige vollstaendige Paare ({len(a)}).")
    return vorher, nachher, a, b


def verfahren_t_test_gepaart(daten: Datensatz, analyse: dict, konf: dict) -> dict[str, Any]:
    name_v, name_n, vorher, nachher = _gepaarte_werte(daten, analyse)
    alpha = konf["alpha"]
    ergebnis = stats.ttest_rel(nachher, vorher)
    df = len(vorher) - 1
    differenz = nachher - vorher
    effekt = cohens_d_gepaart(vorher, nachher)
    lo, hi, methode = bootstrap_ci(
        lambda proben: cohens_d_gepaart(proben[0], proben[1]),
        [vorher, nachher],
        gepaart=True,
        seed=konf["seed"],
        replikationen=konf["replikationen"],
        niveau=konf["niveau"],
    )
    se = float(np.std(differenz, ddof=1)) / math.sqrt(len(differenz))
    diff_lo, diff_hi = _t_ci_differenz(float(np.mean(differenz)), se, df, konf["niveau"])
    return {
        "verfahren": "t_test_gepaart",
        "typ": "inferenz",
        "frage": f"{name_n} gegen {name_v} (verbundene Stichproben)",
        "n": len(vorher),
        "statistik": {"name": "t", "wert": _r(ergebnis.statistic), "df": float(df)},
        "p": _rp(ergebnis.pvalue),
        "effekt": {"name": "Cohen's d_z", "wert": _r(effekt)},
        "ci": {
            "bezug": "Cohen's d_z",
            "lo": _r(lo),
            "hi": _r(hi),
            "niveau": konf["niveau"],
            "methode": methode,
        },
        "zusatz": [
            {
                "name": "mittlere Differenz",
                "wert": _r(np.mean(differenz)),
                "ci": {
                    "lo": _r(diff_lo),
                    "hi": _r(diff_hi),
                    "niveau": konf["niveau"],
                    "methode": f"analytisch (t-Verteilung, df = {df})",
                },
            }
        ],
        "voraussetzungen": [
            _shapiro(
                differenz,
                "Differenzen der Messwertpaare",
                alpha,
                "Wilcoxon-Vorzeichen-Rang-Test",
            )
        ],
        "hinweise": [
            "Geprüft wird die Verteilung der Differenzen, nicht die der beiden Einzelmessungen."
        ],
    }


def verfahren_mann_whitney_u(daten: Datensatz, analyse: dict, konf: dict) -> dict[str, Any]:
    name_a, name_b, x, y = _zwei_gruppen(daten, analyse)
    ergebnis = stats.mannwhitneyu(x, y, alternative="two-sided")
    effekt = rang_biserial(x, y)
    lo, hi, methode = bootstrap_ci(
        lambda proben: rang_biserial(proben[0], proben[1]),
        [x, y],
        gepaart=False,
        seed=konf["seed"],
        replikationen=konf["replikationen"],
        niveau=konf["niveau"],
    )
    return {
        "verfahren": "mann_whitney_u",
        "typ": "inferenz",
        "frage": f"{analyse['messwert']} nach {analyse['gruppierung']} ({name_a} vs. {name_b})",
        "n": len(x) + len(y),
        "gruppen": _gruppen_kennwerte({name_a: x, name_b: y}),
        "statistik": {"name": "U", "wert": _r(ergebnis.statistic), "df": None},
        "p": _rp(ergebnis.pvalue),
        "effekt": {"name": "rangbiseriale Korrelation r", "wert": _r(effekt)},
        "ci": {
            "bezug": "rangbiseriale Korrelation r",
            "lo": _r(lo),
            "hi": _r(hi),
            "niveau": konf["niveau"],
            "methode": methode,
        },
        "voraussetzungen": [
            _mindestbesetzung(
                {name_a: x, name_b: y},
                5,
                "exakte Berechnung statt Normalapproximation",
            ),
            _voraussetzung(
                "Vergleichbare Verteilungsform beider Gruppen",
                f"{name_a} / {name_b}",
                float(abs(float(stats.skew(x)) - float(stats.skew(y)))),
                None,
                "Schiefedifferenz als Anhaltspunkt, kein Test",
                False,
                "",
            ),
        ],
        "hinweise": [
            "Der Test vergleicht Rangsummen. Als Lageaussage über Mediane ist er nur "
            "bei vergleichbarer Verteilungsform lesbar — die Schiefedifferenz oben ist "
            "dafür ein Anhaltspunkt, kein Nachweis."
        ],
    }


def verfahren_wilcoxon(daten: Datensatz, analyse: dict, konf: dict) -> dict[str, Any]:
    name_v, name_n, vorher, nachher = _gepaarte_werte(daten, analyse)
    ergebnis = stats.wilcoxon(nachher, vorher)
    effekt = rang_biserial_gepaart(vorher, nachher)
    lo, hi, methode = bootstrap_ci(
        lambda proben: rang_biserial_gepaart(proben[0], proben[1]),
        [vorher, nachher],
        gepaart=True,
        seed=konf["seed"],
        replikationen=konf["replikationen"],
        niveau=konf["niveau"],
    )
    differenz = nachher - vorher
    nullen = int(np.sum(differenz == 0))
    return {
        "verfahren": "wilcoxon",
        "typ": "inferenz",
        "frage": f"{name_n} gegen {name_v} (verbundene Stichproben, rangbasiert)",
        "n": len(vorher),
        "statistik": {"name": "W", "wert": _r(ergebnis.statistic), "df": None},
        "p": _rp(ergebnis.pvalue),
        "effekt": {"name": "rangbiseriale Korrelation r (matched pairs)", "wert": _r(effekt)},
        "ci": {
            "bezug": "rangbiseriale Korrelation r (matched pairs)",
            "lo": _r(lo),
            "hi": _r(hi),
            "niveau": konf["niveau"],
            "methode": methode,
        },
        "voraussetzungen": [
            _voraussetzung(
                "Mindestzahl auswertbarer Paare (n >= 6)",
                "Differenzen ungleich null",
                float(len(differenz) - nullen),
                None,
                "n >= 6",
                (len(differenz) - nullen) < 6,
                "exakter Vorzeichentest",
            ),
            _voraussetzung(
                "Symmetrie der Differenzverteilung",
                "Differenzen der Messwertpaare",
                float(stats.skew(differenz)),
                None,
                "Schiefe nahe 0 (Anhaltspunkt, kein Test)",
                abs(float(stats.skew(differenz))) > 1.0,
                "Vorzeichentest",
            ),
        ],
        "hinweise": [f"{nullen} Paare mit Differenz null gehen nicht in die Rangbildung ein."],
    }


def _k_gruppen(daten: Datensatz, analyse: dict) -> dict[str, np.ndarray]:
    gruppen = daten.gruppiert(analyse["messwert"], analyse["gruppierung"])
    if len(gruppen) < 3:
        raise ValueError(
            f"{analyse['id']}: '{analyse['gruppierung']}' hat nur {len(gruppen)} "
            f"Auspraegungen — fuer den Mehrgruppenvergleich sind mindestens 3 noetig."
        )
    return gruppen


def verfahren_anova_einfaktoriell(daten: Datensatz, analyse: dict, konf: dict) -> dict[str, Any]:
    gruppen = _k_gruppen(daten, analyse)
    alpha = konf["alpha"]
    werte = list(gruppen.values())
    ergebnis = stats.f_oneway(*werte)
    k = len(werte)
    n = sum(len(g) for g in werte)
    effekt = eta_quadrat(werte)
    lo, hi, methode = bootstrap_ci(
        eta_quadrat,
        werte,
        gepaart=False,
        seed=konf["seed"],
        replikationen=konf["replikationen"],
        niveau=konf["niveau"],
    )
    voraussetzungen = [
        _shapiro(w, f"Gruppe {name}", alpha, "Kruskal-Wallis-Test") for name, w in gruppen.items()
    ]
    voraussetzungen.append(_levene(werte, alpha, "Kruskal-Wallis-Test"))
    return {
        "verfahren": "anova_einfaktoriell",
        "typ": "inferenz",
        "frage": f"{analyse['messwert']} über die Stufen von {analyse['gruppierung']}",
        "n": n,
        "gruppen": _gruppen_kennwerte(gruppen),
        "statistik": {
            "name": "F",
            "wert": _r(ergebnis.statistic),
            "df": [float(k - 1), float(n - k)],
        },
        "p": _rp(ergebnis.pvalue),
        "effekt": {"name": "η²", "wert": _r(effekt)},
        "ci": {
            "bezug": "η²",
            "lo": _r(lo),
            "hi": _r(hi),
            "niveau": konf["niveau"],
            "methode": methode,
        },
        "voraussetzungen": voraussetzungen,
        "hinweise": [
            "Berichtet wird ausschließlich der Omnibus-Test: er sagt, dass sich "
            "mindestens zwei Stufen unterscheiden, nicht welche. Post-hoc-Vergleiche "
            "(Tukey, Bonferroni-korrigierte Paarvergleiche) sind in dieser Fassung "
            "nicht abgedeckt — sie hier von Hand nachzuschieben, wäre unkontrolliertes "
            "Mehrfachtesten."
        ],
    }


def verfahren_kruskal_wallis(daten: Datensatz, analyse: dict, konf: dict) -> dict[str, Any]:
    gruppen = _k_gruppen(daten, analyse)
    werte = list(gruppen.values())
    ergebnis = stats.kruskal(*werte)
    effekt = epsilon_quadrat(werte)
    lo, hi, methode = bootstrap_ci(
        epsilon_quadrat,
        werte,
        gepaart=False,
        seed=konf["seed"],
        replikationen=konf["replikationen"],
        niveau=konf["niveau"],
    )
    return {
        "verfahren": "kruskal_wallis",
        "typ": "inferenz",
        "frage": f"{analyse['messwert']} über die Stufen von {analyse['gruppierung']} (rangbasiert)",
        "n": sum(len(g) for g in werte),
        "gruppen": _gruppen_kennwerte(gruppen),
        "statistik": {"name": "H", "wert": _r(ergebnis.statistic), "df": float(len(werte) - 1)},
        "p": _rp(ergebnis.pvalue),
        "effekt": {"name": "ε²", "wert": _r(effekt)},
        "ci": {
            "bezug": "ε²",
            "lo": _r(lo),
            "hi": _r(hi),
            "niveau": konf["niveau"],
            "methode": methode,
        },
        "voraussetzungen": [
            _mindestbesetzung(gruppen, 5, "exakte Berechnung statt Chi-Quadrat-Approximation")
        ],
        "hinweise": [
            "Auch hier gilt: Omnibus-Test ohne Post-hoc-Vergleiche (Dunn-Test nicht abgedeckt)."
        ],
    }


def verfahren_chi_quadrat_unabhaengigkeit(
    daten: Datensatz, analyse: dict, konf: dict
) -> dict[str, Any]:
    erste, zweite = analyse["merkmale"]
    a, b = daten.kategorial_paare(erste, zweite)
    zeilen, spalten, tabelle = kreuztabelle(a, b)
    if min(tabelle.shape) < 2:
        raise ValueError(f"{analyse['id']}: Kreuztabelle mit weniger als 2x2 Feldern.")
    ergebnis = stats.chi2_contingency(tabelle, correction=False)
    erwartet_min = float(np.min(ergebnis.expected_freq))
    effekt = cramers_v(a, b)
    lo, hi, methode = bootstrap_ci(
        lambda proben: cramers_v(list(proben[0]), list(proben[1])),
        [np.asarray(a, dtype=object), np.asarray(b, dtype=object)],
        gepaart=True,
        seed=konf["seed"],
        replikationen=konf["replikationen"],
        niveau=konf["niveau"],
    )
    hinweise = [
        "Die Kreuztabelle steht vollständig im Ergebnis-JSON und gehört mit in den Ergebnisteil.",
    ]
    if tabelle.shape == (2, 2) and erwartet_min < 5:
        fisher = stats.fisher_exact(tabelle)
        hinweise.append(
            f"Bei 2×2 und kleinen erwarteten Häufigkeiten ist der exakte Test nach "
            f"Fisher die Alternative (p = {float(fisher.pvalue):.4f}). Das geplante "
            f"Verfahren bleibt unverändert der χ²-Test — der Wechsel ist eine "
            f"Entscheidung der Autorin."
        )
    return {
        "verfahren": "chi_quadrat_unabhaengigkeit",
        "typ": "inferenz",
        "frage": f"Zusammenhang von {erste} und {zweite}",
        "n": int(tabelle.sum()),
        "kreuztabelle": {
            "zeilen": zeilen,
            "spalten": spalten,
            "werte": [[int(z) for z in zeile] for zeile in tabelle],
        },
        "statistik": {
            "name": "χ²",
            "wert": _r(ergebnis.statistic),
            "df": float(ergebnis.dof),
        },
        "p": _rp(ergebnis.pvalue),
        "effekt": {"name": "Cramérs V", "wert": _r(effekt)},
        "ci": {
            "bezug": "Cramérs V",
            "lo": _r(lo),
            "hi": _r(hi),
            "niveau": konf["niveau"],
            "methode": methode,
        },
        "voraussetzungen": [
            _voraussetzung(
                "Kleinste erwartete Zellhäufigkeit",
                "alle Felder der Kreuztabelle",
                erwartet_min,
                None,
                "erwartete Häufigkeit >= 5 in jedem Feld",
                erwartet_min < 5,
                "exakter Test nach Fisher (2×2) bzw. Zusammenfassen von Kategorien",
            ),
            _voraussetzung(
                "Unabhängige Beobachtungen",
                "Datensatz",
                float(tabelle.sum()),
                None,
                "eine Zeile = ein Fall",
                False,
                "",
            ),
        ],
        "hinweise": hinweise,
    }


def verfahren_pearson_r(daten: Datensatz, analyse: dict, konf: dict) -> dict[str, Any]:
    erste, zweite = analyse["merkmale"]
    alpha = konf["alpha"]
    x, y = daten.paare(erste, zweite)
    ergebnis = stats.pearsonr(x, y)
    intervall = ergebnis.confidence_interval(confidence_level=konf["niveau"])
    return {
        "verfahren": "pearson_r",
        "typ": "inferenz",
        "frage": f"linearer Zusammenhang von {erste} und {zweite}",
        "n": len(x),
        "statistik": {"name": "r", "wert": _r(ergebnis.statistic), "df": float(len(x) - 2)},
        "p": _rp(ergebnis.pvalue),
        "effekt": {"name": "Pearson r", "wert": _r(ergebnis.statistic)},
        "ci": {
            "bezug": "Pearson r",
            "lo": _r(intervall.low),
            "hi": _r(intervall.high),
            "niveau": konf["niveau"],
            "methode": "analytisch (Fisher-z-Transformation)",
        },
        "voraussetzungen": [
            _shapiro(x, f"Merkmal {erste}", alpha, "Spearman-Rangkorrelation"),
            _shapiro(y, f"Merkmal {zweite}", alpha, "Spearman-Rangkorrelation"),
        ],
        "hinweise": [
            "Linearität und Ausreißerfreiheit sind mit einem Streudiagramm zu prüfen; "
            "r allein trennt sie nicht."
        ],
    }


def verfahren_spearman_rho(daten: Datensatz, analyse: dict, konf: dict) -> dict[str, Any]:
    erste, zweite = analyse["merkmale"]
    x, y = daten.paare(erste, zweite)
    ergebnis = stats.spearmanr(x, y)
    lo, hi, methode = bootstrap_ci(
        lambda proben: float(stats.spearmanr(proben[0], proben[1]).statistic),
        [x, y],
        gepaart=True,
        seed=konf["seed"],
        replikationen=konf["replikationen"],
        niveau=konf["niveau"],
    )
    return {
        "verfahren": "spearman_rho",
        "typ": "inferenz",
        "frage": f"monotoner Zusammenhang von {erste} und {zweite}",
        "n": len(x),
        "statistik": {"name": "ρ", "wert": _r(ergebnis.statistic), "df": float(len(x) - 2)},
        "p": _rp(ergebnis.pvalue),
        "effekt": {"name": "Spearman ρ", "wert": _r(ergebnis.statistic)},
        "ci": {
            "bezug": "Spearman ρ",
            "lo": _r(lo),
            "hi": _r(hi),
            "niveau": konf["niveau"],
            "methode": methode,
        },
        "voraussetzungen": [
            _voraussetzung(
                "Mindestfallzahl (n >= 10)",
                "vollständige Wertepaare",
                float(len(x)),
                None,
                "n >= 10",
                len(x) < 10,
                "exakte Permutationsverteilung",
            ),
            _voraussetzung(
                "Monotoner Zusammenhang",
                f"{erste} / {zweite}",
                _r(ergebnis.statistic),
                None,
                "im Streudiagramm zu beurteilen, kein Test",
                False,
                "",
            ),
        ],
        "hinweise": [
            "ρ misst monotone, nicht lineare Zusammenhänge; Bindungen werden über "
            "Durchschnittsränge behandelt."
        ],
    }


def verfahren_deskriptiv(daten: Datensatz, analyse: dict, konf: dict) -> dict[str, Any]:
    variablen: dict[str, dict[str, Any]] = {}
    skalen = konf.get("variablen", {})
    for name in analyse["variablen"]:
        skala = skalen.get(name, "metrisch")
        n_fehlend = daten.n_fehlend(name)
        if skala in ("nominal", "ordinal", "ordinal_kategorial"):
            werte = daten.kategorial(name)
            haeufigkeiten: dict[str, int] = {}
            for wert in werte:
                haeufigkeiten[wert] = haeufigkeiten.get(wert, 0) + 1
            variablen[name] = {
                "skala": skala,
                "n": len(werte),
                "n_fehlend": n_fehlend,
                "haeufigkeiten": {k: haeufigkeiten[k] for k in sorted(haeufigkeiten)},
            }
        else:
            werte_num = daten.metrisch(name)
            q1, q3 = (
                (float(np.quantile(werte_num, 0.25)), float(np.quantile(werte_num, 0.75)))
                if len(werte_num)
                else (float("nan"), float("nan"))
            )
            variablen[name] = {
                "skala": skala,
                "n": len(werte_num),
                "n_fehlend": n_fehlend,
                "m": _r(np.mean(werte_num)) if len(werte_num) else None,
                "sd": _r(np.std(werte_num, ddof=1)) if len(werte_num) > 1 else None,
                "median": _r(np.median(werte_num)) if len(werte_num) else None,
                "iqr": _r(q3 - q1) if len(werte_num) else None,
                "min": _r(np.min(werte_num)) if len(werte_num) else None,
                "max": _r(np.max(werte_num)) if len(werte_num) else None,
            }
    return {
        "verfahren": "deskriptiv",
        "typ": "deskriptiv",
        "frage": "Verteilung der Variablen " + ", ".join(analyse["variablen"]),
        "n": daten.n_zeilen,
        "variablen": variablen,
        "hinweise": [
            "Fehlende Werte werden fallweise ausgeschlossen und je Variable "
            "ausgewiesen — sie verschwinden nicht stillschweigend."
        ],
    }


VERFAHREN: dict[str, Callable[[Datensatz, dict, dict], dict[str, Any]]] = {
    "deskriptiv": verfahren_deskriptiv,
    "t_test_unabhaengig": verfahren_t_test_unabhaengig,
    "welch_test": verfahren_welch_test,
    "t_test_gepaart": verfahren_t_test_gepaart,
    "mann_whitney_u": verfahren_mann_whitney_u,
    "wilcoxon": verfahren_wilcoxon,
    "anova_einfaktoriell": verfahren_anova_einfaktoriell,
    "kruskal_wallis": verfahren_kruskal_wallis,
    "chi_quadrat_unabhaengigkeit": verfahren_chi_quadrat_unabhaengigkeit,
    "pearson_r": verfahren_pearson_r,
    "spearman_rho": verfahren_spearman_rho,
}


# ---------------------------------------------------------------------------
# Planausfuehrung
# ---------------------------------------------------------------------------


def _konfiguration(plan: dict) -> dict[str, Any]:
    bootstrap = plan.get("bootstrap", {})
    return {
        "alpha": float(plan.get("alpha", STANDARD_ALPHA)),
        "niveau": float(plan.get("konfidenzniveau", STANDARD_NIVEAU)),
        "seed": int(bootstrap.get("seed", STANDARD_SEED)),
        "replikationen": int(bootstrap.get("replikationen", STANDARD_BOOTSTRAP)),
        "variablen": plan.get("variablen", {}),
    }


def fuehre_plan_aus(daten: Datensatz, plan: dict) -> dict[str, Any]:
    """Rechnet jede geplante Analyse und liefert den reproduzierbaren Payload."""
    konf = _konfiguration(plan)
    analysen = plan.get("analysen") or []
    if not analysen:
        raise ValueError("Der Analyseplan enthaelt keine 'analysen'.")
    ergebnisse: list[dict[str, Any]] = []
    for analyse in analysen:
        name = analyse.get("verfahren")
        if name not in VERFAHREN:
            raise ValueError(
                f"Unbekanntes Verfahren '{name}' in Analyse '{analyse.get('id')}'. "
                f"Abgedeckt sind: {', '.join(sorted(VERFAHREN))}."
            )
        ergebnis = VERFAHREN[name](daten, analyse, konf)
        ergebnis["id"] = analyse.get("id", name)
        ergebnisse.append({"id": ergebnis.pop("id"), **ergebnis})
    return {
        "schema": "quantitative-analysis/ergebnisse/1",
        "titel": plan.get("titel", ""),
        "alpha": konf["alpha"],
        "konfidenzniveau": konf["niveau"],
        "daten_sha256": datei_sha256(daten.quelle),
        "plan_sha256": hashlib.sha256(
            json.dumps(plan, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        "n_zeilen": daten.n_zeilen,
        "ergebnisse": ergebnisse,
    }


def baue_lauf_meta(daten_pfad: Path, plan_pfad: Path, out_pfad: Path) -> dict[str, Any]:
    """Alles, was zwischen zwei Laeufen abweichen darf -- streng getrennt vom Payload."""
    kommando = " ".join(
        shlex.quote(teil)
        for teil in [
            "python3",
            str(Path(__file__).resolve()),
            "run",
            "--data",
            str(daten_pfad),
            "--plan",
            str(plan_pfad),
            "--out",
            str(out_pfad),
        ]
    )
    return {
        "zeitpunkt": datetime.now(UTC).isoformat(timespec="seconds"),
        "kommandozeile": kommando,
        "pfade": {
            "daten": str(daten_pfad),
            "plan": str(plan_pfad),
            "ausgabe": str(out_pfad),
        },
        "versionen": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": _scipy_version(),
        },
    }


def _scipy_version() -> str:
    import scipy

    return str(scipy.__version__)


# ---------------------------------------------------------------------------
# Protokoll
# ---------------------------------------------------------------------------


def _fmt(wert: Any, stellen: int = 3) -> str:
    if wert is None:
        return "nicht bestimmbar"
    if isinstance(wert, list):
        return ", ".join(_fmt(w, stellen) for w in wert)
    if isinstance(wert, (int, float)):
        return f"{float(wert):.{stellen}f}"
    return str(wert)


def _fmt_p(wert: Any, mit_gleichheitszeichen: bool = True) -> str:
    """p-Werte mit Vergleichszeichen: unterhalb der Anzeigegrenze '< 0.0001'.

    Ohne die Fallunterscheidung stuende dort '0.0000' -- eine Zahl, die kein
    Test je liefert und die sich von einem echten Nullwert nicht unterscheiden
    laesst.
    """
    if wert is None:
        return "nicht bestimmbar"
    zahl = float(wert)
    if zahl < 0.0001:
        return "< 0.0001"
    return f"= {zahl:.4f}" if mit_gleichheitszeichen else f"{zahl:.4f}"


def _fmt_df(wert: Any) -> str:
    """Freiheitsgrade: ganzzahlig ohne Nachkommastellen, Welch-df mit zweien."""
    if isinstance(wert, list):
        return ", ".join(_fmt_df(w) for w in wert)
    if isinstance(wert, (int, float)) and float(wert).is_integer():
        return str(int(wert))
    return _fmt(wert, 2)


def _pruefe_berichtsform(ergebnis: dict) -> None:
    """Strukturelle Zusage statt Prosa: ohne Effektstaerke und KI kein Bericht."""
    kennung = ergebnis.get("id", "?")
    effekt = ergebnis.get("effekt") or {}
    if not effekt.get("name") or effekt.get("wert") is None:
        raise ValueError(
            f"Ergebnis '{kennung}' hat keine Effektstärke. Teststatistik und p-Wert "
            f"allein sind kein berichtsfähiges Ergebnis (Issue #610, AC3)."
        )
    ci = ergebnis.get("ci") or {}
    if ci.get("lo") is None or ci.get("hi") is None:
        raise ValueError(
            f"Ergebnis '{kennung}' hat kein Vertrauensintervall zur Effektstärke (Issue #610, AC3)."
        )
    if not ergebnis.get("voraussetzungen"):
        raise ValueError(
            f"Ergebnis '{kennung}' berichtet keine Voraussetzungsprüfung (Issue #610, AC4)."
        )


def _rendere_deskriptiv(ergebnis: dict) -> list[str]:
    zeilen = ["| Variable | n | fehlend | Kennwerte |", "| --- | --- | --- | --- |"]
    for name, werte in ergebnis["variablen"].items():
        if "haeufigkeiten" in werte:
            kennwerte = ", ".join(f"{k}: {v}" for k, v in werte["haeufigkeiten"].items())
        else:
            kennwerte = (
                f"M = {_fmt(werte['m'], 2)}, SD = {_fmt(werte['sd'], 2)}, "
                f"Md = {_fmt(werte['median'], 2)}, IQR = {_fmt(werte['iqr'], 2)}, "
                f"Min = {_fmt(werte['min'], 2)}, Max = {_fmt(werte['max'], 2)}"
            )
        zeilen.append(f"| `{name}` | {werte['n']} | {werte['n_fehlend']} | {kennwerte} |")
    return zeilen


def _rendere_voraussetzungen(ergebnis: dict) -> list[str]:
    zeilen = [
        "**Voraussetzungen**",
        "",
        "| Prüfung | Bezug | Kennwert | p | Schwelle | Verdikt | Alternative |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for v in ergebnis["voraussetzungen"]:
        verdikt = "verletzt" if v["verletzt"] else "erfüllt"
        alternative = v["alternative"] or "—"
        p_wert = _fmt_p(v["p"], mit_gleichheitszeichen=False) if v["p"] is not None else "—"
        zeilen.append(
            f"| {v['name']} | {v['bezug']} | {_fmt(v['kennwert'], 3)} | {p_wert} | "
            f"{v['schwelle']} | {verdikt} | {alternative} |"
        )
    verletzt = [v for v in ergebnis["voraussetzungen"] if v["verletzt"]]
    if verletzt:
        zeilen.append("")
        for v in verletzt:
            zeilen.append(
                f"> Voraussetzung verletzt: {v['name']} ({v['bezug']}). "
                f"Naheliegende Alternative: {v['alternative']}. "
                f"Gerechnet wurde weiterhin das geplante Verfahren "
                f"`{ergebnis['verfahren']}` — ein Wechsel ist eine Entscheidung "
                f"der Autorin, keine des Skripts."
            )
    return zeilen


def rendere_protokoll(ergebnisse: dict, meta: dict) -> str:
    """Baut den Bericht. Wirft, sobald ein Ergebnis die Berichtsform verfehlt."""
    versionen = meta.get("versionen", {})
    zeilen: list[str] = [
        "# Auswertungsprotokoll",
        "",
        f"Analyseplan: {ergebnisse.get('titel') or '(ohne Titel)'}",
        "",
        "## Reproduktion",
        "",
        "Derselbe Aufruf über denselben Datensatz führt auf dieselben Werte:",
        "",
        "```bash",
        meta.get("kommandozeile", ""),
        "```",
        "",
        f"- Rohdatensatz: `{meta.get('pfade', {}).get('daten', '')}`",
        f"- SHA-256 der Rohdatei: `{ergebnisse['daten_sha256']}`",
        f"- SHA-256 des Analyseplans: `{ergebnisse['plan_sha256']}`",
        f"- Zeilen im Datensatz: {ergebnisse['n_zeilen']}",
        f"- Lauf: {meta.get('zeitpunkt', '')}",
        f"- Python {versionen.get('python', '?')}, "
        f"numpy {versionen.get('numpy', '?')}, "
        f"scipy {versionen.get('scipy', '?')}",
        f"- Signifikanzniveau α = {ergebnisse['alpha']}, "
        f"Konfidenzniveau {int(ergebnisse['konfidenzniveau'] * 100)} %",
        "",
        "## Ergebnisse",
        "",
    ]
    for ergebnis in ergebnisse["ergebnisse"]:
        zeilen.append(f"### {ergebnis['id']} — {ergebnis['frage']}")
        zeilen.append("")
        zeilen.append(f"Verfahren: `{ergebnis['verfahren']}`")
        zeilen.append("")
        if ergebnis["typ"] == "deskriptiv":
            zeilen.extend(_rendere_deskriptiv(ergebnis))
            zeilen.append("")
        else:
            _pruefe_berichtsform(ergebnis)
            statistik = ergebnis["statistik"]
            df = statistik.get("df")
            df_text = f"({_fmt_df(df)})" if df is not None else ""
            ci = ergebnis["ci"]
            niveau = int(ci["niveau"] * 100)
            zeilen.append(
                f"- Teststatistik: {statistik['name']}{df_text} = "
                f"{_fmt(statistik['wert'])}, p {_fmt_p(ergebnis['p'])}, n = {ergebnis['n']}"
            )
            zeilen.append(
                f"- Effektstärke: {ergebnis['effekt']['name']} = {_fmt(ergebnis['effekt']['wert'])}"
            )
            zeilen.append(
                f"- {niveau}-%-Konfidenzintervall für {ci['bezug']}: "
                f"[{_fmt(ci['lo'])}, {_fmt(ci['hi'])}], {ci['methode']}"
            )
            for zusatz in ergebnis.get("zusatz", []):
                z_ci = zusatz["ci"]
                zeilen.append(
                    f"- {zusatz['name']}: {_fmt(zusatz['wert'])}, "
                    f"{int(z_ci['niveau'] * 100)}-%-Konfidenzintervall "
                    f"[{_fmt(z_ci['lo'])}, {_fmt(z_ci['hi'])}], {z_ci['methode']}"
                )
            p_wert = ergebnis["p"]
            if p_wert is None:
                entscheidung = "nicht bestimmbar (kein p-Wert)"
            elif p_wert < ergebnisse["alpha"]:
                entscheidung = "verworfen"
            else:
                entscheidung = "nicht verworfen"
            zeilen.append(
                f"- Testentscheidung bei α = {ergebnisse['alpha']}: "
                f"die Nullhypothese wird {entscheidung}."
            )
            if ergebnis.get("gruppen"):
                zeilen.append("")
                zeilen.append("| Gruppe | n | M | SD |")
                zeilen.append("| --- | --- | --- | --- |")
                for name, kennwerte in ergebnis["gruppen"].items():
                    zeilen.append(
                        f"| {name} | {int(kennwerte['n'])} | {_fmt(kennwerte['m'], 2)} | "
                        f"{_fmt(kennwerte['sd'], 2)} |"
                    )
            if ergebnis.get("kreuztabelle"):
                kreuz = ergebnis["kreuztabelle"]
                zeilen.append("")
                zeilen.append("| | " + " | ".join(kreuz["spalten"]) + " |")
                zeilen.append("| --- " * (len(kreuz["spalten"]) + 1) + "|")
                for name, werte in zip(kreuz["zeilen"], kreuz["werte"], strict=True):
                    zeilen.append(f"| {name} | " + " | ".join(str(w) for w in werte) + " |")
            zeilen.append("")
            zeilen.extend(_rendere_voraussetzungen(ergebnis))
            zeilen.append("")
        for hinweis in ergebnis.get("hinweise", []):
            zeilen.append(f"- Hinweis: {hinweis}")
        zeilen.append("")
        zeilen.append(DEUTUNGS_PLATZHALTER)
        zeilen.append("")

    zeilen.extend(
        [
            "## Deutung",
            "",
            "Dieses Protokoll rechnet und berichtet. Was die Zahlen für die "
            "Fragestellung bedeuten, steht hier bewusst nicht — das ist Sache der "
            "Autorin und gehört ins Ergebnis- bzw. Diskussionskapitel.",
            "",
            DEUTUNGS_PLATZHALTER,
            "",
        ]
    )
    return "\n".join(zeilen)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _schreibe_json(pfad: Path, payload: dict) -> None:
    pfad.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _cmd_describe(args: argparse.Namespace) -> int:
    fehlende = STANDARD_FEHLWERTE
    if args.plan:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        fehlende = plan.get("fehlende_werte", STANDARD_FEHLWERTE)
    daten = lade_datensatz(Path(args.data), fehlende)
    print(f"Datensatz: {args.data}")
    print(f"SHA-256:   {datei_sha256(Path(args.data))}")
    print(f"Zeilen:    {daten.n_zeilen}")
    print("")
    print(f"{'Spalte':<20} {'gefüllt':>8} {'fehlend':>8}  Beispielwerte")
    for name in daten.spalten:
        gefuellt = daten.n_zeilen - daten.n_fehlend(name)
        beispiele = ", ".join(daten.kategorial(name)[:3])
        print(f"{name:<20} {gefuellt:>8} {daten.n_fehlend(name):>8}  {beispiele}")
    print("")
    print(
        "Die Skalenniveaus stehen bewusst nicht hier — sie gehören in den "
        "Analyseplan und sind eine inhaltliche Entscheidung."
    )
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    daten_pfad = Path(args.data)
    plan_pfad = Path(args.plan)
    out_pfad = Path(args.out)
    out_pfad.mkdir(parents=True, exist_ok=True)
    plan = json.loads(plan_pfad.read_text(encoding="utf-8"))
    daten = lade_datensatz(daten_pfad, plan.get("fehlende_werte"))
    ergebnisse = fuehre_plan_aus(daten, plan)
    meta = baue_lauf_meta(daten_pfad, plan_pfad, out_pfad)
    protokoll = rendere_protokoll(ergebnisse, meta)
    _schreibe_json(out_pfad / "ergebnisse.json", ergebnisse)
    _schreibe_json(out_pfad / "lauf_meta.json", meta)
    (out_pfad / "protokoll.md").write_text(protokoll, encoding="utf-8")
    print(f"{len(ergebnisse['ergebnisse'])} Analysen gerechnet.")
    print(f"  {out_pfad / 'ergebnisse.json'}")
    print(f"  {out_pfad / 'lauf_meta.json'}")
    print(f"  {out_pfad / 'protokoll.md'}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    ergebnisse = json.loads(Path(args.ergebnisse).read_text(encoding="utf-8"))
    meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))
    protokoll = rendere_protokoll(ergebnisse, meta)
    Path(args.out).write_text(protokoll, encoding="utf-8")
    print(f"Protokoll geschrieben: {args.out}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="analyze.py",
        description="Deterministischer Rechenkern des quantitative-analysis-Skills.",
    )
    unter = parser.add_subparsers(dest="kommando", required=True)

    p_describe = unter.add_parser("describe", help="Rohdatensatz sichten")
    p_describe.add_argument("--data", required=True)
    p_describe.add_argument("--plan", default=None)
    p_describe.set_defaults(func=_cmd_describe)

    p_run = unter.add_parser("run", help="Analyseplan ausfuehren")
    p_run.add_argument("--data", required=True)
    p_run.add_argument("--plan", required=True)
    p_run.add_argument("--out", required=True)
    p_run.set_defaults(func=_cmd_run)

    p_report = unter.add_parser("report", help="Protokoll neu rendern")
    p_report.add_argument("--ergebnisse", required=True)
    p_report.add_argument("--meta", required=True)
    p_report.add_argument("--out", required=True)
    p_report.set_defaults(func=_cmd_report)

    args = parser.parse_args(list(argv) if argv is not None else None)
    result: int = args.func(args)
    return result


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
