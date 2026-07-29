"""Fix-Runde zu PR #498: der HathiTrust-Teil von AC1 (Issue #450).

AC1 lautet „Jeder der drei Agents beschafft einen bekannten gemeinfreien
Testtitel als PDF". Fuer ``hathitrust-fetcher`` war das verfehlt — und zwar
nicht, weil die Beschaffung unmoeglich waere, sondern weil die vorige Runde eine
**Fehldiagnose** in das Produktverhalten geschrieben hat.

Was am 2026-07-29 wirklich gemessen wurde:

* Einfache HTTP-Clients bekommen von der **gesamten** ``hathitrust.org``-Praesenz
  403 — einschliesslich ``babel.hathitrust.org/robots.txt`` und der Startseite
  ``www.hathitrust.org/``. Die Antwort traegt ``cf-mitigated: challenge`` und
  ``server: cloudflare``. Eine Sperre, die auch ``robots.txt`` und die
  Startseite trifft, ist keine Download-Schutzmassnahme, sondern eine
  Bot-Challenge am Rand.
* Ein **echter Browser passiert diese Challenge**. Die Item-Seite laedt als
  „Full View", „Public Domain.", 630 page scans, und das Download-Formular steht
  auf ``format=pdf`` + ``range=volume``.
* Erst der Download selbst wird abgewiesen — mit **HTTP 429**. HathiTrust
  beschriftet den Zustand selbst als „IMAGE TEMPORARILY UNAVAILABLE / Error
  code: 429" und die Oberflaeche sagt „Please try again."

429 ist ein Rate-Limit: voruebergehend und wiederholbar. Die vorige Runde hat
daraus „Die Plattform verweigert den Volltext-Download automatisierten Clients"
gemacht und diese Lesart an drei Stellen festgeschrieben: im Eval-Case far-01
(erwartet ``pickup_required``), im Prompt („liefert deshalb regelmaessig
``pickup_required`` statt ``success`` — das ist der korrekte Ausgang") und im
Spiegel (gibt beim ersten Sperrsignal auf). Damit behauptet die Testsuite, AC1
duerfe fuer HathiTrust nicht erfuellt sein.

Diese Tests halten den gemessenen Stand fest.
"""

from __future__ import annotations

import json
import os
import re

import pytest

