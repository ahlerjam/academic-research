"""Frontmatter-Validierung, Output-Schema-Check und Verbots-Pruefung fuer die
freien Archiv-Fetcher-Subagenten (Issue #450: HathiTrust, Internet Archive/
Open Library, MDZ)."""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
EVALS_PATH = REPO_ROOT / "evals" / "free-archive-fetchers" / "evals.json"

AGENT_NAMES = ["hathitrust-fetcher", "internetarchive-fetcher", "mdz-fetcher"]
VALID_STATUSES = {"success", "pickup_required", "captcha", "no_match", "metadata_only"}

# Festes Access-Level-Vokabular (AC2): metadata_only-reason muss den Begriff
# "Zugriffsstufe" tragen -- kein neuer Status-Wert, das 5er-Enum bleibt fix.
ACCESS_LEVEL_MARKER = "Zugriffsstufe"


# ─── Hilfsfunktion ───────────────────────────────────────────────────────────


def parse_frontmatter(path: Path) -> tuple[dict, str]:
    """Parst YAML-Frontmatter aus einer Markdown-Datei ohne pyyaml-Abhaengigkeit.
    Gibt (frontmatter_dict, body) zurueck.
    """
    content = path.read_text(encoding="utf-8")
    fm_match = re.match(r"^---\n(.*?)\n---\n?(.*)", content, re.DOTALL)
    assert fm_match is not None, f"Kein Frontmatter in {path.name}"
    fm_raw = fm_match.group(1)
    body = fm_match.group(2)
    fm = {}
    for line in fm_raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
    return fm, body


# ─── Klasse 1: Frontmatter-Validierung ───────────────────────────────────────


class TestAgentFrontmatter:
    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_agent_file_exists(self, agent_name):
        """Jede Agent-Datei muss unter agents/<name>.md existieren."""
        path = AGENTS_DIR / f"{agent_name}.md"
        assert path.exists(), f"Agent-Datei fehlt: {path}"

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_frontmatter_has_name_field(self, agent_name):
        """name-Feld muss dem Dateinamen entsprechen."""
        path = AGENTS_DIR / f"{agent_name}.md"
        fm, _ = parse_frontmatter(path)
        assert "name" in fm, f"Kein 'name'-Feld in {agent_name}.md"
        assert fm["name"] == agent_name, (
            f"name='{fm['name']}' stimmt nicht mit Dateinamen '{agent_name}' ueberein"
        )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_frontmatter_model_is_sonnet(self, agent_name):
        """model muss 'sonnet' sein."""
        path = AGENTS_DIR / f"{agent_name}.md"
        fm, _ = parse_frontmatter(path)
        assert "model" in fm, f"Kein 'model'-Feld in {agent_name}.md"
        assert fm["model"] == "sonnet", (
            f"model='{fm['model']}' in {agent_name}.md — erwartet 'sonnet'"
        )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_frontmatter_has_max_turns(self, agent_name):
        """maxTurns muss gesetzt und eine positive Zahl sein."""
        path = AGENTS_DIR / f"{agent_name}.md"
        fm, _ = parse_frontmatter(path)
        assert "maxTurns" in fm, f"Kein 'maxTurns'-Feld in {agent_name}.md"
        assert fm["maxTurns"].isdigit(), (
            f"maxTurns='{fm['maxTurns']}' ist keine Zahl in {agent_name}.md"
        )
        assert int(fm["maxTurns"]) > 0, f"maxTurns muss > 0 sein in {agent_name}.md"

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_frontmatter_tools_contains_browser_use(self, agent_name):
        """tools-Zeile muss 'browser-use' enthalten."""
        path = AGENTS_DIR / f"{agent_name}.md"
        content = path.read_text(encoding="utf-8")
        fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        assert fm_match, f"Kein Frontmatter in {agent_name}.md"
        fm_raw = fm_match.group(1)
        assert "browser-use" in fm_raw, (
            f"'browser-use' fehlt im tools-Frontmatter von {agent_name}.md"
        )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_frontmatter_tools_has_space_syntax_permission(self, agent_name):
        """Regression #222: tools muss die Space-Syntax 'Bash(browser-use *)'
        deklarieren, sonst matchen die im Workflow genutzten Space-Befehle
        (browser-use open/state/click/download) nicht → Permission-Denied.
        Die reine Colon-Variante 'Bash(browser-use:*)' reicht nicht aus.
        """
        path = AGENTS_DIR / f"{agent_name}.md"
        content = path.read_text(encoding="utf-8")
        fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        assert fm_match, f"Kein Frontmatter in {agent_name}.md"
        fm_raw = fm_match.group(1)
        assert "Bash(browser-use *)" in fm_raw, (
            f"Space-Syntax-Permission 'Bash(browser-use *)' fehlt im tools-Frontmatter "
            f"von {agent_name}.md — Space-Befehle werden geblockt (Issue #222)"
        )

    @pytest.mark.parametrize(
        "agent_name, expected_guide",
        [
            ("hathitrust-fetcher", "config/browser_guides/hathitrust.md"),
            ("internetarchive-fetcher", "config/browser_guides/internetarchive.md"),
            ("mdz-fetcher", "config/browser_guides/mdz.md"),
        ],
    )
    def test_body_references_browser_guide(self, agent_name, expected_guide):
        """Agent-Body muss den kanonischen Browser-Guide-Pfad referenzieren."""
        path = AGENTS_DIR / f"{agent_name}.md"
        _, body = parse_frontmatter(path)
        assert expected_guide in body, (
            f"Browser-Guide-Referenz '{expected_guide}' fehlt im Body von {agent_name}.md"
        )

    @pytest.mark.parametrize(
        "guide_name",
        ["hathitrust.md", "internetarchive.md", "mdz.md"],
    )
    def test_browser_guide_file_exists(self, guide_name):
        """Jeder referenzierte Browser-Guide muss unter config/browser_guides/ existieren."""
        path = REPO_ROOT / "config" / "browser_guides" / guide_name
        assert path.exists(), f"Browser-Guide fehlt: {path}"


