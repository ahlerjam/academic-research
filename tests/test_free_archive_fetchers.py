"""Site-Config-, Schema- und Eval-Pruefung fuer die freien Archive
(Issue #450: HathiTrust, Internet Archive/Open Library, MDZ).

Seit Issue #840 hat keines der drei Archive einen eigenen Agenten mehr: sie
laufen ueber den Ultimate Fetcher ``agents/generic-fetcher.md`` mit einer
Site-Config unter ``config/browser_guides/``. Alle Regeln, die #450 real
erkauft hat (Zugriffsstufen, Rate-Limit-Diagnose, Rechtehinweis-Gate,
``edition``-Bindung ans Digitalisat), werden deshalb jetzt dort geprueft —
inhaltlich unveraendert, nur an ihrem neuen Ort.
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
GUIDES_DIR = REPO_ROOT / "config" / "browser_guides"
ULTIMATE_FETCHER = AGENTS_DIR / "generic-fetcher.md"
EVALS_PATH = REPO_ROOT / "evals" / "free-archive-fetchers" / "evals.json"

#: Site-Schluessel -> Site-Config der drei freien Archive.
ARCHIVE_GUIDES = {
    "hathitrust": "hathitrust.md",
    "internetarchive": "internetarchive.md",
    "mdz": "mdz.md",
}

VALID_STATUSES = {"success", "pickup_required", "captcha", "no_match", "metadata_only"}

# Festes Access-Level-Vokabular (AC2): metadata_only-reason muss den Begriff
# "Zugriffsstufe" tragen -- kein neuer Status-Wert, das 5er-Enum bleibt fix.
ACCESS_LEVEL_MARKER = "Zugriffsstufe"


def _guide(site: str) -> str:
    return (GUIDES_DIR / ARCHIVE_GUIDES[site]).read_text(encoding="utf-8")


# ─── Klasse 1: Site-Configs existieren und sind fahrbar ──────────────────────


class TestArchiveGuides:
    @pytest.mark.parametrize("site, guide_name", sorted(ARCHIVE_GUIDES.items()))
    def test_browser_guide_file_exists(self, site, guide_name):
        path = GUIDES_DIR / guide_name
        assert path.exists(), f"Site-Config fehlt: {path}"

    @pytest.mark.parametrize("site", sorted(ARCHIVE_GUIDES))
    def test_guide_drives_browser_use(self, site):
        assert "browser-use" in _guide(site), (
            f"config/browser_guides/{ARCHIVE_GUIDES[site]} nennt browser-use nicht"
        )

    @pytest.mark.parametrize("site", sorted(ARCHIVE_GUIDES))
    def test_guide_has_no_direct_http_calls(self, site):
        offenders = re.findall(r"^\s*`?(curl|wget)\b", _guide(site), re.MULTILINE)
        assert not offenders, (
            f"config/browser_guides/{ARCHIVE_GUIDES[site]} beschreibt direkte "
            f"HTTP-Calls: {offenders}"
        )

    def test_book_fetcher_dispatches_every_archive_via_site_config(self):
        """AC3 (#840): die drei Archive haengen als Site-Config in der freien
        Stufe des Masters, nicht mehr als eigene Agenten."""
        text = (AGENTS_DIR / "book-fetcher.md").read_text(encoding="utf-8")
        step3 = text.split("## Schritt 3", 1)[1].split("\n## Schritt 4", 1)[0]
        for guide_name in ARCHIVE_GUIDES.values():
            assert f"config/browser_guides/{guide_name}" in step3, (
                f"{guide_name} fehlt in der freien Stufe von agents/book-fetcher.md"
            )


# ─── Klasse 2: Output-Schema-Validierung ─────────────────────────────────────


class TestOutputSchema:
    """Prueft das gesperrte Output-Schema (5 Status-Werte) und die
    #450-spezifischen Felder, jetzt am Ultimate Fetcher."""

    def _validate_output(self, obj: dict, context: str = ""):
        assert "status" in obj, f"{context}: 'status'-Feld fehlt"
        assert obj["status"] in VALID_STATUSES, (
            f"{context}: status='{obj['status']}' ist kein gueltiger Wert. "
            f"Erlaubt: {VALID_STATUSES}"
        )
        assert obj.get("source") == "generic-fetcher", f"{context}: 'source'-Feld falsch/fehlt"
        assert obj.get("site") in ARCHIVE_GUIDES, f"{context}: 'site'-Feld falsch/fehlt"

    def test_success_output_carries_file_path_and_edition(self):
        """AC4: Ausgabe-/Jahresangabe des Digitalisats, nicht des Originals.
        Geprueft wird der Erfolgs-Block des Ultimate Fetchers selbst — loescht
        man `edition` daraus, muss dieser Test rot werden."""
        content = ULTIMATE_FETCHER.read_text(encoding="utf-8")
        success_block_match = re.search(r'\{\s*"status": "success".*?\n\}', content, re.DOTALL)
        assert success_block_match, (
            "generic-fetcher.md: kein success-Output-Block im Output-Schema gefunden"
        )
        success_block = success_block_match.group(0)
        assert '"file_path"' in success_block, "success-Block ohne file_path-Feld"
        assert '"edition"' in success_block, "success-Block ohne edition-Feld (AC4)"

    @pytest.mark.parametrize("site", sorted(ARCHIVE_GUIDES))
    def test_metadata_only_uses_access_level_vocabulary(self, site):
        """AC2: metadata_only-reason muss 'Zugriffsstufe: ...' tragen."""
        text = _guide(site)
        assert "metadata_only" in text, f"{site}: kein metadata_only-Status dokumentiert"
        assert f"{ACCESS_LEVEL_MARKER}:" in text, (
            f"{site}: kein reason mit dem Access-Level-Vokabular "
            f"'{ACCESS_LEVEL_MARKER}: ...' in der Site-Config (AC2)"
        )

    def test_ultimate_fetcher_knows_the_access_level_vocabulary(self):
        content = ULTIMATE_FETCHER.read_text(encoding="utf-8")
        assert "metadata_only" in content
        assert f"{ACCESS_LEVEL_MARKER}:" in content, (
            "generic-fetcher.md kennt das Access-Level-Vokabular nicht — ohne es "
            "faellt die Verlags-Stufe des Masters lautlos aus"
        )

    @pytest.mark.parametrize("site", sorted(ARCHIVE_GUIDES))
    def test_rate_limit_is_diagnosed_not_no_match(self, site):
        """Rate-Limit (HTTP 429) muss als metadata_only mit Statuscode + Retry-
        Hinweis gemeldet werden, nicht als no_match fehlgedeutet."""
        text = _guide(site)
        assert "429" in text, f"{site}: keine HTTP-429-Regel in der Site-Config"
        # Mindestens eine 429-Stelle muss die Fehldeutung als no_match ausschliessen
        # (429 kommt auch beschreibend im Kopf der Guides vor).
        contexts = re.findall(r"^.*429.*\n(?:.*\n){0,3}", text, re.MULTILINE)
        assert any("no_match" in ctx for ctx in contexts), (
            f"{site}: die 429-Regel grenzt sich nicht explizit gegen no_match ab"
        )
        assert "retry" in text.lower() or "wartezeit" in text.lower(), (
            f"{site}: kein Retry-/Wartezeit-Hinweis fuer den 429-Fall"
        )

    def test_captcha_output(self):
        self._validate_output(
            {
                "status": "captcha",
                "source": "generic-fetcher",
                "site": "mdz",
                "reason": "CAPTCHA auf Seite erkannt",
            },
            "captcha",
        )

    def test_no_match_output(self):
        self._validate_output(
            {
                "status": "no_match",
                "source": "generic-fetcher",
                "site": "hathitrust",
                "reason": "0 Treffer fuer ISBN 000-0-0000-0000-0",
            },
            "no_match",
        )

    def test_all_five_statuses_are_defined(self):
        expected = {"success", "pickup_required", "captcha", "no_match", "metadata_only"}
        assert VALID_STATUSES == expected, (
            f"VALID_STATUSES stimmt nicht: {VALID_STATUSES} vs {expected}"
        )


# ─── Klasse 3: Verbots-Check ─────────────────────────────────────────────────


class TestForbiddenPatterns:
    """Die Verbote der drei Agenten leben jetzt im Ultimate Fetcher."""

    def test_ultimate_fetcher_has_forbidden_section(self):
        content = ULTIMATE_FETCHER.read_text(encoding="utf-8")
        assert re.search(r"##\s*(Verbotene Aktionen|Verbote)", content), (
            "generic-fetcher.md hat keinen Verbote-Abschnitt"
        )

    def test_verbote_forbid_snippet_composition(self):
        """AC2: das Zusammensetzen von Snippet-/Suchtreffer-Text zu einem
        Volltext-Ersatz muss explizit untersagt bleiben."""
        content = ULTIMATE_FETCHER.read_text(encoding="utf-8")
        verbote_match = re.search(r"##\s*Verbotene Aktionen\n(.*)", content, re.DOTALL)
        assert verbote_match, "Kein 'Verbotene Aktionen'-Abschnitt in generic-fetcher.md"
        verbote_body = verbote_match.group(1).lower()
        forbids_composition = (
            "zusammensetz" in verbote_body
            or "snippet" in verbote_body
            or "screenshot" in verbote_body
        )
        assert forbids_composition, (
            "Der Verbote-Abschnitt untersagt das Zusammensetzen von Snippet-/"
            "Suchtreffer-Text zu Volltext nicht explizit (AC2)"
        )

    def test_no_curl_or_wget_in_ultimate_fetcher(self):
        content = ULTIMATE_FETCHER.read_text(encoding="utf-8")
        offenders = re.findall(r"^\s*`?(curl|wget)\b", content, re.MULTILINE)
        assert not offenders, f"Direkter HTTP-Call in generic-fetcher.md: {offenders}"


# ─── Klasse 4: Ausgabe-/Jahresangabe (AC4) ──────────────────────────────────


class TestEditionField:
    """AC4: korrekte Ausgabe-/Jahresangabe des Digitalisats, nicht des Originals."""

    def test_ultimate_fetcher_documents_edition_field(self):
        content = ULTIMATE_FETCHER.read_text(encoding="utf-8")
        assert '"edition"' in content, "Kein 'edition'-Feld im Output-Schema von generic-fetcher.md"

    def test_ultimate_fetcher_forbids_copying_the_input_edition(self):
        content = ULTIMATE_FETCHER.read_text(encoding="utf-8")
        assert "NIE" in content or "NIEMALS" in content, (
            "generic-fetcher.md verbietet die Uebernahme der Eingabe-Ausgabe nicht explizit"
        )
        assert "Eingabe-ISBN" in content or "Eingabe-Titel" in content, (
            "generic-fetcher.md referenziert die Eingabe-ISBN/-Titel im Edition-Kontext nicht"
        )

    @pytest.mark.parametrize("site", sorted(ARCHIVE_GUIDES))
    def test_guide_names_the_authoritative_edition_source(self, site):
        text = _guide(site)
        assert "Ausgabe-/Jahresangabe" in text, (
            f"config/browser_guides/{ARCHIVE_GUIDES[site]} nennt die massgebliche "
            "Quelle der Ausgabe-/Jahresangabe nicht"
        )


# ─── Klasse 5: Eval-Cases ────────────────────────────────────────────────────


class TestEvalCases:
    def test_evals_file_exists(self):
        assert EVALS_PATH.exists(), f"Eval-Datei fehlt: {EVALS_PATH}"

    def test_evals_is_valid_json(self):
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, list), "evals.json muss ein JSON-Array sein"

    def test_evals_has_three_cases(self):
        """evals.json muss genau 3 Cases haben (je 1 pro Archiv)."""
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        assert len(data) == 3, f"Erwartet 3 Eval-Cases, gefunden: {len(data)}"

    def test_each_eval_has_required_fields(self):
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        for case in data:
            assert "id" in case, f"id fehlt in Case: {case}"
            assert "description" in case, f"description fehlt in Case {case['id']}"
            assert "expected" in case, f"expected fehlt in Case {case['id']}"
            assert case.get("agent") == "generic-fetcher", (
                f"Case {case['id']}: die freien Archive laufen seit #840 ueber "
                f"den Ultimate Fetcher, agent='{case.get('agent')}'"
            )
            assert case.get("site") in ARCHIVE_GUIDES, (
                f"Case {case['id']}: unbekannte site={case.get('site')!r}"
            )
            guide = case.get("site_config", "")
            assert (REPO_ROOT / guide).exists() if guide else False, (
                f"Case {case['id']}: site_config fehlt oder zeigt ins Leere: {guide!r}"
            )

    def test_one_eval_per_archive(self):
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        assert {c["site"] for c in data} == set(ARCHIVE_GUIDES), (
            "Nicht jedes Archiv hat einen Eval-Case"
        )

    def test_eval_cases_reference_known_public_domain_titles(self):
        """AC1: jeder Case referenziert einen konkreten, bekannten gemeinfreien
        Testtitel (nicht-leerer input.title)."""
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        for case in data:
            input_ = case.get("input", {})
            assert input_.get("title"), f"Case {case['id']}: kein Testtitel in input.title"


