"""Frontmatter-, Schema-, Verbots-, Zugriffsstufen- und Edition-Pruefung fuer die
drei freien Archiv-Fetcher-Subagenten (Issue #450): hathitrust-fetcher,
internetarchive-fetcher, mdz-fetcher.

Struktur analog zu ``tests/test_oa_fetchers.py`` — dieselben vier Klassen
(Frontmatter, Output-Schema, Verbote, Eval-Cases) plus zwei neue Klassen fuer
die issue-spezifischen Akzeptanzkriterien AC2 (Zugriffsstufe statt
unvollstaendigem Volltext) und AC4 (Ausgabe-/Jahresangabe des Digitalisats).
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
EVALS_PATH = REPO_ROOT / "evals" / "free-archive-fetchers" / "evals.json"
LIVE_RECORD_PATH = REPO_ROOT / "evals" / "free-archive-fetchers" / "live-verification.json"

AGENT_NAMES = ["hathitrust-fetcher", "internetarchive-fetcher", "mdz-fetcher"]
VALID_STATUSES = {"success", "pickup_required", "captcha", "no_match", "metadata_only"}
ACCESS_LEVEL_PREFIX = "Zugriffsstufe:"

#: Der Radiobutton der MDZ-Download-Zwischenseite. Einzige Quelle: der
#: Live-Lauf vom 2026-07-29 (siehe live-verification.json).
MDZ_RIGHTS_RADIO = "xdfz"


# ─── Hilfsfunktion (identisch zu tests/test_oa_fetchers.py) ─────────────────


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
        path = AGENTS_DIR / f"{agent_name}.md"
        assert path.exists(), f"Agent-Datei fehlt: {path}"

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_frontmatter_has_name_field(self, agent_name):
        path = AGENTS_DIR / f"{agent_name}.md"
        fm, _ = parse_frontmatter(path)
        assert "name" in fm, f"Kein 'name'-Feld in {agent_name}.md"
        assert fm["name"] == agent_name, (
            f"name='{fm['name']}' stimmt nicht mit Dateinamen '{agent_name}' ueberein"
        )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_frontmatter_model_is_sonnet(self, agent_name):
        path = AGENTS_DIR / f"{agent_name}.md"
        fm, _ = parse_frontmatter(path)
        assert "model" in fm, f"Kein 'model'-Feld in {agent_name}.md"
        assert fm["model"] == "sonnet", (
            f"model='{fm['model']}' in {agent_name}.md — erwartet 'sonnet'"
        )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_frontmatter_has_max_turns(self, agent_name):
        path = AGENTS_DIR / f"{agent_name}.md"
        fm, _ = parse_frontmatter(path)
        assert "maxTurns" in fm, f"Kein 'maxTurns'-Feld in {agent_name}.md"
        assert fm["maxTurns"].isdigit(), (
            f"maxTurns='{fm['maxTurns']}' ist keine Zahl in {agent_name}.md"
        )
        assert int(fm["maxTurns"]) > 0, f"maxTurns muss > 0 sein in {agent_name}.md"

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_frontmatter_tools_contains_browser_use(self, agent_name):
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
        "agent_name, guide_name",
        [
            ("hathitrust-fetcher", "hathitrust.md"),
            ("internetarchive-fetcher", "internetarchive.md"),
            ("mdz-fetcher", "mdz.md"),
        ],
    )
    def test_browser_guide_file_exists(self, agent_name, guide_name):
        path = REPO_ROOT / "config" / "browser_guides" / guide_name
        assert path.exists(), f"Browser-Guide fehlt: {path}"


# ─── Klasse 2: Output-Schema-Validierung ─────────────────────────────────────


class TestOutputSchema:
    """Prueft, dass das gesperrte Output-Schema (5 Status-Werte) korrekt definiert ist."""

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

    def test_success_output_has_pdf_path_and_edition(self):
        output = {
            "status": "success",
            "source_subagent": "hathitrust-fetcher",
            "pdf_path": "/tmp/book.pdf",
            "edition": "1897, Reclam Verlag",
        }
        self._validate_output(output, "success")
        assert output["pdf_path"], "pdf_path darf nicht leer sein"
        assert "edition" in output, "success-Output braucht edition (AC4)"

    def test_metadata_only_output_has_url_and_access_level_reason(self):
        output = {
            "status": "metadata_only",
            "source_subagent": "internetarchive-fetcher",
            "url": "https://archive.org/details/example",
            "reason": "Zugriffsstufe: Borrow-only (Controlled Digital Lending)",
        }
        self._validate_output(output, "metadata_only")
        assert "url" in output, "metadata_only-Output braucht url"
        assert ACCESS_LEVEL_PREFIX in output["reason"]

    def test_pickup_required_output(self):
        output = {
            "status": "pickup_required",
            "source_subagent": "mdz-fetcher",
            "url": "https://www.digitale-sammlungen.de/...",
            "reason": "Kein Digitalisat verlinkt",
        }
        self._validate_output(output, "pickup_required")

    def test_captcha_output(self):
        output = {
            "status": "captcha",
            "source_subagent": "hathitrust-fetcher",
            "reason": "CAPTCHA auf Detailseite erkannt",
        }
        self._validate_output(output, "captcha")

    def test_no_match_output(self):
        output = {
            "status": "no_match",
            "source_subagent": "mdz-fetcher",
            "reason": "0 Treffer fuer Titel X",
        }
        self._validate_output(output, "no_match")

    def test_all_five_statuses_are_defined(self):
        expected = {"success", "pickup_required", "captcha", "no_match", "metadata_only"}
        assert VALID_STATUSES == expected


# ─── Klasse 3: Verbots-Check ─────────────────────────────────────────────────


class TestForbiddenPatterns:
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
    def test_forbids_reconstructing_fulltext_from_snippets(self, agent_name):
        """AC2: Ein eingeschraenkt sichtbarer Titel darf NIE als Volltext aus
        Suchtreffern/Snippets zusammengesetzt werden — das muss im Verbote-
        Abschnitt explizit stehen, nicht nur implizit aus dem Standard-Flow
        folgen."""
        path = AGENTS_DIR / f"{agent_name}.md"
        _, body = parse_frontmatter(path)
        verbote_match = re.search(
            r"##\s*(?:Verbote|Forbidden|Einschraenkungen)(.*?)(?:\n##\s|\Z)",
            body,
            re.IGNORECASE | re.DOTALL,
        )
        assert verbote_match, f"Kein Verbote-Abschnitt in {agent_name}.md"
        lowered = verbote_match.group(1).lower()
        assert "volltext" in lowered, (
            f"Verbote-Abschnitt von {agent_name}.md muss 'Volltext' erwaehnen (AC2)"
        )
        assert "snippet" in lowered or "suchtreffer" in lowered, (
            f"Verbote-Abschnitt von {agent_name}.md muss Snippet-/Suchtreffer-"
            f"Zusammensetzung explizit untersagen (AC2)"
        )


# ─── Klasse 4: Zugriffsstufen-Vokabular (AC2) ────────────────────────────────


class TestAccessLevelReporting:
    """AC2: bei eingeschraenkter Sichtbarkeit meldet der Agent die Zugriffsstufe
    statt einen unvollstaendigen Volltext auszugeben."""

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_body_documents_access_level_vocabulary(self, agent_name):
        path = AGENTS_DIR / f"{agent_name}.md"
        _, body = parse_frontmatter(path)
        assert ACCESS_LEVEL_PREFIX in body, (
            f"{agent_name}.md muss das feste Vokabular '{ACCESS_LEVEL_PREFIX} …' im "
            f"metadata_only-Beispiel verwenden (AC2, Plan-Entscheidung Issue #450)"
        )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_metadata_only_example_shows_access_level_reason(self, agent_name):
        """Das metadata_only-Beispiel im Output-Schema selbst muss das
        Vokabular zeigen (nicht nur irgendwo im Fliesstext)."""
        path = AGENTS_DIR / f"{agent_name}.md"
        _, body = parse_frontmatter(path)
        schema_match = re.search(
            r"##\s*Output-Schema(.*?)(?:\n##\s|\Z)", body, re.IGNORECASE | re.DOTALL
        )
        assert schema_match, f"Kein Output-Schema-Abschnitt in {agent_name}.md"
        assert ACCESS_LEVEL_PREFIX in schema_match.group(1), (
            f"Output-Schema von {agent_name}.md zeigt kein metadata_only-Beispiel mit "
            f"'{ACCESS_LEVEL_PREFIX} …'"
        )


# ─── Klasse 5: Edition-Feld (AC4) ────────────────────────────────────────────


class TestEditionField:
    """AC4: uebernommene Titel tragen die korrekte Ausgabe-/Jahresangabe des
    Digitalisats, nicht die des Originals."""

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_success_schema_has_edition_field(self, agent_name):
        path = AGENTS_DIR / f"{agent_name}.md"
        _, body = parse_frontmatter(path)
        schema_match = re.search(
            r"##\s*Output-Schema(.*?)(?:\n##\s|\Z)", body, re.IGNORECASE | re.DOTALL
        )
        assert schema_match, f"Kein Output-Schema-Abschnitt in {agent_name}.md"
        assert '"edition"' in schema_match.group(1), (
            f"success-Beispiel im Output-Schema von {agent_name}.md zeigt kein 'edition'-Feld (AC4)"
        )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_flow_instructs_edition_from_source_not_input(self, agent_name):
        """Der Standard-Flow muss ausdruecklich anweisen, Jahr/Ausgabe/Verlag aus
        dem Katalog-/Metadaten-Eintrag der Quelle zu entnehmen statt aus der
        Eingabe zu uebernehmen."""
        path = AGENTS_DIR / f"{agent_name}.md"
        _, body = parse_frontmatter(path)
        lowered = body.lower()
        assert "edition" in lowered
        assert "eingabe" in lowered, (
            f"{agent_name}.md muss erwaehnen, dass die Edition NICHT aus der "
            f"Eingabe uebernommen wird (AC4)"
        )
        assert "katalog" in lowered or "metadaten" in lowered, (
            f"{agent_name}.md muss die Katalog-/Metadaten-Quelle fuer die "
            f"Edition-Angabe benennen (AC4)"
        )


# ─── Klasse 6: Eval-Cases ────────────────────────────────────────────────────


class TestEvalCases:
    def test_evals_file_exists(self):
        assert EVALS_PATH.exists(), f"Eval-Datei fehlt: {EVALS_PATH}"

    def test_evals_is_valid_json(self):
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, list), "evals.json muss ein JSON-Array sein"

    def test_evals_has_six_cases(self):
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        assert len(data) == 6, f"Erwartet 6 Eval-Cases, gefunden: {len(data)}"

    def test_eval_ids_are_correct(self):
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        ids = [c["id"] for c in data]
        assert ids == [
            "far-01",
            "far-02",
            "far-03",
            "far-04",
            "far-05",
            "far-06",
        ], f"Falsche IDs: {ids}"

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


# ─── Klasse 7: Tier-Reihenfolge (AC3) — Referenz auf den Routing-Spiegel ─────


class TestTierOrderReferencesFreeArchives:
    """AC3: die freien Archive muessen im book-fetcher-Master VOR den
    lizenzpflichtigen Verlags-Subagenten aufgerufen werden. Der eigentliche
    Beweis liegt in tests/test_book_fetcher.py (Routing-Spiegel); hier wird nur
    sichergestellt, dass die drei neuen Agenten ueberhaupt als OA-Subagenten in
    Schritt 3 des Master-Prompts auftauchen."""

    def setUp(self):
        pass

    def test_book_fetcher_step3_lists_all_three_new_agents(self):
        book_fetcher = (AGENTS_DIR / "book-fetcher.md").read_text(encoding="utf-8")
        step3_match = re.search(
            r"##\s*Schritt 3(.*?)(?:\n##\s|\Z)", book_fetcher, re.IGNORECASE | re.DOTALL
        )
        assert step3_match, "Kein 'Schritt 3'-Abschnitt in agents/book-fetcher.md"
        step3 = step3_match.group(1)
        for agent_name in AGENT_NAMES:
            assert agent_name in step3, (
                f"'{agent_name}' fehlt in Schritt 3 (OA-Subagenten-Kette) von "
                f"agents/book-fetcher.md"
            )

    def test_book_fetcher_tools_include_all_three_new_agents(self):
        book_fetcher = (AGENTS_DIR / "book-fetcher.md").read_text(encoding="utf-8")
        lines = book_fetcher.split("\n")
        end = lines.index("---", 1)
        fm_raw = "\n".join(lines[1:end])
        for agent_name in AGENT_NAMES:
            assert f"Agent({agent_name})" in fm_raw, (
                f"'Agent({agent_name})' fehlt im tools-Frontmatter von agents/book-fetcher.md"
            )


# ─── Klasse 8: MDZ-Rechtehinweis-Schritt (Fix-Runde PR #498) ─────────────────


class TestMdzRightsAcknowledgmentStep:
    """Die Download-Zwischenseite (`download.digitale-sammlungen.de/BOOKS/
    download.pl`) verlangt vor dem PDF-Link, den vorbelegten
    Rechtehinweis-Radiobutton `xdfz` von `1` ("Nein") auf `2` ("Ja")
    umzustellen und den WEITER-Button des Abschnitts "Sofort-Download als
    PDF-Datei" zu klicken -- auch bei gemeinfreien Werken. Bleibt die Vorgabe
    stehen, liefert MDZ nur wieder die Zwischenseite.

    Beleg: Live-Lauf 2026-07-29 an Goethes Faust. 1 (bsb10109182), aufgezeichnet
    in evals/free-archive-fetchers/live-verification.json und nachfahrbar ueber
    tests/test_free_archive_live_fetch.py. Die Weiche selbst ist ausgefuehrt
    geprueft in tests/test_free_archive_download.py.
    """

    def setup_method(self):
        path = AGENTS_DIR / "mdz-fetcher.md"
        _, self.body = parse_frontmatter(path)

    def test_standard_flow_documents_rights_acknowledgment_step(self):
        flow_match = re.search(
            r"##\s*Standard-Flow(.*?)(?:\n##\s|\Z)", self.body, re.IGNORECASE | re.DOTALL
        )
        assert flow_match, "Kein Standard-Flow-Abschnitt in mdz-fetcher.md"
        lowered = flow_match.group(1).lower()
        assert "rechtehinweis" in lowered, (
            "Standard-Flow von mdz-fetcher.md muss den Rechtehinweis-Schritt "
            "auf der Download-Zwischenseite dokumentieren"
        )
        assert '"ja"' in lowered or "'ja'" in lowered or "auf „ja“" in lowered, (
            "Standard-Flow muss ausdruecklich benennen, dass die Vorgabe "
            "'Nein' auf 'Ja' umgestellt werden muss"
        )

    def test_standard_flow_names_the_actual_form_field(self):
        """Ein Prompt, der nur „Ja anklicken" sagt, ist nicht nachbaubar.

        Der Radiobutton heisst `xdfz`, „Ja" ist `value=2`. Ohne diese Angabe
        muss jede Umsetzung raten -- und eine erste Fassung des Test-Spiegels
        hat genau daran gescheitert.
        """
        assert MDZ_RIGHTS_RADIO in self.body, (
            f"mdz-fetcher.md muss das Formularfeld '{MDZ_RIGHTS_RADIO}' benennen"
        )
        assert f"{MDZ_RIGHTS_RADIO}=2" in self.body, (
            f"mdz-fetcher.md muss den zu setzenden Wert '{MDZ_RIGHTS_RADIO}=2' benennen"
        )


# ─── Klasse 9: Der Download-Schritt muss ausfuehrbar sein (AC1) ──────────────


class TestDownloadStepUsesAnExistingCommand:
    """Die Wurzel dafuer, dass es zu AC1 nie einen Beleg gab.

    Alle drei Agenten endeten mit `browser-use download <idx> --to <pfad>`.
    Dieses Unterkommando existiert nicht -- weder in der installierten Version
    (0.12.6) noch in der Dokumentation des Projekts. Der Aufruf bricht mit
    `invalid choice: 'download'` ab; es entsteht nie eine Datei, und damit kann
    kein Agent je einen Testtitel beschafft haben.

    Der reale Mechanismus: Chromium nimmt Downloads selbst an
    (`accept_downloads`, `auto_download_pdfs`) und legt sie unter
    `<TMPDIR>/browser-use-downloads-<id>/` ab; von dort wird verschoben und
    geprueft. Genau das muss im Prompt stehen.
    """

    #: Ein Aufruf, kein Zitat. `browser-use download …` in der Erklaerung
    #: („dieses Kommando gibt es nicht") soll erlaubt bleiben.
    INVOCATION_RE = re.compile(r"browser-use\s+download\s+<")

    TARGETS = [AGENTS_DIR / f"{name}.md" for name in AGENT_NAMES] + [
        REPO_ROOT / "config" / "browser_guides" / f"{guide}.md"
        for guide in ("hathitrust", "internetarchive", "mdz")
    ]

    @pytest.mark.parametrize("path", TARGETS, ids=lambda p: p.name)
    def test_no_call_to_nonexistent_browser_use_download(self, path):
        content = path.read_text(encoding="utf-8")
        hits = self.INVOCATION_RE.findall(content)
        assert not hits, (
            f"{path.name} ruft 'browser-use download' auf — dieses Unterkommando "
            f"existiert nicht (browser-use 0.12.6: invalid choice: 'download'). "
            f"Der Download laeuft ueber 'browser-use click' plus das "
            f"Session-Download-Verzeichnis."
        )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_agent_documents_the_real_download_mechanism(self, agent_name):
        content = (AGENTS_DIR / f"{agent_name}.md").read_text(encoding="utf-8")
        assert "browser-use click" in content, (
            f"{agent_name}.md muss den Download ueber 'browser-use click' ausloesen"
        )
        assert "browser-use-downloads-" in content, (
            f"{agent_name}.md muss das Session-Download-Verzeichnis "
            f"'<TMPDIR>/browser-use-downloads-<id>/' benennen — dort landet die Datei"
        )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_agent_verifies_the_file_from_disk(self, agent_name):
        content = (AGENTS_DIR / f"{agent_name}.md").read_text(encoding="utf-8")
        assert "%PDF-" in content, f"{agent_name}.md muss die Magic-Bytes '%PDF-' pruefen"
        assert "10 KB" in content, f"{agent_name}.md muss die Groessenschwelle nennen"


# ─── Klasse 10: Der Live-Beleg zu AC1 ────────────────────────────────────────


class TestLiveVerificationRecord:
    """AC1 ist eine Aussage ueber das echte Netz — hier haengt der Beleg dran.

    Ohne diese Datei bleibt „der Agent beschafft ein PDF" eine Behauptung. Der
    Test prueft nicht, ob die Laeufe gut ausgingen (einer ging nicht gut aus),
    sondern dass fuer jeden der drei Agenten ueberhaupt ein pruefbarer Befund
    vorliegt und dass Eval-Cases und Befund dieselben Exemplare meinen.
    """

    def setup_method(self):
        self.record = json.loads(LIVE_RECORD_PATH.read_text(encoding="utf-8"))
        self.runs = {run["agent"]: run for run in self.record["runs"]}
        self.cases = json.loads(EVALS_PATH.read_text(encoding="utf-8"))

    def test_record_exists_and_covers_every_agent(self):
        assert set(self.runs) == set(AGENT_NAMES), (
            f"Live-Beleg deckt nicht alle Agenten ab: {set(self.runs)}"
        )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_every_run_carries_a_checkable_verdict(self, agent_name):
        run = self.runs[agent_name]
        assert run["verdict"] in self.record["verdict_vocabulary"], (
            f"Unbekanntes Verdict {run['verdict']!r} fuer {agent_name}"
        )
        assert run["url_chain"], f"{agent_name}: leere URL-Kette ist kein Beleg"
        assert run["item_id"], f"{agent_name}: kein Exemplar benannt"

    @pytest.mark.parametrize("agent_name", ["internetarchive-fetcher", "mdz-fetcher"])
    def test_successful_runs_name_a_real_artifact(self, agent_name):
        """Wer `pdf_verified` sagt, muss Bytes, Magic und Pruefsumme zeigen."""
        run = self.runs[agent_name]
        assert run["verdict"] == "pdf_verified"
        artifact = run["artifact"]
        assert artifact["http_status"] == 200
        assert artifact["content_type"] == "application/pdf"
        assert artifact["magic"].startswith("%PDF-")
        assert artifact["bytes"] > 10 * 1024
        assert re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]), (
            f"{agent_name}: sha256 sieht nicht wie eine Pruefsumme aus"
        )

    def test_rate_limited_run_does_not_pretend_to_have_a_file(self):
        run = self.runs["hathitrust-fetcher"]
        assert run["verdict"] == "rate_limited"
        assert run["artifact"]["sha256"] is None
        assert run["artifact"]["bytes"] is None
        assert run["observations"], "Eine Absage ohne Beobachtungen ist kein Befund"

    @pytest.mark.parametrize(
        "case_id, id_field",
        [("far-01", "hathitrust_id"), ("far-02", "archive_id"), ("far-03", "bsb_id")],
    )
    def test_eval_cases_reference_the_verified_items(self, case_id, id_field):
        """Beleg und Eval duerfen nicht auseinanderlaufen."""
        case = next(c for c in self.cases if c["id"] == case_id)
        run = self.runs[case["agent"]]
        assert case["input"][id_field] == run["item_id"], (
            f"{case_id} prueft {case['input'][id_field]!r}, belegt ist {run['item_id']!r}"
        )
        assert case["evidence"].startswith("evals/free-archive-fetchers/live-verification.json")


class TestEvalCasesDoNotAcceptMetadataOnlyAsEquivalent:
    """AC1 verlangt eine Beschaffung, keinen Ausweichausgang.

    Vor der Fix-Runde liessen alle drei Cases `status_in: [success,
    metadata_only]` zu — damit war jeder Ausgang richtig und der Eval sagte
    nichts. Jeder Case legt sich jetzt auf genau einen Status fest.
    """

    def setup_method(self):
        self.cases = json.loads(EVALS_PATH.read_text(encoding="utf-8"))

    def test_no_case_offers_a_choice_of_statuses(self):
        for case in self.cases:
            assert "status_in" not in case["expected"], (
                f"{case['id']}: 'status_in' laesst mehrere Ausgaenge gelten — "
                f"ein Eval, der nicht scheitern kann, misst nichts"
            )
            assert "status" in case["expected"], f"{case['id']}: kein erwarteter Status"

    @pytest.mark.parametrize("case_id", ["far-02", "far-03"])
    def test_public_domain_cases_demand_a_verified_pdf(self, case_id):
        case = next(c for c in self.cases if c["id"] == case_id)
        expected = case["expected"]
        assert expected["status"] == "success", (
            f"{case_id} betrifft ein frei ladbares gemeinfreies Digitalisat — "
            f"hier ist metadata_only ein Fehlschlag, kein Sonderfall"
        )
        assert expected["pdf_starts_with"] == "%PDF-"
        assert expected["pdf_min_bytes"] >= 10 * 1024
        assert expected["edition"], f"{case_id}: AC4 verlangt die Ausgabe des Digitalisats"

    def test_hathitrust_rate_limit_case_is_separate_from_the_ac1_case(self):
        """far-01 verlangt die Beschaffung, far-06 beschreibt den 429-Ausgang.

        Zusammengelegt waere das Rate-Limit wieder der Sollzustand — der Fehler,
        den die Fix-Runde zu PR #498 behoben hat.
        """
        ac1 = next(c for c in self.cases if c["id"] == "far-01")
        rate_limited = next(c for c in self.cases if c["id"] == "far-06")
        assert ac1["expected"]["status"] == "success"
        assert rate_limited["expected"]["status"] == "pickup_required"
        assert rate_limited["expected"]["reason"] == (
            "Zugriffsstufe: Vollansicht, Download vom Rate-Limit abgewiesen (HTTP 429)"
        )
        assert rate_limited["expected"]["min_download_attempts"] >= 2, (
            "Ein einziger Versuch fuehrt bei einem Rate-Limit nie zu einer Datei"
        )

    def test_negative_controls_exist_for_restricted_access(self):
        restricted = [c for c in self.cases if c["expected"]["status"] == "metadata_only"]
        assert len(restricted) >= 2, (
            "Ohne Gegenproben waere metadata_only ein Auffangbecken, in dem die "
            "success-Cases stillschweigend mitlaufen koennten"
        )
        for case in restricted:
            assert case["expected"]["reason"].startswith(ACCESS_LEVEL_PREFIX)
            assert case["expected"]["pdf_path_absent"] is True
