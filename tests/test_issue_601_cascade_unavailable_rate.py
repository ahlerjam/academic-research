"""Tests fuer die unavailable-Raten-Warnung der Zitat-Kaskade (Issue #601).

Die Kaskadenlogik selbst (jeder Nicht-2xx = `unavailable`) bleibt unangetastet
— dieses Modul prueft ausschliesslich die neue Beobachtungs-Warnung, die
sichtbar macht, wenn ein dauerhaft blockierter Egress viele Einzelanfragen
ins Leere laufen laesst.

Akzeptanzkriterien (Issue #601):
  AC1  Nach einem Lauf liegen Gesamtzahl und unavailable-Zahl vor.
  AC2  Ueberschreitet der Anteil Schwelle+Mindestfallzahl -> Warnung mit
       beiden Zahlen und dem haeufigsten Grund.
  AC3  Unterhalb Schwelle ODER Mindestfallzahl -> keine Warnung.
  AC4  Bewertung einzelner HTTP-Antworten unveraendert (bestehende #378-Tests
       bleiben gruen, siehe test_issue_378_citation_guard.py).
  AC5  Schwelle und Mindestfallzahl sind ohne Codeaenderung (per Env)
       einstellbar.
"""

import json
import os
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "verbatim-guard.mjs"
HOOKS_DOC = REPO_ROOT / "docs" / "reference" / "hooks.md"

# Wegwerf-Ziel fuer die Guard-Logs dieses Testmoduls (siehe run_hook in
# test_issue_378_citation_guard.py — gleiches Muster, lokale Kopie da tests/
# klassisches pytest ist und keine stabile Bibliotheks-API zwischen den
# Testmodulen unterstellt werden soll).
_GUARD_LOG_DIR = Path(tempfile.mkdtemp(prefix="vault-guard-test-logs-601-"))


# ---------------------------------------------------------------------------
# Stub-HTTP-Server fuer die Kaskade (arXiv / CrossRef / Semantic Scholar)
# ---------------------------------------------------------------------------


def _arxiv_feed(entries: list[dict]) -> str:
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


# ---------------------------------------------------------------------------
# Hook-Runner
# ---------------------------------------------------------------------------


