"""AC1 aus Issue #450, ausgefuehrt statt behauptet.

Der Akzeptanzpunkt lautet: „Jeder der drei Agents beschafft einen bekannten
gemeinfreien Testtitel als PDF." Bis zur Fix-Runde zu PR #498 gab es dafuer nur
Prosa-Assertions (Regex ueber den Prompt) und Eval-Cases, die ``metadata_only``
als gleichwertig durchgehen liessen — beides belegt keine Beschaffung.

Hier laeuft die Beschaffung wirklich: ``tests/helpers/local_origin.py`` serviert
die live erhobene DOM der drei Archive **und** eine PDF-Route auf 127.0.0.1,
``tests/helpers/archive_fetcher_nav.py`` faehrt den Weg des jeweiligen Agenten
ab, laesst die Datei im Download-Verzeichnis landen, verschiebt sie auf den
Zielpfad und liest sie von der Platte zurueck. Der Test vergleicht die
geschriebenen Bytes mit den ausgelieferten.

Was hier NICHT abgedeckt ist: das oeffentliche Netz der drei Archive. Dafuer
gibt es ``tests/test_free_archive_live_fetch.py`` (opt-in) und den Belegstand in
``evals/free-archive-fetchers/live-verification.json``.
"""

from __future__ import annotations

import os

import pytest

from tests.helpers.archive_fetcher_nav import (
    ACCESS_LEVEL_PREFIX,
    HATHITRUST_BULK_BLOCK_REASON,
    MIN_PDF_BYTES,
    ArchiveFetcherNavigator,
)
from tests.helpers.local_origin import LocalOrigin

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "free_archives")
PDF_SOURCE = os.path.join(os.path.dirname(__file__), "fixtures", "fulltext", "nonce_paper.pdf")

HTML_TYPE = "text/html; charset=utf-8"
PDF_TYPE = "application/pdf"


def _fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as fh:
        return fh.read()


def _real_pdf_bytes() -> bytes:
    """Ein echtes PDF, aufgefuellt ueber die 10-KB-Schwelle der Agenten.

    Die Auffuellung haengt als PDF-Kommentar hinter ``%%EOF`` — die Datei bleibt
    lesbar und beginnt weiterhin mit ``%PDF-``.
    """
    with open(PDF_SOURCE, "rb") as fh:
        base = fh.read()
    padding = b"\n%% padding fuer die 10-KB-Schwelle " + b"x" * MIN_PDF_BYTES
    return base + padding


@pytest.fixture
def pdf_bytes() -> bytes:
    return _real_pdf_bytes()


# ─── AC1: es wird tatsaechlich ein PDF beschafft ─────────────────────────────


class TestPdfActuallyFetched:
    """Pro Agent ein durchgefuehrter Beschaffungsvorgang mit Datei auf der Platte."""

    def test_internetarchive_writes_and_verifies_pdf(self, tmp_path, pdf_bytes):
        routes = {
            "/details/onoriginofspecie1859darw": (
                HTML_TYPE,
                _fixture("internetarchive_public_domain.html").encode("utf-8"),
            ),
            "/download/onoriginofspecie1859darw/onoriginofspecie1859darw.pdf": (
                PDF_TYPE,
                pdf_bytes,
            ),
        }
        target = str(tmp_path / "out" / "darwin.pdf")
        with LocalOrigin(routes) as origin:
            nav = ArchiveFetcherNavigator(
                "internetarchive",
                pages=origin.page_transport(),
                downloads=origin.asset_transport(),
                downloads_dir=str(tmp_path / "browser-use-downloads-test"),
            )
            result = nav.fetch(origin.url("/details/onoriginofspecie1859darw"), target)

        assert result["status"] == "success", result
        assert result["source_subagent"] == "internetarchive-fetcher"
        assert os.path.isfile(target)
        with open(target, "rb") as fh:
            written = fh.read()
        assert written == pdf_bytes
        assert written.startswith(b"%PDF-")
        assert len(written) > MIN_PDF_BYTES
        # AC4: die Ausgabe stammt aus dem Katalogeintrag des Digitalisats.
        assert result["edition"] == "London : John Murray, 1859"

    def test_mdz_writes_and_verifies_pdf(self, tmp_path, pdf_bytes):
        target = str(tmp_path / "out" / "faust.pdf")
        with LocalOrigin(_mdz_routes(pdf_bytes)) as origin:
            nav = ArchiveFetcherNavigator(
                "mdz",
                pages=origin.page_transport(),
                downloads=origin.asset_transport(),
                downloads_dir=str(tmp_path / "browser-use-downloads-test"),
            )
            result = nav.fetch(origin.url("/de/view/bsb10109182"), target)

        assert result["status"] == "success", result
        assert result["source_subagent"] == "mdz-fetcher"
        assert os.path.isfile(target)
        with open(target, "rb") as fh:
            written = fh.read()
        assert written == pdf_bytes
        assert result["edition"] == "Stuttgart : J. G. Cotta 1833"

    def test_hathitrust_writes_and_verifies_pdf_when_platform_serves_it(self, tmp_path, pdf_bytes):
        """Der Weg selbst traegt — geblockt wird er von HathiTrust, nicht vom Agenten.

        Deshalb wird hier der Fall geprueft, dass die signierte URL die Datei
        liefert. Der real beobachtete Ausgang (Sperrseite) steht in
        :class:`TestHathiTrustBulkDownloadIsBlocked`.
        """
        routes = {
            "/cgi/pt": (HTML_TYPE, _fixture("hathitrust_full_view.html").encode("utf-8")),
            "/cgi/imgsrv/download/pdf": (PDF_TYPE, pdf_bytes),
        }
        target = str(tmp_path / "out" / "kant.pdf")
        with LocalOrigin(routes) as origin:
            nav = ArchiveFetcherNavigator(
                "hathitrust",
                pages=origin.page_transport(),
                downloads=origin.asset_transport(),
                downloads_dir=str(tmp_path / "browser-use-downloads-test"),
            )
            result = nav.fetch(origin.url("/cgi/pt?id=hvd.hntupx&seq=5"), target)

        assert result["status"] == "success", result
        assert os.path.isfile(target)
        with open(target, "rb") as fh:
            assert fh.read() == pdf_bytes
        assert result["edition"] == "Leipzig : Leopold Voss, 1878"


