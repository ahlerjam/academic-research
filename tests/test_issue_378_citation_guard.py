"""Tests fuer die Klammer-Zitat-Validierung im verbatim-guard-Hook (Issue #378).

Der Hook wird als Node.js-Subprocess gestartet (JSON auf stdin, JSON auf stdout,
Exit 0 = allow, Exit 2 = block). Die externe Kaskade laeuft in allen Tests gegen
einen lokalen Stub-HTTP-Server — niemals gegen echte APIs.

Akzeptanzkriterien (Issue #378):
  AC1  Klammer-Beleg mit Vault-Treffer (Autor/Jahr/Seite) blockiert nicht.
  AC2  Erfundener Autor/Jahr oder falsche Seitenzahl wird blockiert.
  AC3  Externer API-Ausfall -> [UNVERIFIED]-Soft-Fail statt Hard-Block.
  AC4  Score-Schwellen der Kaskade sind konfigurierbar und dokumentiert.
"""

import json
import os
import re
import socket
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "verbatim-guard.mjs"

# Wegwerf-Ziel fuer die Guard-Logs dieses Testmoduls (siehe run_hook).
_GUARD_LOG_DIR = Path(tempfile.mkdtemp(prefix="vault-guard-test-logs-"))
# Seit #402 ist die README nur noch Landing-Page; der Hook-Stack samt
# Env-Variablen steht in docs/reference/hooks.md — dort prüfen die
# Doku-Regressionstests (tests/test_readme_hook_stack_doc.py) mit.
HOOKS_DOC = REPO_ROOT / "docs" / "reference" / "hooks.md"


# ---------------------------------------------------------------------------
# Stub-HTTP-Server fuer die Kaskade (arXiv / CrossRef / Semantic Scholar)
# ---------------------------------------------------------------------------


def _arxiv_feed(entries: list[dict]) -> str:
    """Baut eine arXiv-Atom-Antwort aus [{title, year, authors}]."""
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<feed xmlns="http://www.w3.org/2005/Atom">']
    for entry in entries:
        authors = "".join(f"<author><name>{n}</name></author>" for n in entry["authors"])
        parts.append(
            f"<entry><title>{entry['title']}</title>"
            f"<published>{entry['year']}-01-01T00:00:00Z</published>"
            f"{authors}</entry>"
        )
    parts.append("</feed>")
    return "".join(parts)


def _crossref_payload(entries: list[dict]) -> str:
    items = [
        {
            "title": [e["title"]],
            "author": [
                {"family": n.split()[-1], "given": " ".join(n.split()[:-1])} for n in e["authors"]
            ],
            "issued": {"date-parts": [[e["year"]]]},
        }
        for e in entries
    ]
    return json.dumps({"message": {"items": items}})


def _s2_payload(entries: list[dict]) -> str:
    data = [
        {"title": e["title"], "year": e["year"], "authors": [{"name": n} for n in e["authors"]]}
        for e in entries
    ]
    return json.dumps({"data": data})


class CascadeStub:
    """Lokaler HTTP-Stub mit konfigurierbarem Verhalten pro Kaskaden-Stufe."""

    def __init__(self, behaviour: dict):
        # behaviour: {"arxiv": {...}, "crossref": {...}, "s2": {...}}
        # je Stufe: {"status": 200, "entries": [...]}, {"status": 503} oder
        # {"status": 200, "body": "<roher Body>"} fuer unparsbare Antworten.
        self.behaviour = behaviour
        self.hits: list[str] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                route = self.path.split("?")[0].strip("/")
                stub.hits.append(route)
                spec = stub.behaviour.get(route, {"status": 200, "entries": []})
                status = spec.get("status", 200)
                if status != 200:
                    self.send_response(status)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"upstream error")
                    return
                if "body" in spec:
                    raw = spec["body"].encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", spec.get("ctype", "text/html"))
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                entries = spec.get("entries", [])
                if route == "arxiv":
                    body = _arxiv_feed(entries).encode("utf-8")
                    ctype = "application/atom+xml"
                elif route == "crossref":
                    body = _crossref_payload(entries).encode("utf-8")
                    ctype = "application/json"
                else:
                    body = _s2_payload(entries).encode("utf-8")
                    ctype = "application/json"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # noqa: A003
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def env(self) -> dict:
        base = f"http://127.0.0.1:{self.port}"
        return {
            "ACADEMIC_CITATION_ARXIV_URL": f"{base}/arxiv",
            "ACADEMIC_CITATION_CROSSREF_URL": f"{base}/crossref",
            "ACADEMIC_CITATION_S2_URL": f"{base}/s2",
        }