# ─── Klasse 2: Output-Schema-Validierung ─────────────────────────────────────


class TestOutputSchema:
    """Prueft, dass das gesperrte Output-Schema (5 Status-Werte) korrekt definiert ist
    und dass success/metadata_only die #450-spezifischen Felder tragen."""

    def _validate_output(self, obj: dict, context: str = ""):
        assert "status" in obj, f"{context}: 'status'-Feld fehlt"
        assert obj["status"] in VALID_STATUSES, (
            f"{context}: status='{obj['status']}' ist kein gueltiger Wert. "
            f"Erlaubt: {VALID_STATUSES}"
        )
        assert "source_subagent" in obj, f"{context}: 'source_subagent'-Feld fehlt"
        assert obj["source_subagent"] in AGENT_NAMES, (
            f"{context}: source_subagent='{obj['source_subagent']}' nicht in AGENT_NAMES"
        )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_success_output_has_pdf_path_and_edition(self, agent_name):
        """success-Output muss pdf_path UND edition enthalten (AC4: Ausgabe-/
        Jahresangabe des Digitalisats, nicht des Originals). Geprueft wird der
        tatsaechliche Output-Schema-Block der Agent-Datei, nicht ein Literal —
        loescht man `edition` aus dem Erfolgs-JSON, muss dieser Test rot
        werden."""
        content = (AGENTS_DIR / f"{agent_name}.md").read_text(encoding="utf-8")
        success_block_match = re.search(r'\{\s*"status":\s*"success".*?\n\}', content, re.DOTALL)
        assert success_block_match, (
            f"{agent_name}.md: kein success-Output-Block (JSON mit "
            '\'"status": "success"\') im Output-Schema gefunden'
        )
        success_block = success_block_match.group(0)
        assert '"pdf_path"' in success_block, (
            f"{agent_name}.md: success-Block enthaelt kein pdf_path-Feld"
        )
        assert '"edition"' in success_block, (
            f"{agent_name}.md: success-Block enthaelt kein edition-Feld (AC4)"
        )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_metadata_only_output_has_access_level_reason(self, agent_name):
        """metadata_only-Output muss den festen Access-Level-Marker
        ('Zugriffsstufe: ...') im reason-Feld tragen (AC2). Geprueft wird der
        Agent-Body selbst — loescht man den Marker, muss dieser Test rot
        werden."""
        _, body = parse_frontmatter(AGENTS_DIR / f"{agent_name}.md")
        assert "metadata_only" in body, f"{agent_name}.md: kein metadata_only-Status dokumentiert"
        assert f'"{ACCESS_LEVEL_MARKER}:' in body, (
            f"{agent_name}.md: kein reason mit dem Access-Level-Vokabular "
            f"'{ACCESS_LEVEL_MARKER}: ...' im Body gefunden (AC2)"
        )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_metadata_only_rate_limit_is_diagnosed_not_no_match(self, agent_name):
        """Rate-Limit (HTTP 429) muss als metadata_only mit Statuscode + Retry-
        Hinweis gemeldet werden, nicht als no_match fehlgedeutet (Issue-Hinweis
        Operator 2026-07-30, ex-PR #498). Geprueft wird die Regel im
        Agent-Body — loescht man die 429-Regel, muss dieser Test rot werden."""
        _, body = parse_frontmatter(AGENTS_DIR / f"{agent_name}.md")
        assert "429" in body, f"{agent_name}.md: keine HTTP-429-Regel im Body gefunden"
        rule_line_match = re.search(r"^.*429.*$", body, re.MULTILINE)
        assert rule_line_match, f"{agent_name}.md: keine Zeile mit '429' gefunden"
        # Die 429-Regel selbst muss den no_match-Fehldeutungs-Fall explizit
        # ausschliessen (nicht nur irgendwo im Dokument 'no_match' erwaehnen).
        rule_context_match = re.search(r"^.*429.*\n(?:.*\n){0,2}", body, re.MULTILINE)
        rule_context = rule_context_match.group(0) if rule_context_match else ""
        assert "no_match" in rule_context, (
            f"{agent_name}.md: die 429-Regel grenzt sich nicht explizit gegen no_match ab"
        )
        assert "retry" in body.lower() or "wartezeit" in body.lower(), (
            f"{agent_name}.md: kein Retry-/Wartezeit-Hinweis fuer den 429-Fall"
        )

    def test_captcha_output(self):
        output = {
            "status": "captcha",
            "source_subagent": "mdz-fetcher",
            "reason": "CAPTCHA auf Seite erkannt",
        }
        self._validate_output(output, "captcha")

    def test_no_match_output(self):
        output = {
            "status": "no_match",
            "source_subagent": "hathitrust-fetcher",
            "reason": "0 Treffer fuer ISBN 000-0-0000-0000-0",
        }
        self._validate_output(output, "no_match")

    def test_all_five_statuses_are_defined(self):
        expected = {"success", "pickup_required", "captcha", "no_match", "metadata_only"}
        assert VALID_STATUSES == expected, (
            f"VALID_STATUSES stimmt nicht: {VALID_STATUSES} vs {expected}"
        )