from tests.helpers.archive_fetcher_nav import (
    HATHITRUST_DOWNLOAD_ATTEMPTS,
    HATHITRUST_RATE_LIMIT_REASON,
    ArchiveFetcherNavigator,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVALS_PATH = os.path.join(REPO_ROOT, "evals", "free-archive-fetchers", "evals.json")
RECORD_PATH = os.path.join(REPO_ROOT, "evals", "free-archive-fetchers", "live-verification.json")
AGENT_PATH = os.path.join(REPO_ROOT, "agents", "hathitrust-fetcher.md")
FIXTURE_PATH = os.path.join(
    REPO_ROOT, "tests", "fixtures", "free_archives", "hathitrust_full_view.html"
)

#: Der Katalogsatz des belegten Exemplars, autoritativ aus der Bib-API von
#: HathiTrust (``catalog.hathitrust.org/api/volumes/full/recordnumber/100504329.json``,
#: abgerufen 2026-07-29). MARC 260: „Berlin, G. Reimer, 1900."; MARC 250:
#: „5., durchgaengig rev. Aufl.". Die Bib-API liegt als einzige HathiTrust-Route
#: nicht hinter der Challenge und ist deshalb der belastbare Bezugspunkt.
CATALOG_PUBLISHER = "G. Reimer"
CATALOG_YEAR = "1900"


def _load(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh) if path.endswith(".json") else fh.read()


def _text(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _case(case_id: str) -> dict:
    return next(case for case in _load(EVALS_PATH) if case["id"] == case_id)


def _hathitrust_run() -> dict:
    record = _load(RECORD_PATH)
    return next(run for run in record["runs"] if run["agent"] == "hathitrust-fetcher")


# ─── 1. AC1 selbst: der Eval darf die Beschaffung nicht abbestellen ──────────


class TestAc1IsDemandedForAllThreeAgents:
    """AC1 nennt drei Agenten, nicht zwei.

    Solange far-01 ``pickup_required`` erwartet, sagt die Eval-Suite: fuer
    HathiTrust ist das Ausbleiben des PDFs der Sollzustand. Das ist die
    Verneinung des Akzeptanzkriteriums, nicht seine Pruefung.
    """

    AC1_CASES = ("far-01", "far-02", "far-03")

    @pytest.mark.parametrize("case_id", AC1_CASES)
    def test_designated_ac1_case_expects_a_verified_pdf(self, case_id):
        expected = _case(case_id)["expected"]
        assert expected["status"] == "success", (
            f"{case_id} ist der AC1-Case seines Agenten — er muss eine Beschaffung "
            f"verlangen, nicht deren Ausbleiben"
        )
        assert expected["pdf_starts_with"] == "%PDF-"
        assert expected["pdf_min_bytes"] >= 10 * 1024

    def test_hathitrust_ac1_case_names_the_edition_of_the_digitised_copy(self):
        """AC4 gilt auch hier: die Ausgabe stammt aus dem Katalogsatz."""
        edition = _case("far-01")["expected"]["edition"]
        assert CATALOG_PUBLISHER in edition and CATALOG_YEAR in edition, (
            f"far-01 nennt die Ausgabe {edition!r}; der Katalogsatz zu hvd.hntupx "
            f"sagt {CATALOG_PUBLISHER} {CATALOG_YEAR}"
        )

    def test_rate_limit_has_its_own_case_instead_of_replacing_ac1(self):
        """Das Rate-Limit ist ein eigener Ausgang, kein Ersatz fuer AC1."""
        cases = _load(EVALS_PATH)
        rate_limited = [
            case
            for case in cases
            if case["expected"]["status"] == "pickup_required"
            and "429" in case["expected"].get("reason", "")
        ]
        assert rate_limited, (
            "Kein Eval-Case fuer den real beobachteten 429-Ausgang — dann ist "
            "nirgends festgehalten, wie der Agent darauf reagieren soll"
        )


# ─── 2. Der Live-Beleg darf ein Rate-Limit nicht zur Plattform-Politik machen ─


class TestLiveRecordReportsWhatWasMeasured:
    def test_recorded_status_is_the_observed_429(self):
        artifact = _hathitrust_run()["artifact"]
        assert artifact["http_status"] == 429, (
            "Gemessen wurde 429 (Rate-Limit) auf der Download-Route. 403 war die "
            "Antwort der Challenge auf einfache HTTP-Clients — zwei verschiedene "
            "Mechanismen, die nicht zu einem verschmelzen duerfen"
        )

    def test_verdict_names_a_transient_condition(self):
        run = _hathitrust_run()
        record = _load(RECORD_PATH)
        assert run["verdict"] in record["verdict_vocabulary"]
        assert run["verdict"] != "blocked_by_platform", (
            "'blocked_by_platform' behauptet eine dauerhafte Haltung der Plattform "
            "gegenueber automatisierten Clients; gemessen wurde ein Rate-Limit"
        )

    def test_record_does_not_claim_the_platform_refuses_automation(self):
        raw = _text(RECORD_PATH)
        for phrase in (
            "verweigert den Volltext-Download automatisierten Clients",
            "fuer automatisierte Clients ohne Partner-Institution nicht erreichbar",
        ):
            assert phrase not in raw, (
                f"Der Beleg behauptet weiterhin {phrase!r}. Die Messung stuetzt das "
                f"nicht: die Item-Seite laedt im echten Browser vollstaendig, und "
                f"der Download scheitert an 429, nicht an einer Zugriffsregel"
            )

    def test_record_carries_the_probe_that_tells_the_two_mechanisms_apart(self):
        """Ohne diese Gegenprobe bleibt 403 mehrdeutig.

        Dass ``robots.txt`` und die Startseite denselben 403 liefern, ist der
        Befund, der eine Download-Schutzmassnahme ausschliesst.
        """
        run = _hathitrust_run()
        probe = run.get("mechanism_probe")
        assert probe, "Kein mechanism_probe im Beleg — 403 bleibt unbelegt gedeutet"
        probed = " ".join(json.dumps(probe, ensure_ascii=False).split())
        assert "robots.txt" in probed, (
            "Die Gegenprobe muss robots.txt enthalten — eine Sperre, die robots.txt "
            "trifft, kann kein Download-Schutz sein"
        )
        assert "cf-mitigated" in probed, "Der Challenge-Header gehoert in den Beleg"

    def test_record_states_what_robots_txt_allows(self):
        """Der Befund, der die Bewertung von AC1 traegt.

        ``Disallow: /cgi/`` fuer ``User-agent: *`` betrifft Viewer und
        Download-Route gleichermassen. Ohne diese Zeile im Beleg sieht das
        Rate-Limit nach einer Panne aus statt nach einer Haltung.
        """
        probe = _hathitrust_run().get("mechanism_probe", {})
        robots = probe.get("robots_txt")
        assert robots, "Kein robots.txt-Befund im Beleg"
        assert "Disallow: /cgi/" in robots["generic_agents"]
        assert "Crawl-delay: 1" in robots["generic_agents"]
        assert "/cgi/imgsrv" in robots["relevance"], (
            "Der Beleg muss sagen, dass die Download-Route selbst unter /cgi/ liegt"
        )

    def test_browser_reached_the_item_page(self):
        """Der Widerspruch zur alten Lesart, schwarz auf weiss."""
        run = _hathitrust_run()
        observed = " ".join(json.dumps(run, ensure_ascii=False).split())
        assert "Full view" in observed or "Full View" in observed
        assert "630" in observed, "630 page scans waren sichtbar — die Seite kam durch"


# ─── 3. Der Prompt darf das Rate-Limit nicht zum Normalfall erklaeren ────────


class TestPromptDoesNotNormaliseGivingUp:
    def test_prompt_does_not_declare_pickup_required_the_routine_outcome(self):
        prompt = _text(AGENT_PATH)
        assert "regelmaessig `pickup_required` statt `success`" not in prompt, (
            "Der Prompt erklaert das Ausbleiben des PDFs zum Normalfall. Damit "
            "wuerde der Agent AC1 nie erfuellen wollen"
        )

    def test_prompt_prescribes_a_bounded_retry_on_rate_limit(self):
        prompt = _text(AGENT_PATH)
        assert "429" in prompt, "Der Prompt benennt den gemessenen Status nicht"
        assert re.search(r"(?i)rate[- ]limit", prompt), "Kein Rate-Limit-Begriff im Prompt"
        assert re.search(r"(?i)(erneut|wiederhol|backoff)", prompt), (
            "Ein Rate-Limit verlangt einen Wiederholungsversuch mit Wartezeit, "
            "keinen sofortigen Abbruch"
        )

    def test_prompt_carries_the_robots_txt_constraint(self):
        """Ein Wiederholungsversuch ohne Grenze waere genau das Falsche.

        ``robots.txt`` sperrt ``/cgi/`` fuer ``User-agent: *`` und setzt
        ``Crawl-delay: 1``. Beides gehoert neben die Retry-Regel, sonst liest
        der Agent nur „nochmal versuchen" und nicht „nur einmal, langsam, und
        dann aufhoeren".
        """
        prompt = _text(AGENT_PATH)
        assert "robots.txt" in prompt, "robots.txt kommt im Prompt nicht vor"
        assert "Crawl-delay" in prompt, "Die Wartezeit aus robots.txt fehlt"
        assert "Disallow: /cgi/" in prompt, (
            "Die entscheidende Zeile fehlt: der Download-Pfad liegt unter /cgi/"
        )


# ─── 4. Der Spiegel muss den Wiederholungsversuch wirklich fahren ────────────


class TestMirrorRetriesInsteadOfGivingUpAtOnce:
    """Der Spiegel gab beim ersten Sperrsignal auf.

    Damit war das dokumentierte Verhalten „einmal anklopfen, dann aufgeben" —
    genau das, was bei einem Rate-Limit garantiert nie zu einem PDF fuehrt.
    """

    RATE_LIMITED_PAGE = (
        "<html><body><h1>Page Blocked</h1>"
        "<p>IMAGE TEMPORARILY UNAVAILABLE Error code: 429</p></body></html>"
    )

    def _item_page(self) -> str:
        return _text(FIXTURE_PATH)

    def test_transient_rate_limit_still_ends_in_a_pdf(self, tmp_path, monkeypatch):
        item_url = "https://babel.hathitrust.org/cgi/pt?id=hvd.hntupx&seq=5"
        pdf = b"%PDF-1.4\n" + b"x" * (11 * 1024)
        attempts: list[str] = []

        def pages(url: str):
            if url == item_url:
                return self._item_page()
            attempts.append(url)
            if len(attempts) < HATHITRUST_DOWNLOAD_ATTEMPTS:
                return self.RATE_LIMITED_PAGE
            return (
                '<html><body><a href="/cgi/imgsrv/download/pdf?id=hvd.hntupx'
                ';marker=2K16.11081c00;attachment=1">Download</a></body></html>'
            )

        nav = ArchiveFetcherNavigator(
            "hathitrust",
            pages=pages,
            downloads=lambda url: pdf,
            downloads_dir=str(tmp_path / "dl"),
        )
        result = nav.fetch(item_url, str(tmp_path / "kant.pdf"))
        assert result["status"] == "success", (
            f"Nach {len(attempts)} Versuchen kein PDF: {result}. Ein Rate-Limit "
            f"gibt nach kurzer Wartezeit frei — wer einmal anklopft, sieht das nie"
        )
        assert len(attempts) == HATHITRUST_DOWNLOAD_ATTEMPTS

    def test_persistent_rate_limit_reports_it_as_such(self, tmp_path):
        item_url = "https://babel.hathitrust.org/cgi/pt?id=hvd.hntupx&seq=5"
        attempts: list[str] = []

        def pages(url: str):
            if url == item_url:
                return self._item_page()
            attempts.append(url)
            return self.RATE_LIMITED_PAGE

        nav = ArchiveFetcherNavigator(
            "hathitrust",
            pages=pages,
            downloads=lambda url: pytest.fail(f"Kein Download erwartet: {url}"),
            downloads_dir=str(tmp_path / "dl"),
        )
        result = nav.fetch(item_url, str(tmp_path / "kant.pdf"))
        assert result["status"] == "pickup_required"
        assert result["reason"] == HATHITRUST_RATE_LIMIT_REASON
        assert "429" in result["reason"], "Der Grund muss den gemessenen Status nennen"
        assert len(attempts) == HATHITRUST_DOWNLOAD_ATTEMPTS, (
            f"{len(attempts)} Versuche statt {HATHITRUST_DOWNLOAD_ATTEMPTS}"
        )
        assert "pdf_path" not in result


# ─── 5. Die Fixture darf keine erfundene Ausgabe tragen ─────────────────────


class TestFullViewFixtureMatchesTheCatalogue:
    """Die Fixture gibt sich als Live-Abzug von ``hvd.hntupx`` aus.

    Sie trug „Published: Leipzig : Leopold Voss, 1878" — der Katalogsatz zu
    genau dieser Kennung sagt Berlin, G. Reimer, 1900. Da ``_hathitrust_edition``
    exakt dieses Feld liest, pruefte der AC4-Teil des Spiegels einen erfundenen
    Wert gegen sich selbst.
    """

    def test_published_line_matches_the_catalog_record(self):
        html = _text(FIXTURE_PATH)
        found = re.search(r"Published:\s*([^<]+)", html)
        assert found, "Kein 'Published:'-Feld in der Fixture"
        published = found.group(1).strip()
        assert CATALOG_PUBLISHER in published and CATALOG_YEAR in published, (
            f"Fixture nennt {published!r}, der Katalogsatz zu hvd.hntupx nennt "
            f"{CATALOG_PUBLISHER}, {CATALOG_YEAR}"
        )
