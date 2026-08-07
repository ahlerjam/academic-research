#!/usr/bin/env python3
"""Prototypen der beiden Query-Umformungen aus Issue #733.

Hier steht ausschliesslich, was beide Verfahren ausmacht: die Prompt-Vorlagen
fuer die Umformung und die Rangfusion fuer Multi-Query. Gemessen wird in
``scripts/eval/run_hyde_multiquery_eval.py``, erzeugt wird die Fixture in
``scripts/eval/build_hyde_multiquery_fixture.py``.

**HyDE** erzeugt zu einer Frage eine hypothetische Antwortpassage und embeddet
diese statt der Frage. **Multi-Query** erzeugt mehrere Umformulierungen, sucht
mit jeder einzeln und fusioniert die Ranglisten.

Warum eine eigene Fusion und nicht ``academic_vault.retrieval.reciprocal_rank_fusion``:
die Produktionsfunktion ist auf genau zwei Listen und den Schluessel
``paper_id`` festgelegt: hier werden N Ranglisten ueber ``chunk_id`` fusioniert.
Ein Umbau der Produktionsfunktion waere ein Eingriff in einen geschuetzten
Bereich fuer einen Prototyp, dessen Ergebnis noch offen ist.

Die Prompt-Vorlagen sind bewusst so gebaut, dass das Modell **nur** den
Query-Text sieht — kein Goldset, keine Anker, kein Zieltext. Sonst waere ein
gemessener Gewinn durchgereichte Loesung statt Verfahrensgewinn
(``test_transforms_carry_no_goldset_leakage``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

#: Arme des Messlaufs. ``hyde_query_prefix`` und ``hyde_passage_prefix``
#: unterscheiden sich nur darin, mit welchem e5-Praefix die hypothetische
#: Passage eingebettet wird — welches richtig ist, ist fuer e5 nicht
#: dokumentiert und deshalb hier eine Messfrage statt einer Annahme.
ARMS = ("baseline", "hyde_query_prefix", "hyde_passage_prefix", "multi_query")

#: Anzahl der Umformulierungen je Query im Multi-Query-Arm (ohne das Original).
MULTI_QUERY_VARIANTS = 3

#: RRF-Konstante. 60 ist der Wert aus der Originalarbeit und derselbe Default
#: wie in ``academic_vault.retrieval.rrf_score``.
RRF_K = 60

HYDE_PROMPT_TEMPLATE = """Du bekommst eine Suchanfrage an eine Sammlung wissenschaftlicher Volltexte.

Schreibe eine hypothetische Passage von drei bis fünf Sätzen, die so in einem \
Fachtext stehen könnte, der diese Anfrage beantwortet. Schreibe im Register \
wissenschaftlicher Fachprosa und auf Englisch — der üblichen Sprache dieser \
Fachliteratur —, unabhängig davon, in welcher Sprache die Anfrage gestellt ist.

Die Passage muss nicht wahr sein; sie muss klingen wie die Textstelle, die die \
Anfrage beantwortet. Gib ausschließlich die Passage aus: keine Einleitung, \
keine Anführungszeichen, keine Überschrift.

Anfrage: {query}"""

MULTI_QUERY_PROMPT_TEMPLATE = """Du bekommst eine Suchanfrage an eine Sammlung wissenschaftlicher Volltexte.

Schreibe genau {n} Umformulierungen dieser Anfrage, die dieselbe Informationsfrage \
stellen, aber anders formuliert sind:

1. eine in englischer Fachsprache,
2. eine in deutscher Fachsprache,
3. eine, die die Frage präziser und ausführlicher stellt als das Original, in der \
Sprache der Anfrage.

Jede Umformulierung steht auf einer eigenen Zeile, ohne Nummerierung, ohne \
Aufzählungszeichen, ohne Anführungszeichen. Gib nichts außer den {n} Zeilen aus.