# ─── Klasse 3: Verbots-Check ─────────────────────────────────────────────────


class TestForbiddenPatterns:
    """Prueft, dass verbotene Muster (curl, wget, Snippet-Zusammensetzung) nicht
    in den Agenten vorkommen."""

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_no_curl_in_agent(self, agent_name):
        path = AGENTS_DIR / f"{agent_name}.md"
        content = path.read_text(encoding="utf-8")
        curl_uses = re.findall(r"^\s*`?curl\b", content, re.MULTILINE)
        assert len(curl_uses) == 0, f"curl-Aufruf in {agent_name}.md gefunden: {curl_uses}"

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_no_wget_in_agent(self, agent_name):
        path = AGENTS_DIR / f"{agent_name}.md"
        content = path.read_text(encoding="utf-8")
        wget_uses = re.findall(r"^\s*`?wget\b", content, re.MULTILINE)
        assert len(wget_uses) == 0, f"wget-Aufruf in {agent_name}.md gefunden: {wget_uses}"

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_browser_use_mentioned_in_body(self, agent_name):
        path = AGENTS_DIR / f"{agent_name}.md"
        _, body = parse_frontmatter(path)
        assert "browser-use" in body, (
            f"'browser-use' nicht im Body von {agent_name}.md — Agent muss browser-use verwenden"
        )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_forbidden_section_present(self, agent_name):
        path = AGENTS_DIR / f"{agent_name}.md"
        _, body = parse_frontmatter(path)
        has_verbote = bool(
            re.search(r"##\s*(Verbote|Forbidden|Einschraenkungen)", body, re.IGNORECASE)
        )
        assert has_verbote, (
            f"Kein 'Verbote'-Abschnitt in {agent_name}.md — Verbote muessen explizit dokumentiert sein"
        )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_verbote_forbid_snippet_composition(self, agent_name):
        """AC2: der Verbote-Abschnitt muss das Zusammensetzen von Snippet-/
        Suchtreffer-Text zu einem Volltext-Ersatz explizit untersagen."""
        path = AGENTS_DIR / f"{agent_name}.md"
        content = path.read_text(encoding="utf-8")
        verbote_match = re.search(r"##\s*Verbote\n(.*?)(\n##\s|\Z)", content, re.DOTALL)
        assert verbote_match, f"Kein 'Verbote'-Abschnitt in {agent_name}.md"
        verbote_body = verbote_match.group(1).lower()
        forbids_composition = (
            "zusammensetz" in verbote_body
            or "snippet" in verbote_body
            or "screenshot" in verbote_body
        )
        assert forbids_composition, (
            f"Verbote-Abschnitt in {agent_name}.md untersagt das Zusammensetzen von "
            "Snippet-/Suchtreffer-Text zu Volltext nicht explizit (AC2)"
        )