def _mdz_routes(pdf_bytes: bytes) -> dict:
    """MDZ-Routing inkl. der Rechtehinweis-Weiche.

    ``/BOOKS/download.pl`` antwortet abhaengig von ``xdfz``: ohne die
    Bestaetigung („Ja" = ``xdfz=2``) kommt wieder das Formular, erst mit ihr die
    Bereitstellungsseite mit dem PDF-Link. Genau so verhaelt sich MDZ live.
    """
    form = _fixture("mdz_rights_form.html").encode("utf-8")
    ready = _fixture("mdz_download_ready.html").encode("utf-8")

    def download_pl(full_path: str) -> tuple[str, bytes]:
        return (HTML_TYPE, ready if "xdfz=2" in full_path else form)

    return {
        "/de/view/bsb10109182": (
            HTML_TYPE,
            _fixture("mdz_record_full_view.html").encode("utf-8"),
        ),
        "/BOOKS/download.pl": download_pl,
        "/pdf/17853191418888bsb10109182.pdf": (PDF_TYPE, pdf_bytes),
    }


# ─── AC2: eingeschraenkte Sichtbarkeit meldet die Stufe, statt Text zu liefern ─


class TestAccessLevelInsteadOfPartialFulltext:
    @pytest.mark.parametrize(
        "archive, entry, fixture_name, expected_level",
        [
            (
                "hathitrust",
                "/cgi/pt",
                "hathitrust_limited_search_only.html",
                "Suche-im-Buch",
            ),
            (
                "internetarchive",
                "/details/originofspecies00darw",
                "internetarchive_borrow_only.html",
                "Borrow-only (Controlled Digital Lending)",
            ),
            (
                "mdz",
                "/de/view/bsb00000000",
                "mdz_record_metadata_only.html",
                "nur Metadaten",
            ),
        ],
    )
    def test_restricted_item_yields_metadata_only_without_file(
        self, tmp_path, archive, entry, fixture_name, expected_level
    ):
        target = str(tmp_path / "out.pdf")
        with LocalOrigin({entry: (HTML_TYPE, _fixture(fixture_name).encode("utf-8"))}) as origin:
            nav = ArchiveFetcherNavigator(
                archive,
                pages=origin.page_transport(),
                downloads=lambda url: pytest.fail(f"Kein Download erlaubt, versucht: {url}"),
                downloads_dir=str(tmp_path / "downloads"),
            )
            result = nav.fetch(origin.url(entry), target)

        assert result["status"] == "metadata_only", result
        assert result["reason"] == f"{ACCESS_LEVEL_PREFIX} {expected_level}"
        assert "pdf_path" not in result
        assert not os.path.exists(target)


