"""Query-Umformung (Multi-Query) fuer die produktive Vault-Suche (Issue #734).

Multi-Query ist das in #733 gemessene und empfohlene Verfahren (regelbasiert:
HyDE verliert same-language-Recall bei Cross-Language-Queries, Multi-Query
nicht). Dieses Modul ist die einzige Quelle fuer Prompt, Antwort-Parsing und
Rangfusion -- verschoben aus ``scripts/eval/query_expansion_prototypes.py``,
das ab hier re-exportiert statt dupliziert (kein zweiter Wahrheitsort fuer
denselben Prompt-Text, sonst driftet die Messung vom produktiven Pfad ab).

Der Schalter folgt demselben Vorrang wie die drei Modellschalter aus #719
(Argument > Env > ``config/parallel_agents.json`` > Default) ueber
:func:`academic_vault.config_switches.resolve_bool_switch`. Default: **aus**
-- die Messung aus #733 zeigt einen Gesamtmittel-MRR-Verlust (-0,0666) und
eine ~350-fache Latenz gegen einen Nutzen, der nur bei language-gap-Queries
greift.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
from collections.abc import Sequence
from pathlib import Path

from .config_switches import resolve_bool_switch

logger = logging.getLogger(__name__)

#: Kanonische Env-Variable (Issue #734). Kein Alt-Schalter zu migrieren --
#: dies ist der einzige Schalter fuer dieses neue Verfahren.
ENV_QUERY_EXPANSION_ENABLED = "ACADEMIC_RESEARCH_QUERY_EXPANSION"
CONFIG_KEY = "query_expansion_enabled"

#: Anzahl der Umformulierungen je Query (ohne das Original).
MULTI_QUERY_VARIANTS = 3

#: RRF-Konstante fuer die Fusion ueber die Multi-Query-Ranglisten. 60 ist der
#: Wert aus der Originalarbeit (Cormack et al. 2009) und derselbe Default wie
#: in ``academic_vault.retrieval.rrf_score``.
RRF_K = 60

#: Modell fuer die Umformung (#733: Sonnet, ueber die eingeloggte CLI-Sitzung,
#: kein API-Key -- #632).
DEFAULT_MODEL = "sonnet"

#: Timeout je ``claude -p``-Aufruf. Derselbe Wert wie im #733-Messlauf
#: (``scripts/eval/build_hyde_multiquery_fixture.py``): der CLI-Start bringt
#: Prozess-/Sitzungsaufbau mit, den eine Umformung innerhalb einer laufenden
#: Sitzung nicht bezahlt -- 240s ist eine grosszuegige obere Schranke, keine
#: erwartete Laufzeit.
CLI_TIMEOUT_S = 240

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
    beim Vergleich gegen eine eingefrorene Fixture auf.
    """
    digest = hashlib.sha256(template.encode("utf-8")).hexdigest()[:12]
    return f"{kind}-{digest}"


MULTI_QUERY_PROMPT_ID = prompt_id("mq", MULTI_QUERY_PROMPT_TEMPLATE)


def multi_query_prompt(query: str, n: int = MULTI_QUERY_VARIANTS) -> str:
    """Prompt, der zu einer Anfrage ``n`` Umformulierungen erzeugt."""
    return MULTI_QUERY_PROMPT_TEMPLATE.format(query=query, n=n)


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


def fuse_rankings_with_scores(
    rankings: Sequence[Sequence[str]], k: int = RRF_K
) -> list[tuple[str, float]]:
    """Reciprocal-Rank-Fusion ueber N Ranglisten von IDs.

    Jede Rangliste steuert fuer ihr Element auf Rang ``r`` (1-basiert) den
    Beitrag ``1 / (k + r)`` bei; die Beitraege werden je ID summiert. Eine ID,
    die in einer Liste fehlt, bekommt von dieser Liste nichts — sie wird nicht
    bestraft, sie geht nur leer aus.

    Bei Gleichstand entscheidet die Reihenfolge des ersten Auftretens ueber
    alle Listen hinweg -- ohne festen Tie-Break haengt das Ergebnis an der
    Iterationsreihenfolge eines Dicts.

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


def resolve_query_expansion_enabled(
    explicit: bool | None = None,
    config_path: str | Path | None = None,
) -> bool:
    """Ob die Multi-Query-Umformung vor der Suche aktiv ist (Issue #734).

    Vorrang: Argument > Env ``ACADEMIC_RESEARCH_QUERY_EXPANSION`` >
    ``config/parallel_agents.json`` (Schluessel ``query_expansion_enabled``) >
    Default ``False``. Kein Alt-Schalter/Alias -- dies ist der einzige
    Schalter fuer dieses Verfahren.
    """
    return resolve_bool_switch(
        explicit,
        [ENV_QUERY_EXPANSION_ENABLED],
        CONFIG_KEY,
        False,
        config_path,
    )


def expand_query(query: str, model: str = DEFAULT_MODEL) -> tuple[list[str], str | None]:
    """Erzeugt bis zu :data:`MULTI_QUERY_VARIANTS` Umformulierungen ueber die
    eingeloggte ``claude``-CLI (Subprozess, OAuth-Sitzung -- kein API-Key,
    #632).

    Schlaegt der Aufruf fehl (CLI fehlt, Timeout, Non-Zero-Exit, leere oder
    unbrauchbare Antwort), wirft diese Funktion NICHT -- die Suche darf daran
    nie scheitern. Stattdessen liefert sie eine leere Variantenliste und einen
    Fehlertext; der Aufrufer meldet diesen einmal und faehrt mit der
    unveraenderten Query fort.

    Returns:
        ``(Umformulierungen, Fehlertext)``. Bei Erfolg ist der Fehlertext
        ``None`` und die Liste hat bis zu :data:`MULTI_QUERY_VARIANTS`
        Eintraege. Bei Fehlschlag ist die Liste leer und der Fehlertext
        gesetzt.
    """
    prompt = multi_query_prompt(query)
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--model", model],
            capture_output=True,
            text=True,
            timeout=CLI_TIMEOUT_S,
        )
    except FileNotFoundError:
        return [], "claude-CLI nicht gefunden (nicht im PATH)"
    except subprocess.TimeoutExpired:
        return [], f"claude-CLI Timeout nach {CLI_TIMEOUT_S}s"
    except OSError as exc:
        return [], f"claude-CLI konnte nicht gestartet werden: {exc}"

    if proc.returncode != 0:
        stderr_tail = proc.stderr.strip()[-200:] if proc.stderr else ""
        return [], f"claude-CLI endete mit {proc.returncode}: {stderr_tail}"

    variants = parse_multi_query_response(proc.stdout.strip())
    if not variants:
        return [], "claude-CLI lieferte keine brauchbaren Umformulierungen"
    return variants, None