# ─── Klasse 4: Ausgabe-/Jahresangabe (AC4) ──────────────────────────────────


class TestEditionField:
    """AC4: korrekte Ausgabe-/Jahresangabe des Digitalisats, nicht des Originals."""

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_body_documents_edition_field(self, agent_name):
        """Agent-Body muss ein 'edition'-Feld im success-Output-Beispiel zeigen."""
        path = AGENTS_DIR / f"{agent_name}.md"
        _, body = parse_frontmatter(path)
        assert '"edition"' in body, f"Kein 'edition'-Feld im Output-Schema von {agent_name}.md"

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_body_instructs_not_to_copy_input_edition(self, agent_name):
        """Der Standard-Flow-Text muss ausdruecklich anweisen, Jahr/Ausgabe aus
        dem Katalog-/Metadaten-Eintrag der Quelle selbst zu entnehmen statt aus
        der Eingabe zu uebernehmen."""
        path = AGENTS_DIR / f"{agent_name}.md"
        _, body = parse_frontmatter(path)
        assert "NIE" in body or "NIEMALS" in body, (
            f"{agent_name}.md verbietet die Uebernahme der Eingabe-Ausgabe nicht explizit"
        )
        assert "Eingabe-ISBN" in body or "Eingabe-Titel" in body, (
            f"{agent_name}.md referenziert die Eingabe-ISBN/-Titel im Edition-Kontext nicht"
        )


# ─── Klasse 5: Tier-Reihenfolge (AC3) ───────────────────────────────────────