# ─── Klasse 6: Zugriffshindernisse, die der Live-Lauf gefunden hat ───────────


class TestLiveObservedAccessBarriers:
    """Jede Regel hier stammt aus einem realen Abruf, nicht aus einer Annahme.

    Der Live-Lauf zu #450 AC1 (dokumentiert in
    ``evals/free-archive-fetchers/live-verification.json``) hat drei Hindernisse
    gefunden, die unter keine der urspruenglichen Regeln fielen. Sie sind mit
    der Konsolidierung (#840) in die Site-Configs gewandert und muessen dort
    vollstaendig stehen — sonst haette ein Agent, der auf sie stoesst, keinen
    zutreffenden Status zu melden.

    Der Gegentest zu jeder Regel steht in ``tests/test_issue_450_live_fetch.py``
    und faehrt gegen das echte Netz.
    """

    def test_hathitrust_maps_the_platform_block(self):
        """HTTP 403 Sperrseite — weder CAPTCHA noch Rate-Limit."""
        text = _guide("hathitrust")
        assert "403" in text, (
            "config/browser_guides/hathitrust.md nennt HTTP 403 nicht. Die "
            "Sperrseite ist der real gemessene Ausgang des Download-Endpunkts."
        )
        assert ACCESS_LEVEL_MARKER in text, (
            "Fuer den 403-Fall fehlt eine Zuordnung zu einer Zugriffsstufe."
        )

    def test_hathitrust_forbids_reporting_the_block_as_captcha(self):
        text = _guide("hathitrust").lower()
        assert "kein** `captcha`" in text or "kein captcha" in text, (
            "config/browser_guides/hathitrust.md unterscheidet die Sperrseite "
            "nicht vom CAPTCHA-Fall. Beide sehen im Browser aehnlich aus, "
            "verlangen aber unterschiedliche Meldungen."
        )

    def test_internetarchive_maps_http_401_and_403_on_restricted_items(self):
        """Der reale Fehlerpfad bei Controlled Digital Lending — archive.org hat
        den Statuscode einmal von 401 auf 403 gewechselt (Issue #799)."""
        text = _guide("internetarchive")
        for code in ("401", "403"):
            assert code in text, (
                f"config/browser_guides/internetarchive.md nennt HTTP {code} nicht — "
                "beide sind derselbe real gemessene Ausgang bei einem gesperrten Item."
            )

    def test_internetarchive_names_the_machine_readable_restriction_signal(self):
        """``access-restricted-item`` unterscheidet frei von CDL zuverlaessig.

        Der Borrow-Button ist ein Layout-Merkmal; das Metadatenfeld ist die
        Eigenschaft selbst.
        """
        assert "access-restricted-item" in _guide("internetarchive"), (
            "config/browser_guides/internetarchive.md nennt das Metadatenfeld "
            "nicht, an dem sich frei herunterladbare von CDL-Items unterscheiden."
        )

    def test_mdz_guide_documents_the_mandatory_rights_statement_confirmation(self):
        """Ohne Bestaetigung des Rechtehinweises liefert MDZ kein PDF: HTTP 200,
        wieder das Formular, kein Fehlerstatus — der Schritt scheitert lautlos."""
        assert "Rechtehinweis" in _guide("mdz"), (
            "config/browser_guides/mdz.md beschreibt den Download-Weg ohne die "
            "Pflicht-Bestaetigung — die Anleitung fuehrt so ins Leere."
        )