class TestHathiTrustBulkDownloadIsBlocked:
    """Der live beobachtete Ausgang: Vollansicht, aber Gesamtband-Download gesperrt.

    Belegt am 2026-07-29 (HTTP 403, „Page Blocked", Cloudflare Ray ID
    a22b480dee5ec7bc) — siehe ``evals/free-archive-fetchers/live-verification.json``.
    Der Agent darf daraus weder ``success`` noch ein stilles ``metadata_only``
    machen: die Zugriffsstufe ist Vollansicht, blockiert ist der Massen-Download.
    """

    def test_block_page_yields_pickup_required_with_named_reason(self, tmp_path):
        routes = {
            "/cgi/pt": (HTML_TYPE, _fixture("hathitrust_full_view.html").encode("utf-8")),
            "/cgi/imgsrv/download/pdf": (
                HTML_TYPE,
                _fixture("hathitrust_bulk_blocked.html").encode("utf-8"),
            ),
        }
        target = str(tmp_path / "kant.pdf")
        with LocalOrigin(routes) as origin:
            nav = ArchiveFetcherNavigator(
                "hathitrust",
                pages=origin.page_transport(),
                downloads=lambda url: pytest.fail(f"Kein Download erlaubt, versucht: {url}"),
                downloads_dir=str(tmp_path / "downloads"),
            )
            result = nav.fetch(origin.url("/cgi/pt?id=hvd.hntupx&seq=5"), target)

        assert result["status"] == "pickup_required", result
        assert result["reason"] == HATHITRUST_BULK_BLOCK_REASON
        assert "pdf_path" not in result
        assert not os.path.exists(target)


# ─── Die Verifikation muss auch wirklich aussortieren ────────────────────────


class TestDownloadVerificationRejectsNonPdf:
    def test_html_error_page_instead_of_pdf_is_not_success(self, tmp_path):
        routes = {
            "/details/x": (HTML_TYPE, _fixture("internetarchive_public_domain.html").encode()),
            "/download/onoriginofspecie1859darw/onoriginofspecie1859darw.pdf": (
                PDF_TYPE,
                b"<html><body>503 Service Unavailable</body></html>",
            ),
        }
        target = str(tmp_path / "out.pdf")
        with LocalOrigin(routes) as origin:
            nav = ArchiveFetcherNavigator(
                "internetarchive",
                pages=origin.page_transport(),
                downloads=origin.asset_transport(),
                downloads_dir=str(tmp_path / "downloads"),
            )
            result = nav.fetch(origin.url("/details/x"), target)

        assert result["status"] == "pickup_required", result
        assert not os.path.exists(target), "Halbes Artefakt darf nicht liegen bleiben"

    def test_pdf_below_size_floor_is_not_success(self, tmp_path):
        with open(PDF_SOURCE, "rb") as fh:
            too_small = fh.read()
        assert len(too_small) < MIN_PDF_BYTES
        routes = {
            "/details/x": (HTML_TYPE, _fixture("internetarchive_public_domain.html").encode()),
            "/download/onoriginofspecie1859darw/onoriginofspecie1859darw.pdf": (
                PDF_TYPE,
                too_small,
            ),
        }
        target = str(tmp_path / "out.pdf")
        with LocalOrigin(routes) as origin:
            nav = ArchiveFetcherNavigator(
                "internetarchive",
                pages=origin.page_transport(),
                downloads=origin.asset_transport(),
                downloads_dir=str(tmp_path / "downloads"),
            )
            result = nav.fetch(origin.url("/details/x"), target)

        assert result["status"] == "pickup_required", result
        assert not os.path.exists(target)


class TestMdzRightsAcknowledgmentIsLoadBearing:
    """Ohne ``xdfz=2`` liefert MDZ nur wieder die Zwischenseite — nie das PDF."""

    def test_without_rights_acceptance_no_pdf_link_appears(self, tmp_path, pdf_bytes):
        routes = dict(_mdz_routes(pdf_bytes))
        # Weiche entschaerft: die Zwischenseite antwortet immer mit dem Formular,
        # egal was gesendet wird. Genau dieser Zustand entsteht, wenn die
        # Vorbelegung "Nein" stehen bleibt.
        routes["/BOOKS/download.pl"] = (
            HTML_TYPE,
            _fixture("mdz_rights_form.html").encode("utf-8"),
        )
        target = str(tmp_path / "faust.pdf")
        with LocalOrigin(routes) as origin:
            nav = ArchiveFetcherNavigator(
                "mdz",
                pages=origin.page_transport(),
                downloads=origin.asset_transport(),
                downloads_dir=str(tmp_path / "downloads"),
            )
            result = nav.fetch(origin.url("/de/view/bsb10109182"), target)

        assert result["status"] == "pickup_required", result
        assert not os.path.exists(target)
