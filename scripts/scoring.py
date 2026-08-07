#!/usr/bin/env python3
"""5D-Scoring fuer /academic-research:score (#704, #705).

Portiert die vier *gerechneten* Dimensionen (Aktualitaet, Qualitaet,
Autoritaet, Zugaenglichkeit) aus der Prosa-Formel in
``commands/score.md`` (Abschnitt "Schritt 3+4: 4 weitere Dimensionen berechnen...") nach Python, verhaltensgleich. Die
Relevanz-Dimension (Gewicht 0.35) bleibt beim ``relevance-scorer``-Agenten
und wird hier nur als Parameter entgegengenommen und gewichtet summiert --
sie erfordert Urteilsvermoegen ueber Titel/Abstract, kein arithmetisches
Portat.

Seit #705: ``quality()`` bevorzugt den feldnormalisierten OpenAlex-Wert
``fwci`` (Field-Weighted Citation Impact, Weltdurchschnitt = 1.0), wenn er
vorliegt, mit Rueckfall auf die rohe log-skalierte Zitationsformel. Die
Herkunft ist am Rueckgabewert erkennbar (``QualityResult.source``).
``recency()`` nimmt eine Halbwertszeit entgegen statt sie fest auf 5 Jahre
zu verdrahten. Halbwertszeit + die fuenf Gewichte koennen per
``load_profile()`` aus einem Bibliotheksprofil-YAML (Abschnitt ``scoring:``)
geladen werden, mit Fallback auf die bisherigen Konstanten.

Aufruf als Skript (CLI, fuer commands/score.md):

    python3 scripts/scoring.py '<paper-json>' <relevance> [current_year] [profile_path]

``<paper-json>`` ist ein JSON-Objekt mit den Feldern ``year``,
``citations``, ``venue`` sowie optional ``oa_url``, ``open_access_pdf``,
``doi``, ``url``, ``citations_normalized`` (fwci). ``profile_path`` ist
optional; fehlt er, gilt ``~/.academic-research/library-profiles/active.yaml``
falls vorhanden, sonst die dokumentierten Defaults. Gibt ein JSON-Objekt auf
stdout aus mit ``total`` (Float), ``quality_source`` (``"fwci"``|``"raw"``)
und ``recency_half_life_years`` (Float) -- vor #705 war die Ausgabe ein
nackter Float; ``commands/score.md`` liest seither das ``total``-Feld.

Gewichte (Defaults, unveraendert gegenueber der urspruenglichen Prosa-Formel;
per Profil ueberschreibbar):
    Relevanz 0.35, Aktualitaet 0.20, Qualitaet 0.15, Autoritaet 0.15,
    Zugang 0.15.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import sys
from pathlib import Path
from typing import Any, NamedTuple

from text_utils import load_yaml

WEIGHT_RELEVANCE = 0.35
WEIGHT_RECENCY = 0.20
WEIGHT_QUALITY = 0.15
WEIGHT_AUTHORITY = 0.15
WEIGHT_ACCESS = 0.15

DEFAULT_HALF_LIFE_YEARS = 5.0

DEFAULT_WEIGHTS: dict[str, float] = {
    "relevance": WEIGHT_RELEVANCE,
    "recency": WEIGHT_RECENCY,
    "quality": WEIGHT_QUALITY,
    "authority": WEIGHT_AUTHORITY,
    "access": WEIGHT_ACCESS,
}

DEFAULT_ACTIVE_PROFILE_PATH = (
    Path.home() / ".academic-research" / "library-profiles" / "active.yaml"
)


class QualityResult(NamedTuple):
    """Rueckgabe von :func:`quality`: Wert plus Herkunft (AC1)."""

    value: float
    source: str  # "fwci" | "raw"


# Venue-Klassifikation fuer `authority()`. Die urspruengliche Prosa-Formel
# beschreibt vier Buckets ("bekannte Top-Venues", "indexierte Journals",
# "Konferenzen", "sonst"), die dort implizit vom Modell per Urteilsvermoegen
# zugeordnet wurden. Fuer eine deterministische Portierung wird das als
# Schluesselwort-Suche im (kleingeschriebenen) Venue-String operationalisiert
# -- das ist eine Formalisierung der genannten Kategorien, keine inhaltliche
# Aenderung der Gewichte oder Schwellenwerte.
_TOP_VENUE_KEYWORDS = ("ieee", "acm", "springer", "nature", "elsevier")
_JOURNAL_KEYWORDS = ("journal",)
_CONFERENCE_KEYWORDS = ("conference", "proceedings", "workshop", "symposium")


def _current_year(current_year: int | None) -> int:
    return current_year if current_year is not None else _dt.date.today().year


def recency(
    year: int | None,
    current_year: int | None = None,
    half_life_years: float = DEFAULT_HALF_LIFE_YEARS,
) -> float:
    """Aktualitaet: exponentieller Decay mit konfigurierbarer Halbwertszeit.

    ``recency = exp(-ln(2) * (current_year - year) / half_life_years)``

    ``half_life_years`` ist seit #705 ein Parameter statt fest verdrahtet
    (Default weiterhin 5 Jahre, verhaltensgleich zu vorher). Ueber
    :func:`load_profile` kommt er aus dem Bibliotheksprofil -- eine laengere
    Halbwertszeit bestraft Grundlagenliteratur weniger stark (AC3/AC4).

    Fehlendes ``year`` -> 0.0 (dokumentierter Default: ohne Publikationsjahr
    wird konservativ keine Aktualitaet attestiert, statt eine stille
    Annahme ueber das Alter zu treffen).

    Publikationsjahr in der Zukunft (``year > current_year``) ergibt einen
    positiven Exponenten und damit einen Rohwert > 1.0; wie bei
    :func:`quality` wird das obere Ende auf 1.0 geklemmt, damit
    :func:`total_score` immer im [0, 1]-Intervall bleibt.
    """
    if year is None:
        return 0.0
    if half_life_years <= 0:
        # Degenerierte Konfiguration (kaputtes Profil): sofortiger Abfall,
        # ausser das Paper ist taufrisch -- kein ZeroDivisionError.
        return 1.0 if year >= _current_year(current_year) else 0.0
    cy = _current_year(current_year)
    delta = cy - year
    value = math.exp(-math.log(2) * delta / half_life_years)
    return min(value, 1.0)


def quality(
    citations: int | None,
    year: int | None,
    current_year: int | None = None,
    citations_normalized: float | None = None,
) -> QualityResult:
    """Qualitaet: feldnormalisierter OpenAlex-Wert (fwci), sonst roh log-skaliert.

    Liegt ``citations_normalized`` (OpenAlex ``fwci``, Weltdurchschnitt = 1.0)
    vor, wird er verwendet: ``value = clamp(fwci / 2, 0, 1)`` -- ein Paper mit
    doppeltem Weltdurchschnitt (fwci=2) erreicht den Maximalwert, der
    Weltdurchschnitt selbst (fwci=1) landet bei 0.5. ``fwci`` ist nach oben
    unbeschraenkt, daher der explizite Clamp (AC5-Invariante: ``total_score``
    bleibt in [0, 1]). Die Herkunft steht in ``QualityResult.source``
    (``"fwci"``) -- AC1.

    Fehlt ``citations_normalized``, gilt wie vor #705 die rohe log-skalierte
    Formel (Herkunft ``"raw"``):

    ``value = min(log10(citations / max(1, years_since_pub) + 1) / 2, 1.0)``

    Fehlendes/0 ``citations`` -> wie ``citations=0`` behandelt (die
    Formel liefert dafuer bereits einen definierten Wert, kein Sonderfall
    noetig).

    Fehlendes ``year`` -> ``years_since_pub`` ist im Rohwert-Zweig nicht
    berechenbar -> 0.0 (dokumentierter Default, analog :func:`recency`). Der
    fwci-Zweig braucht kein ``year`` -- fwci ist bereits altersnormalisiert.
    """
    if citations_normalized is not None:
        value = max(0.0, min(citations_normalized / 2.0, 1.0))
        return QualityResult(value, "fwci")
    if year is None:
        return QualityResult(0.0, "raw")
    cy = _current_year(current_year)
    c = citations if citations else 0
    years_since_pub = cy - year
    value = math.log10(c / max(1, years_since_pub) + 1) / 2
    return QualityResult(min(value, 1.0), "raw")


def authority(venue: str | None) -> float:
    """Autoritaet: Venue-Heuristik.

    1.0 fuer bekannte Top-Venues (IEEE, ACM, Springer, Nature, Elsevier),
    0.7 fuer indexierte Journals, 0.4 fuer Konferenzen, 0.2 sonst.

    Fehlendes/leeres ``venue`` -> 0.2 (dokumentierter Default: wie die
    "sonst"-Kategorie behandelt, keine Sonderbehandlung noetig).
    """
    if not venue:
        return 0.2
    v = venue.lower()
    if any(k in v for k in _TOP_VENUE_KEYWORDS):
        return 1.0
    if any(k in v for k in _JOURNAL_KEYWORDS):
        return 0.7
    if any(k in v for k in _CONFERENCE_KEYWORDS):
        return 0.4
    return 0.2


def access(paper: dict) -> float:
    """Zugaenglichkeit: Open Access > DOI+Institutional > nur DOI > nur URL.

    1.0 Open Access, 0.8 DOI mit Institutional Access, 0.5 nur DOI,
    0.2 nur URL.

    Liegt keines der Felder vor -> 0.0 (dokumentierter Default: kein
    bekannter Zugangsweg).
    """
    if paper.get("oa_url") or paper.get("open_access_pdf"):
        return 1.0
    doi = paper.get("doi")
    if doi:
        return 0.5
    if paper.get("url"):
        return 0.2
    return 0.0


def load_profile(path: str | Path | None) -> dict[str, Any]:
    """Laedt Halbwertszeit + die fuenf Gewichte aus einem Bibliotheksprofil-YAML.

    Erwartete Struktur (Abschnitt ``scoring:`` in ``active.yaml``/Presets):

    .. code-block:: yaml

        scoring:
          half_life_years: 5
          weights:
            relevance: 0.35
            recency: 0.20
            quality: 0.15
            authority: 0.15
            access: 0.15

    Fallback auf die heutigen Konstanten (AC2), einzeln pro fehlendem Feld:
    fehlt die Datei, der ``scoring:``-Abschnitt, der ``weights:``-Unterabschnitt,
    ein einzelnes Gewicht oder ist die Datei nicht parsebar, greift fuer genau
    dieses Feld der Default -- Bestandsprofile ohne ``scoring:``-Abschnitt
    (z. B. via ``scihub_optin.py`` ausgerollte ``active.yaml``) duerfen nicht
    crashen.
    """
    weights = dict(DEFAULT_WEIGHTS)
    half_life = DEFAULT_HALF_LIFE_YEARS
    if path is None:
        return {"half_life_years": half_life, "weights": weights}
    p = Path(path)
    if not p.exists():
        return {"half_life_years": half_life, "weights": weights}
    try:
        data = load_yaml(p)
    except Exception:
        return {"half_life_years": half_life, "weights": weights}
    scoring_cfg = data.get("scoring") if isinstance(data, dict) else None
    if not isinstance(scoring_cfg, dict):
        return {"half_life_years": half_life, "weights": weights}
    raw_half_life = scoring_cfg.get("half_life_years")
    if isinstance(raw_half_life, (int, float)) and not isinstance(raw_half_life, bool):
        half_life = float(raw_half_life)
    yaml_weights = scoring_cfg.get("weights")
    if isinstance(yaml_weights, dict):
        for key in weights:
            raw_weight = yaml_weights.get(key)
            if isinstance(raw_weight, (int, float)) and not isinstance(raw_weight, bool):
                weights[key] = float(raw_weight)
    return {"half_life_years": half_life, "weights": weights}


def total_score(
    relevance: float,
    paper: dict,
    current_year: int | None = None,
    profile: dict[str, Any] | None = None,
) -> float:
    """Gewichteter Gesamtscore aus allen 5 Dimensionen.

    ``total = w_relevance*relevance + w_recency*recency + w_quality*quality
               + w_authority*authority + w_access*access``

    ``profile`` (aus :func:`load_profile`) liefert Halbwertszeit + Gewichte;
    ``None`` -> Defaults (verhaltensgleich zu vor #705).

    ``relevance`` kommt vom ``relevance-scorer``-Agenten und wird hier nur
    entgegengenommen, nie berechnet. Das Ergebnis wird zusaetzlich auf
    [0, 1] geklemmt (Sicherheitsnetz fuer AC5, ergaenzend zum Clamp in
    :func:`recency`/:func:`quality`).
    """
    weights = profile["weights"] if profile is not None else DEFAULT_WEIGHTS
    half_life = profile["half_life_years"] if profile is not None else DEFAULT_HALF_LIFE_YEARS
    r = recency(paper.get("year"), current_year, half_life)
    q = quality(
        paper.get("citations"),
        paper.get("year"),
        current_year,
        paper.get("citations_normalized"),
    )
    a = authority(paper.get("venue"))
    ac = access(paper)
    total = (
        weights["relevance"] * relevance
        + weights["recency"] * r
        + weights["quality"] * q.value
        + weights["authority"] * a
        + weights["access"] * ac
    )
    return max(0.0, min(total, 1.0))


def score_paper(
    relevance: float,
    paper: dict,
    current_year: int | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wie :func:`total_score`, aber mit Provenienz fuer den CLI-JSON-Output.

    Liefert ``total`` (Float, identisch zu ``total_score(...)``),
    ``quality_source`` (``"fwci"``|``"raw"``, AC1) und
    ``recency_half_life_years`` (Float, das tatsaechlich verwendete Profil).
    """
    half_life = profile["half_life_years"] if profile is not None else DEFAULT_HALF_LIFE_YEARS
    q = quality(
        paper.get("citations"),
        paper.get("year"),
        current_year,
        paper.get("citations_normalized"),
    )
    return {
        "total": total_score(relevance, paper, current_year, profile),
        "quality_source": q.source,
        "recency_half_life_years": half_life,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(
            "Usage: python3 scoring.py '<paper-json>' <relevance> [current_year] [profile_path]",
            file=sys.stderr,
        )
        return 2
    paper = json.loads(argv[1])
    relevance = float(argv[2])
    current_year = int(argv[3]) if len(argv) > 3 and argv[3] else None
    profile_path: str | Path | None
    if len(argv) > 4 and argv[4]:
        profile_path = argv[4]
    elif DEFAULT_ACTIVE_PROFILE_PATH.exists():
        profile_path = DEFAULT_ACTIVE_PROFILE_PATH
    else:
        profile_path = None
    profile = load_profile(profile_path)
    result = score_paper(relevance, paper, current_year, profile)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
