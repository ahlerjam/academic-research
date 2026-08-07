#!/usr/bin/env python3
"""Baut ``extended-cases.json`` aus den Rohdateien des erweiterten Goldsets
(Issue #721, 186 Faelle aus 30 echten Papern ueber acht Fachrichtungen).

Rohquellen (unveraendert aus den Issue-Kommentaren uebernommen):

* ``set_med.json`` / ``set_soz.json`` -- 94 + 92 Faelle, je Feld ``claim``
  (deutsche Kapitelbehauptung), ``type`` (Verzerrungstyp oder ``None`` bei
  ``faithful``) und ``pick`` (1-basiert, Index in die flachgeklopfte
  Picks-Liste unten).
* ``picks.json`` -- 30 Paper, je Paper eine Liste ``picks`` (Quellsatz +
  Kontext); ``pick`` in den Fall-Dateien zaehlt ALLE ``picks`` aller Paper
  nacheinander 1-basiert durch (nicht je Paper neu).

Ausgabe (``extended-cases.json``) uebernimmt die Feldstruktur von
``real-cases.json`` (Issue #592) -- ``id``, ``claim_lang``, ``context_lang``,
``verzerrend_type``, ``chapter_claim``, ``context_before``, ``verbatim``,
``context_after``, ``label`` -- ergaenzt um ``source`` (DOI-Rueckfuehrbarkeit,
AC2 aus #721: ``source.doi`` statt ``source.arxiv_id``/``url`` wie bei den
60 Faellen aus #592).

Aufruf:
    python3 evals/524-nli-prefilter/build_extended_cases.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SET_FILES = ("set_med.json", "set_soz.json")
PICKS_PATH = HERE / "picks.json"
OUT_PATH = HERE / "extended-cases.json"


def _flatten_picks(picks: list[dict]) -> list[dict]:
    """Klopft die Paper-gruppierten Picks zu einer 0-indexierten Liste flach,
    jeder Eintrag angereichert um die Paper-Metadaten (Feld/DOI/Titel/Jahr)."""
    flat = []
    for paper in picks:
        for pick in paper["picks"]:
            flat.append(
                {
                    **pick,
                    "field": paper["field"],
                    "doi": paper["doi"],
                    "title": paper["title"],
                    "year": paper["year"],
                }
            )
    return flat


def build_extended_cases() -> dict:
    picks = json.loads(PICKS_PATH.read_text(encoding="utf-8"))
    flat_picks = _flatten_picks(picks)

    cases = []
    for fname in SET_FILES:
        raw = json.loads((HERE / fname).read_text(encoding="utf-8"))
        for case in raw["cases"]:
            pick = flat_picks[case["pick"] - 1]
            cases.append(
                {
                    "id": case["id"],
                    "claim_lang": "de",
                    "context_lang": "en",
                    "verzerrend_type": case["type"],
                    "chapter_claim": case["claim"],
                    "context_before": pick.get("context_before", ""),
                    "verbatim": pick["sentence"],
                    "context_after": pick.get("context_after", ""),
                    "label": case["label"],
                    "source": {
                        "doi": pick["doi"],
                        "title": pick["title"],
                        "field": pick["field"],
                        "year": pick["year"],
                    },
                }
            )

    return {
        "description": (
            "Erweitertes NLI-Goldset (Issue #721): 186 Faelle aus 30 echten, "
            "Open-Access-Papern (OpenAlex) ueber acht Fachrichtungen (Medizin, "
            "Public Health, Psychologie, Paedagogik, Soziologie, Wirtschaft, "
            "Umwelt, Informatik). Praemissen sind unveraenderte "
            "Abstract-Ausschnitte; Labels folgen einer Konstruktionsregel "
            "(fuenf feste Transformationen), nicht einem Einzelurteil. "
            "Generiert aus set_med.json + set_soz.json + picks.json via "
            "build_extended_cases.py -- nicht von Hand editieren."
        ),
        "cases": cases,
    }


def main() -> None:
    result = build_extended_cases()
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    faithful = sum(1 for c in result["cases"] if c["label"] == "faithful")
    verzerrend = sum(1 for c in result["cases"] if c["label"] == "verzerrend")
    print(
        f"{len(result['cases'])} Faelle -> {OUT_PATH} (faithful={faithful} verzerrend={verzerrend})"
    )


if __name__ == "__main__":
    main()
