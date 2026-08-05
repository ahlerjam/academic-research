#!/usr/bin/env python3
"""Offline-Qualitaetsmetrik fuer chapter-writer (Issue #606).

Gemessen wird **Zitatintegritaet am fertigen Kapitelentwurf** — der Defekt, der
ungeprueft in die abgegebene Arbeit wandert und dort nicht mehr auffaellt:

1. **Loest jeder Klammerbeleg auf?** Jedes ``(Autor, Jahr)`` wird ueber die
   Produktionsfunktion ``academic_vault.server.verify_citations()`` gegen einen
   Vault gefahren, der aus ``corpus.json`` aufgebaut wird. Kein Treffer =
   erfundene Quelle.
2. **Ist jedes Direktzitat woertlich?** Jeder Text in deutschen
   Anfuehrungszeichen wird ueber ``search_quote_text()`` gesucht. Kein Treffer =
   verfaelschter Wortlaut.
3. **Wird ueberhaupt genug belegt?** Zitatdichte je 1000 Woerter gegen die
   Schwelle aus ``skills/chapter-writer/references/quality-review-config.md``
   (``Quellen pro 1000 Woerter``, ``>= 5``).

Kein Netz, kein API-Schluessel: der Vault ist eine temporaere SQLite-Datei, die
Pruefpfade sind dieselben, die ``hooks/verbatim-guard.mjs`` im Betrieb nutzt.

Aufruf: python3 evals/chapter-writer/runner.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = Path(__file__).resolve().parent
CORPUS_PATH = EVAL_DIR / "corpus.json"
COUNTER_PATH = EVAL_DIR / "counter_examples.json"

sys.path.insert(0, str(REPO_ROOT))

from academic_vault.db import VaultDB  # noqa: E402
from academic_vault.server import search_quote_text, verify_citations  # noqa: E402

_YEAR = r"1[89]\d{2}|20\d{2}"
_NAME = r"[A-ZÄÖÜ][\wÄÖÜäöüß'-]*"
#: Beide im Deutschen ueblichen Belegformen:
#: klammernd ``(Bauer, 2021)`` / ``(Bauer & Kern, 2019, S. 44)`` und
#: narrativ ``Bauer (2021)`` / ``Bauer et al. (2021)``. Nur die erste Form zu
#: erkennen haette in einem realen Kapitelentwurf die Mehrzahl der Belege
#: uebersehen und die Zitatdichte systematisch zu niedrig gemessen.
CITATION_RE = re.compile(
    rf"\((?P<pauthors>{_NAME}(?:\s+(?:&|und)\s+{_NAME}|\s+et\s+al\.)?),"
    rf"\s*(?P<pyear>{_YEAR})(?:,\s*S\.\s*\d+)?\)"
    rf"|(?P<nauthors>{_NAME}(?:\s+(?:&|und)\s+{_NAME}|\s+et\s+al\.)?)"
    rf"\s\((?P<nyear>{_YEAR})(?:,\s*S\.\s*\d+)?\)"
)
#: Fuer die Wortzaehlung: jede Klammer, die eine Jahreszahl enthaelt. Bewusst
#: NICHT ``CITATION_RE`` — bei narrativen Belegen steht der Autorname im Satz
#: und zaehlt als Fliesstext mit.
CITATION_PAREN_RE = re.compile(rf"\([^()]*(?:{_YEAR})[^()]*\)")
#: Deutsche Anfuehrungszeichen — das Format, das die Skills selbst verwenden.
QUOTE_RE = re.compile(r"„([^„“]+)“")
#: Markdown-Ueberschriften zaehlen nicht als Fliesstext.
HEADING_RE = re.compile(r"^#{1,6}\s.*$", re.M)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def build_vault(spec: dict[str, Any]) -> str:
    """Baut eine temporaere SQLite-Datenbank aus dem committeten Bestand."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp.name
    tmp.close()

    db = VaultDB(db_path)
    db.init_schema()

    conn = VaultDB._open(db_path)
    now = int(time.time())
    for paper in spec["papers"]:
        csl = {
            "title": paper["title"],
            "author": [{"family": paper["family"], "given": paper["given"]}],
            "issued": {"date-parts": [[paper["year"]]]},
        }
        conn.execute(
            """INSERT OR REPLACE INTO papers
               (paper_id, type, csl_json, added_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                paper["paper_id"],
                "article-journal",
                json.dumps(csl, ensure_ascii=False),
                now,
                now,
            ),
        )
    for quote in spec["quotes"]:
        conn.execute(
            """INSERT INTO quotes
               (quote_id, paper_id, verbatim, extraction_method, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (str(uuid4()), quote["paper_id"], quote["verbatim"], "manual", now),
        )
    conn.commit()
    conn.close()
    return db_path


def _first_family(authors: str) -> str:
    """``Bauer & Kern`` / ``Bauer et al.`` / ``Bauer und Kern`` -> ``Bauer``."""
    cleaned = re.split(r"\s+(?:&|und)\s+|\s+et al\.?", authors.strip())[0]
    return cleaned.strip().rstrip(",").split()[-1] if cleaned.strip() else ""


def extract_citations(text: str) -> list[dict[str, Any]]:
    citations = []
    for match in CITATION_RE.finditer(text):
        authors = match.group("pauthors") or match.group("nauthors")
        year = match.group("pyear") or match.group("nyear")
        citations.append(
            {
                "raw": match.group(0),
                "family": _first_family(authors),
                "year": int(year),
            }
        )
    return citations


def extract_direct_quotes(text: str) -> list[str]:
    return [_normalize_whitespace(match) for match in QUOTE_RE.findall(text)]


def count_words(text: str) -> int:
    """Fliesstext-Woerter: ohne Ueberschriften, ohne Klammerbelege, ohne Satzzeichen.

    Die Belege selbst zaehlen nicht mit, sonst haette ein Entwurf mit vielen
    Belegen automatisch auch mehr Woerter und die Dichte bliebe stehen.
    """
    body = HEADING_RE.sub("", text)
    body = CITATION_PAREN_RE.sub(" ", body)
    return sum(1 for token in body.split() if re.search(r"[0-9A-Za-zÄÖÜäöüß]", token))


def evaluate_draft(db_path: str, text: str, density_min: float) -> dict[str, Any]:
    """Misst einen einzelnen Entwurf gegen alle drei Pruefpfade."""
    citations = extract_citations(text)
    quotes = extract_direct_quotes(text)
    words = count_words(text)

    verdicts = verify_citations(
        db_path, [{"family": c["family"], "year": c["year"], "page": None} for c in citations]
    )
    unresolved = [
        f"{citation['family']} {citation['year']}"
        for citation, verdict in zip(citations, verdicts)
        if verdict["status"] == "no-match"
    ]

    not_verbatim = [quote for quote in quotes if not search_quote_text(db_path, quote)]

    density = round(1000.0 * len(citations) / words, 1) if words else 0.0

    failures = []
    if unresolved:
        failures.append(f"nicht aufloesbare Belege: {unresolved}")
    if not_verbatim:
        failures.append(f"nicht woertliche Direktzitate: {len(not_verbatim)}")
    if density < density_min:
        failures.append(f"Zitatdichte {density}/1000 Woerter < {density_min}")

    return {
        "words": words,
        "citations_total": len(citations),
        "citations_unresolved": len(unresolved),
        "unresolved_examples": unresolved,
        "direct_quotes_total": len(quotes),
        "quotes_not_verbatim": len(not_verbatim),
        "not_verbatim_examples": not_verbatim,
        "citation_density_per_1000": density,
        "verdict": "PASS" if not failures else "FAIL",
        "failures": failures,
    }


def run_eval_cases() -> dict[str, Any]:
    """Fuehrt Korpus und Gegenproben aus. Importierbar, ohne Seiteneffekte."""
    corpus = _load(CORPUS_PATH)
    counter = _load(COUNTER_PATH)
    density_min = float(corpus["thresholds"]["citation_density_per_1000_min"])
    db_path = build_vault(corpus["vault"])

    try:
        cases = []
        for case in corpus["cases"]:
            text = (EVAL_DIR / case["draft"]).read_text(encoding="utf-8")
            measured = evaluate_draft(db_path, text, density_min)
            cases.append(
                {
                    "id": case["id"],
                    "draft": case["draft"],
                    "expected": case["expected"],
                    "measured": measured,
                    "matches_expected": all(
                        measured[key] == value for key, value in case["expected"].items()
                    ),
                }
            )

        counter_cases = []
        for case in counter["cases"]:
            text = (EVAL_DIR / case["draft"]).read_text(encoding="utf-8")
            measured = evaluate_draft(db_path, text, density_min)
            counter_cases.append(
                {
                    "id": case["id"],
                    "label": case["label"],
                    "defect": case["defect"],
                    "expected": case["expected"],
                    "measured": measured,
                    "rejected": measured["verdict"] == "FAIL",
                    "matches_expected": all(
                        measured[key] == value for key, value in case["expected"].items()
                    ),
                }
            )
    finally:
        os.unlink(db_path)

    return {
        "component": "chapter-writer",
        "density_min": density_min,
        "vault_papers": len(corpus["vault"]["papers"]),
        "vault_quotes": len(corpus["vault"]["quotes"]),
        "cases": cases,
        "counter_examples": counter_cases,
        "passed": sum(1 for case in cases if case["measured"]["verdict"] == "PASS"),
        "total": len(cases),
    }


def run_eval() -> None:
    """CLI-Einstiegspunkt: Report drucken, Exit 1 bei Abweichung."""
    summary = run_eval_cases()
    ok = True
    print(f"Vault: {summary['vault_papers']} Paper, {summary['vault_quotes']} Zitate\n")
    for case in summary["cases"]:
        measured = case["measured"]
        mark = "OK" if case["matches_expected"] and measured["verdict"] == "PASS" else "FAIL"
        ok = ok and mark == "OK"
        print(
            f"  [{mark}] {case['id']}: {measured['words']} Woerter, "
            f"{measured['citations_total']} Belege ({measured['citations_unresolved']} offen), "
            f"{measured['direct_quotes_total']} Direktzitate "
            f"({measured['quotes_not_verbatim']} nicht woertlich), "
            f"Dichte {measured['citation_density_per_1000']}/1000"
        )
    print("\nGegenproben:")
    for case in summary["counter_examples"]:
        mark = "OK" if case["rejected"] and case["matches_expected"] else "NICHT ERKANNT"
        ok = ok and mark == "OK"
        print(f"  [{mark}] {case['id']} ({case['label']}): {case['measured']['failures']}")
    if not ok:
        sys.exit(1)
    print("\nAlle Entwuerfe wie erwartet bewertet, alle Gegenproben ausgeschlagen.")


if __name__ == "__main__":
    run_eval()
