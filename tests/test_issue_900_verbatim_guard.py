"""Regressionstests fuer Issue #900: Anfuehrungszeichen-Paarung und den
[UNVERIFIED]-Marker in hooks/verbatim-guard.mjs.

Zwei Befunde vom 12.08.2026:

1. ``extractQuoteSpans()`` paarte Anfuehrungszeichen ueber eine gierige Regex
   (``/"([^"]{10,})"/g``), die bei zwei KURZEN Begriffen in Anfuehrungszeichen
   im selben Absatz das SCHLIESSENDE Zeichen des ersten mit dem OEFFNENDEN des
   zweiten verband — der Fliesstext dazwischen wurde faelschlich als Zitat
   gelesen und blockte den Write. Fix: ein sequenzieller Paar-Scanner je
   Delimiter-Typ (scanDelimiterPairs) statt der gierigen Regex.

2. Der ``[UNVERIFIED]``-Marker fuer Klammerbelege (Issue #378) wurde auch
   INNERHALB eines Anfuehrungszeichen-Zitats gesetzt und veraenderte damit den
   geprueften Wortlaut. Fix: Belege, deren Fundstelle in einem
   extractQuoteSpans()-Span liegt, werden weiterhin gemeldet, aber nicht mehr
   markiert.

Der Hook laeuft als echter node-Subprocess (Muster aus
tests/test_issue_378_citation_guard.py / tests/test_verbatim_figure_guard.py).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "verbatim-guard.mjs"

pytest.importorskip("academic_vault", reason="academic_vault-Paket nicht importierbar")


def run_hook(
    content: str,
    file_path: str = "kapitel/kap1.md",
    env_overrides: dict | None = None,
) -> subprocess.CompletedProcess:
    payload = json.dumps(
        {"tool_name": "Write", "tool_input": {"file_path": file_path, "content": content}}
    )
    env = os.environ.copy()
    for key in [k for k in env if k.startswith("ACADEMIC_CITATION_")]:
        del env[key]
    env["VAULT_DB_PATH"] = str(REPO_ROOT / "nonexistent_vault_for_tests.db")
    env["ACADEMIC_CITATION_CASCADE"] = "off"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["node", str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def updated_content(result: subprocess.CompletedProcess) -> str:
    assert result.stdout.strip(), f"Kein stdout-JSON. stderr: {result.stderr}"
    data = json.loads(result.stdout)
    return data["hookSpecificOutput"]["updatedInput"]["content"]


def _make_vault(tmp_path: Path, name: str) -> str:
    from academic_vault.db import VaultDB

    db_path = str(tmp_path / name)
    db = VaultDB(db_path)
    db.init_schema()
    return db_path


@pytest.fixture
def empty_vault(tmp_path):
    return _make_vault(tmp_path, "empty_900.db")


@pytest.fixture
def vault_with_quote(tmp_path):
    """Vault mit genau EINEM verifizierten woertlichen Zitat."""
    from academic_vault.server import add_paper, add_quote

    db_path = _make_vault(tmp_path, "quote_900.db")
    add_paper(
        db_path=db_path,
        paper_id="test-900",
        csl_json=json.dumps({"title": "Test", "type": "article-journal"}),
    )
    add_quote(
        db_path=db_path,
        paper_id="test-900",
        verbatim="this is a real and verifiable quotation",
        extraction_method="manual",
        printed_page=12,
    )
    add_quote(
        db_path=db_path,
        paper_id="test-900",
        verbatim="this is a real and verifiable (Fantasius 1999) quotation",
        extraction_method="manual",
        printed_page=13,
    )
    return db_path


# ---------------------------------------------------------------------------
# AC1/AC5 — Gegenprobe aus dem Issue: kein Block durch Fehlpaarung
# ---------------------------------------------------------------------------


def test_gegenprobe_short_quoted_terms_do_not_block(empty_vault):
    """Zwei kurze Begriffe in Anfuehrungszeichen im selben Satz duerfen den
    Write nicht blockieren — der Fliesstext dazwischen ist kein Zitat.

    Regressionsbeweis fuer AC5: mit der alten gieirgen Regex
    (`/"([^"]{10,})"/g`) paarte das schliessende Zeichen von "easy" mit dem
    oeffnenden von "hard" und las ``" von den als "`` als (unbelegtes) Zitat —
    dieser Test wird rot, sobald die Fehlpaarung zurueckkehrt.
    """
    content = 'Die Studie unterscheidet "easy" von den als "hard" bezeichneten Aufgaben.'
    result = run_hook(content, env_overrides={"VAULT_DB_PATH": empty_vault})
    assert result.returncode == 0, (
        f"Gegenprobe faelschlich blockiert: exit {result.returncode}. stderr: {result.stderr}"
    )


def test_gegenprobe_holds_with_a_populated_vault_too(vault_with_quote):
    """Dieselbe Gegenprobe, diesmal gegen eine NICHT-leere Vault-DB — die
    Fehlpaarung darf nicht erst durch eine leere DB verdeckt werden.
    """
    content = 'Die Studie unterscheidet "easy" von den als "hard" bezeichneten Aufgaben.'
    result = run_hook(content, env_overrides={"VAULT_DB_PATH": vault_with_quote})
    assert result.returncode == 0, (
        f"Gegenprobe faelschlich blockiert: exit {result.returncode}. stderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# AC2 — echtes Zitat zwischen zwei kurzen Begriffen bleibt erkannt
# ---------------------------------------------------------------------------


def test_real_quote_between_two_short_quoted_terms_is_still_checked_and_blocked(empty_vault):
    """Drei "-Paare im selben Absatz, das MITTLERE ein echtes >=10-Zeichen-Zitat
    ohne Vault-Treffer — muss weiterhin blockiert werden.
    """
    content = (
        'Er nennt es "gut" und schreibt "this is a real and verifiable quotation" statt "schlecht".'
    )
    result = run_hook(content, env_overrides={"VAULT_DB_PATH": empty_vault})
    assert result.returncode == 2, (
        f"Echtes unbelegtes Zitat nicht blockiert: exit {result.returncode}. stderr: {result.stderr}"
    )
    assert "this is a real and verifiable quotation" in result.stderr


def test_real_quote_between_two_short_quoted_terms_passes_with_vault_hit(vault_with_quote):
    """Dieselbe Konstellation, jetzt MIT Vault-Treffer — kein Block."""
    content = (
        'Er nennt es "gut" und schreibt "this is a real and verifiable quotation" statt "schlecht".'
    )
    result = run_hook(content, env_overrides={"VAULT_DB_PATH": vault_with_quote})
    assert result.returncode == 0, (
        f"Verifiziertes Zitat faelschlich blockiert: exit {result.returncode}. stderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# AC3 — [UNVERIFIED]-Marker greift nie in einen Anfuehrungszeichen-Span
# ---------------------------------------------------------------------------


def test_unverified_citation_marker_inside_a_real_quote_is_not_inserted(vault_with_quote):
    """Ein unverifizierter Klammerbeleg MITTEN in einem echten (verifizierten)
    Zitat darf den Zitatwortlaut nicht mit [UNVERIFIED] durchbrechen.
    """
    content = 'Wie belegt: "this is a real and verifiable (Fantasius 1999) quotation" steht dort.'
    result = run_hook(
        content,
        env_overrides={
            "VAULT_DB_PATH": vault_with_quote,
            "ACADEMIC_CITATION_AMBIGUOUS": "mark",
        },
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    if "updatedInput" in result.stdout:
        marked = updated_content(result)
        assert "[UNVERIFIED]" not in marked[content.index('"') : content.rindex('"') + 1], (
            f"Marker im Zitat-Span gesetzt: {marked!r}"
        )
        # Marker darf ueberhaupt nicht INNERHALB der Anfuehrungszeichen stehen —
        # unabhaengig davon, ob er (erlaubt) irgendwo ausserhalb landet.
        assert '(Fantasius 1999) [UNVERIFIED] quotation"' not in marked
        assert '(Fantasius 1999) quotation"' in marked


# ---------------------------------------------------------------------------
# AC4 — Klammerbeleg-Marker AUSSERHALB von Zitaten bleibt unveraendert (#378)
# ---------------------------------------------------------------------------


def test_unverified_citation_marker_outside_quotes_still_works(empty_vault):
    """Regressionsschutz: die #378-Markierung fuer Klammerbelege AUSSERHALB
    von Anfuehrungszeichen bleibt unveraendert (kein Verlust durch den
    Quote-Overlap-Filter).
    """
    content = "Der Befund (Fantasius 1999) belegt die These eindeutig."
    result = run_hook(
        content,
        env_overrides={
            "VAULT_DB_PATH": empty_vault,
            "ACADEMIC_CITATION_AMBIGUOUS": "mark",
        },
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    marked = updated_content(result)
    assert "(Fantasius 1999) [UNVERIFIED]" in marked, f"Nicht markiert: {result.stdout!r}"