Anfrage: {query}"""


def prompt_id(kind: str, template: str) -> str:
    """Kurzer Fingerabdruck einer Prompt-Vorlage.

    Haengt an der Vorlage selbst statt an einer handgepflegten Versionsnummer:
    wer den Prompt aendert, ohne die Umformungen neu zu erzeugen, faellt damit
    beim Vergleich gegen ``transforms.json`` auf.
    """
    digest = hashlib.sha256(template.encode("utf-8")).hexdigest()[:12]
    return f"{kind}-{digest}"


HYDE_PROMPT_ID = prompt_id("hyde", HYDE_PROMPT_TEMPLATE)
MULTI_QUERY_PROMPT_ID = prompt_id("mq", MULTI_QUERY_PROMPT_TEMPLATE)


def hyde_passage_prompt(query: str) -> str:
    """Prompt, der zu einer Anfrage eine hypothetische Antwortpassage erzeugt."""
    return HYDE_PROMPT_TEMPLATE.format(query=query)


def multi_query_prompt(query: str, n: int = MULTI_QUERY_VARIANTS) -> str:
    """Prompt, der zu einer Anfrage ``n`` Umformulierungen erzeugt."""
    return MULTI_QUERY_PROMPT_TEMPLATE.format(query=query, n=n)


def fuse_rankings_with_scores(
    rankings: Sequence[Sequence[str]], k: int = RRF_K
) -> list[tuple[str, float]]:
    """Reciprocal-Rank-Fusion ueber N Ranglisten von IDs.

    Jede Rangliste steuert fuer ihr Element auf Rang ``r`` (1-basiert) den
    Beitrag ``1 / (k + r)`` bei; die Beitraege werden je ID summiert. Eine ID,
    die in einer Liste fehlt, bekommt von dieser Liste nichts — sie wird nicht
    bestraft, sie geht nur leer aus.

    Beispiel, von Hand nachgerechnet (``k=60``)::

        [["a", "b"], ["b", "a"]]
        a: 1/(60+1) + 1/(60+2) = 0,016393 + 0,016129 = 0,032522
        b: 1/(60+2) + 1/(60+1) = 0,016129 + 0,016393 = 0,032522

    Bei Gleichstand entscheidet die Reihenfolge des ersten Auftretens ueber alle
    Listen hinweg. Das ist keine Kosmetik: ohne festen Tie-Break haengt das
    Ergebnis an der Iterationsreihenfolge eines Dicts, und zwei Laeufe desselben
    Codes lieferten verschiedene Metriken.

    Args:
        rankings: Ranglisten, jeweils absteigend nach Relevanz.
        k: RRF-Konstante. Kleines ``k`` gewichtet vordere Raenge staerker.

    Returns:
        ``(id, score)`` absteigend nach Score.
    """
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    position = 0
    for ranking in rankings:
        for rank, identifier in enumerate(ranking, start=1):
            scores[identifier] = scores.get(identifier, 0.0) + 1.0 / (k + rank)
            if identifier not in first_seen:
                first_seen[identifier] = position
                position += 1
    return sorted(scores.items(), key=lambda item: (-item[1], first_seen[item[0]]))


def fuse_rankings(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> list[str]:
    """Wie :func:`fuse_rankings_with_scores`, aber nur die fusionierte Reihenfolge."""
    return [identifier for identifier, _ in fuse_rankings_with_scores(rankings, k=k)]


def parse_multi_query_response(text: str, n: int = MULTI_QUERY_VARIANTS) -> list[str]:
    """Zerlegt die Modellantwort in Umformulierungen — eine je Zeile.

    Raeumt auf, was Modelle trotz Prompt gelegentlich beilegen: Nummerierung,
    Aufzaehlungszeichen, Anfuehrungszeichen. Mehr als ``n`` Zeilen werden
    abgeschnitten; weniger sind ein Fehler des Aufrufers, nicht dieser Funktion.
    """
    cleaned: list[str] = []
    for line in text.splitlines():
        stripped = line.strip().strip('"').strip()
        if not stripped:
            continue
        for prefix in (f"{len(cleaned) + 1}.", f"{len(cleaned) + 1})", "-", "*", "•"):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix) :].strip().strip('"').strip()
                break
        if stripped:
            cleaned.append(stripped)
    return cleaned[:n]
