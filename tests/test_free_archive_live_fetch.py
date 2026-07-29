"""Nachvollzug des Live-Belegs zu AC1 (Issue #450) gegen das echte Netz.

Dieser Lauf ist **opt-in**: ohne ``RUN_LIVE_ARCHIVE_FETCH=1`` skippt jeder Test.
CI faehrt ihn nicht — ein Ausfall bei archive.org oder der Bayerischen
Staatsbibliothek darf diese Pipeline nicht rot faerben (gleiche Begruendung wie
bei ``oa-fetchers``, siehe ``docs/evals/STRATEGY.md``).

Warum es ihn trotzdem gibt: ``evals/free-archive-fetchers/live-verification.json``
behauptet, dass zwei der drei Agenten am 2026-07-29 real ein PDF beschafft haben.
Eine Behauptung, die niemand nachfahren kann, ist kein Beleg. Dieser Test ist der
Nachfahrweg — er holt dieselben Dateien und prueft sie gegen die aufgezeichneten
Kennwerte.

    RUN_LIVE_ARCHIVE_FETCH=1 uv run pytest tests/test_free_archive_live_fetch.py -v

Abdeckung und ihre Grenzen:

* **Internet Archive** — vollstaendig: Detailseite, PDF-Link, Datei, SHA-256.
* **MDZ** — ab der Download-Zwischenseite. Die Werk-Detailseite ist eine
  JavaScript-Anwendung; der PDF/DaFo-Link entsteht erst im Browser. Der
  server-gerenderte Teil (Rechtehinweis-Weiche ``xdfz`` und der daraus erzeugte
  PDF-Link) ist genau der Abschnitt, an dem der Ablauf haengt, und genau der
  wird hier gefahren.
* **HathiTrust** — nicht abgedeckt, mit Ansage. Katalog und Viewer liegen hinter
  einer Cloudflare-Managed-Challenge, der Gesamtband-Download wird von der
  Plattform geblockt. Der Beleg dafuer steht als ``blocked_by_platform`` in der
  Aufzeichnung; ein Test, der das gruen meldet, waere Selbstbetrug.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest

from tests.helpers.archive_fetcher_nav import (
    MIN_PDF_BYTES,
    PDF_MAGIC,
    ArchiveFetcherNavigator,
)

REPO_ROOT = Path(__file__).parent.parent
RECORD_PATH = REPO_ROOT / "evals" / "free-archive-fetchers" / "live-verification.json"

RUN_LIVE = os.environ.get("RUN_LIVE_ARCHIVE_FETCH") == "1"
TIMEOUT_SECONDS = 300
USER_AGENT = "academic-research/free-archive-fetchers (Issue #450 live verification)"

pytestmark = pytest.mark.skipif(
    not RUN_LIVE,
    reason="Live-Lauf gegen fremde Archive — nur mit RUN_LIVE_ARCHIVE_FETCH=1",
)


def _record() -> dict:
    return json.loads(RECORD_PATH.read_text(encoding="utf-8"))


def _run(agent: str) -> dict:
    return next(run for run in _record()["runs"] if run["agent"] == agent)


def _open(url: str) -> tuple[str, bytes] | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return response.headers.get_content_type(), response.read()
    except OSError:
        return None


def _page_transport(url: str) -> str | None:
    payload = _open(url)
    return None if payload is None else payload[1].decode("utf-8", errors="replace")


def _download_transport(url: str) -> bytes | None:
    payload = _open(url)
    return None if payload is None else payload[1]


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return _sha256_bytes(fh.read())


#: Das Trailer-Feld ``/ID`` ist der einzige Teil, den MDZ je Generierung neu
#: wuerfelt (58 Bytes, gemessen am 2026-07-29). Ohne diese Normalisierung waere
#: jeder Pruefsummen-Vergleich gegen MDZ garantiert rot.
_PDF_ID_RE = re.compile(rb"/ID\s*\[<[0-9A-Fa-f]*><[0-9A-Fa-f]*>\]")


def _normalized_pdf_digest(payload: bytes) -> str:
    return _sha256_bytes(_PDF_ID_RE.sub(b"/ID []", payload))


class TestInternetArchiveLive:
    def test_recorded_pdf_is_still_fetchable_and_identical(self, tmp_path):
        run = _run("internetarchive-fetcher")
        pdf_url = run["url_chain"][-1]
        target = str(tmp_path / "darwin.pdf")

        payload = _download_transport(pdf_url)
        assert payload is not None, f"Kein Inhalt unter {pdf_url}"
        Path(target).write_bytes(payload)

        assert payload.startswith(PDF_MAGIC)
        assert len(payload) > MIN_PDF_BYTES
        assert len(payload) == run["artifact"]["bytes"], (
            "Groesse weicht von der Aufzeichnung ab — Digitalisat wurde ersetzt?"
        )
        assert _sha256(target) == run["artifact"]["sha256"], (
            "SHA-256 weicht von der Aufzeichnung ab — die Datei ist nicht mehr dieselbe"
        )

    def test_details_page_needs_a_browser_and_says_so(self):
        """Belegt, warum der Agent hier browser-use braucht und nicht HTTP.

        Die Detailseite ist eine JavaScript-Anwendung; einfachen Clients
        antwortet archive.org mit einem Bot-Check. Der Spiegel erkennt genau das
        und meldet ``captcha`` statt einen Treffer zu erfinden.
        """
        run = _run("internetarchive-fetcher")
        nav = ArchiveFetcherNavigator(
            "internetarchive",
            pages=_page_transport,
            downloads=lambda url: pytest.fail(f"Kein Download erwartet, versucht: {url}"),
            downloads_dir="/tmp/should-not-be-used",
        )
        result = nav.fetch(run["url_chain"][0], "/tmp/should-not-be-written.pdf")
        assert result["status"] in ("captcha", "metadata_only"), result
        assert "pdf_path" not in result


class TestMdzLive:
    """Die Rechtehinweis-Weiche, live gefahren.

    Ohne ``xdfz=2`` liefert MDZ wieder nur das Formular. Der Test prueft beide
    Seiten der Weiche — sonst waere nicht belegt, dass der Pflichtklick wirklich
    traegt und nicht bloss mitgeschleppte Folklore ist.
    """

    def _intermediate_url(self) -> str:
        return _run("mdz-fetcher")["url_chain"][1]

    def test_without_rights_acceptance_no_pdf_link(self):
        html = _page_transport(self._intermediate_url())
        assert html is not None
        # Quote-agnostisch: der Server schreibt name='xdfz', der Browser-DOM-Abzug
        # name="xdfz". Eine auf eine Variante festgelegte Pruefung geht schief.
        assert re.search(r"""name\s*=\s*['"]?xdfz['"]?""", html), (
            "Rechtehinweis-Radiobutton fehlt — Ablauf hat sich geaendert"
        )
        assert "herunterladen" not in html, "PDF-Link darf ohne Bestaetigung nicht erscheinen"

    def test_with_rights_acceptance_pdf_is_served(self, tmp_path):
        parts = urlsplit(self._intermediate_url())
        query = dict(parse_qsl(parts.query))
        query.update({"xdfz": "2", "vers": "d", "abschicken": "ja", "submitbutton": "WEITER"})
        ready_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))

        html = _page_transport(ready_url)
        assert html is not None, f"Bereitstellungsseite {ready_url} nicht ladbar"
        assert "herunterladen" in html, "Kein PDF-Link nach bestaetigtem Rechtehinweis"

        href = re.search(r"""href\s*=\s*["']([^"']*\.pdf)["']""", html, re.I)
        assert href, "PDF-Link auf der Bereitstellungsseite nicht gefunden"
        pdf_url = urlunsplit((parts.scheme, parts.netloc, href.group(1), "", ""))

        payload = _download_transport(pdf_url)
        assert payload is not None, f"Kein Inhalt unter {pdf_url}"
        assert payload.startswith(PDF_MAGIC)
        assert len(payload) > MIN_PDF_BYTES

        artifact = _run("mdz-fetcher")["artifact"]
        assert len(payload) == artifact["bytes"]
        # Die rohe Pruefsumme taugt hier NICHT: MDZ erzeugt das PDF je Abruf neu
        # und wuerfelt dabei das Trailer-Feld /ID. Alles andere ist identisch.
        assert artifact["sha256_is_reproducible"] is False
        assert _normalized_pdf_digest(payload) == artifact["sha256_normalized"]


class TestHathiTrustLiveIsHonestlyOutOfReach:
    def test_record_states_blocked_rather_than_claiming_success(self):
        run = _run("hathitrust-fetcher")
        assert run["verdict"] == "blocked_by_platform"
        assert run["artifact"]["sha256"] is None
