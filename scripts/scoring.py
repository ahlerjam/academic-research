#!/usr/bin/env python3
"""5D-Scoring fuer /academic-research:score (#704).

Portiert die vier *gerechneten* Dimensionen (Aktualitaet, Qualitaet,
Autoritaet, Zugaenglichkeit) aus der Prosa-Formel in
``commands/score.md`` (Abschnitt "Schritt 3+4: 4 weitere Dimensionen berechnen...") nach Python, verhaltensgleich. Die
Relevanz-Dimension (Gewicht 0.35) bleibt beim ``relevance-scorer``-Agenten
und wird hier nur als Parameter entgegengenommen und gewichtet summiert --
sie erfordert Urteilsvermoegen ueber Titel/Abstract, kein arithmetisches
Portat.

Aufruf als Skript (CLI, fuer commands/score.md):

    python3 scripts/scoring.py '<paper-json>' <relevance> [current_year]

``<paper-json>`` ist ein JSON-Objekt mit den Feldern ``year``,
``citations``, ``venue`` sowie optional ``oa_url``, ``open_access_pdf``,
``doi``, ``url``. Gibt den Gesamtscore als Float auf stdout aus.

Gewichte (unveraendert gegenueber der Prosa-Formel):
    Relevanz 0.35, Aktualitaet 0.20, Qualitaet 0.15, Autoritaet 0.15,
    Zugang 0.15.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import sys

WEIGHT_RELEVANCE = 0.35
WEIGHT_RECENCY = 0.20
WEIGHT_QUALITY = 0.15
WEIGHT_AUTHORITY = 0.15
WEIGHT_ACCESS = 0.15

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


def recency(year: int | None, current_year: int | None = None) -> float:
    """Aktualitaet: exponentieller Decay, 5-Jahres-Halbwertszeit.

    ``recency = exp(-ln(2) * (current_year - year) / 5)``

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
    cy = _current_year(current_year)
    delta = cy - year
    value = math.exp(-math.log(2) * delta / 5)
    return min(value, 1.0)


def quality(citations: int | None, year: int | None, current_year: int | None = None) -> float:
    """Qualitaet: log-skalierte Zitationen pro Jahr seit Publikation.

    ``quality = min(log10(citations / max(1, years_since_pub) + 1) / 2, 1.0)``

    Fehlendes/0 ``citations`` -> wie ``citations=0`` behandelt (die
    Formel liefert dafuer bereits einen definierten Wert, kein Sonderfall
    noetig).

    Fehlendes ``year`` -> ``years_since_pub`` ist nicht berechenbar -> 0.0
    (dokumentierter Default, analog :func:`recency`).
    """
    if year is None:
        return 0.0
    cy = _current_year(current_year)
    c = citations if citations else 0
    years_since_pub = cy - year
    value = math.log10(c / max(1, years_since_pub) + 1) / 2
    return min(value, 1.0)


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


def total_score(relevance: float, paper: dict, current_year: int | None = None) -> float:
    """Gewichteter Gesamtscore aus allen 5 Dimensionen.

    ``total = 0.35*relevance + 0.20*recency + 0.15*quality
               + 0.15*authority + 0.15*access``

    ``relevance`` kommt vom ``relevance-scorer``-Agenten und wird hier nur
    entgegengenommen, nie berechnet. Das Ergebnis wird zusaetzlich auf
    [0, 1] geklemmt (Sicherheitsnetz fuer AC5, ergaenzend zum Clamp in
    :func:`recency`/:func:`quality`).
    """
    r = recency(paper.get("year"), current_year)
    q = quality(paper.get("citations"), paper.get("year"), current_year)
    a = authority(paper.get("venue"))
    ac = access(paper)
    total = (
        WEIGHT_RELEVANCE * relevance
        + WEIGHT_RECENCY * r
        + WEIGHT_QUALITY * q
        + WEIGHT_AUTHORITY * a
        + WEIGHT_ACCESS * ac
    )
    return max(0.0, min(total, 1.0))


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(
            "Usage: python3 scoring.py '<paper-json>' <relevance> [current_year]",
            file=sys.stderr,
        )
        return 2
    paper = json.loads(argv[1])
    relevance = float(argv[2])
    current_year = int(argv[3]) if len(argv) > 3 else None
    print(total_score(relevance, paper, current_year))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
