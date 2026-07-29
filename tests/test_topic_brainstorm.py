"""Tests fuer Topic-Brainstorm Scorer (Issue #471).

`scorer.py` enthielt vormals eine fest kodierte `_TOPIC_DB` mit 5 Themen aus
einem einzigen Fachbereich (Cyber Security); jede unbekannte Studienrichtung
wurde still auf "Wirtschaftsinformatik" normalisiert. Nach #471 generiert das
Modell (SKILL.md) die Themenkandidaten fach- und interessenspassend selbst;
`scorer.py` normalisiert/scored ausschliesslich noch die vom Aufrufer per
`--topics-json` gelieferten Kandidaten (Feasibility- und Novelty-Modifikatoren
aus Budget/Datenzugang/Interessen bleiben Scorer-Arithmetik, Career-Fit und
`reason` werden unveraendert durchgereicht).

Diese Tests decken:
- Kein Fixed-DB-Fallback mehr, keine Feld-Normalisierung (AC3)
- `reason`-Feld pro Kandidat (AC2)
- Fachabhaengigkeit wird durchgereicht statt auf eine Domaene normalisiert (AC1/AC4)
- Ausfuehrungspfad der Fach-Kontrast-Eval-Prompts tb-04/tb-05 (Fix-Runde zu PR #484)

Was diese Tests **nicht** zeigen: dass das Modell bei einer realen Anfrage von
sich aus fachlich passende Themen entwirft. Das ist Generierungsverhalten,
laut `docs/evals/STRATEGY.md` fuer diese Komponente `structural`/API-gated und
ohne `ANTHROPIC_API_KEY` nicht messbar. Der Versuch, es per pytest zu belegen,
ist in dieser PR schon einmal fehlgeschlagen — siehe
`tests/test_issue_471_evidence_honesty.py` fuer die ausgefuehrte Gegenprobe.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_WORKTREE_ROOT = Path(__file__).parent.parent

_SCORER = _WORKTREE_ROOT / "skills" / "topic-brainstorm" / "scripts" / "scorer.py"
_EVALS_JSON = _WORKTREE_ROOT / "evals" / "topic-brainstorm" / "evals.json"


def _eval_prompts() -> list[dict]:
    """Quality-Eval-Prompts der Komponente aus evals/topic-brainstorm/evals.json."""
    return json.loads(_EVALS_JSON.read_text(encoding="utf-8"))["prompts"]


# ---------------------------------------------------------------------------
# Fixtures: zwei fachlich disjunkte Themenkandidaten-Sets (vom Modell geliefert)
# ---------------------------------------------------------------------------

_BWL_TOPICS: list[dict] = [
    {
        "title": "Preisstrategien im stationaeren Einzelhandel unter Inflationsdruck",
        "keywords": ["pricing", "einzelhandel", "inflation", "bwl"],
        "reason": "Passt zur BWL, da Preistheorie und Marktbeobachtung Kernkompetenzen des Studiengangs sind.",
        "base_feasibility": 7.0,
        "base_novelty": 6.0,
        "base_career_fit": 8.5,
        "research_questions": [
            "Wie reagieren Einzelhaendler auf anhaltende Inflation bei der Preissetzung?",
            "Welche Preisstrategien wirken sich am staerksten auf die Kundenbindung aus?",
        ],
        "pilot_papers": ["Simon & Fassnacht (2019): Preismanagement, Springer Gabler"],
    },
    {
        "title": "Working-Capital-Management in mittelstaendischen Familienunternehmen",
        "keywords": ["working capital", "mittelstand", "finanzierung", "bwl"],
        "reason": "Kernthema der Finanzwirtschaft, direkt an BWL-Curricula anschlussfaehig.",
        "base_feasibility": 6.5,
        "base_novelty": 5.5,
        "base_career_fit": 8.0,
        "research_questions": [
            "Welche Working-Capital-Strategien verfolgen mittelstaendische Familienunternehmen?",
            "Wie wirkt sich das Working-Capital-Management auf die Liquiditaet in Krisenzeiten aus?",
        ],
        "pilot_papers": [
            "Baños-Caballero et al. (2014): Working capital management, corporate performance"
        ],
    },
    {
        "title": "Employer Branding im Mittelstand aus Sicht der Generation Z",
        "keywords": ["employer branding", "generation z", "personal", "bwl"],
        "reason": "Personalwirtschaftliches Thema mit klarem BWL-Bezug und guter Datenlage per Survey.",
        "base_feasibility": 7.5,
        "base_novelty": 6.5,
        "base_career_fit": 7.5,
        "research_questions": [
            "Welche Erwartungen stellt die Generation Z an Arbeitgeber im Mittelstand?",
            "Wie unterscheidet sich effektives Employer Branding fuer KMU von Grosskonzernen?",
        ],
        "pilot_papers": ["Dabirian et al. (2017): Employee Value Proposition, Employer Branding"],
    },
]

_INFORMATIK_TOPICS: list[dict] = [
    {
        "title": "Statische Analyse von Nebenlaeufigkeitsfehlern in Rust-Programmen",
        "keywords": ["rust", "static analysis", "concurrency", "informatik"],
        "reason": "Klassisches Informatik-Thema an der Schnittstelle Programmiersprachen/Verifikation.",
        "base_feasibility": 6.0,
        "base_novelty": 8.0,
        "base_career_fit": 9.0,
        "research_questions": [
            "Welche Klassen von Nebenlaeufigkeitsfehlern erkennt statische Analyse in Rust zuverlaessig?",
            "Wie vergleicht sich die Erkennungsrate mit dynamischen Verfahren?",
        ],
        "pilot_papers": ["Jung et al. (2018): RustBelt: Securing the Foundations of Rust, POPL"],
    },
    {
        "title": "Effiziente Approximationsalgorithmen fuer Graph-Partitionierung",
        "keywords": ["graph partitioning", "approximation", "algorithms", "informatik"],
        "reason": "Theorie-nahes Informatik-Thema mit klarer Methodik (Algorithmenanalyse).",
        "base_feasibility": 5.5,
        "base_novelty": 7.5,
        "base_career_fit": 8.5,
        "research_questions": [
            "Welche Approximationsguete erreichen aktuelle Heuristiken bei grossen Graphen?",
            "Wie skaliert die Laufzeit mit der Graphgroesse in der Praxis?",
        ],
        "pilot_papers": ["Karypis & Kumar (1998): Multilevel k-way Partitioning Scheme"],
    },
    {
        "title": "WebAssembly als Compile-Target fuer Legacy-C-Codebasen",
        "keywords": ["webassembly", "compiler", "legacy", "informatik"],
        "reason": "Systemnahes Informatik-Thema mit praktischer Machbarkeit ueber Open-Source-Toolchains.",
        "base_feasibility": 7.0,
        "base_novelty": 6.5,
        "base_career_fit": 8.0,
        "research_questions": [
            "Welche Performance-Einbussen entstehen beim Kompilieren von Legacy-C-Code nach WebAssembly?",
        ],
        "pilot_papers": ["Haas et al. (2017): Bringing the Web up to Speed with WebAssembly, PLDI"],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_scorer(
    topics: list[dict],
    interests: list[str],
    budget: str,
    data_access: str,
    output_mode: str = "list",
    extra_args: list[str] | None = None,
):
    """Fuehrt scorer.py als Subprocess aus, Topics per stdin (--topics-json -)."""
    cmd = [
        sys.executable,
        str(_SCORER),
        "--topics-json",
        "-",
        "--interests",
        ",".join(interests),
        "--budget",
        budget,
        "--data-access",
        data_access,
        "--output-mode",
        output_mode,
    ]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(
        cmd,
        input=json.dumps(topics),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"scorer.py exitcode {result.returncode}\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Passthrough: scorer.py scored die uebergebenen Kandidaten, generiert keine eigenen
# ---------------------------------------------------------------------------


class TestScorerPassthrough:
    """scorer.py scored exakt die uebergebenen Kandidaten (kein Fixed-Set)."""

    def test_returns_same_count_as_input(self):
        topics = _run_scorer(
            _BWL_TOPICS,
            interests=["Preisstrategie"],
            budget="6 Monate",
            data_access="Literatur-Only",
        )
        assert isinstance(topics, list), "Ausgabe muss eine Liste sein"
        assert len(topics) == len(_BWL_TOPICS), (
            f"Erwartet {len(_BWL_TOPICS)} Topics (Eingabegroesse), erhalten {len(topics)}"
        )

    def test_topic_has_title(self):
        topics = _run_scorer(
            _BWL_TOPICS,
            interests=["Preisstrategie"],
            budget="6 Monate",
            data_access="Literatur-Only",
        )
        for t in topics:
            assert "title" in t, f"Topic fehlt 'title': {t}"
            assert isinstance(t["title"], str) and t["title"].strip(), (
                f"'title' muss ein nicht-leerer String sein: {t}"
            )


# ---------------------------------------------------------------------------
# Scores: alle 3 Scores pro Kandidat, Bereich 0-10
# ---------------------------------------------------------------------------


class TestScoreRanges:
    """Feasibility, Novelty, Career-Fit sind normiert auf 0-10."""

    def test_all_three_scores_present(self):
        topics = _run_scorer(
            _BWL_TOPICS,
            interests=["Preisstrategie"],
            budget="6 Monate",
            data_access="Literatur-Only",
        )
        for t in topics:
            for score_key in ("feasibility", "novelty", "career_fit"):
                assert score_key in t, f"Kandidat '{t.get('title')}' fehlt '{score_key}'"

    def test_scores_normalized_0_to_10(self):
        topics = _run_scorer(
            _BWL_TOPICS,
            interests=["Preisstrategie"],
            budget="6 Monate",
            data_access="Literatur-Only",
        )
        for t in topics:
            for score_key in ("feasibility", "novelty", "career_fit"):
                val = t[score_key]
                assert isinstance(val, (int, float)), (
                    f"Score '{score_key}' in '{t.get('title')}' ist kein Zahlenwert: {val}"
                )
                assert 0 <= val <= 10, (
                    f"Score '{score_key}' in '{t.get('title')}' ausserhalb [0,10]: {val}"
                )


# ---------------------------------------------------------------------------
# Forschungsfragen und Pilot-Papers bleiben erhalten
# ---------------------------------------------------------------------------


class TestResearchQuestionsAndPapers:
    """Jeder Kandidat behaelt seine Forschungsfragen und Pilot-Papers aus dem Input."""

    def test_each_topic_has_research_questions(self):
        topics = _run_scorer(
            _BWL_TOPICS,
            interests=["Preisstrategie"],
            budget="6 Monate",
            data_access="Literatur-Only",
        )
        for t in topics:
            assert "research_questions" in t, (
                f"Kandidat '{t.get('title')}' fehlt 'research_questions'"
            )
            rqs = t["research_questions"]
            assert isinstance(rqs, list) and len(rqs) >= 1
            for rq in rqs:
                assert isinstance(rq, str) and rq.strip()

    def test_each_topic_has_pilot_papers(self):
        topics = _run_scorer(
            _BWL_TOPICS,
            interests=["Preisstrategie"],
            budget="6 Monate",
            data_access="Literatur-Only",
        )
        for t in topics:
            assert "pilot_papers" in t, f"Kandidat '{t.get('title')}' fehlt 'pilot_papers'"
            pp = t["pilot_papers"]
            assert isinstance(pp, list)
            assert len(pp) >= 1, f"'{t.get('title')}' hat kein Pilot-Paper"


# ---------------------------------------------------------------------------
# AC2: Jeder Vorschlag nennt einen Grund
# ---------------------------------------------------------------------------


class TestReasonField:
    """Jeder Kandidat hat ein nicht-leeres 'reason'-Feld (AC2)."""

    def test_each_topic_has_reason(self):
        topics = _run_scorer(
            _BWL_TOPICS,
            interests=["Preisstrategie"],
            budget="6 Monate",
            data_access="Literatur-Only",
        )
        for t in topics:
            assert "reason" in t, f"Kandidat '{t.get('title')}' fehlt 'reason'"
            assert isinstance(t["reason"], str) and t["reason"].strip(), (
                f"'reason' von '{t.get('title')}' muss ein nicht-leerer String sein"
            )

    def test_reason_matches_input_reason(self):
        """Der Scorer erfindet keine eigene Begruendung, sondern reicht sie durch."""
        topics = _run_scorer(
            _BWL_TOPICS,
            interests=["Preisstrategie"],
            budget="6 Monate",
            data_access="Literatur-Only",
        )
        input_reasons = {t["title"]: t["reason"] for t in _BWL_TOPICS}
        for t in topics:
            assert t["reason"] == input_reasons[t["title"]], (
                f"'reason' fuer '{t['title']}' wurde veraendert statt durchgereicht"
            )


# ---------------------------------------------------------------------------
# AC1 + AC4: Fachabhaengigkeit wird durchgereicht, nicht auf eine Domaene normalisiert
# ---------------------------------------------------------------------------


class TestFieldDependency:
    """Zwei fachlich unterschiedliche Kandidaten-Sets bleiben unveraendert und disjunkt."""

    def test_scorer_preserves_field_specific_titles_without_normalizing(self):
        """Titel im Output entsprechen exakt den Titeln im Input (kein Fallback/Rewrite)."""
        for fixture in (_BWL_TOPICS, _INFORMATIK_TOPICS):
            topics = _run_scorer(
                fixture,
                interests=["Forschung"],
                budget="6 Monate",
                data_access="Literatur-Only",
            )
            input_titles = {t["title"] for t in fixture}
            output_titles = {t["title"] for t in topics}
            assert output_titles == input_titles, (
                f"Scorer hat Titel veraendert/normalisiert: {output_titles} != {input_titles}"
            )

    def test_two_different_fields_yield_different_titles(self):
        """BWL- und Informatik-Kandidaten sind disjunkt — keine Normalisierung auf eine Domaene."""
        bwl_topics = _run_scorer(
            _BWL_TOPICS,
            interests=["Forschung"],
            budget="6 Monate",
            data_access="Literatur-Only",
        )
        informatik_topics = _run_scorer(
            _INFORMATIK_TOPICS,
            interests=["Forschung"],
            budget="6 Monate",
            data_access="Literatur-Only",
        )
        bwl_titles = {t["title"] for t in bwl_topics}
        informatik_titles = {t["title"] for t in informatik_topics}
        assert bwl_titles.isdisjoint(informatik_titles), (
            "BWL- und Informatik-Themenvorschlaege ueberschneiden sich — "
            "deutet auf Normalisierung/Fixed-Set hin"
        )


# ---------------------------------------------------------------------------
# AC1 (Fix-Runde PR #484): Ausfuehrungspfad der Fach-Kontrast-Eval-Prompts
# ---------------------------------------------------------------------------


class TestEvalContrastPromptsAreWired:
    """Die Fach-Kontrast-Prompts muessen von einem Runner eingesammelt werden.

    Der inhaltliche Teil von AC1 — dass das Modell bei zwei Anfragen aus
    unterschiedlichen Faechern selbst fachlich passende Themen entwirft — ist
    Generierungsverhalten und offline nicht messbar. Messbar und deshalb hier
    erzwungen ist, dass die dafuer zustaendigen Eval-Prompts ueberhaupt einen
    Ausfuehrungspfad haben: `tests/evals/test_triggers.py` liest ausschliesslich
    `trigger_evals.json`, und `tests/evals/test_rest_evals.py` sammelt nur die
    Komponenten aus seinen Listen ein. Stand PR #484 lag `topic-brainstorm` in
    keiner der beiden — tb-04/tb-05 waren tote Datei, auch mit API-Key.
    """

    def test_quality_prompts_are_collected_by_the_quality_runner(self):
        """Jeder Prompt aus evals.json wird vom Quality-Runner eingesammelt."""
        from tests.evals.test_rest_evals import PROMPTS

        defined = {p["id"] for p in _eval_prompts()}
        collected = {p["id"] for component, p in PROMPTS if component == "topic-brainstorm"}
        assert defined <= collected, (
            f"Eval-Prompts ohne Ausfuehrungspfad: {sorted(defined - collected)}. "
            "Sie stehen in evals/topic-brainstorm/evals.json, werden aber von keinem "
            "Runner eingesammelt und laufen daher auch mit ANTHROPIC_API_KEY nie."
        )

    def test_field_contrast_prompts_exist_with_field_specific_expectations(self):
        """tb-04/tb-05 pruefen je fachspezifische Begriffe, nicht dasselbe Muster."""
        by_id = {p["id"]: p for p in _eval_prompts()}
        assert {"tb-04", "tb-05"} <= set(by_id), (
            f"Fach-Kontrast-Prompts fehlen in {_EVALS_JSON}: {sorted(by_id)}"
        )
        tb04 = by_id["tb-04"]["expected"]["value"]
        tb05 = by_id["tb-05"]["expected"]["value"]
        assert tb04 != tb05, (
            "tb-04 und tb-05 pruefen dasselbe Erfolgskriterium — damit kontrastieren "
            "sie die Faecher nicht."
        )


# ---------------------------------------------------------------------------
# AC3: Keine feste Themenliste mehr im Code
# ---------------------------------------------------------------------------


class TestNoHardcodedTopicDatabase:
    """scorer.py enthaelt keine fest kodierte Themen-DB und keine Feld-Normalisierung mehr."""

    def test_topic_db_symbol_removed(self):
        source = _SCORER.read_text(encoding="utf-8")
        assert "_TOPIC_DB" not in source, "'_TOPIC_DB' darf nicht mehr in scorer.py vorkommen"

    def test_old_fixed_titles_removed(self):
        source = _SCORER.read_text(encoding="utf-8")
        for old_title in (
            "Cyber Security Awareness in KMU",
            "Ransomware-Resilienz in Kritischen Infrastrukturen",
            "Zero-Trust-Architektur in Cloud-nativen Unternehmensumgebungen",
            "Phishing-Erkennung mittels Machine Learning",
            "Datenschutz und DSGVO-Compliance in agilen Softwareentwicklungsprozessen",
        ):
            assert old_title not in source, (
                f"Alter Fixed-Titel noch in scorer.py vorhanden: {old_title!r}"
            )

    def test_field_normalization_removed(self):
        source = _SCORER.read_text(encoding="utf-8")
        assert "_normalize_field" not in source, (
            "'_normalize_field' (stiller Fach-Fallback) darf nicht mehr existieren"
        )
        assert "_FIELD_NORMALIZE" not in source, (
            "'_FIELD_NORMALIZE'-Mapping darf nicht mehr existieren"
        )


# ---------------------------------------------------------------------------
# Top-Topic wird korrekt identifiziert (hoechste Score-Summe)
# ---------------------------------------------------------------------------


class TestTopTopicIdentification:
    """Das Top-Topic ist das mit der hoechsten Summe der drei Scores."""

    def test_top_topic_has_highest_total_score(self):
        data = _run_scorer(
            _BWL_TOPICS,
            interests=["Preisstrategie"],
            budget="6 Monate",
            data_access="Literatur-Only",
            output_mode="full",
        )
        assert "topics" in data, "Vollstaendige Ausgabe muss 'topics' enthalten"
        assert "top_topic" in data, "Vollstaendige Ausgabe muss 'top_topic' enthalten"
        topics = data["topics"]
        top_title = data["top_topic"]
        top_candidate = next((t for t in topics if t["title"] == top_title), None)
        assert top_candidate is not None, f"top_topic '{top_title}' nicht in topics gefunden"
        top_score = (
            top_candidate["feasibility"] + top_candidate["novelty"] + top_candidate["career_fit"]
        )
        for t in topics:
            t_score = t["feasibility"] + t["novelty"] + t["career_fit"]
            assert top_score >= t_score, (
                f"Top-Topic '{top_title}' (Score {top_score}) hat niedrigeren Score als '{t['title']}' ({t_score})"
            )


# ---------------------------------------------------------------------------
# academic_context.md wird geschrieben (unveraenderter Mechanismus)
# ---------------------------------------------------------------------------


class TestAcademicContextWrite:
    """scorer.py --write-context schreibt das Top-Topic in academic_context.md."""

    def test_writes_top_topic_to_academic_context(self, tmp_path):
        ctx_file = tmp_path / "academic_context.md"
        ctx_file.write_text(
            "---\nname: academic-context\n---\n\n### Profil\n- Studiengang: BWL\n\n### Arbeit\n- Thema: [noch offen]\n",
            encoding="utf-8",
        )

        _run_scorer(
            _BWL_TOPICS,
            interests=["Preisstrategie"],
            budget="6 Monate",
            data_access="Literatur-Only",
            output_mode="full",
            extra_args=["--write-context", str(ctx_file)],
        )

        content = ctx_file.read_text(encoding="utf-8")
        assert "Thema:" in content
        assert "[noch offen]" not in content, (
            "academic_context.md Thema-Zeile wurde nicht aktualisiert"
        )

    def test_creates_context_file_if_missing(self, tmp_path):
        ctx_file = tmp_path / "academic_context.md"
        # Datei existiert NICHT

        _run_scorer(
            _BWL_TOPICS,
            interests=["Preisstrategie"],
            budget="6 Monate",
            data_access="Literatur-Only",
            output_mode="full",
            extra_args=["--write-context", str(ctx_file)],
        )

        assert ctx_file.exists(), "academic_context.md wurde nicht angelegt"
        content = ctx_file.read_text(encoding="utf-8")
        assert "Thema:" in content, "Neu angelegte Datei muss Thema enthalten"


# ---------------------------------------------------------------------------
# SKILL.md dupliziert KEINE Scoring-Tabellen (Issue #180)
# ---------------------------------------------------------------------------


class TestNoScoringTableDuplication:
    """SKILL.md darf die Scoring-Tabellen nicht duplizieren (Progressive Disclosure).

    Die Modifikator-Tabellen (Datenverfuegbarkeit, Zeitbudget, Studienrichtung)
    leben kanonisch in references/scoring-criteria.md. SKILL.md verweist nur darauf.
    """

    _SKILL_MD = _WORKTREE_ROOT / "skills" / "topic-brainstorm" / "SKILL.md"
    _SCORING_REF = (
        _WORKTREE_ROOT / "skills" / "topic-brainstorm" / "references" / "scoring-criteria.md"
    )

    def test_skill_md_has_no_data_access_table_rows(self):
        text = self._SKILL_MD.read_text(encoding="utf-8")
        for forbidden in (
            "| Public Datasets | +1.0 |",
            "| Literatur-Only | +0.5 |",
            "| Unternehmensdaten | -1.0 |",
        ):
            assert forbidden not in text, (
                f"SKILL.md dupliziert Scoring-Tabelle (gefunden: {forbidden!r}) "
                "— gehoert nach references/scoring-criteria.md"
            )

    def test_skill_md_has_no_time_budget_table_rows(self):
        text = self._SKILL_MD.read_text(encoding="utf-8")
        for forbidden in (
            "| 3 Monate | -1.0 |",
            "| 6 Monate | 0.0 |",
            "| 12 Monate | +1.0 |",
        ):
            assert forbidden not in text, (
                f"SKILL.md dupliziert Zeitbudget-Tabelle (gefunden: {forbidden!r})"
            )

    def test_skill_md_has_no_field_modifier_table(self):
        text = self._SKILL_MD.read_text(encoding="utf-8")
        assert "| Modifier-Referenz |" not in text, (
            "SKILL.md dupliziert Studienrichtung-Modifier-Tabelle "
            "— gehoert nach references/scoring-criteria.md"
        )

    def test_skill_md_references_scoring_criteria(self):
        text = self._SKILL_MD.read_text(encoding="utf-8")
        assert "references/scoring-criteria.md" in text, (
            "SKILL.md muss auf references/scoring-criteria.md verweisen"
        )

    def test_scoring_tables_remain_in_reference(self):
        ref = self._SCORING_REF.read_text(encoding="utf-8")
        assert "| Public Datasets | +1.0 |" in ref, (
            "Datenverfuegbarkeit-Tabelle fehlt in scoring-criteria.md"
        )
        assert "| 3 Monate | -1.0 |" in ref, "Zeitbudget-Tabelle fehlt in scoring-criteria.md"


# ---------------------------------------------------------------------------
# skill_sizes.json enthaelt 'topic-brainstorm'
# ---------------------------------------------------------------------------


class TestSkillSizes:
    """tests/baselines/skill_sizes.json enthaelt 'topic-brainstorm'."""

    def test_skill_sizes_contains_topic_brainstorm(self):
        sizes_path = _WORKTREE_ROOT / "tests" / "baselines" / "skill_sizes.json"
        sizes = json.loads(sizes_path.read_text())
        assert "topic-brainstorm" in sizes, (
            "skill_sizes.json enthaelt keinen 'topic-brainstorm'-Eintrag"
        )
        assert sizes["topic-brainstorm"] > 0, (
            "skill_sizes.json 'topic-brainstorm'-Wert muss > 0 sein"
        )