def _closed_port() -> int:
    """Liefert einen Port, auf dem garantiert nichts lauscht (ECONNREFUSED)."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


# ---------------------------------------------------------------------------
# Hook-Runner
# ---------------------------------------------------------------------------


def run_hook(payload: dict, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # Hermetisch: die Default-Schwellen-Tests (AC4) beweisen "Verhalten kippt
    # allein ueber Env" nur, wenn kein ACADEMIC_CITATION_* aus der Shell des
    # Entwicklers oder des CI-Runners durchschlaegt.
    for key in [k for k in env if k.startswith("ACADEMIC_CITATION_")]:
        del env[key]
    env["VAULT_DB_PATH"] = str(REPO_ROOT / "nonexistent_vault_for_tests.db")
    # Guard-Logs in ein Wegwerf-Verzeichnis umleiten. Ohne das schreibt jeder
    # der ~50 run_hook-Aufrufe in das ECHTE ~/.academic-research/ des
    # Entwicklers bzw. des CI-Runners: ACADEMIC_CITATION_CASCADE unten ist ein
    # gesetzter Env-Schalter, den verbatim-guard.mjs seit #519 protokolliert,
    # und der SessionStart-Report meldete danach Schalter-Nutzungen, die nur
    # aus dem Testlauf stammen.
    env["VAULT_GUARD_ENV_SWITCH_LOG"] = str(_GUARD_LOG_DIR / "env-switch.log")
    env["VAULT_GUARD_BYPASS_LOG"] = str(_GUARD_LOG_DIR / "bypass.log")
    # Default in Tests: keine echte Netz-Kaskade.
    env["ACADEMIC_CITATION_CASCADE"] = "off"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["node", str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def write_payload(content: str, file_path: str = "kapitel/kap1.md") -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": file_path, "content": content}}


def updated_content(result: subprocess.CompletedProcess) -> str:
    """Extrahiert updatedInput.content aus der stdout-JSON-Ausgabe."""
    assert result.stdout.strip(), f"Kein stdout-JSON. stderr: {result.stderr}"
    data = json.loads(result.stdout)
    return data["hookSpecificOutput"]["updatedInput"]["content"]


def assert_marker_only(updated: str, original: str) -> None:
    """Invariante: der Soft-Fail haengt Marker an — er veraendert sonst nichts.

    Faellt der Marker in ein Wort hinein (verschobene Offsets), schlaegt genau
    diese Zeile an, waehrend ein blosses ``"[UNVERIFIED]" in updated`` den
    Schaden nicht sieht.
    """
    assert updated.replace(" [UNVERIFIED]", "") == original, (
        f"Text ueber die Markierung hinaus veraendert: {updated!r}"
    )


# ---------------------------------------------------------------------------
# Vault-Fixtures
# ---------------------------------------------------------------------------


def _make_vault(tmp_path, name: str) -> str:
    from academic_vault.db import VaultDB

    db_path = str(tmp_path / name)
    db = VaultDB(db_path)
    db.init_schema()
    return db_path


@pytest.fixture
def empty_vault(tmp_path):
    return _make_vault(tmp_path, "empty_378.db")


@pytest.fixture
def vault_with_mueller(tmp_path):
    """Vault mit Paper Mueller 2021, Seiten 40-60."""
    from academic_vault.server import add_paper

    db_path = _make_vault(tmp_path, "mueller_378.db")
    add_paper(
        db_path=db_path,
        paper_id="mueller-2021",
        csl_json=json.dumps(
            {
                "title": "Digitale Transformation",
                "type": "article-journal",
                "author": [{"family": "Müller", "given": "Anna"}],
                "issued": {"date-parts": [[2021]]},
            }
        ),
        page_first=40,
        page_last=60,
    )
    return db_path


@pytest.fixture
def vault_with_particle_name(tmp_path):
    """Vault mit einem Paper, dessen Autor ein Namenspartikel traegt.

    CSL-JSON modelliert das Partikel als eigenes Feld (``non-dropping-particle``),
    der Familienname bleibt ``Neumann``. Im Kapiteltext steht dagegen die im
    Deutschen uebliche Zitierform ``(von Neumann 1945)``.
    """
    from academic_vault.server import add_paper

    db_path = _make_vault(tmp_path, "particle_378.db")
    add_paper(
        db_path=db_path,
        paper_id="neumann-1945",
        csl_json=json.dumps(
            {
                "title": "First Draft of a Report on the EDVAC",
                "type": "book",
                "author": [{"family": "Neumann", "given": "John", "non-dropping-particle": "von"}],
                "issued": {"date-parts": [[1945]]},
            }
        ),
        page_first=1,
        page_last=101,
    )
    return db_path


@pytest.fixture
def vault_with_quote_page_only(tmp_path):
    """Vault mit Buch OHNE page_first/page_last, aber mit einem Zitat von S. 45.

    Der Regelfall beim Buch-Ingest: der Seitenumfang steht nicht im CSL, aus dem
    PDF sind bisher nur einzelne Zitate erfasst. ``quotes.printed_page`` ist
    damit eine punktuelle Stichprobe und kein Seitenbereich.
    """
    from academic_vault.server import add_paper, add_quote

    db_path = _make_vault(tmp_path, "quotepages_378.db")
    add_paper(
        db_path=db_path,
        paper_id="schmidt-2020",
        csl_json=json.dumps(
            {
                "title": "Ein Buch ohne Seitenangabe",
                "type": "book",
                "author": [{"family": "Schmidt", "given": "Bernd"}],
                "issued": {"date-parts": [[2020]]},
            }
        ),
    )
    add_quote(
        db_path=db_path,
        paper_id="schmidt-2020",
        verbatim="Ein woertliches Zitat von Seite 45",
        extraction_method="manual",
        printed_page=45,
    )
    return db_path


# ---------------------------------------------------------------------------
# Python-Ebene: Vault-Lookup (Task 1)
# ---------------------------------------------------------------------------


def test_find_papers_by_author_year_matches_umlaut_family(vault_with_mueller):
    from academic_vault.db import VaultDB

    db = VaultDB(vault_with_mueller)
    assert db.find_papers_by_author_year("Müller", 2021)
    # Umlaut-Faltung: "Mueller" und "Muller" muessen ebenfalls treffen
    assert db.find_papers_by_author_year("Mueller", 2021)
    assert db.find_papers_by_author_year("Muller", 2021)
    assert db.find_papers_by_author_year("Müller", 2020) == []
    assert db.find_papers_by_author_year("Fantasius", 2021) == []


def test_page_coverage_states(vault_with_mueller, empty_vault):
    from academic_vault.db import VaultDB
    from academic_vault.server import add_paper

    db = VaultDB(vault_with_mueller)
    assert db.page_coverage("mueller-2021", 45) == "covered"
    assert db.page_coverage("mueller-2021", 999) == "outside"

    # Paper ohne jede Seiteninformation -> "unknown" (dokumentierter Soft-Pass)
    add_paper(
        db_path=empty_vault,
        paper_id="ohne-seiten",
        csl_json=json.dumps(
            {
                "title": "Ohne Seiten",
                "type": "article-journal",
                "author": [{"family": "Schmidt"}],
                "issued": {"date-parts": [[2019]]},
            }
        ),
    )
    assert VaultDB(empty_vault).page_coverage("ohne-seiten", 45) == "unknown"


def test_page_coverage_quote_pages_never_refute(vault_with_quote_page_only):
    """``quotes.printed_page`` bestaetigt eine Seite, widerlegt sie aber nie.

    Die Quote-Seiten sind eine Stichprobe der bereits erfassten Stellen, kein
    Seitenumfang: dass S. 47 nicht darunter ist, sagt nichts darueber aus, ob
    das Buch eine S. 47 hat. Nur ein vollstaendiges ``[page_first, page_last]``
    darf ``"outside"`` ergeben.
    """
    from academic_vault.db import VaultDB

    db = VaultDB(vault_with_quote_page_only)
    # Erfasste Stichprobe bestaetigt weiterhin.
    assert db.page_coverage("schmidt-2020", 45) == "covered"
    # Jede andere Seite ist mangels Seitenumfang schlicht unbekannt.
    assert db.page_coverage("schmidt-2020", 47) == "unknown"
    assert db.page_coverage("schmidt-2020", 3) == "unknown"


def test_verify_citation_unsampled_page_is_verified(vault_with_quote_page_only):
    """Kein ``page-mismatch``, solange nur Quote-Seiten bekannt sind."""
    from academic_vault.server import verify_citation

    assert verify_citation(vault_with_quote_page_only, "Schmidt", 2020, 45)["status"] == "verified"
    assert verify_citation(vault_with_quote_page_only, "Schmidt", 2020, 47)["status"] == "verified"


def test_verify_citation_statuses(vault_with_mueller):
    from academic_vault.server import verify_citation

    assert verify_citation(vault_with_mueller, "Müller", 2021, 45)["status"] == "verified"
    assert verify_citation(vault_with_mueller, "Müller", 2021, None)["status"] == "verified"
    assert verify_citation(vault_with_mueller, "Müller", 2021, 999)["status"] == "page-mismatch"
    assert verify_citation(vault_with_mueller, "Fantasius", 1999, None)["status"] == "no-match"


# ---------------------------------------------------------------------------
# Issue #501 — Batch-Lookup: ein Papers-Scan je Write statt je Beleg
# ---------------------------------------------------------------------------


def test_verify_citations_batch_scans_papers_table_once(vault_with_mueller, monkeypatch):
    """AC1/AC3: N Belege in einem Write loesen genau einen Papers-Scan aus."""
    from academic_vault import db as db_module
    from academic_vault.server import verify_citations

    call_count = 0
    original = db_module.VaultDB._papers_snapshot

    def counting_snapshot(self):
        nonlocal call_count
        call_count += 1
        return original(self)

    monkeypatch.setattr(db_module.VaultDB, "_papers_snapshot", counting_snapshot)

    items = [
        {"family": "Müller", "year": 2021, "page": 45},
        {"family": "Müller", "year": 2021, "page": None},
        {"family": "Fantasius", "year": 1999, "page": None},
    ]
    results = verify_citations(vault_with_mueller, items)

    assert call_count == 1
    assert [r["status"] for r in results] == ["verified", "verified", "no-match"]


def test_verify_citations_batch_matches_single_item_behavior(vault_with_mueller):
    """AC2: verify_citations() liefert je Beleg identisch zu verify_citation()."""
    from academic_vault.server import verify_citation, verify_citations

    items = [
        {"family": "Müller", "year": 2021, "page": 45},
        {"family": "Müller", "year": 2021, "page": None},
        {"family": "Müller", "year": 2021, "page": 999},
        {"family": "Fantasius", "year": 1999, "page": None},
    ]
    batch_results = verify_citations(vault_with_mueller, items)
    single_results = [
        verify_citation(vault_with_mueller, i["family"], i["year"], i["page"]) for i in items
    ]
    assert batch_results == single_results


# ---------------------------------------------------------------------------
# AC1 — Vault-Treffer blockiert nicht
# ---------------------------------------------------------------------------


def test_citation_in_vault_allows(vault_with_mueller):
    """AC1: (Müller 2021, S. 45) ist im Vault -> kein Block, keine Markierung."""
    content = "Wie (Müller 2021, S. 45) zeigt, steigt der Wert deutlich an."
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": vault_with_mueller, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 0, f"Erwartet 0, got {result.returncode}. stderr: {result.stderr}"
    assert "BLOCKIERT" not in result.stderr
    assert "[UNVERIFIED]" not in result.stdout


def test_citation_narrative_form_in_vault_allows(vault_with_mueller):
    """AC1: Auch die Nicht-Klammer-Form 'vgl. Müller 2021' wird erkannt und passiert."""
    content = "Der Effekt ist belegt, vgl. Müller 2021, S. 50 in der Fachliteratur."
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": vault_with_mueller, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_page_softpass_when_vault_has_no_page_data(empty_vault):
    """Kein Massen-False-Positive: hat der Vault zum Paper keine Seitendaten,
    ist die Seitenzahl nicht blockierbar."""
    from academic_vault.server import add_paper

    add_paper(
        db_path=empty_vault,
        paper_id="schmidt-2019",
        csl_json=json.dumps(
            {
                "title": "Ohne Seiten",
                "type": "article-journal",
                "author": [{"family": "Schmidt"}],
                "issued": {"date-parts": [[2019]]},
            }
        ),
    )
    content = "Der Befund (Schmidt 2019, S. 123) ist gut belegt."
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 0, f"Erwartet Soft-Pass, got {result.returncode}. {result.stderr}"


# ---------------------------------------------------------------------------
# AC2 — erfundener Beleg / falsche Seite wird blockiert
# ---------------------------------------------------------------------------


def test_citation_unknown_author_blocks(empty_vault):
    """AC2: Erfundener Autor, Vault leer, Kaskade antwortet sauber leer -> Block."""
    content = "Der Befund (Fantasius 1999, S. 12) belegt die These eindeutig."
    with CascadeStub(
        {
            "arxiv": {"status": 200, "entries": []},
            "crossref": {"status": 200, "entries": []},
            "s2": {"status": 200, "entries": []},
        }
    ) as stub:
        env = {"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "on"}
        env.update(stub.env())
        result = run_hook(write_payload(content), env_overrides=env)
    assert result.returncode == 2, f"Erwartet 2 (Block), got {result.returncode}. {result.stderr}"
    assert "[Citation-Guard] BLOCKIERT" in result.stderr
    assert "Fantasius" in result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_citation_wrong_page_blocks(vault_with_mueller):
    """AC2: Autor/Jahr im Vault, Seite ausserhalb 40-60 -> Block (Vault ist
    fuer bekannte Seitenbereiche autoritativ, keine Kaskaden-Rettung)."""
    content = "Wie (Müller 2021, S. 999) belegt, ist der Effekt gross."
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": vault_with_mueller, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 2, f"Erwartet 2 (Block), got {result.returncode}. {result.stderr}"
    assert "999" in result.stderr


def test_citation_page_beyond_quote_sample_allows(vault_with_quote_page_only):
    """Gegenstueck zu ``wrong_page_blocks``: ohne page_first/page_last darf eine
    nicht abgetastete Seite NICHT blocken.

    Der Vault kennt von diesem Buch nur ein Zitat auf S. 45. Ein Beleg auf S. 47
    ist damit weder bestaetigt noch widerlegt — blocken hiesse, korrekte Belege
    allein deshalb abzulehnen, weil aus derselben Seite noch nichts extrahiert
    wurde.
    """
    content = "Wie (Schmidt 2020, S. 47) zeigt, ist der Effekt stabil."
    result = run_hook(
        write_payload(content),
        env_overrides={
            "VAULT_DB_PATH": vault_with_quote_page_only,
            "ACADEMIC_CITATION_CASCADE": "off",
        },
    )
    assert result.returncode == 0, f"Erwartet 0 (allow), got {result.returncode}. {result.stderr}"
    assert "BLOCKIERT" not in result.stderr


def test_cascade_off_without_vault_hit_blocks(empty_vault):
    """Kill-Switch: ACADEMIC_CITATION_CASCADE=off ist Vault-only -> Block ohne Netz."""
    content = "Der Befund (Fantasius 1999, S. 12) belegt die These eindeutig."
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 2, f"Erwartet 2, got {result.returncode}. {result.stderr}"


def test_cascade_confirmed_hit_allows(empty_vault):
    """Kaskaden-Treffer >= confirmed (Autor + Jahr exakt) -> allow ohne Markierung."""
    content = "Der Befund (Müller 2021) ist mehrfach repliziert worden."
    with CascadeStub(
        {
            "arxiv": {
                "status": 200,
                "entries": [
                    {"title": "Digitale Transformation", "year": 2021, "authors": ["Anna Müller"]}
                ],
            }
        }
    ) as stub:
        env = {"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "on"}
        env.update(stub.env())
        result = run_hook(write_payload(content), env_overrides=env)
    assert result.returncode == 0, f"Erwartet 0, got {result.returncode}. {result.stderr}"
    assert "[UNVERIFIED]" not in result.stdout
    # Frühausstieg: CrossRef/S2 duerfen nach einem confirmed-Treffer nicht mehr laufen
    assert "crossref" not in stub.hits


# ---------------------------------------------------------------------------
# AC3 — API-Ausfall -> [UNVERIFIED] statt Hard-Block
# ---------------------------------------------------------------------------


def test_cascade_unavailable_soft_fails(empty_vault):
    """AC3: Alle Stufen liefern 503 -> allow + [UNVERIFIED]-Markierung."""
    content = "Der Befund (Fantasius 1999, S. 12) belegt die These eindeutig."
    with CascadeStub(
        {
            "arxiv": {"status": 503},
            "crossref": {"status": 503},
            "s2": {"status": 503},
        }
    ) as stub:
        env = {"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "on"}
        env.update(stub.env())
        result = run_hook(write_payload(content), env_overrides=env)
    assert result.returncode == 0, (
        f"Erwartet 0 (Soft-Fail), got {result.returncode}. {result.stderr}"
    )
    marked = updated_content(result)
    assert "[UNVERIFIED]" in marked
    assert "(Fantasius 1999, S. 12) [UNVERIFIED]" in marked
    assert_marker_only(marked, content)


def test_cascade_http_403_soft_fails(empty_vault):
    """AC3: 4xx ist keine saubere Antwort -> [UNVERIFIED] statt Block.

    403 ist der Regelfall, wenn Semantic Scholar ohne API-Key drosselt oder ein
    Firmenproxy den Egress blockt. Als ``no-match`` gewertet, wuerde ausgerechnet
    der Netzausfall wie ein Halluzinations-Nachweis wirken.
    """
    content = "Der Befund (Fantasius 1999, S. 12) belegt die These eindeutig."
    with CascadeStub(
        {
            "arxiv": {"status": 403},
            "crossref": {"status": 404},
            "s2": {"status": 403},
        }
    ) as stub:
        env = {"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "on"}
        env.update(stub.env())
        result = run_hook(write_payload(content), env_overrides=env)
    assert result.returncode == 0, (
        f"Erwartet 0 (Soft-Fail), got {result.returncode}. {result.stderr}"
    )
    assert "(Fantasius 1999, S. 12) [UNVERIFIED]" in updated_content(result)


def test_cascade_unparsable_body_soft_fails(empty_vault):
    """AC3: HTTP 200 mit unlesbarem Body ist keine saubere Antwort.

    Captive Portals und Proxys liefern gern 200 + HTML-Fehlerseite. „Antwort
    nicht verstanden" darf nicht auf „Beleg existiert nicht" abgebildet werden.
    """
    garbage = "<html><body>502 Bad Gateway (proxy)</body></html>"
    content = "Der Befund (Fantasius 1999, S. 12) belegt die These eindeutig."
    with CascadeStub(
        {
            "arxiv": {"status": 200, "body": garbage},
            "crossref": {"status": 200, "body": garbage},
            "s2": {"status": 200, "body": garbage},
        }
    ) as stub:
        env = {"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "on"}
        env.update(stub.env())
        result = run_hook(write_payload(content), env_overrides=env)
    assert result.returncode == 0, (
        f"Erwartet 0 (Soft-Fail), got {result.returncode}. {result.stderr}"
    )
    assert "(Fantasius 1999, S. 12) [UNVERIFIED]" in updated_content(result)


def test_cascade_empty_but_valid_answers_still_block(empty_vault):
    """Gegenprobe: sauber beantwortete Leerergebnisse bleiben ein Hard-Block.

    Der Soft-Fail darf nur greifen, wenn die Antwort ausgeblieben oder unlesbar
    war — sonst waere der Guard wirkungslos.
    """
    content = "Der Befund (Fantasius 1999, S. 12) belegt die These eindeutig."
    with CascadeStub(
        {
            "arxiv": {"status": 200, "entries": []},
            "crossref": {"status": 200, "entries": []},
            "s2": {"status": 200, "entries": []},
        }
    ) as stub:
        env = {"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "on"}
        env.update(stub.env())
        result = run_hook(write_payload(content), env_overrides=env)
    assert result.returncode == 2, f"Erwartet 2 (Block), got {result.returncode}. {result.stderr}"


def test_cascade_connection_refused_soft_fails(empty_vault):
    """AC3: Kaskaden-Endpunkte nicht erreichbar (ECONNREFUSED) -> [UNVERIFIED].

    Der Beleg traegt eine Seitenangabe und waere damit bei sauberem Negativ ein
    Hard-Block — nur so belegt der Test wirklich den unavailable-Pfad.
    """
    port = _closed_port()
    base = f"http://127.0.0.1:{port}"
    content = "Der Befund (Fantasius 1999, S. 12) belegt die These eindeutig."
    result = run_hook(
        write_payload(content),
        env_overrides={
            "VAULT_DB_PATH": empty_vault,
            "ACADEMIC_CITATION_CASCADE": "on",
            "ACADEMIC_CITATION_ARXIV_URL": f"{base}/arxiv",
            "ACADEMIC_CITATION_CROSSREF_URL": f"{base}/crossref",
            "ACADEMIC_CITATION_S2_URL": f"{base}/s2",
        },
    )
    assert result.returncode == 0, (
        f"Erwartet 0 (Soft-Fail), got {result.returncode}. {result.stderr}"
    )
    updated = updated_content(result)
    assert "[UNVERIFIED]" in updated
    assert_marker_only(updated, content)


def test_soft_fail_marks_edit_new_string(empty_vault):
    """AC3 (Edit-Shape): updatedInput markiert new_string, nicht content."""
    port = _closed_port()
    base = f"http://127.0.0.1:{port}"
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "kapitel/kap1.md",
            "old_string": "Platzhalter",
            "new_string": "Der Befund (Fantasius 1999, S. 12) belegt die These.",
        },
    }
    result = run_hook(
        payload,
        env_overrides={
            "VAULT_DB_PATH": empty_vault,
            "ACADEMIC_CITATION_CASCADE": "on",
            "ACADEMIC_CITATION_ARXIV_URL": f"{base}/arxiv",
            "ACADEMIC_CITATION_CROSSREF_URL": f"{base}/crossref",
            "ACADEMIC_CITATION_S2_URL": f"{base}/s2",
        },
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    updated = data["hookSpecificOutput"]["updatedInput"]
    assert "[UNVERIFIED]" in updated["new_string"]
    assert_marker_only(updated["new_string"], payload["tool_input"]["new_string"])
    assert updated["old_string"] == "Platzhalter", "unveraenderte Felder muessen erhalten bleiben"


def test_soft_fail_marks_multiedit_edits(empty_vault):
    """AC3 (MultiEdit-Shape): updatedInput markiert edits[].new_string."""
    port = _closed_port()
    base = f"http://127.0.0.1:{port}"
    payload = {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": "kapitel/kap1.md",
            "edits": [
                {"old_string": "a", "new_string": "Ein harmloser Absatz."},
                {
                    "old_string": "b",
                    "new_string": "Der Befund (Fantasius 1999, S. 12) belegt die These.",
                },
            ],
        },
    }
    result = run_hook(
        payload,
        env_overrides={
            "VAULT_DB_PATH": empty_vault,
            "ACADEMIC_CITATION_CASCADE": "on",
            "ACADEMIC_CITATION_ARXIV_URL": f"{base}/arxiv",
            "ACADEMIC_CITATION_CROSSREF_URL": f"{base}/crossref",
            "ACADEMIC_CITATION_S2_URL": f"{base}/s2",
        },
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    edits = json.loads(result.stdout)["hookSpecificOutput"]["updatedInput"]["edits"]
    assert "[UNVERIFIED]" not in edits[0]["new_string"]
    assert "[UNVERIFIED]" in edits[1]["new_string"]
    for got, sent in zip(edits, payload["tool_input"]["edits"], strict=True):
        assert_marker_only(got["new_string"], sent["new_string"])


# ---------------------------------------------------------------------------
# AC4 — Schwellen konfigurierbar + dokumentiert
# ---------------------------------------------------------------------------


PROBABLE_STUB = {
    "arxiv": {
        "status": 200,
        # Autor trifft (40), Jahr um 1 daneben (20), Autor-Ueberlapp 1/2 (10) => Score 70
        "entries": [
            {
                "title": "Digitale Transformation",
                "year": 2020,
                "authors": ["Anna Müller", "Bernd Zweit"],
            }
        ],
    },
    "crossref": {"status": 200, "entries": []},
    "s2": {"status": 200, "entries": []},
}


def test_thresholds_default_yields_unverified(empty_vault):
    """AC4: Score 70 liegt bei Defaults (confirmed 80 / probable 65) im probable-Band."""
    content = "Der Befund (Müller 2021, S. 45) ist umstritten."
    with CascadeStub(PROBABLE_STUB) as stub:
        env = {"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "on"}
        env.update(stub.env())
        result = run_hook(write_payload(content), env_overrides=env)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "[UNVERIFIED]" in updated_content(result)


def test_thresholds_env_configurable(empty_vault):
    """AC4: Derselbe Input wird mit ACADEMIC_CITATION_CONFIRMED_MIN=65 sauber
    durchgelassen — der Verhaltensunterschied belegt die Konfigurierbarkeit."""
    content = "Der Befund (Müller 2021, S. 45) ist umstritten."
    with CascadeStub(PROBABLE_STUB) as stub:
        env = {
            "VAULT_DB_PATH": empty_vault,
            "ACADEMIC_CITATION_CASCADE": "on",
            "ACADEMIC_CITATION_CONFIRMED_MIN": "65",
        }
        env.update(stub.env())
        result = run_hook(write_payload(content), env_overrides=env)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "[UNVERIFIED]" not in result.stdout


def test_probable_min_env_configurable(empty_vault):
    """AC4: Wird probable_min ueber den Score gehoben, faellt derselbe Kandidat
    unter 'kein Treffer' und wird geblockt."""
    content = "Der Befund (Müller 2021, S. 45) ist umstritten."
    with CascadeStub(PROBABLE_STUB) as stub:
        env = {
            "VAULT_DB_PATH": empty_vault,
            "ACADEMIC_CITATION_CASCADE": "on",
            "ACADEMIC_CITATION_PROBABLE_MIN": "90",
            "ACADEMIC_CITATION_CONFIRMED_MIN": "95",
        }
        env.update(stub.env())
        result = run_hook(write_payload(content), env_overrides=env)
    assert result.returncode == 2, f"Erwartet 2, got {result.returncode}. {result.stderr}"


def test_docs_document_citation_thresholds():
    """AC4: docs/reference/hooks.md dokumentiert Schwellen und Env-Variablen."""
    text = HOOKS_DOC.read_text(encoding="utf-8")
    for token in (
        "ACADEMIC_CITATION_CONFIRMED_MIN",
        "ACADEMIC_CITATION_PROBABLE_MIN",
        "ACADEMIC_CITATION_CASCADE",
        "[UNVERIFIED]",
    ):
        assert token in text, f"docs/reference/hooks.md dokumentiert '{token}' nicht (AC4)."
    section = re.search(r"### Klammer-Zitat-Validierung.*?(?=\n### |\n## |\Z)", text, re.DOTALL)
    assert section, "docs/reference/hooks.md enthaelt keine Sektion '### Klammer-Zitat-Validierung'"
    assert "80" in section.group(0) and "65" in section.group(0), (
        "README nennt die Default-Schwellen 80/65 nicht."
    )


# ---------------------------------------------------------------------------
# Skip-Regeln (False-Positive-Schutz)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "```\nprint((Fantasius 1999))\n```\n",
        "Ein Beispiel `(Fantasius 1999)` im Inline-Code.",
        "Der Beleg \\cite{Fantasius1999} steht im LaTeX-Makro.",
        "Wie oben gezeigt (siehe Kapitel 2) folgt daraus die These.",
        "Die Zahl (2021) steht ohne Autor im Text.",
        "Dieselbe Quelle (ebd.) bestaetigt das, ebenso (a.a.O.).",
        "## Literaturverzeichnis\n\nFantasius, K. (1999). Ein Werk. Verlag.\n",
    ],
)
def test_skip_rules_do_not_block(empty_vault, content):
    """Kein Block fuer Code, LaTeX-Makros, Kapitelverweise, nackte Jahre,
    ebd./a.a.O. und das Literaturverzeichnis."""
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 0, (
        f"Skip-Regel verletzt fuer {content!r}: exit {result.returncode}. {result.stderr}"
    )


def test_bypass_marker_skips_citation_check(empty_vault):
    """<!-- vault-guard: skip --> deaktiviert auch den Klammer-Zitat-Check."""
    content = "<!-- vault-guard: skip -->\nDer Befund (Fantasius 1999, S. 12) belegt die These."
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 0


def test_unprotected_path_skips_citation_check(empty_vault):
    """Nicht-Kapitel-Pfade bleiben unangetastet."""
    result = run_hook(
        write_payload(
            "Der Befund (Fantasius 1999, S. 12) belegt die These.", file_path="README.md"
        ),
        env_overrides={"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 0


def test_missing_vault_db_fails_open():
    """Fail-open bleibt erhalten: ohne Vault-DB kein Block."""
    result = run_hook(write_payload("Der Befund (Fantasius 1999, S. 12) belegt die These."))
    assert result.returncode == 0, f"stderr: {result.stderr}"


# ---------------------------------------------------------------------------
# hooks.json — Timeout-Budget
# ---------------------------------------------------------------------------


def test_hooks_json_timeout_covers_cascade_budget():
    """Das PreToolUse-Timeout muss Vault-Subprozesse + Kaskaden-Budget abdecken."""
    hooks = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    entries = hooks["hooks"]["PreToolUse"][0]["hooks"]
    guard = next(h for h in entries if "verbatim-guard" in h["command"])
    assert guard["timeout"] >= 30, (
        f"verbatim-guard-Timeout {guard['timeout']}s reicht fuer die Kaskade nicht aus."
    )


# ---------------------------------------------------------------------------
# Fix-Runde: Namenspartikel (von/van/de) duerfen den Vault-Treffer nicht kosten
# ---------------------------------------------------------------------------


def test_normalize_family_name_ignores_leading_particle():
    """``von Neumann`` und ``Neumann`` muessen als derselbe Name gelten.

    Der Parser liest das Partikel aus dem Kapiteltext mit, CSL-JSON haelt es in
    einem eigenen Feld. Ohne Partikel-Variante treffen die beiden Schreibweisen
    nie aufeinander.
    """
    from academic_vault.db import family_names_match, normalize_family_name

    assert "neumann" in normalize_family_name("von Neumann")
    assert family_names_match("von Neumann", "Neumann")
    assert family_names_match("Neumann", "von Neumann")
    assert family_names_match("de la Cruz", "Cruz")
    # Gegenprobe: das Partikel allein darf nicht zu einem leeren Namen
    # kollabieren und damit auf alles passen.
    assert not family_names_match("von", "Neumann")


def test_find_papers_by_author_year_matches_particle_family(vault_with_particle_name):
    """Vault-Lookup findet das Paper auch, wenn nur der Beleg das Partikel traegt."""
    from academic_vault.db import VaultDB

    db = VaultDB(vault_with_particle_name)
    assert db.find_papers_by_author_year("von Neumann", 1945), (
        "Paper liegt im Vault, wird aber wegen des Partikels nicht gefunden"
    )
    assert db.find_papers_by_author_year("Neumann", 1945)


def test_citation_with_particle_name_in_vault_allows(vault_with_particle_name):
    """AC1: ``(von Neumann 1945, S. 12)`` ist eingepflegt -> kein Hard-Block."""
    content = "Wie (von Neumann 1945, S. 12) zeigt, war die Architektur neu."
    result = run_hook(
        write_payload(content),
        env_overrides={
            "VAULT_DB_PATH": vault_with_particle_name,
            "ACADEMIC_CITATION_CASCADE": "off",
        },
    )
    assert result.returncode == 0, (
        f"AC1 verletzt: eingepflegtes Paper blockiert. exit {result.returncode}. {result.stderr}"
    )
    assert "BLOCKIERT" not in result.stderr


def test_cascade_matches_particle_name(empty_vault):
    """Auch die JS-Seite (Score-Modell der Kaskade) muss das Partikel tolerieren.

    CrossRef/arXiv liefern ``Neumann`` als Familiennamen; der Beleg im Text
    lautet ``von Neumann``. Ohne Partikel-Normalisierung faellt der Score auf 0.
    """
    content = "Der Entwurf (von Neumann 1945) praegte die Rechnerarchitektur."
    with CascadeStub(
        {
            "arxiv": {
                "status": 200,
                "entries": [
                    {
                        "title": "First Draft of a Report on the EDVAC",
                        "year": 1945,
                        "authors": ["John Neumann"],
                    }
                ],
            }
        }
    ) as stub:
        env = {"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "on"}
        env.update(stub.env())
        result = run_hook(write_payload(content), env_overrides=env)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "[UNVERIFIED]" not in result.stdout, (
        "Kaskaden-Treffer wurde wegen des Namenspartikels nicht als confirmed gewertet"
    )


# ---------------------------------------------------------------------------
# Fix-Runde: (Wort Jahr) ohne Signalwort ist kein Halluzinations-Nachweis
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "Die Erhebung lief im ersten Quartal (Januar 2021) ohne Ausfaelle.",
        "Der Zeitraum (März 2020) war besonders volatil.",
        "Die Zahlen (Stand 2021) stammen aus der amtlichen Statistik.",
        "Die Norm (Fassung 2019) gilt unveraendert weiter.",
        "Der Bericht (May 2018) wurde spaeter zurueckgezogen.",
    ],
)
def test_date_and_status_words_are_not_citations(empty_vault, content):
    """Datums- und Standangaben sind keine Belege: kein Block UND keine Markierung.

    ``(Januar 2021)`` hat exakt die Form ``(Wort Jahr)``, ist aber ein Datum.
    Ein ``[UNVERIFIED]`` im Fliesstext waere hier bereits eine Textverfaelschung.
    """
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 0, (
        f"Datumsangabe {content!r} blockiert: exit {result.returncode}. {result.stderr}"
    )
    assert "[UNVERIFIED]" not in result.stdout, (
        f"Datumsangabe {content!r} wurde als unbelegtes Zitat markiert"
    )


@pytest.mark.parametrize(
    "content",
    [
        "Der Reaktorunfall (Fukushima 2011) veraenderte die Energiedebatte.",
        "Die Pandemie (Corona 2020) traf den Einzelhandel hart.",
        "Der Beschluss (Bologna 1999) reformierte die Studienstruktur.",
    ],
)
def test_bare_word_year_stays_soft_under_the_mark_policy(empty_vault, content):
    """``(Wort Jahr)`` ohne Signalwort, Seite oder Co-Autor ist mehrdeutig.

    Ereignis- und Ortsnamen sind von Autorennamen lexikalisch nicht zu
    unterscheiden. Wer solche Prosa schreibt, setzt
    ``ACADEMIC_CITATION_AMBIGUOUS=mark`` — dann bleibt es auch bei komplett
    leerer Evidenzlage (leerer Vault, Kaskade aus) beim Anhaengen:
    ``[UNVERIFIED]`` hinter der Klammer, kein Eingriff in den uebrigen Satz.

    Der Default blockt diese Form dagegen (AC2, siehe
    ``test_bare_invented_citation_blocks_by_default``). Dass ein Treffer beide
    Reaktionen erspart, zeigen
    ``test_bare_word_year_with_a_known_author_stays_untouched`` (Kaskade) und
    ``test_bare_form_with_vault_hit_stays_untouched`` (Vault).
    """
    result = run_hook(
        write_payload(content),
        env_overrides={
            "VAULT_DB_PATH": empty_vault,
            "ACADEMIC_CITATION_CASCADE": "off",
            "ACADEMIC_CITATION_AMBIGUOUS": "mark",
        },
    )
    assert result.returncode == 0, (
        f"Prosa {content!r} hart geblockt: exit {result.returncode}. {result.stderr}"
    )
    if "updatedInput" in result.stdout:
        assert_marker_only(updated_content(result), content)


@pytest.mark.parametrize(
    "content",
    [
        "Der Reaktorunfall (Fukushima 2011) veraenderte die Energiedebatte.",
        "Der Beschluss (Bologna 1999) reformierte die Studienstruktur.",
    ],
)
def test_bare_word_year_with_a_known_author_stays_untouched(empty_vault, content):
    """Prosa-Schutz im Regelbetrieb: der Treffer haelt den Marker heraus.

    ``Fukushima`` und ``Bologna`` sind zugleich Orte UND reale Nachnamen. Steht
    zur Wort-Jahr-Kombination irgendwo ein Paper, bestaetigt die Kaskade sie und
    der Guard schweigt — die haeufigen Prosa-Faelle bleiben unberuehrt, ohne dass
    die Form pauschal von der Pruefung ausgenommen werden muss.
    """
    year = int(re.search(r"\d{4}", content).group(0))
    family = re.search(r"\((\w+)", content).group(1)
    with CascadeStub(
        {
            "arxiv": {
                "status": 200,
                "entries": [
                    {"title": "Reaktorsicherheit", "year": year, "authors": [f"K. {family}"]}
                ],
            }
        }
    ) as stub:
        env = {"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "on"}
        env.update(stub.env())
        result = run_hook(write_payload(content), env_overrides=env)
    assert result.returncode == 0, f"Prosa geblockt: exit {result.returncode}. {result.stderr}"
    assert "[UNVERIFIED]" not in result.stdout, (
        f"Bestaetigte Wort-Jahr-Form trotzdem markiert: {result.stdout!r}"
    )


def test_bare_citation_is_marked_but_not_rewritten(empty_vault):
    """Unter ``mark`` wird der mehrdeutige Fall markiert und sonst nicht angefasst.

    Fruehere Fassung: uebergehen. Das riss ein AC2-Loch — ein erfundenes
    ``(Fantasius 1999)`` lief unblockiert UND unmarkiert durch. Der Marker ist
    die schwaechste Reaktion, die noch zur Evidenzlage passt; alles darueber
    hinaus ausser dem Block (Umschreiben) waere ein Eingriff, den die Form nicht
    traegt.
    """
    content = "Der Befund (Fantasius 1999) belegt die These eindeutig."
    result = run_hook(
        write_payload(content),
        env_overrides={
            "VAULT_DB_PATH": empty_vault,
            "ACADEMIC_CITATION_CASCADE": "off",
            "ACADEMIC_CITATION_AMBIGUOUS": "mark",
        },
    )
    assert result.returncode == 0, f"Erwartet 0 (kein Hard-Block), got {result.returncode}."
    marked = updated_content(result)
    assert "(Fantasius 1999) [UNVERIFIED]" in marked, f"Nicht markiert: {result.stdout!r}"
    assert_marker_only(marked, content)


@pytest.mark.parametrize(
    "content",
    [
        # Seitenangabe
        "Der Befund (Fantasius 1999, S. 12) belegt die These.",
        # Signalwort in der Klammer
        "Der Befund (vgl. Fantasius 1999) belegt die These.",
        # Signalwort narrativ
        "Der Befund ist belegt, vgl. Fantasius 1999 in der Fachliteratur.",
        # Co-Autoren-Kette
        "Der Befund (Fantasius/Zweitautor 1999) belegt die These.",
        "Der Befund (Fantasius u. a. 1999) belegt die These.",
    ],
)
def test_strong_citation_shapes_still_block(empty_vault, content):
    """Eindeutige Beleg-Formen bleiben ein Hard-Block (AC2).

    Seitenangabe, Signalwort und Co-Autoren-Kette kommen in Prosa nicht
    versehentlich vor — hier ist die Zitierabsicht unstrittig.
    """
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 2, (
        f"Erfundener Beleg {content!r} nicht geblockt: exit {result.returncode}. {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Fix-Runde: AC2-Luecke der mehrdeutigen Form schliessen, ohne Prosa zu treffen
# ---------------------------------------------------------------------------


def test_bare_citation_blocks_when_author_is_cited_unambiguously(vault_with_mueller):
    """AC2: die nackte Form ist ein Beleg, sobald das Dokument sie als solchen ausweist.

    ``(Müller 2099)`` allein ist mehrdeutig. Steht im selben Dokument aber
    ``(Müller 2021, S. 45)`` — eine unstrittige Beleg-Form mit demselben
    Familiennamen —, dann zitiert dieser Text nachweislich einen Autor Müller.
    Damit ist die Zitierabsicht der nackten Form belegt und ein frei erfundenes
    Jahr wieder blockierbar, ohne die Prosa-Faelle (``(Fukushima 2011)``)
    anzufassen.
    """
    content = (
        "Der Befund (Müller 2021, S. 45) ist gut belegt.\n"
        "Ergaenzend heisst es dort (Müller 2099) zum selben Thema.\n"
    )
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": vault_with_mueller, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 2, (
        f"Erfundenes Jahr trotz belegter Zitierabsicht nicht geblockt: "
        f"exit {result.returncode}. stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "(Müller 2099)" in result.stderr, (
        f"Block nennt den ausloesenden Beleg nicht: {result.stderr!r}"
    )


def test_uncorroborated_bare_form_stays_out_of_the_block(vault_with_mueller):
    """Gegenprobe: die Aufwertung greift nur beim korroborierten Familiennamen.

    Derselbe Text, aber der Prosa-Fall traegt einen anderen Namen — er darf von
    der Zitierabsicht des Müller-Belegs nicht angesteckt werden. Unter
    ``ACADEMIC_CITATION_AMBIGUOUS=mark`` heisst das: kein Hard-Block, hoechstens
    ein Marker (der Vault kennt ``Fukushima`` nicht); der uebrige Satz bleibt
    unangetastet. Waere die Ansteckung da, blockte er auch unter ``mark``.
    """
    content = (
        "Der Befund (Müller 2021, S. 45) ist gut belegt.\n"
        "Der Reaktorunfall (Fukushima 2011) veraenderte die Energiedebatte.\n"
    )
    result = run_hook(
        write_payload(content),
        env_overrides={
            "VAULT_DB_PATH": vault_with_mueller,
            "ACADEMIC_CITATION_CASCADE": "off",
            "ACADEMIC_CITATION_AMBIGUOUS": "mark",
        },
    )
    assert result.returncode == 0, (
        f"Prosa neben einem echten Beleg geblockt: exit {result.returncode}. {result.stderr}"
    )
    marked = updated_content(result)
    assert "(Müller 2021, S. 45) [UNVERIFIED]" not in marked, (
        f"Vault-Treffer trotzdem markiert: {marked!r}"
    )
    assert_marker_only(marked, content)


# ---------------------------------------------------------------------------
# Fix-Runde: die Mengenbegrenzung darf keinen stillen Pruef-Ausfall erzeugen
# ---------------------------------------------------------------------------


def _many_bare_parentheses(count: int) -> str:
    """``count`` Saetze mit je einem eigenen ``(Name Jahr)`` in Prosa-Form."""
    letters = "abcdefghijklmnopqrstuvwxyz"
    lines = []
    for i in range(count):
        name = f"Aar{letters[(i // 26) % 26]}{letters[i % 26]}"
        lines.append(f"Der Ort ({name} 2011) war fuer die Region relevant.")
    return "\n".join(lines)


def test_ambiguous_parentheses_do_not_consume_the_citation_budget(empty_vault):
    """AC2 darf nicht daran scheitern, wie viele Klammern vorher im Text stehen.

    110 mehrdeutige ``(Wort Jahr)``-Klammern gefolgt von einem frei erfundenen
    Beleg mit Seitenangabe: der erfundene Beleg muss blocken, sonst genuegt
    genug harmlose Prosa, um den Guard auszuhebeln.
    """
    content = (
        _many_bare_parentheses(110) + "\nDer Befund (Fantasius 1999, S. 12) belegt die These.\n"
    )
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 2, (
        f"Erfundener Beleg hinter 110 Klammern nicht geblockt: exit {result.returncode}. "
        f"stdout={result.stdout[:400]!r} stderr={result.stderr[:400]!r}"
    )


def test_budget_overflow_is_marked_instead_of_silently_skipped(vault_with_mueller):
    """Ueber der Obergrenze wird markiert, nicht stillschweigend durchgewinkt.

    Mit ``ACADEMIC_CITATION_MAX_PER_WRITE=1`` passt nur der erste Beleg ins
    Pruefkontingent. Der zweite ist damit *ungeprueft* — und ungeprueft ist
    dieselbe Evidenzlage wie ein API-Ausfall: ``[UNVERIFIED]`` statt Block,
    aber niemals ein stiller Durchlauf.
    """
    content = (
        "Der Befund (Müller 2021, S. 45) ist gut belegt.\n"
        "Der zweite Befund (Fantasius 1999, S. 12) steht daneben.\n"
    )
    result = run_hook(
        write_payload(content),
        env_overrides={
            "VAULT_DB_PATH": vault_with_mueller,
            "ACADEMIC_CITATION_CASCADE": "off",
            "ACADEMIC_CITATION_MAX_PER_WRITE": "1",
        },
    )
    assert result.returncode == 0, (
        f"Ungeprueftes Kontingent-Ueberhang geblockt statt markiert: "
        f"exit {result.returncode}. {result.stderr}"
    )
    assert "(Fantasius 1999, S. 12) [UNVERIFIED]" in updated_content(result), (
        f"Ueberhang nicht markiert: {result.stdout!r}"
    )
    assert "ACADEMIC_CITATION_MAX_PER_WRITE" in result.stderr, (
        f"Kappung erfolgt ohne Hinweis auf stderr: {result.stderr!r}"
    )


def test_docs_document_citation_budget_limit():
    """AC4-Analogie: die Mengenbegrenzung ist konfigurierbar UND dokumentiert."""
    text = HOOKS_DOC.read_text(encoding="utf-8")
    section = re.search(r"### Klammer-Zitat-Validierung.*?(?=\n### |\n## |\Z)", text, re.DOTALL)
    assert section, "docs/reference/hooks.md enthaelt keine Sektion '### Klammer-Zitat-Validierung'"
    assert "ACADEMIC_CITATION_MAX_PER_WRITE" in section.group(0), (
        "docs/reference/hooks.md dokumentiert die Mengenbegrenzung nicht."
    )


# ---------------------------------------------------------------------------
# Fix-Runde: Markierung muss die GEPRUEFTE Fundstelle treffen (Blocker #378)
#
# Der Parser deduplizierte Belege und verwarf die Fundstelle; die Markierung
# suchte den Beleg per indexOf im unmaskierten Text neu. Drei Ausprägungen
# desselben Fehlers: falsches Vorkommen (Code-Fence vor Prosa), nur das erste
# von mehreren Vorkommen, und bei MultiEdit das falsche Segment.
# ---------------------------------------------------------------------------

FENCE = "```"


def mark_env(vault: str) -> dict:
    """Env, die den Soft-Fail-Pfad erzwingt: leerer Vault + nicht erreichbare Kaskade.

    Nur so entsteht überhaupt ein ``updatedInput`` — ein sauberes Negativ würde
    blocken und nie markieren.
    """
    base = f"http://127.0.0.1:{_closed_port()}"
    return {
        "VAULT_DB_PATH": vault,
        "ACADEMIC_CITATION_CASCADE": "on",
        "ACADEMIC_CITATION_ARXIV_URL": f"{base}/arxiv",
        "ACADEMIC_CITATION_CROSSREF_URL": f"{base}/crossref",
        "ACADEMIC_CITATION_S2_URL": f"{base}/s2",
    }


def run_node(source: str) -> subprocess.CompletedProcess:
    """Führt ein ESM-Snippet gegen die Hook-Module aus (Node-Unit über Subprozess)."""
    return subprocess.run(
        ["node", "--input-type=module", "-e", source],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=60,
    )


def test_extract_citations_reports_spans():
    """Span-Invariante: content.slice(start, end) === raw für jeden Beleg."""
    source = """
    import { extractCitations } from './hooks/lib/citation-parse.mjs';
    const content = [
      'Der Befund (Müller 2021, S. 45) gilt.',
      'Auch vgl. Schmidt 2019 wird genannt.',
      'Und nochmals (Müller 2021, S. 45) am Ende.',
    ].join('\\n');
    const cites = extractCitations(content);
    const bad = cites.filter((c) => content.slice(c.start, c.end) !== c.raw);
    console.log(JSON.stringify({ count: cites.length, bad: bad.length }));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    data = json.loads(result.stdout)
    assert data["bad"] == 0, "Span zeigt nicht auf den Beleg-Text"
    assert data["count"] == 3, (
        f"Erwartet 3 Fundstellen (zwei identische Belege + narrativ), got {data['count']}"
    )


