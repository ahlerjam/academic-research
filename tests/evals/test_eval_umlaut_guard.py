"""Umlaut-Guard fuer Eval-Erwartungen (Issue #826).

Das Repo schreibt Deutsch mit voller Orthografie (AGENTS.md). Eine
``expected.value``/``expected.reject``-Erwartung, die ausschliesslich eine
ASCII-Transliteration (``ae``/``oe``/``ue`` statt ``ä``/``ö``/``ü``) enthaelt,
kann eine inhaltlich richtige, korrekt orthografierte Antwort nicht treffen --
der Fall ``sc-02`` (``evals/submission-checker/evals.json``) ist genau daran
gescheitert (Doppelfehlschlag ``with_skill``/``without_skill`` am 2026-08-10,
obwohl die Antwort inhaltlich richtig war). Dieser Test verhindert Rueckfaelle:
er scannt alle ``evals/*/evals.json`` auf genau dieses Muster.

Heuristik: ``ae``/``oe``/``ue``/``Ae``/``Oe``/``Ue`` gilt als Transliterations-
Kandidat, ausser das vorangehende Zeichen ist ein Vokal oder ``q`` -- das
schliesst echte Nicht-Umlaut-Faelle wie ``qu`` + Vokal (``question``,
``quellennah``) und den Diphthong ``eu`` + ``er`` (``Betreuer``) aus, ohne eine
Wortliste pflegen zu muessen. Ein Treffer ist nur dann ein Fund, wenn die
GESAMTE ``value``/``reject``-Zeichenkette keinen einzigen echten Umlaut
enthaelt -- Faelle wie ``Pr(ü|ue)fbericht``, die beide Schreibweisen
abdecken, sind das gewuenschte Muster und bleiben unbeanstandet.

Eigennamen sind eine legitime Ausnahme, wenn die Fixture-Daten sie exakt so
schreiben (z. B. ``vault_fixture.py``/``literature_state.md`` fuer
``Mueller``) oder der Eval-Input die Schreibweise woertlich vorgibt, ohne dass
eine Vault-Quelle sie normalisieren koennte. Diese Faelle sind explizit
gegen die Fixtures geprueft (Issue #826) und ausdruecklich, mit Begruendung,
von diesem Guard ausgenommen.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests.evals.eval_runner import EVALS_ROOT

_CANDIDATE = re.compile(r"(ae|oe|ue|Ae|Oe|Ue)")
_NON_UMLAUT_PRECEDERS = set("aeiouqAEIOUQ")
_UMLAUT_CHARS = re.compile(r"[äöüÄÖÜ]")

# (evals.json-Pfad relativ zu EVALS_ROOT, prompt/case-id) -- gegen die
# Fixture-Daten geprueft (Issue #826): "Mueller" ist dort selbst ASCII
# geschrieben (tests/evals/vault_fixture.py, fixtures/context_fs/
# literature_state.md), bzw. der Eval-Input liefert die Schreibweise woertlich
# ohne Vault-Normalisierung (ce-02). Kein toter Zweig, sondern korrekte
# Spiegelung der Datenlage.
ALLOWED_ASCII_NAMES = {
    ("chapter-writer/evals.json", "cw-04"),
    ("citation-extraction/evals.json", "ce-02"),
    ("citation-extraction/evals.json", "ce-vault-02"),
}


def _has_ascii_transliteration_candidate(value: str) -> bool:
    for m in _CANDIDATE.finditer(value):
        idx = m.start()
        prev = value[idx - 1] if idx > 0 else None
        if prev is not None and prev.isalpha() and prev in _NON_UMLAUT_PRECEDERS:
            continue
        return True
    return False


def _dead_ascii_branches(value: str) -> bool:
    """True, wenn ``value`` einen Transliterations-Kandidaten enthaelt, aber
    keinerlei echten Umlaut -- also die Erwartung nie auf eine korrekt
    orthografierte Antwort passen kann."""
    return _has_ascii_transliteration_candidate(value) and not _UMLAUT_CHARS.search(value)


def _iter_expectations(data: dict[str, Any] | list[Any]) -> list[tuple[str, str, str]]:
    """Liefert (case_id, field_label, value) fuer alle expected.value/.reject.

    Deckt beide Eval-Schemata im Repo ab: ``{"prompts": [...], "cases": [...]}``
    (die meisten Skill-Suiten) UND die abweichenden Top-Level-Listen der
    Fetcher-Suiten (``fetch``/``figure-verifier``/``oa-fetchers``/
    ``free-archive-fetchers``/``publisher-fetchers``/``generic-fetcher``).
    Deren ``expected``-Objekte sind strukturelle Booleans/Keys statt
    ``type``/``value``/``reject`` -- ``.get("value")``/``.get("reject")``
    liefert dort einfach ``None`` und die Datei traegt nichts zum Guard bei
    (bewusst, Issue #826-Scope-Abgrenzung zu #823/#824)."""
    out: list[tuple[str, str, str]] = []
    all_cases: list[dict[str, Any]] = []
    if isinstance(data, list):
        all_cases.extend(data)
    else:
        for key in ("prompts", "cases"):
            entries = data.get(key)
            if isinstance(entries, list):
                all_cases.extend(entries)
    for case in all_cases:
        expected = case.get("expected")
        if not isinstance(expected, dict):
            continue
        case_id = str(case.get("id"))
        for label in ("value", "reject"):
            raw = expected.get(label)
            if raw is None:
                continue
            values = [raw] if isinstance(raw, str) else raw
            for v in values:
                if isinstance(v, str):
                    out.append((case_id, label, v))
    return out


def _eval_files() -> list[Path]:
    return sorted(EVALS_ROOT.glob("*/evals.json"))


@pytest.mark.parametrize("path", _eval_files(), ids=lambda p: p.parent.name)
def test_no_dead_ascii_umlaut_expectations(path: Path) -> None:
    data = json.loads(path.read_text())
    rel = f"{path.parent.name}/{path.name}"
    offenders = []
    for case_id, label, value in _iter_expectations(data):
        if (rel, case_id) in ALLOWED_ASCII_NAMES:
            continue
        if _dead_ascii_branches(value):
            offenders.append(f"{case_id} (expected.{label}={value!r})")
    assert not offenders, (
        f"{rel}: Erwartung(en) mit reiner ASCII-Transliteration ohne "
        f"Umlaut-Alternative -- kann eine korrekt orthografierte Antwort "
        f"nicht treffen (Issue #826): {offenders}"
    )


def test_guard_detects_synthetic_dead_branch() -> None:
    """Gegenprobe: der Guard muss auf einem konstruierten Fall anschlagen,
    der exakt dem urspruenglichen sc-02-Defekt entspricht (kein committetes
    Fixture -- rein synthetisch, beweist nur die Guard-Logik selbst)."""
    assert _dead_ascii_branches("Pruefziffer")
    assert _dead_ascii_branches("Erklaerung")
    # Das reparierte Muster (beide Schreibweisen) darf NICHT anschlagen.
    assert not _dead_ascii_branches("Erkl(ä|ae)rung")
    assert not _dead_ascii_branches("Pr(ü|ue)fziffer")
    # Bekannte Nicht-Umlaut-Faelle (qu + Vokal, eu + er) duerfen nicht anschlagen.
    assert not _dead_ascii_branches("research-question-refiner")
    assert not _dead_ascii_branches("quellennah")
    assert not _dead_ascii_branches("Betreuer")