def run_hook(payload: dict, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    for key in [k for k in env if k.startswith("ACADEMIC_CITATION_")]:
        del env[key]
    env["VAULT_DB_PATH"] = str(REPO_ROOT / "nonexistent_vault_for_tests_601.db")
    env["VAULT_GUARD_ENV_SWITCH_LOG"] = str(_GUARD_LOG_DIR / "env-switch.log")
    env["VAULT_GUARD_BYPASS_LOG"] = str(_GUARD_LOG_DIR / "bypass.log")
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


@pytest.fixture
def empty_vault(tmp_path):
    from academic_vault.db import VaultDB

    db_path = str(tmp_path / "empty_601.db")
    db = VaultDB(db_path)
    db.init_schema()
    return db_path


# Mehrere unterschiedliche Belege, damit genug Kaskaden-Anfragen entstehen
# (arXiv-Batch: 1 Anfrage fuer alle: + CrossRef/S2 je Beleg). Vier eindeutige
# Belege (Signalwort "S.") ergeben 1 (arXiv) + 4 (CrossRef) + 4 (S2) = 9
# Anfragen, sofern kein Treffer vorzeitig aussteigt.
FOUR_CITATIONS = (
    "Der Befund (Fantasius 1999, S. 12) belegt die These eindeutig. "
    "Ebenso zeigt (Wurzelbach 2001, S. 5) den Effekt. "
    "Auch (Lindqvist 2010, S. 30) bestaetigt dies. "
    "Zuletzt untermauert (Okonkwo 2015, S. 8) den Befund."
)


# ---------------------------------------------------------------------------
# AC2 — hohe Rate bei ausreichender Fallzahl -> Warnung
# ---------------------------------------------------------------------------


def test_high_unavailable_rate_warns_with_numbers_and_reason(empty_vault):
    """AC1+AC2: genug Anfragen, alle unavailable -> Warnung mit Zahlen + Grund."""
    with CascadeStub(
        {
            "arxiv": {"status": 503},
            "crossref": {"status": 503},
            "s2": {"status": 503},
        }
    ) as stub:
        env = {"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "on"}
        env.update(stub.env())
        result = run_hook(write_payload(FOUR_CITATIONS), env_overrides=env)
    assert result.returncode == 0, (
        f"Erwartet 0 (Soft-Fail), got {result.returncode}. {result.stderr}"
    )
    assert "9/9" in result.stderr, f"stderr: {result.stderr!r}"
    assert "HTTP 503" in result.stderr, f"stderr: {result.stderr!r}"


# ---------------------------------------------------------------------------
# AC3 — unterhalb Schwelle oder Mindestfallzahl -> keine Warnung
# ---------------------------------------------------------------------------


def test_single_unavailable_citation_below_min_requests_no_warning(empty_vault):
    """AC3: ein einzelner Beleg (3 Anfragen) bleibt unter der Default-Mindestfallzahl (5)."""
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
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "[Citation-Cascade]" not in result.stderr, f"stderr: {result.stderr!r}"


def test_enough_requests_but_low_rate_no_warning(empty_vault):
    """AC3: genug Anfragen, aber die meisten sauber beantwortet -> Rate unter Schwelle, keine Warnung.

    Drei der vier Belege finden einen confirmed-Treffer bereits in Stufe 1
    (arXiv) und steigen sofort aus der Kaskade aus; nur der vierte bleibt
    offen und produziert unavailable-Anfragen in Stufe 2/3. Das haelt die
    Rate unter der Default-Schwelle von 0.5, obwohl total >= 5 ist.
    """
    with CascadeStub(
        {
            "arxiv": {
                "status": 200,
                "entries": [
                    {"title": "T1", "year": 1999, "authors": ["Anna Fantasius"]},
                    {"title": "T2", "year": 2001, "authors": ["Bruno Wurzelbach"]},
                    {"title": "T3", "year": 2010, "authors": ["Carla Lindqvist"]},
                ],
            },
            "crossref": {"status": 503},
            "s2": {"status": 503},
        }
    ) as stub:
        env = {"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "on"}
        env.update(stub.env())
        result = run_hook(write_payload(FOUR_CITATIONS), env_overrides=env)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "[Citation-Cascade]" not in result.stderr, f"stderr: {result.stderr!r}"


# ---------------------------------------------------------------------------
# AC5 — Schwelle/Mindestfallzahl per Env konfigurierbar, ohne Codeaenderung
# ---------------------------------------------------------------------------


def test_min_requests_env_lowers_threshold_to_trigger_warning(empty_vault):
    """AC5: derselbe Single-Beleg-Stub loest bei niedrigerer Mindestfallzahl eine Warnung aus."""
    content = "Der Befund (Fantasius 1999, S. 12) belegt die These eindeutig."
    with CascadeStub(
        {
            "arxiv": {"status": 503},
            "crossref": {"status": 503},
            "s2": {"status": 503},
        }
    ) as stub:
        env = {
            "VAULT_DB_PATH": empty_vault,
            "ACADEMIC_CITATION_CASCADE": "on",
            "ACADEMIC_CITATION_UNAVAILABLE_RATE_MIN_REQUESTS": "3",
        }
        env.update(stub.env())
        result = run_hook(write_payload(content), env_overrides=env)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "3/3" in result.stderr, f"stderr: {result.stderr!r}"


def test_rate_threshold_env_suppresses_warning_despite_high_count(empty_vault):
    """AC5: eine hochgesetzte Schwelle unterdrueckt die Warnung beim selben Stub."""
    with CascadeStub(
        {
            "arxiv": {"status": 503},
            "crossref": {"status": 503},
            "s2": {"status": 503},
        }
    ) as stub:
        env = {
            "VAULT_DB_PATH": empty_vault,
            "ACADEMIC_CITATION_CASCADE": "on",
            "ACADEMIC_CITATION_UNAVAILABLE_RATE_THRESHOLD": "1",
        }
        env.update(stub.env())
        result = run_hook(write_payload(FOUR_CITATIONS), env_overrides=env)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "[Citation-Cascade]" not in result.stderr, f"stderr: {result.stderr!r}"


def test_docs_document_unavailable_rate_config():
    """AC5: docs/reference/hooks.md dokumentiert die neuen Env-Variablen."""
    text = HOOKS_DOC.read_text(encoding="utf-8")
    for token in (
        "ACADEMIC_CITATION_UNAVAILABLE_RATE_THRESHOLD",
        "ACADEMIC_CITATION_UNAVAILABLE_RATE_MIN_REQUESTS",
    ):
        assert token in text, f"docs/reference/hooks.md dokumentiert '{token}' nicht (AC5)."