def test_mark_spans_skips_span_mismatch():
    """Wächter: passt der Span nicht zum raw-Text, wird NICHT geraten."""
    source = """
    import { markSpans } from './hooks/lib/citation-parse.mjs';
    const text = 'Ein harmloser Satz ohne Beleg.';
    const out = markSpans(text, [{ raw: '(Müller 2021)', start: 4, end: 17 }], ' [UNVERIFIED]');
    console.log(JSON.stringify({ unchanged: out === text }));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    assert json.loads(result.stdout)["unchanged"], "Marker wurde an falscher Stelle gesetzt"


def test_marker_lands_on_checked_occurrence_not_code_fence(empty_vault):
    """Der Marker gehört an die geprüfte Prosa-Stelle, nicht in den Code-Fence.

    Der Fence ist maskiert und wird gar nicht geprüft. Landet der Marker dort,
    bleibt der wirklich ungeprüfte Beleg unmarkiert — der Write geht mit einem
    unbelegten Zitat durch.
    """
    content = (
        "Beispielausgabe:\n\n"
        f"{FENCE}\n(Fantasius 1999, S. 12)\n{FENCE}\n\n"
        "Der Befund (Fantasius 1999, S. 12) belegt die These.\n"
    )
    result = run_hook(
        write_payload(content),
        env_overrides=mark_env(empty_vault),
    )
    assert result.returncode == 0, f"Erwartet Soft-Fail, got {result.returncode}: {result.stderr}"
    updated = updated_content(result)
    assert f"{FENCE}\n(Fantasius 1999, S. 12)\n{FENCE}" in updated, (
        f"Code-Fence wurde verändert: {updated!r}"
    )
    assert "Der Befund (Fantasius 1999, S. 12) [UNVERIFIED] belegt" in updated, (
        f"Prosa-Beleg nicht markiert: {updated!r}"
    )
    assert_marker_only(updated, content)


def test_all_repeated_occurrences_marked(empty_vault):
    """Drei identische Belege ergeben drei Marker, nicht einen."""
    content = (
        "Erstens (Fantasius 1999, S. 12) sagt das.\n"
        "Zweitens (Fantasius 1999, S. 12) auch.\n"
        "Drittens (Fantasius 1999, S. 12) ebenso.\n"
    )
    result = run_hook(
        write_payload(content),
        env_overrides=mark_env(empty_vault),
    )
    assert result.returncode == 0, f"Erwartet Soft-Fail, got {result.returncode}: {result.stderr}"
    updated = updated_content(result)
    assert updated.count("[UNVERIFIED]") == 3, (
        f"Erwartet 3 Marker, got {updated.count('[UNVERIFIED]')}: {updated!r}"
    )
    assert_marker_only(updated, content)


def test_multiedit_marks_only_own_segment(empty_vault):
    """Ein Beleg aus edits[1] darf nicht in edits[0] markiert werden."""
    payload = {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": "kapitel/kap1.md",
            "edits": [
                {
                    "old_string": "a",
                    "new_string": f"{FENCE}\n(Fantasius 1999, S. 12)\n{FENCE}",
                },
                {
                    "old_string": "b",
                    "new_string": "Der Befund (Fantasius 1999, S. 12) belegt die These.",
                },
            ],
        },
    }
    sent = [dict(edit) for edit in payload["tool_input"]["edits"]]
    result = run_hook(payload, env_overrides=mark_env(empty_vault))
    assert result.returncode == 0, f"Erwartet Soft-Fail, got {result.returncode}: {result.stderr}"
    edits = json.loads(result.stdout)["hookSpecificOutput"]["updatedInput"]["edits"]
    for got, original in zip(edits, sent, strict=True):
        assert_marker_only(got["new_string"], original["new_string"])
    assert edits[0]["new_string"] == payload["tool_input"]["edits"][0]["new_string"], (
        f"Maskiertes Segment wurde verändert: {edits[0]['new_string']!r}"
    )
    assert "[UNVERIFIED]" in edits[1]["new_string"], (
        f"Eigenes Segment nicht markiert: {edits[1]['new_string']!r}"
    )


# ---------------------------------------------------------------------------
# Fix-Runde 2: verschachtelte Fundstellen (Deep-Review-P1, PR #412)
#
# Der Narrativ-Pass laeuft auf ``withoutParens``, wo eine Klammer zu Leerzeichen
# maskiert ist — das ``\s+`` hinter dem Signalwort sprang darueber hinweg und
# erzeugte eine Fundstelle, die eine andere ENTHAELT. markSpans pruefte den
# Waechter gegen den Originaltext, spleisste aber in den bereits mutierten Text:
# der zweite Marker landete mitten im Wort ("Schmi [UNVERIFIED]dt").
# ---------------------------------------------------------------------------

OVERLAP_CONTENT = "vgl. (Müller 2021, S. 45) Schmidt 2019, S. 7 ist relevant."


def test_overlapping_citations_never_split_a_word(empty_vault):
    """Der Marker darf nur angehaengt werden, nie in ein Wort hineinschneiden."""
    result = run_hook(
        write_payload(OVERLAP_CONTENT),
        env_overrides=mark_env(empty_vault),
    )
    assert result.returncode == 0, f"Erwartet Soft-Fail, got {result.returncode}: {result.stderr}"
    updated = updated_content(result)
    assert "Schmi [UNVERIFIED]dt" not in updated, f"Marker zerschneidet ein Wort: {updated!r}"
    assert updated.replace(" [UNVERIFIED]", "") == OVERLAP_CONTENT, (
        f"Text wurde ueber die Markierung hinaus veraendert: {updated!r}"
    )


def test_narrative_pass_does_not_swallow_a_paren_citation():
    """Ein Narrativ-Treffer ueber einer maskierten Region ist keine Fundstelle."""
    source = """
    import { extractCitations } from './hooks/lib/citation-parse.mjs';
    const overlap = 'vgl. (Müller 2021, S. 45) Schmidt 2019, S. 7 ist relevant.';
    const latex = 'vgl. \\\\cite{mueller2021} Schmidt 2019, S. 7 ist relevant.';
    const dump = (content) => extractCitations(content).map((c) => ({
      raw: c.raw,
      ok: content.slice(c.start, c.end) === c.raw,
    }));
    console.log(JSON.stringify({ overlap: dump(overlap), latex: dump(latex) }));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    data = json.loads(result.stdout)
    assert [c["raw"] for c in data["overlap"]] == ["(Müller 2021, S. 45)"], (
        f"Erwartet genau die Klammer-Fundstelle, got {data['overlap']}"
    )
    assert all(c["ok"] for c in data["overlap"]), "Span-Invariante verletzt"
    assert data["latex"] == [], (
        f"Narrativ-Treffer ueber \\cite{{...}} darf nicht zaehlen, got {data['latex']}"
    )


