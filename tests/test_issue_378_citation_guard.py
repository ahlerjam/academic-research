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
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "verbatim-guard.mjs"
README = REPO_ROOT / "README.md"


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
    env["VAULT_DB_PATH"] = str(REPO_ROOT / "nonexistent_vault_for_tests.db")
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
    assert "[UNVERIFIED]" in updated_content(result)


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


def test_readme_documents_citation_thresholds():
    """AC4: README dokumentiert Schwellenwerte und Env-Variablen nachvollziehbar."""
    text = README.read_text(encoding="utf-8")
    for token in (
        "ACADEMIC_CITATION_CONFIRMED_MIN",
        "ACADEMIC_CITATION_PROBABLE_MIN",
        "ACADEMIC_CITATION_CASCADE",
        "[UNVERIFIED]",
    ):
        assert token in text, f"README dokumentiert '{token}' nicht (AC4)."
    section = re.search(r"### Klammer-Zitat-Validierung.*?(?=\n### |\n## |\Z)", text, re.DOTALL)
    assert section, "README enthaelt keine Sektion '### Klammer-Zitat-Validierung'"
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
def test_bare_word_year_never_hard_blocks(empty_vault, content):
    """``(Wort Jahr)`` ohne Signalwort, Seite oder Co-Autor ist mehrdeutig.

    Ereignis- und Ortsnamen sind von Autorennamen lexikalisch nicht zu
    unterscheiden. Ein Hard-Block auf dieser Evidenzlage stoppt legitime Prosa;
    hoechstens eine ``[UNVERIFIED]``-Markierung ist angemessen.
    """
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 0, (
        f"Prosa {content!r} hart geblockt: exit {result.returncode}. {result.stderr}"
    )


def test_bare_citation_without_match_marks_unverified(empty_vault):
    """Gegenprobe: der schwache Fall verschwindet nicht, er wird markiert."""
    content = "Der Befund (Fantasius 1999) belegt die These eindeutig."
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 0, f"Erwartet 0 (Soft-Fail), got {result.returncode}."
    assert "(Fantasius 1999) [UNVERIFIED]" in updated_content(result)


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