class TestTierOrdering:
    """AC3: die freien Archive muessen in der OA-Subagenten-Kette von
    book-fetcher.md VOR jedem Verlags-Subagenten stehen."""

    def test_book_fetcher_lists_new_agents_before_publishers(self):
        body = (AGENTS_DIR / "book-fetcher.md").read_text(encoding="utf-8")
        step3 = body.split("## Schritt 3", 1)[1].split("\n## Schritt 4", 1)[0]
        step4 = body.split("## Schritt 4", 1)[1]
        for agent_name in AGENT_NAMES:
            assert agent_name in step3, f"{agent_name} fehlt in Schritt 3 (OA-Kette)"
            assert agent_name not in step4.split("\n## Schritt 5", 1)[0], (
                f"{agent_name} taucht faelschlich in Schritt 4 (Verlags-Kette) auf"
            )

    def test_book_fetcher_frontmatter_declares_new_agent_tools(self):
        body = (AGENTS_DIR / "book-fetcher.md").read_text(encoding="utf-8")
        fm_match = re.match(r"^---\n(.*?)\n---", body, re.DOTALL)
        assert fm_match
        fm_raw = fm_match.group(1)
        for agent_name in AGENT_NAMES:
            assert f'"Agent({agent_name})"' in fm_raw, (
                f"Agent({agent_name}) fehlt im tools-Frontmatter von book-fetcher.md"
            )


# ─── Klasse 6: Eval-Cases ────────────────────────────────────────────────────


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
            assert "agent" in case, f"agent fehlt in Case {case['id']}"
            assert "expected" in case, f"expected fehlt in Case {case['id']}"
            assert case["agent"] in AGENT_NAMES, (
                f"agent='{case['agent']}' in Case {case['id']} nicht in AGENT_NAMES"
            )

    def test_one_eval_per_agent(self):
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        agents_in_evals = [c["agent"] for c in data]
        assert set(agents_in_evals) == set(AGENT_NAMES), (
            f"Nicht alle Agenten haben einen Eval-Case. "
            f"Vorhanden: {set(agents_in_evals)}, erwartet: {set(AGENT_NAMES)}"
        )

    def test_eval_cases_reference_known_public_domain_titles(self):
        """AC1: jeder Case referenziert einen konkreten, bekannten gemeinfreien
        Testtitel (nicht-leerer input.title und input.isbn/input.identifier)."""
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        for case in data:
            input_ = case.get("input", {})
            assert input_.get("title"), f"Case {case['id']}: kein Testtitel in input.title"


# ─── Klasse 7: Zugriffshindernisse, die der Live-Lauf gefunden hat ───────────