def test_mark_spans_skips_overlapping_spans():
    """Waechter: ueberlappende Spans werden verworfen statt geraten."""
    source = """
    import { markSpans } from './hooks/lib/citation-parse.mjs';
    const text = 'vgl. (Müller 2021, S. 45) Schmidt 2019, S. 7 ist relevant.';
    const spans = [
      { raw: text.slice(0, 44), start: 0, end: 44 },
      { raw: text.slice(5, 25), start: 5, end: 25 },
    ];
    const warnings = [];
    const out = markSpans(text, spans, ' [UNVERIFIED]', (m) => warnings.push(m));
    console.log(JSON.stringify({ out, warnings: warnings.length }));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    data = json.loads(result.stdout)
    assert (
        data["out"] == "vgl. (Müller 2021, S. 45) [UNVERIFIED] Schmidt 2019, S. 7 ist relevant."
    ), f"Nur der innere Span darf markiert werden, got {data['out']!r}"
    assert data["warnings"] == 1, f"Erwartet eine Warnung, got {data['warnings']}"


def test_mark_spans_keeps_adjacent_spans():
    """Grenzfall: ein Span endet genau dort, wo der naechste beginnt — kein Overlap."""
    source = """
    import { markSpans } from './hooks/lib/citation-parse.mjs';
    const text = 'AAAAABBBBB';
    const spans = [
      { raw: 'AAAAA', start: 0, end: 5 },
      { raw: 'BBBBB', start: 5, end: 10 },
    ];
    console.log(JSON.stringify({ out: markSpans(text, spans, '#') }));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    assert json.loads(result.stdout)["out"] == "AAAAA#BBBBB#"


