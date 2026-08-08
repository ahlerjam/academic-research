#!/usr/bin/env python3
"""Prototypen der beiden Query-Umformungen aus Issue #733.

Hier steht ausschliesslich, was beide Verfahren ausmacht: die Prompt-Vorlagen
fuer die Umformung und die Rangfusion fuer Multi-Query. Gemessen wird in
``scripts/eval/run_hyde_multiquery_eval.py``, erzeugt wird die Fixture in
``scripts/eval/build_hyde_multiquery_fixture.py``.

**HyDE** erzeugt zu einer Frage eine hypothetische Antwortpassage und embeddet
diese statt der Frage. **Multi-Query** erzeugt mehrere Umformulierungen, sucht
mit jeder einzeln und fusioniert die Ranglisten.

Fusion liegt jetzt produktiv in ``academic_vault.query_expansion`` (Issue
#734, Multi-Query war das empfohlene Verfahren): Prompt, Antwort-Parsing und
Rangfusion fuer Multi-Query sind dorthin verschoben und werden hier nur noch
re-exportiert -- HyDE (das unterlegene Verfahren, #733) bleibt ausschliesslich
hier, es wird nicht produktiv angebunden.

Die Prompt-Vorlagen sind bewusst so gebaut, dass das Modell **nur** den
Query-Text sieht — kein Goldset, keine Anker, kein Zieltext. Sonst waere ein
gemessener Gewinn durchgereichte Loesung statt Verfahrensgewinn
(``test_transforms_carry_no_goldset_leakage``).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from academic_vault.query_expansion import (  # noqa: E402
    MULTI_QUERY_PROMPT_ID,
    MULTI_QUERY_PROMPT_TEMPLATE,
    MULTI_QUERY_VARIANTS,
    RRF_K,
    fuse_rankings,
    fuse_rankings_with_scores,
    multi_query_prompt,
    parse_multi_query_response,
    prompt_id,
)

__all__ = [
    "ARMS",
    "HYDE_PROMPT_ID",
    "HYDE_PROMPT_TEMPLATE",
    "MULTI_QUERY_PROMPT_ID",
    "MULTI_QUERY_PROMPT_TEMPLATE",
    "MULTI_QUERY_VARIANTS",
    "RRF_K",
    "fuse_rankings",
    "fuse_rankings_with_scores",
    "hyde_passage_prompt",
    "multi_query_prompt",
    "parse_multi_query_response",
    "prompt_id",
]

#: Arme des Messlaufs. ``hyde_query_prefix`` und ``hyde_passage_prefix``
#: unterscheiden sich nur darin, mit welchem e5-Praefix die hypothetische
#: Passage eingebettet wird — welches richtig ist, ist fuer e5 nicht
#: dokumentiert und deshalb hier eine Messfrage statt einer Annahme.
ARMS = ("baseline", "hyde_query_prefix", "hyde_passage_prefix", "multi_query")

HYDE_PROMPT_TEMPLATE = """Du bekommst eine Suchanfrage an eine Sammlung wissenschaftlicher Volltexte.

Schreibe eine hypothetische Passage von drei bis fünf Sätzen, die so in einem \
Fachtext stehen könnte, der diese Anfrage beantwortet. Schreibe im Register \
wissenschaftlicher Fachprosa und auf Englisch — der üblichen Sprache dieser \
Fachliteratur —, unabhängig davon, in welcher Sprache die Anfrage gestellt ist.

Die Passage muss nicht wahr sein; sie muss klingen wie die Textstelle, die die \
Anfrage beantwortet. Gib ausschließlich die Passage aus: keine Einleitung, \
keine Anführungszeichen, keine Überschrift.

Anfrage: {query}"""

HYDE_PROMPT_ID = prompt_id("hyde", HYDE_PROMPT_TEMPLATE)


def hyde_passage_prompt(query: str) -> str:
    """Prompt, der zu einer Anfrage eine hypothetische Antwortpassage erzeugt."""
    return HYDE_PROMPT_TEMPLATE.format(query=query)
