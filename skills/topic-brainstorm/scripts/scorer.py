#!/usr/bin/env python3
"""scorer.py — Topic-Brainstorm Feasibility/Novelty-Heuristik.

Scored eine vom Aufrufer gelieferte Liste von Topic-Kandidaten (--topics-json).
Die Kandidaten selbst stammen NICHT aus einer fest kodierten Datenbank —
sie werden vom Modell in `SKILL.md` fach- und interessenspassend entworfen
(je Kandidat inkl. `reason`, warum er zum Zuschnitt passt) und dem Scorer
als JSON uebergeben. `scorer.py` uebernimmt ausschliesslich die numerische
Normalisierung:

- Feasibility: Basiswert des Kandidaten + Modifikatoren aus Zeitbudget
  (--budget) und Datenzugang (--data-access)
- Novelty: Basiswert des Kandidaten + Bonus aus Stichwort-Ueberschneidung
  mit den Interessensgebieten (--interests)
- Career-Fit und `reason`: unveraendert durchgereicht (die fachliche
  Einschaetzung liegt beim Modell, nicht beim Scorer)

Ausgabe (Standard-Modus):
  JSON-Array mit den gescorten Kandidaten (gleiche Anzahl wie Input).

Ausgabe (--output-mode full):
  JSON-Objekt { "topics": [...], "top_topic": "<Titel>" }

Optionen:
  --topics-json <pfad|->  JSON-Array der Topic-Kandidaten (siehe unten).
                           "-" liest von stdin.
  --write-context <pfad>  Top-Topic in academic_context.md schreiben (erstellen falls noetig)

Schema pro Kandidat in --topics-json:
  {
    "title": str,                    # Pflicht, nicht-leer
    "keywords": list[str],           # optional, Default []
    "reason": str,                   # Pflicht, nicht-leer — warum passt das Thema?
    "base_feasibility": float,       # Pflicht, 0-10
    "base_novelty": float,           # Pflicht, 0-10
    "base_career_fit": float,        # Pflicht, 0-10
    "research_questions": list[str], # Pflicht, mind. 1 Eintrag
    "pilot_papers": list[str],       # Pflicht, mind. 1 Eintrag
  }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Score-Berechnung
# ---------------------------------------------------------------------------

_BUDGET_FEASIBILITY_MODIFIER = {
    "3 monate": -1.0,
    "6 monate": 0.0,
    "12 monate": +1.0,
}

_DATA_FEASIBILITY_MODIFIER = {
    "public datasets": +1.0,
    "literatur-only": +0.5,
    "interview-fähig": 0.0,
    "unternehmensdaten": -1.0,
}

_REQUIRED_TOPIC_FIELDS = (
    "title",
    "reason",
    "base_feasibility",
    "base_novelty",
    "base_career_fit",
    "research_questions",
    "pilot_papers",
)


def _clamp(val: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, round(val, 1)))


def _keyword_overlap(interests: list[str], topic_keywords: list[str]) -> float:
    """Berechnet Stichwort-Ueberschneidung als Novelty-Modifikator."""
    interest_words = {w.lower() for phrase in interests for w in phrase.split()}
    matches = sum(1 for kw in topic_keywords if any(w in kw.lower() for w in interest_words))
    return min(2.0, matches * 0.5)


def _validate_topic(topic: dict[str, Any], index: int) -> None:
    missing = [f for f in _REQUIRED_TOPIC_FIELDS if f not in topic]
    if missing:
        raise ValueError(f"Topic-Kandidat #{index} fehlen Pflichtfelder: {missing}")
    if not isinstance(topic["title"], str) or not topic["title"].strip():
        raise ValueError(f"Topic-Kandidat #{index}: 'title' muss ein nicht-leerer String sein")
    if not isinstance(topic["reason"], str) or not topic["reason"].strip():
        raise ValueError(f"Topic-Kandidat #{index}: 'reason' muss ein nicht-leerer String sein")


def score_topics(
    topics_input: list[dict[str, Any]],
    interests: list[str],
    budget: str,
    data_access: str,
) -> list[dict[str, Any]]:
    """Scored die uebergebenen Topic-Kandidaten (keine feste Themen-DB)."""
    budget_mod = _BUDGET_FEASIBILITY_MODIFIER.get(budget.lower(), 0.0)
    data_mod = _DATA_FEASIBILITY_MODIFIER.get(data_access.lower(), 0.0)

    results = []
    for index, topic in enumerate(topics_input):
        _validate_topic(topic, index)
        keywords = topic.get("keywords", [])

        feasibility = _clamp(topic["base_feasibility"] + budget_mod + data_mod)
        novelty = _clamp(topic["base_novelty"] + _keyword_overlap(interests, keywords))
        career_fit = _clamp(topic["base_career_fit"])

        results.append(
            {
                "title": topic["title"],
                "feasibility": feasibility,
                "novelty": novelty,
                "career_fit": career_fit,
                "reason": topic["reason"],
                "research_questions": list(topic["research_questions"]),
                "pilot_papers": list(topic["pilot_papers"]),
            }
        )

    return results


def find_top_topic(topics: list[dict[str, Any]]) -> str:
    """Gibt den Titel des Topics mit der hoechsten Score-Summe zurueck."""
    return max(
        topics,
        key=lambda t: t["feasibility"] + t["novelty"] + t["career_fit"],
    )["title"]


# ---------------------------------------------------------------------------
# academic_context.md schreiben
# ---------------------------------------------------------------------------


def write_to_context(ctx_path: Path, top_title: str) -> None:
    """Schreibt das Top-Topic in academic_context.md (erstellt Datei falls noetig)."""
    if ctx_path.exists():
        content = ctx_path.read_text(encoding="utf-8")
        # Thema-Zeile aktualisieren
        if re.search(r"^- Thema:", content, re.MULTILINE):
            content = re.sub(
                r"^- Thema:.*$",
                lambda _m: f"- Thema: {top_title}",
                content,
                flags=re.MULTILINE,
            )
        else:
            # Unter ### Arbeit einhaengen falls vorhanden, sonst ans Ende
            if "### Arbeit" in content:
                content = content.replace(
                    "### Arbeit",
                    f"### Arbeit\n- Thema: {top_title}",
                    1,
                )
            else:
                content += f"\n### Arbeit\n- Thema: {top_title}\n"
        ctx_path.write_text(content, encoding="utf-8")
    else:
        ctx_path.parent.mkdir(parents=True, exist_ok=True)
        ctx_path.write_text(
            f"---\nname: academic-context\ndescription: Akademischer Kontext der aktuellen Abschlussarbeit\ntype: project\n---\n\n### Arbeit\n- Thema: {top_title}\n",
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_topics_input(source: str) -> list[dict[str, Any]]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("--topics-json muss ein JSON-Array von Topic-Kandidaten enthalten")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Topic-Brainstorm Scorer")
    parser.add_argument(
        "--topics-json",
        required=True,
        help="Pfad zu einer JSON-Datei mit Topic-Kandidaten, oder '-' fuer stdin",
    )
    parser.add_argument("--interests", required=True, help="Interessensgebiete, kommagetrennt")
    parser.add_argument("--budget", required=True, help="Zeitbudget (z.B. '6 Monate')")
    parser.add_argument("--data-access", required=True, help="Datenzugang")
    parser.add_argument(
        "--output-mode",
        default="list",
        choices=["list", "full"],
        help="'list' = JSON-Array; 'full' = {topics, top_topic}",
    )
    parser.add_argument("--write-context", help="Pfad zur academic_context.md")
    args = parser.parse_args()

    interests = [i.strip() for i in args.interests.split(",") if i.strip()]
    topics_input = _load_topics_input(args.topics_json)
    topics = score_topics(
        topics_input=topics_input,
        interests=interests,
        budget=args.budget,
        data_access=args.data_access,
    )

    top_title = find_top_topic(topics)

    if args.write_context:
        write_to_context(Path(args.write_context), top_title)

    if args.output_mode == "full":
        output: Any = {"topics": topics, "top_topic": top_title}
    else:
        output = topics

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