def test_narrative_citation_survives_line_break_and_signal_words():
    """Kein Kollateralschaden: legitime Narrativformen bleiben erkannt."""
    source = """
    import { extractCitations } from './hooks/lib/citation-parse.mjs';
    const cases = {
      plain: 'siehe Schmidt 2019, S. 7 ist relevant.',
      lineBreak: 'Der Befund vgl.\\n  Schmidt 2019, S. 7 ist relevant.',
      zitNach: 'Der Befund zit. nach Weber 2018, S. 7 ist relevant.',
    };
    const out = {};
    for (const [name, content] of Object.entries(cases)) {
      out[name] = extractCitations(content).map((c) => ({
        family: c.family,
        page: c.page,
        ok: content.slice(c.start, c.end) === c.raw,
      }));
    }
    console.log(JSON.stringify(out));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    data = json.loads(result.stdout)
    for name, expected_family in (
        ("plain", "Schmidt"),
        ("lineBreak", "Schmidt"),
        ("zitNach", "Weber"),
    ):
        assert len(data[name]) == 1, f"{name}: erwartet genau eine Fundstelle, got {data[name]}"
        assert data[name][0]["family"] == expected_family, f"{name}: {data[name]}"
        assert data[name][0]["page"] == 7, f"{name}: Seite nicht erkannt, got {data[name]}"
        assert data[name][0]["ok"], f"{name}: Span-Invariante verletzt"


# ---------------------------------------------------------------------------
# Fix-Runde 3: confidence steuert die REAKTIONSSTAERKE, nicht das Ob der Pruefung
#
# Zwei Befunde, eine Wurzel — ``confidence`` wurde als Ja/Nein-Tor benutzt:
#
#   (a) Falsch-negativ: die unkorroborierte nackte Form "(Wort Jahr)" wurde vor
#       jeder Verifikation ausgefiltert. Ein frei erfundenes "(Fantasius 2087)"
#       lief unblockiert UND unmarkiert durch (AC2-Loch).
#   (b) Falsch-positiv: ``COAUTHORS`` liess das Trennzeichen ohne folgenden
#       Namen zu, und ``strong`` las das rohe Trennzeichen statt einen wirklich
#       gelesenen Zweitautor. Prosa wie "(Paris, 2015)" galt dadurch als
#       eindeutiger Beleg und wurde hart geblockt.
#
# Neue Regel: geprueft wird jede erkannte Form. ``strong`` darf blocken,
# ``weak`` hoechstens ``[UNVERIFIED]`` setzen.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "Der Vertrag (Paris, 2015) veraenderte die Klimapolitik weltweit.",
        "Die Erklaerung (Bologna, 1999) reformierte die Studienstruktur.",
        "Die Konferenz (Rio, 1992) setzte den Rahmen fuer spaetere Gipfel.",
    ],
)
def test_comma_before_year_is_not_an_unambiguous_citation(empty_vault, content):
    """(b) Ein Komma vor der Jahreszahl ist kein Co-Autoren-Marker.

    ``(Paris, 2015)`` hat exakt die Form von ``(Müller, 2021)``: ein Name, ein
    Komma, ein Jahr. Ohne zweiten Namen belegt das Komma keine Zitierabsicht —
    es trennt nur. Wer daraus einen *eindeutigen* Beleg macht, nimmt jeder
    Ort-Komma-Jahr-Nennung in Prosa die Wirkung von
    ``ACADEMIC_CITATION_AMBIGUOUS=mark``: sie blockte dann trotz gesetztem
    Schalter. Genau das prueft dieser Test — die Parser-Gegenprobe steht in
    ``test_coauthor_marker_requires_a_second_name``.
    """
    result = run_hook(
        write_payload(content),
        env_overrides={
            "VAULT_DB_PATH": empty_vault,
            "ACADEMIC_CITATION_CASCADE": "off",
            "ACADEMIC_CITATION_AMBIGUOUS": "mark",
        },
    )
    assert result.returncode != 2, (
        f"Prosa {content!r} hart geblockt: exit {result.returncode}. {result.stderr}"
    )


def test_coauthor_marker_requires_a_second_name():
    """(b) Parser-Ebene: nur ein wirklich gelesener Zweitautor macht ``strong``.

    Gegenprobe in beide Richtungen — ``u. a.``/``et al.`` bleiben eindeutige
    Marker ohne folgenden Namen, ein blosses Trennzeichen wird keiner.
    """
    source = """
    import { extractCitations } from './hooks/lib/citation-parse.mjs';
    const cases = {
      commaOnly: 'Der Vertrag (Paris, 2015) galt.',
      commaAuthor: 'Der Befund (Müller, 2021) gilt.',
      slashPair: 'Der Befund (Müller/Schmidt 2019) gilt.',
      commaPair: 'Der Befund (Müller, Schmidt 2019) gilt.',
      etAl: 'Der Befund (Müller u. a. 2021) gilt.',
    };
    const out = {};
    for (const [name, content] of Object.entries(cases)) {
      out[name] = extractCitations(content).map((c) => ({
        family: c.family,
        authors: c.authors,
        confidence: c.confidence,
        ok: content.slice(c.start, c.end) === c.raw,
      }));
    }
    console.log(JSON.stringify(out));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    data = json.loads(result.stdout)
    for name in data:
        assert len(data[name]) == 1, f"{name}: erwartet genau eine Fundstelle, got {data[name]}"
        assert data[name][0]["ok"], f"{name}: Span-Invariante verletzt"
    assert data["commaOnly"][0]["confidence"] == "weak", (
        f"Komma ohne Zweitautor als eindeutiger Beleg gelesen: {data['commaOnly']}"
    )
    assert data["commaOnly"][0]["authors"] == ["Paris"], (
        f"Leerer Co-Autor mitgeschleppt: {data['commaOnly']}"
    )
    assert data["commaAuthor"][0]["confidence"] == "weak", (
        f"(Name, Jahr) ist lexikalisch dieselbe Form wie (Ort, Jahr): {data['commaAuthor']}"
    )
    for name, expected in (("slashPair", "Schmidt"), ("commaPair", "Schmidt")):
        assert data[name][0]["confidence"] == "strong", f"{name}: {data[name]}"
        assert expected in data[name][0]["authors"], f"{name}: Zweitautor fehlt, {data[name]}"
    assert data["etAl"][0]["confidence"] == "strong", (
        f"'u. a.' ist ein eindeutiger Marker auch ohne Namen: {data['etAl']}"
    )


