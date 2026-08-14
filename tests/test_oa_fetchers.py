"""Frontmatter-, Guide- und Eval-Pruefung fuer die freie OA-Stufe.

Seit Issue #840 hat von den vier OA-Quellen nur noch TIB einen eigenen Agenten.
DOAB, OAPEN und KVK laufen ueber den Ultimate Fetcher `generic-fetcher` mit
einer Site-Config unter ``config/browser_guides/`` — ihr Site-Wissen wird
deshalb dort geprueft statt in einer Agent-Datei.
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
GUIDES_DIR = REPO_ROOT / "config" / "browser_guides"
EVALS_PATH = REPO_ROOT / "evals" / "oa-fetchers" / "evals.json"

#: OA-Quelle mit eigenem Agenten.
AGENT_NAMES = ["tib-fetcher"]

#: OA-Quellen ohne eigenen Agenten -> Site-Schluessel und Site-Config (#840).
GUIDE_SITES = {
    "oapen": "oapen.md",
    "doab": "doab.md",
    "kvk": "kvk.md",
}

VALID_STATUSES = {"success", "pickup_required", "captcha", "no_match", "metadata_only"}


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
    # Minimaler YAML-Parser: nur Key: Value (kein nested, kein list-block)
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

    def test_tib_fetcher_max_turns_is_15(self):
        """tib-fetcher muss maxTurns: 15 haben (laut Ticket-Spec)."""
        path = AGENTS_DIR / "tib-fetcher.md"
        fm, _ = parse_frontmatter(path)
        assert fm.get("maxTurns") == "15", (
            f"tib-fetcher maxTurns='{fm.get('maxTurns')}' — erwartet 15 (Ticket-Spec)"
        )

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
        [("tib-fetcher", "config/browser_guides/tib.md")],
    )
    def test_body_references_browser_guide(self, agent_name, expected_guide):
        """Agent-Body muss den kanonischen Browser-Guide-Pfad referenzieren."""
        path = AGENTS_DIR / f"{agent_name}.md"
        _, body = parse_frontmatter(path)
        assert expected_guide in body, (
            f"Browser-Guide-Referenz '{expected_guide}' fehlt im Body von {agent_name}.md"
        )


# ─── Klasse 2: Site-Configs der agentenlosen OA-Quellen (#840) ───────────────


class TestGuideDrivenSites:
    """DOAB, OAPEN und KVK haben keinen eigenen Agenten mehr — ihre Anleitung
    muss vollstaendig in der Site-Config stehen, sonst ist der Zugriffsweg weg."""

    @pytest.mark.parametrize("site, guide_name", sorted(GUIDE_SITES.items()))
    def test_guide_exists(self, site, guide_name):
        assert (GUIDES_DIR / guide_name).exists(), f"Site-Config fehlt fuer {site}"

    @pytest.mark.parametrize("site, guide_name", sorted(GUIDE_SITES.items()))
    def test_guide_drives_browser_use(self, site, guide_name):
        """Seit #906 wiederholen Guides die CLI-Syntax nicht mehr inline,
        sondern verweisen auf die einzige Quelle ``_cli.md`` (Heredoc-Form,
        Helfer, Element-Adressierung, Download)."""
        text = (GUIDES_DIR / guide_name).read_text(encoding="utf-8")
        assert "_cli.md" in text, (
            f"config/browser_guides/{guide_name} verweist nicht auf die "
            "CLI-Doku (_cli.md) — der Zugriffsweg waere ohne Werkzeug beschrieben"
        )

    @pytest.mark.parametrize("site, guide_name", sorted(GUIDE_SITES.items()))
    def test_guide_documents_status_vocabulary(self, site, guide_name):
        text = (GUIDES_DIR / guide_name).read_text(encoding="utf-8")
        found = {status for status in VALID_STATUSES if status in text}
        assert {"success", "metadata_only", "no_match"} <= found, (
            f"config/browser_guides/{guide_name} dokumentiert das Status-Vokabular "
            f"unvollstaendig: {sorted(found)}"
        )

    @pytest.mark.parametrize("site, guide_name", sorted(GUIDE_SITES.items()))
    def test_guide_has_no_direct_http_calls(self, site, guide_name):
        text = (GUIDES_DIR / guide_name).read_text(encoding="utf-8")
        offenders = re.findall(r"^\s*`?(curl|wget)\b", text, re.MULTILINE)
        assert not offenders, (
            f"config/browser_guides/{guide_name} beschreibt direkte HTTP-Calls: {offenders}"
        )


# ─── Klasse 3: Output-Schema-Validierung ─────────────────────────────────────


class TestOutputSchema:
    """Prueft, dass das gesperrte Output-Schema (5 Status-Werte) korrekt definiert ist."""

    def _validate_output(self, obj: dict, context: str = ""):
        """Gemeinsame Schema-Validierung fuer alle Status-Werte."""
        assert "status" in obj, f"{context}: 'status'-Feld fehlt"
        assert obj["status"] in VALID_STATUSES, (
            f"{context}: status='{obj['status']}' ist kein gueltiger Wert. "
            f"Erlaubt: {VALID_STATUSES}"
        )
        assert "source" in obj, f"{context}: 'source'-Feld fehlt"

    def test_success_output_has_file_path(self):
        """success-Output muss file_path enthalten."""
        output = {
            "status": "success",
            "source": "tib-fetcher",
            "file_path": "/tmp/book.pdf",
        }
        self._validate_output(output, "success")
        assert output["file_path"], "file_path darf nicht leer sein"

    def test_metadata_only_output_has_url(self):
        """metadata_only-Output muss url enthalten."""
        output = {
            "status": "metadata_only",
            "source": "generic-fetcher",
            "site": "oapen",
            "url": "https://library.oapen.org/handle/12345",
        }
        self._validate_output(output, "metadata_only")
        assert "url" in output, "metadata_only-Output braucht url"

    def test_generic_dispatch_carries_site(self):
        """Ohne `site` waeren die generic-fetcher-Eintraege ununterscheidbar (#840)."""
        output = {
            "status": "metadata_only",
            "source": "generic-fetcher",
            "site": "kvk",
            "url": "https://kvk.bibliothek.kit.edu/...",
            "reason": "Standorte: BSB Muenchen, UB Berlin",
        }
        self._validate_output(output, "metadata_only")
        assert output["site"] in GUIDE_SITES

    def test_captcha_output(self):
        """captcha-Output ist gueltiger Status."""
        output = {
            "status": "captcha",
            "source": "tib-fetcher",
            "reason": "CAPTCHA auf Detailseite erkannt",
        }
        self._validate_output(output, "captcha")

    def test_no_match_output(self):
        """no_match-Output ist gueltiger Status."""
        output = {
            "status": "no_match",
            "source": "generic-fetcher",
            "site": "doab",
            "reason": "0 Treffer fuer ISBN 000-0-0000-0000-0",
        }
        self._validate_output(output, "no_match")

    def test_invalid_status_rejected(self):
        """Ungueltige Status-Werte sollen erkannt werden."""
        invalid = {"status": "unknown_status", "source": "tib-fetcher"}
        assert invalid["status"] not in VALID_STATUSES, (
            "unknown_status muss als ungueltig erkannt werden"
        )

    def test_all_five_statuses_are_defined(self):
        """Alle 5 gesperrten Status-Werte muessen in VALID_STATUSES enthalten sein."""
        expected = {"success", "pickup_required", "captcha", "no_match", "metadata_only"}
        assert VALID_STATUSES == expected, (
            f"VALID_STATUSES stimmt nicht: {VALID_STATUSES} vs {expected}"
        )


# ─── Klasse 4: Verbots-Check ─────────────────────────────────────────────────


class TestForbiddenPatterns:
    """Prueft, dass verbotene Muster (curl, wget, direkte HTTP-Calls) nicht in Agenten vorkommen."""

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_no_curl_in_agent(self, agent_name):
        """Agent darf kein 'curl' als Shell-Command enthalten."""
        path = AGENTS_DIR / f"{agent_name}.md"
        content = path.read_text(encoding="utf-8")
        curl_uses = re.findall(r"^\s*`?curl\b", content, re.MULTILINE)
        assert len(curl_uses) == 0, f"curl-Aufruf in {agent_name}.md gefunden: {curl_uses}"

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_no_wget_in_agent(self, agent_name):
        """Agent darf kein 'wget' als Shell-Command enthalten."""
        path = AGENTS_DIR / f"{agent_name}.md"
        content = path.read_text(encoding="utf-8")
        wget_uses = re.findall(r"^\s*`?wget\b", content, re.MULTILINE)
        assert len(wget_uses) == 0, f"wget-Aufruf in {agent_name}.md gefunden: {wget_uses}"

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_browser_use_mentioned_in_body(self, agent_name):
        """Agent-Body muss 'browser-use' als Werkzeug referenzieren."""
        path = AGENTS_DIR / f"{agent_name}.md"
        _, body = parse_frontmatter(path)
        assert "browser-use" in body, (
            f"'browser-use' nicht im Body von {agent_name}.md — Agent muss browser-use verwenden"
        )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_forbidden_section_present(self, agent_name):
        """Agent-Body sollte einen 'Verbote'- oder 'Forbidden'-Abschnitt haben."""
        path = AGENTS_DIR / f"{agent_name}.md"
        _, body = parse_frontmatter(path)
        has_verbote = bool(
            re.search(r"##\s*(Verbote|Forbidden|Einschraenkungen)", body, re.IGNORECASE)
        )
        assert has_verbote, (
            f"Kein 'Verbote'-Abschnitt in {agent_name}.md — Verbote muessen explizit dokumentiert sein"
        )


# ─── Klasse 5: Eval-Cases ────────────────────────────────────────────────────


class TestEvalCases:
    def test_evals_file_exists(self):
        """evals/oa-fetchers/evals.json muss existieren."""
        assert EVALS_PATH.exists(), f"Eval-Datei fehlt: {EVALS_PATH}"

    def test_evals_is_valid_json(self):
        """evals.json muss valides JSON sein."""
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, list), "evals.json muss ein JSON-Array sein"

    def test_evals_has_four_cases(self):
        """evals.json muss genau 4 Cases haben (je 1 pro Platform)."""
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        assert len(data) == 4, f"Erwartet 4 Eval-Cases, gefunden: {len(data)}"

    def test_eval_ids_are_correct(self):
        """Eval-IDs muessen oa-01 bis oa-04 sein."""
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        ids = [c["id"] for c in data]
        assert ids == ["oa-01", "oa-02", "oa-03", "oa-04"], f"Falsche IDs: {ids}"

    def test_each_eval_has_required_fields(self):
        """Jeder Eval-Case muss id, description, agent und expected enthalten."""
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        allowed = set(AGENT_NAMES) | {"generic-fetcher"}
        for case in data:
            assert "id" in case, f"id fehlt in Case: {case}"
            assert "description" in case, f"description fehlt in Case {case['id']}"
            assert "agent" in case, f"agent fehlt in Case {case['id']}"
            assert "expected" in case, f"expected fehlt in Case {case['id']}"
            assert case["agent"] in allowed, (
                f"agent='{case['agent']}' in Case {case['id']} ist kein bekannter Fetcher"
            )

    def test_generic_cases_name_their_site_config(self):
        """#840: ein generic-fetcher-Case ohne site_config waere nicht reproduzierbar."""
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        for case in data:
            if case["agent"] != "generic-fetcher":
                continue
            guide = case.get("site_config", "")
            assert guide.startswith("config/browser_guides/"), (
                f"Case {case['id']}: site_config fehlt oder zeigt woandershin: {guide!r}"
            )
            assert (REPO_ROOT / guide).exists(), f"Case {case['id']}: {guide} existiert nicht"

    def test_every_oa_source_has_exactly_one_eval(self):
        """Jede der 4 OA-Quellen muss genau einen Eval-Case haben."""
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        covered = {c.get("site") or c["agent"] for c in data}
        assert covered == set(GUIDE_SITES) | set(AGENT_NAMES), (
            f"Nicht jede OA-Quelle hat einen Eval-Case. Vorhanden: {covered}"
        )