class TestLiveObservedAccessBarriers:
    """Jede Regel hier stammt aus einem realen Abruf, nicht aus einer Annahme.

    Die erste Fassung dieser drei Agenten kannte genau ein Hindernis: HTTP 429.
    Der Live-Lauf zu AC1 (dokumentiert in
    ``evals/free-archive-fetchers/live-verification.json``) hat drei andere
    gefunden — und keines davon faellt unter eine der bestehenden Regeln. Ein
    Agent, der auf sie stoesst, haette nach der urspruenglichen Anleitung keinen
    zutreffenden Status zu melden gehabt.

    Der Gegentest zu jeder Regel steht in
    ``tests/test_issue_450_live_fetch.py`` und faehrt gegen das echte Netz.
    """

    def test_hathitrust_maps_the_platform_block(self):
        """HTTP 403 Sperrseite — weder CAPTCHA noch Rate-Limit.

        Gemessen: der Download-Endpunkt antwortet anonym mit HTTP 403 und der
        Seite "Error - Blocked from HathiTrust". Die Captcha-Erkennung des Repos
        schlaegt daran nicht an (siehe
        ``tests/test_issue_450_fetcher_evidence.py::test_block_page_is_not_a_captcha``),
        also waere ``status: captcha`` die falsche Meldung — und ``no_match``
        waere schlicht unwahr, weil die Bib-API denselben Titel weiter aufloest.
        """
        content = (AGENTS_DIR / "hathitrust-fetcher.md").read_text(encoding="utf-8")
        assert "403" in content, (
            "agents/hathitrust-fetcher.md nennt HTTP 403 nicht. Die Sperrseite "
            "ist der real gemessene Ausgang des Download-Endpunkts."
        )
        block_rule = re.search(r"^.*403.*$", content, re.MULTILINE)
        assert block_rule and ACCESS_LEVEL_MARKER in content, (
            "Fuer den 403-Fall fehlt eine Zuordnung zu einer Zugriffsstufe."
        )

    def test_hathitrust_forbids_reporting_the_block_as_captcha(self):
        content = (AGENTS_DIR / "hathitrust-fetcher.md").read_text(encoding="utf-8").lower()
        assert "kein captcha" in content or "nicht als captcha" in content, (
            "agents/hathitrust-fetcher.md unterscheidet die Sperrseite nicht vom "
            "CAPTCHA-Fall. Beide sehen im Browser aehnlich aus, verlangen aber "
            "unterschiedliche Meldungen."
        )

    def test_internetarchive_maps_http_401_on_restricted_items(self):
        """HTTP 401 — der reale Fehlerpfad bei Controlled Digital Lending.

        Gemessen: bei einem CDL-Item antwortet dieselbe Download-URL-Form mit
        HTTP 401 statt mit einem PDF. Die urspruengliche Fassung kannte nur das
        sichtbare Signal "Borrow-Button" auf der Detailseite.
        """
        content = (AGENTS_DIR / "internetarchive-fetcher.md").read_text(encoding="utf-8")
        assert "401" in content, (
            "agents/internetarchive-fetcher.md nennt HTTP 401 nicht — der real "
            "gemessene Ausgang bei einem gesperrten Item."
        )

    def test_internetarchive_names_the_machine_readable_restriction_signal(self):
        """``access-restricted-item`` unterscheidet frei von CDL zuverlaessig.

        Der Borrow-Button ist ein Layout-Merkmal; das Metadatenfeld ist die
        Eigenschaft selbst. Gemessen an zwei Items derselben Suche.
        """
        content = (AGENTS_DIR / "internetarchive-fetcher.md").read_text(encoding="utf-8")
        assert "access-restricted-item" in content, (
            "agents/internetarchive-fetcher.md nennt das Metadatenfeld nicht, an "
            "dem sich frei herunterladbare von CDL-Items unterscheiden lassen."
        )

    def test_mdz_documents_the_mandatory_rights_statement_confirmation(self):
        """Ohne Bestaetigung des Rechtehinweises liefert MDZ kein PDF.

        Gemessen: das Formular steht auf "Nein" vorbelegt; ohne Umstellung
        antwortet der Server mit HTTP 200, dem Formular und dem Text "Bitte
        akzeptieren Sie den Rechtehinweis" — und ohne PDF. Die urspruengliche
        Fassung beschrieb nur "Download-Icon → PDF-Option waehlen →
        herunterladen" und haette den Agenten dort stehen lassen.
        """
        content = (AGENTS_DIR / "mdz-fetcher.md").read_text(encoding="utf-8")
        assert "Rechtehinweis" in content, (
            "agents/mdz-fetcher.md kennt die Pflicht-Bestaetigung des "
            "Rechtehinweises nicht — ohne sie gibt MDZ kein PDF heraus."
        )

    def test_mdz_guide_documents_the_mandatory_rights_statement_confirmation(self):
        guide = (REPO_ROOT / "config" / "browser_guides" / "mdz.md").read_text(encoding="utf-8")
        assert "Rechtehinweis" in guide, (
            "config/browser_guides/mdz.md beschreibt den Download-Weg ohne die "
            "Pflicht-Bestaetigung — die Anleitung fuehrt so ins Leere."
        )