def test_bare_invented_citation_is_marked_instead_of_passing_silently(empty_vault):
    """(a) AC2: der erfundene nackte Beleg verlaesst den Guard nicht spurlos.

    Mehrdeutig ist kein Grund, gar nicht erst nachzusehen — vor Runde 3 war die
    Form vom Lookup ausgenommen und lief unmarkiert durch. Selbst unter der
    schwaechstmoeglichen Politik (``mark``) bleibt eine Spur; der Default blockt
    (``test_bare_invented_citation_blocks_by_default``).
    """
    content = "Der Befund (Fantasius 2087) belegt die These eindeutig."
    result = run_hook(
        write_payload(content),
        env_overrides={
            "VAULT_DB_PATH": empty_vault,
            "ACADEMIC_CITATION_CASCADE": "off",
            "ACADEMIC_CITATION_AMBIGUOUS": "mark",
        },
    )
    assert result.returncode == 0, (
        f"Mehrdeutige Form hart geblockt: exit {result.returncode}. {result.stderr}"
    )
    marked = updated_content(result)
    assert "(Fantasius 2087) [UNVERIFIED]" in marked, (
        f"Erfundener nackter Beleg lief unmarkiert durch: {result.stdout!r}"
    )
    assert_marker_only(marked, content)


def test_bare_form_with_vault_hit_stays_untouched(vault_with_mueller):
    """(a) Gegenprobe: was der Vault kennt, wird nicht angefasst.

    Der Schutz vor Marker-Rauschen ist der tatsaechliche Treffer — nicht das
    Ausfiltern der Form vor jeder Pruefung.
    """
    content = "Der Befund (Müller 2021) ist gut belegt und mehrfach repliziert."
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": vault_with_mueller, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 0, f"Vault-Treffer geblockt: {result.stderr}"
    assert "updatedInput" not in result.stdout, f"Vault-Treffer wurde markiert: {result.stdout!r}"


