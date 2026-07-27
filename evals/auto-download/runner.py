#!/usr/bin/env python3
"""Eval-Runner fuer auto-download (Issue #390).

Prueft hermetisch (kein Netz, kein API-Key), ob die 20 kuratierten Quellen aus
``sources.yaml`` den in ``expected_tier`` genannten Tier von ``resolve_pdf_url()``
(``scripts/pdf.py``) ueberhaupt erreichen.

Verfahren: Fuer jede Quelle wird genau eine Tier-Funktion auf „Treffer" gestellt
und alle uebrigen auf „kein Treffer". Erreicht die Aufloesung den erwarteten
Tier nicht, fehlen der Quelle die noetigen Metadaten (EuropePMC braucht eine
DOI, arXiv einen Titel, DOAB ISBN oder Titel) oder die Tier-Reihenfolge in
``scripts/pdf.py`` hat sich geaendert.

Ausdruecklich NICHT geprueft wird ``expected_hit``: ob eine reale API heute ein
PDF liefert, ist netzabhaengig und darf eine CI nicht rot faerben. Der Live-Lauf
gegen echte APIs bleibt ein manueller Operator-Schritt (siehe README.md).

Aufruf: python3 evals/auto-download/runner.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import yaml

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent.parent
SOURCES_PATH = EVAL_DIR / "sources.yaml"

if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pdf as pdf_module  # noqa: E402

# Tier-Label (Rueckgabewert von resolve_pdf_url) -> Name der Tier-Funktion in
# scripts/pdf.py. Aenderungen an der Tier-Liste muessen hier nachgezogen werden;
# tests/evals/test_auto_download_routing.py prueft das Vokabular gegen sources.yaml.
TIER_FUNCTIONS: dict[str, str] = {
    "unpaywall": "tier_unpaywall",
    "core": "tier_core",
    "module_oa": "tier_module_urls",
    "direct": "tier_direct_url",
    "arxiv": "tier_arxiv_title",
    "doab": "tier_doab",
    "openaccessbutton": "tier_openaccessbutton",
    "europepmc": "tier_europepmc",
}

_HIT_URL = "https://eval.invalid/routed.pdf"
_EVAL_EMAIL = "eval@example.invalid"


def load_sources() -> list[dict[str, Any]]:
    """Laedt die kuratierten Quellen aus sources.yaml."""
    data = yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8"))
    return list(data["sources"])


def _paper_from_source(source: dict[str, Any]) -> dict[str, Any]:
    """Bildet einen sources.yaml-Eintrag auf das paper-dict von resolve_pdf_url ab."""
    return {
        "doi": source.get("doi"),
        "isbn": source.get("isbn"),
        "title": source.get("title"),
        "type": source.get("type"),
    }


def resolve_with_only(paper: dict[str, Any], hit_tier: str | None) -> tuple[str | None, str | None]:
    """Loest ``paper`` auf, wobei ausschliesslich ``hit_tier`` einen Treffer liefert.

    Alle Tier-Funktionen in ``scripts/pdf.py`` werden fuer die Dauer des Aufrufs
    ersetzt; der uebergebene httpx-Client ist ein MagicMock und wird nie benutzt.
    ``hit_tier=None`` stellt alle Tiers auf Fehlschlag (Negativkontrolle).
    """
    originals = {name: getattr(pdf_module, name) for name in TIER_FUNCTIONS.values()}
    hit_function = TIER_FUNCTIONS[hit_tier] if hit_tier else None
    try:
        for tier_label, func_name in TIER_FUNCTIONS.items():
            hit = func_name == hit_function

            def _stub(*_args: Any, _hit: bool = hit, **_kwargs: Any) -> str | None:
                return _HIT_URL if _hit else None

            setattr(pdf_module, func_name, _stub)
            del tier_label
        url, tier, _error = pdf_module.resolve_pdf_url(MagicMock(), paper, _EVAL_EMAIL)
        return url, tier
    finally:
        for name, func in originals.items():
            setattr(pdf_module, name, func)


def run_eval_cases() -> dict:
    """Fuehrt alle Routing-Cases aus und gibt strukturierte Ergebnisse zurueck.

    Rueckgabe:
        dict mit ``passed`` / ``failed`` / ``total`` und ``details`` (je Quelle:
        id/expected_tier/routed_tier/routed_url/blank_run_tier/blank_run_url/ok).
    """
    details: list[dict] = []
    for source in load_sources():
        paper = _paper_from_source(source)
        expected = source.get("expected_tier")

        routed_url, routed_tier = resolve_with_only(paper, expected)
        blank_url, blank_tier = resolve_with_only(paper, None)

        ok = routed_tier == expected and blank_tier is None and blank_url is None
        details.append(
            {
                "id": source["id"],
                "type": source.get("type"),
                "domain": source.get("domain"),
                "expected_tier": expected,
                "routed_tier": routed_tier,
                "routed_url": routed_url,
                "blank_run_tier": blank_tier,
                "blank_run_url": blank_url,
                "ok": ok,
            }
        )

    passed = sum(1 for d in details if d["ok"])
    return {
        "passed": passed,
        "failed": len(details) - passed,
        "total": len(details),
        "details": details,
    }


def run_eval() -> None:
    """CLI-Einstiegspunkt: Report auf stdout, Exit 1 bei Routing-Fehler."""
    summary = run_eval_cases()
    for d in summary["details"]:
        status = "OK" if d["ok"] else "FAIL"
        print(
            f"  [{status}] {d['id']:12} expected_tier={str(d['expected_tier']):17}"
            f" routed={str(d['routed_tier'])}"
        )

    print(f"\n{'=' * 60}")
    print(f"Routing: {summary['passed']}/{summary['total']} Quellen erreichen ihren Tier")
    print("Negativkontrolle: ohne Treffer muss jede Quelle (None, None) liefern")
    print("Nicht geprueft: expected_hit (netzabhaengig, Operator-Schritt)")

    if summary["failed"] > 0:
        sys.exit(1)
    print("\nAlle Routing-Cases bestanden.")


if __name__ == "__main__":
    run_eval()