def test_bare_form_is_checked_against_the_cascade(empty_vault):
    """(a) Die nackte Form erreicht die Kaskade ueberhaupt.

    Vorher filterte ``runCitationCheck`` sie vor jedem Lookup weg — bestehende
    Kaskaden-Tests auf dieser Form liefen dadurch ins Leere. Der Nachweis haengt
    hier an ``stub.hits``, nicht am Exit-Code allein.
    """
    content = "Der Befund (Müller 2021) ist mehrfach repliziert worden."
    with CascadeStub(
        {
            "arxiv": {
                "status": 200,
                "entries": [
                    {"title": "Digitale Transformation", "year": 2021, "authors": ["Anna Müller"]}
                ],
            }
        }
    ) as stub:
        env = {"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "on"}
        env.update(stub.env())
        result = run_hook(write_payload(content), env_overrides=env)
    assert "arxiv" in stub.hits, f"Nackte Form nie an die Kaskade gestellt (hits={stub.hits})"
    assert result.returncode == 0, f"Kaskaden-Treffer geblockt: {result.stderr}"
    assert "[UNVERIFIED]" not in result.stdout, (
        f"Bestaetigter Beleg trotzdem markiert: {result.stdout!r}"
    )


def test_strong_citation_keeps_priority_in_the_budget(empty_vault):
    """Die nun mitgeprueften nackten Formen duerfen den Block nicht verdraengen.

    Kontingent 2, davor 110 mehrdeutige Klammern: haette die Textreihenfolge
    Vorrang vor der Belegstaerke, fiele der eindeutige erfundene Beleg aus dem
    Kontingent und der Hard-Block verschwaende hinter genug harmloser Prosa.
    """
    content = (
        _many_bare_parentheses(110) + "\nDer Befund (Fantasius 1999, S. 12) belegt die These.\n"
    )
    result = run_hook(
        write_payload(content),
        env_overrides={
            "VAULT_DB_PATH": empty_vault,
            "ACADEMIC_CITATION_CASCADE": "off",
            "ACADEMIC_CITATION_MAX_PER_WRITE": "2",
        },
    )
    assert result.returncode == 2, (
        f"Eindeutiger Beleg aus dem Kontingent verdraengt: exit {result.returncode}. "
        f"stdout={result.stdout[:300]!r} stderr={result.stderr[:300]!r}"
    )


# ---------------------------------------------------------------------------
# Fix-Runde 4: AC2 gilt auch fuer die nackte Form — der Trade-off wird
# konfigurierbar, statt das AC unilateral einzuschraenken
#
# Runde 3 hatte den Halbschritt gemacht: die nackte Form "(Wort Jahr)" wird
# zwar geprueft, aber ihre Reaktion war fest auf [UNVERIFIED] gedeckelt. Damit
# lief genau der im Issue als Motivation genannte Fall — frei erfundener Autor
# plus Jahr — weiter durch den Write hindurch. Das Issue kennt diese
# Einschraenkung nicht.
#
# Die Rechtfertigung des Deckels ("koennte Prosa sein") traegt nicht mehr,
# sobald derselbe Code diese Prosa bereits umschreibt: wer "(Fukushima 2011)"
# zu "(Fukushima 2011) [UNVERIFIED]" macht, hat den Eingriff in moeglicherweise
# unbeteiligten Text schon akzeptiert — und der Block ist der ehrlichere
# Eingriff, weil er sichtbar ist und nichts in die Datei schreibt.
#
# Neue Regel: bei sauberem Negativ blockt jede Beleg-Form. Wer prosa-lastig
# schreibt, setzt ACADEMIC_CITATION_AMBIGUOUS=mark und bekommt das bisherige
# Verhalten zurueck. Fehlende Evidenz (unavailable, Kontingent) bleibt in
# beiden Politiken ein Soft-Fail — AC3 steht ueber der Politik.
# ---------------------------------------------------------------------------


def test_bare_invented_citation_blocks_by_default(empty_vault):
    """AC2 ohne Formvorbehalt: der erfundene nackte Beleg wird geblockt.

    Wortgleicher Repro aus dem Review: leerer Vault, Kaskade aus, nackte Form
    ohne Seite, Signalwort oder Co-Autor. Vorher Exit 0 mit Marker.
    """
    content = "(Fantasius 2087) zeigt einen deutlichen Effekt"
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 2, (
        f"Erfundener nackter Beleg nicht geblockt: exit {result.returncode}. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "(Fantasius 2087)" in result.stderr, (
        f"Block nennt den ausloesenden Beleg nicht: {result.stderr!r}"
    )


def test_ambiguous_block_names_the_documented_escape(empty_vault):
    """Ein False Positive muss ohne Quellcode-Lektuere aufloesbar sein.

    Der Block auf einer mehrdeutigen Form kann Prosa treffen (``(Rio 1992)``).
    Dann muss die Meldung den Schalter nennen, der genau diesen Fall entschaerft
    — sonst bleibt dem Schreibenden nur der Bypass fuer den ganzen Text.
    """
    result = run_hook(
        write_payload("Die Konferenz (Rio 1992) setzte den Rahmen."),
        env_overrides={"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 2, f"Mehrdeutige Form nicht geblockt: {result.stderr!r}"
    assert "ACADEMIC_CITATION_AMBIGUOUS" in result.stderr, (
        f"Block auf mehrdeutiger Form nennt den Ausstieg nicht: {result.stderr!r}"
    )


def test_ambiguous_policy_mark_restores_the_soft_reaction(empty_vault):
    """``ACADEMIC_CITATION_AMBIGUOUS=mark`` stellt das Markieren wieder her.

    Der Schalter wirkt nur auf die mehrdeutige Form — dass die eindeutige davon
    unberuehrt bleibt, zeigt ``test_mark_policy_never_softens_a_strong_form``.
    """
    content = "(Fantasius 2087) zeigt einen deutlichen Effekt"
    result = run_hook(
        write_payload(content),
        env_overrides={
            "VAULT_DB_PATH": empty_vault,
            "ACADEMIC_CITATION_CASCADE": "off",
            "ACADEMIC_CITATION_AMBIGUOUS": "mark",
        },
    )
    assert result.returncode == 0, (
        f"mark-Politik blockt trotzdem: exit {result.returncode}. {result.stderr}"
    )
    marked = updated_content(result)
    assert "(Fantasius 2087) [UNVERIFIED]" in marked, f"Nicht markiert: {result.stdout!r}"
    assert_marker_only(marked, content)


def test_mark_policy_never_softens_a_strong_form(empty_vault):
    """Gegenprobe: der Schalter ist kein Kill-Switch fuer AC2 insgesamt.

    Seitenangabe = unstrittige Zitierabsicht. Wer sie erfindet, bekommt den
    Block auch unter ``mark``.
    """
    result = run_hook(
        write_payload("Der Befund (Fantasius 1999, S. 12) belegt die These."),
        env_overrides={
            "VAULT_DB_PATH": empty_vault,
            "ACADEMIC_CITATION_CASCADE": "off",
            "ACADEMIC_CITATION_AMBIGUOUS": "mark",
        },
    )
    assert result.returncode == 2, (
        f"Eindeutiger erfundener Beleg unter mark-Politik durchgelassen: "
        f"exit {result.returncode}. {result.stderr}"
    )


def test_ambiguous_form_unavailable_still_soft_fails(empty_vault):
    """AC3 steht ueber der Politik: fehlende Evidenz ist kein Gegenbeweis.

    Die Verschaerfung gilt nur fuer das *saubere* Negativ. Antwortet die
    Kaskade mit 503, ist ueber den Beleg nichts bekannt — dann bleibt es beim
    Marker, auch bei der nackten Form und auch unter der Block-Politik.
    """
    content = "Der Befund (Fantasius 2087) belegt die These eindeutig."
    with CascadeStub(
        {"arxiv": {"status": 503}, "crossref": {"status": 503}, "s2": {"status": 503}}
    ) as stub:
        env = {"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "on"}
        env.update(stub.env())
        result = run_hook(write_payload(content), env_overrides=env)
    assert result.returncode == 0, (
        f"API-Ausfall auf mehrdeutiger Form hart geblockt: exit {result.returncode}. "
        f"{result.stderr}"
    )
    marked = updated_content(result)
    assert "(Fantasius 2087) [UNVERIFIED]" in marked, f"Nicht markiert: {result.stdout!r}"
    assert_marker_only(marked, content)


def test_ambiguous_form_over_budget_still_soft_fails(vault_with_mueller):
    """Zweite Evidenzluecke, dieselbe Regel: ungeprueft bleibt ungeprueft.

    Ueber dem Pruefkontingent ist auch die nackte Form nur *ungeprueft* — die
    Block-Politik darf daraus keinen Halluzinations-Nachweis machen.
    """
    content = (
        "Der Befund (Müller 2021, S. 45) ist gut belegt.\n"
        "Der Reaktorunfall (Fantasius 2087) veraenderte die Debatte.\n"
    )
    result = run_hook(
        write_payload(content),
        env_overrides={
            "VAULT_DB_PATH": vault_with_mueller,
            "ACADEMIC_CITATION_CASCADE": "off",
            "ACADEMIC_CITATION_MAX_PER_WRITE": "1",
        },
    )
    assert result.returncode == 0, (
        f"Kontingent-Ueberhang geblockt statt markiert: exit {result.returncode}. {result.stderr}"
    )
    assert "(Fantasius 2087) [UNVERIFIED]" in updated_content(result), (
        f"Ueberhang nicht markiert: {result.stdout!r}"
    )


def test_docs_document_ambiguous_policy():
    """AC4-Analogie: der Trade-off ist konfigurierbar UND dokumentiert."""
    text = HOOKS_DOC.read_text(encoding="utf-8")
    section = re.search(r"### Klammer-Zitat-Validierung.*?(?=\n### |\n## |\Z)", text, re.DOTALL)
    assert section, "docs/reference/hooks.md enthaelt keine Sektion '### Klammer-Zitat-Validierung'"
    assert "ACADEMIC_CITATION_AMBIGUOUS" in section.group(0), (
        "docs/reference/hooks.md dokumentiert die Ambiguitaets-Politik nicht."
    )
