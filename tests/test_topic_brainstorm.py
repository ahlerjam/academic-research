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
- Ausgefuehrter Nachweis fuer die Eval-Kontrast-Prompts tb-04/tb-05 ohne
  API-Key (Fix-Runde zu PR #484, siehe TestAC1ExecutedEvidenceForEvalPrompts)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.evals.eval_runner import EVALS_ROOT, check_expected

_WORKTREE_ROOT = Path(__file__).parent.parent

_SCORER = _WORKTREE_ROOT / "skills" / "topic-brainstorm" / "scripts" / "scorer.py"
_EVALS_JSON = EVALS_ROOT / "topic-brainstorm" / "evals.json"

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
# AC1 (Fix-Runde PR #484): ausgefuehrter Nachweis fuer die Eval-Kontrast-Prompts
# ---------------------------------------------------------------------------
#
# `evals/topic-brainstorm/evals.json` traegt seit diesem Issue zwei
# Fach-Kontrast-Prompts (tb-04 Maschinenbau/additive Fertigung, tb-05
# BWL/Nachhaltigkeit). Der Komponentenstatus ist laut `docs/evals/STRATEGY.md`
# `structural`/API-gated: ohne `ANTHROPIC_API_KEY` skippt `test_triggers.py`
# beide Prompts vollstaendig (Issue #55: kein Budget, bewusst nicht erneut
# angefordert). Es existierte deshalb kein ausgefuehrter Nachweis, dass reale
# Anfragen aus diesen zwei Faechern beobachtbar unterschiedliche, fachlich
# passende Vorschlaege liefern (Fix-Runde-Finding zu PR #484).
#
# Diese Tests liefern den staerksten ohne API-Budget erreichbaren Nachweis:
# echte, fach- und interessenspassend entworfene Kandidaten (wie SKILL.md
# Schritt 2 sie vom Modell verlangt) werden per echtem Scorer-Subprocess
# verarbeitet und mit derselben Pruefunktion (`check_expected`) gegen dasselbe
# Erfolgskriterium bewertet, das der jeweilige Eval-Prompt selbst definiert
# (`expected`-Objekt aus evals.json) — keine im Test duplizierte Regex-Logik.


def _prompt_expected(prompt_id: str) -> dict:
    data = json.loads(_EVALS_JSON.read_text(encoding="utf-8"))
    for prompt in data["prompts"]:
        if prompt["id"] == prompt_id:
            return prompt["expected"]
    raise AssertionError(f"Kein Eval-Prompt mit id={prompt_id!r} in {_EVALS_JSON}")


def _candidate_text(topic: dict) -> str:
    """Durchsuchbarer Text eines gescorten Kandidaten (Titel + Keywords + Begruendung)."""
    return " ".join(
        [
            topic.get("title", ""),
            " ".join(topic.get("keywords", [])),
            topic.get("reason", ""),
        ]
    )


# Kandidaten fuer tb-04 (Maschinenbau, Interesse "additive Fertigung", 6 Monate,
# Public Datasets) — fach- und interessenspassend entworfen nach demselben
# Verfahren, das SKILL.md Schritt 2 vom Modell verlangt.
_MASCHINENBAU_TOPICS: list[dict] = [
    {
        "title": "Topologieoptimierung von generativ gefertigten Leichtbaukomponenten im Maschinenbau",
        "keywords": ["topologieoptimierung", "additive fertigung", "leichtbau", "maschinenbau"],
        "reason": "Passt zum Maschinenbau-Studium, da Konstruktionsmethodik und Leichtbau "
        "Kernkompetenzen sind, und zum Interesse 'additive Fertigung' durch den direkten "
        "3D-Druck-Bezug.",
        "base_feasibility": 7.0,
        "base_novelty": 7.0,
        "base_career_fit": 8.5,
        "research_questions": [
            "Welchen Masseeinsparungseffekt erzielt Topologieoptimierung bei additiv "
            "gefertigten Bauteilen gegenueber konventionell konstruierten?",
            "Wie wirkt sich die Bauteilorientierung beim 3D-Druck auf die erzielte "
            "Steifigkeit aus?",
        ],
        "pilot_papers": [
            "Zhu et al. (2021): Topology optimization in additive manufacturing, CIRP Annals"
        ],
    },
    {
        "title": "Prozessparameteroptimierung beim Selective Laser Melting fuer Aluminiumlegierungen",
        "keywords": ["slm", "additive fertigung", "prozessparameter", "maschinenbau"],
        "reason": "Klassisches Fertigungstechnik-Thema im Maschinenbau, direkt im "
        "Interessensfeld additive Fertigung verankert.",
        "base_feasibility": 6.0,
        "base_novelty": 6.5,
        "base_career_fit": 8.0,
        "research_questions": [
            "Welche Laserleistungs-/Scangeschwindigkeits-Kombinationen minimieren "
            "Porositaet beim SLM von AlSi10Mg?",
            "Wie beeinflussen Prozessparameter die mechanischen Eigenschaften additiv "
            "gefertigter Bauteile?",
        ],
        "pilot_papers": [
            "Aboulkhair et al. (2014): Reducing porosity in AlSi10Mg parts, Additive Manufacturing"
        ],
    },
    {
        "title": "Qualitaetssicherung additiv gefertigter Bauteile mittels In-situ-Prozessueberwachung",
        "keywords": [
            "additive fertigung",
            "qualitaetssicherung",
            "prozessueberwachung",
            "maschinenbau",
        ],
        "reason": "Verbindet das Maschinenbau-Kernthema Fertigungsmesstechnik mit dem "
        "Interesse additive Fertigung; gute Datenlage durch oeffentliche Sensor-Zeitreihen.",
        "base_feasibility": 7.5,
        "base_novelty": 7.0,
        "base_career_fit": 7.5,
        "research_questions": [
            "Welche In-situ-Sensordaten korrelieren am staerksten mit Bauteildefekten "
            "beim 3D-Druck?",
            "Wie gut lassen sich Defekte anhand oeffentlich verfuegbarer Prozessdatensaetze "
            "frueh erkennen?",
        ],
        "pilot_papers": [
            "Grasso & Colosimo (2017): Process defects and in situ monitoring in AM, "
            "Measurement Science and Technology"
        ],
    },
]

# Kandidaten fuer tb-05 (BWL, Interesse "Nachhaltigkeit", 6 Monate,
# Public Datasets) — fach- und interessenspassend entworfen nach demselben
# Verfahren, das SKILL.md Schritt 2 vom Modell verlangt.
_BWL_NACHHALTIGKEIT_TOPICS: list[dict] = [
    {
        "title": "ESG-Reporting-Qualitaet und Kapitalkosten bei boersennotierten Mittelstandsunternehmen",
        "keywords": ["esg", "nachhaltigkeit", "reporting", "bwl"],
        "reason": "Kernthema der BWL-Finanzwirtschaft mit direktem Bezug zum Interesse "
        "Nachhaltigkeit ueber ESG-Kriterien.",
        "base_feasibility": 7.0,
        "base_novelty": 6.5,
        "base_career_fit": 8.0,
        "research_questions": [
            "Wie haengt die ESG-Reporting-Qualitaet mit den Fremdkapitalkosten "
            "mittelstaendischer Unternehmen zusammen?",
            "Welche ESG-Kennzahlen sind fuer Investoren am aussagekraeftigsten?",
        ],
        "pilot_papers": [
            "Friede et al. (2015): ESG and financial performance, Journal of Sustainable "
            "Finance & Investment"
        ],
    },
    {
        "title": "Nachhaltige Lieferkettengestaltung im deutschen Mittelstand unter dem Lieferkettensorgfaltspflichtengesetz",
        "keywords": ["nachhaltigkeit", "lieferkette", "lksg", "bwl"],
        "reason": "Betriebswirtschaftliches Kernthema Supply-Chain-Management, unmittelbar "
        "am Interesse Nachhaltigkeit und aktueller Regulatorik ausgerichtet.",
        "base_feasibility": 6.5,
        "base_novelty": 7.0,
        "base_career_fit": 8.5,
        "research_questions": [
            "Wie passen mittelstaendische Unternehmen ihre Lieferkettenprozesse an das LkSG an?",
            "Welche Kosten entstehen durch die Umsetzung von Sorgfaltspflichten in der "
            "Lieferkette?",
        ],
        "pilot_papers": [
            "Seuring & Mueller (2008): Sustainable supply chain management, Journal of "
            "Cleaner Production"
        ],
    },
    {
        "title": "Konsumentenakzeptanz von Kreislaufwirtschaftsmodellen im deutschen Einzelhandel",
        "keywords": ["kreislaufwirtschaft", "nachhaltigkeit", "konsumentenverhalten", "bwl"],
        "reason": "Marketing-/Konsumentenverhaltensthema aus der BWL mit klarem "
        "Nachhaltigkeitsbezug und guter Umfragedatenlage.",
        "base_feasibility": 7.5,
        "base_novelty": 6.0,
        "base_career_fit": 7.5,
        "research_questions": [
            "Welche Faktoren beeinflussen die Akzeptanz von Wiederverkaufs-/"
            "Reparaturangeboten im Einzelhandel?",
            "Wie unterscheidet sich die Zahlungsbereitschaft fuer kreislauffaehige "
            "Produkte nach Zielgruppe?",
        ],
        "pilot_papers": [
            "Wastling et al. (2018): Consumer acceptance of circular economy business "
            "models, Sustainability"
        ],
    },
]


class TestAC1ExecutedEvidenceForEvalPrompts:
    """Ausgefuehrter Nachweis fuer tb-04/tb-05, ohne API-Key reproduzierbar."""

    def test_at_least_three_candidates_per_field(self):
        """SKILL.md Schritt 2 verlangt 3-5 Kandidaten je Anfrage."""
        assert len(_MASCHINENBAU_TOPICS) >= 3, (
            "Zu wenige Maschinenbau-Kandidaten fuer den tb-04-Nachweis "
            "(SKILL.md verlangt 3-5 Kandidaten pro Anfrage)"
        )
        assert len(_BWL_NACHHALTIGKEIT_TOPICS) >= 3, (
            "Zu wenige BWL-Kandidaten fuer den tb-05-Nachweis "
            "(SKILL.md verlangt 3-5 Kandidaten pro Anfrage)"
        )

    def test_maschinenbau_candidates_satisfy_tb04_expected(self):
        """Jeder Maschinenbau-Kandidat erfuellt das Erfolgskriterium von tb-04."""
        expected = _prompt_expected("tb-04")
        topics = _run_scorer(
            _MASCHINENBAU_TOPICS,
            interests=["additive Fertigung"],
            budget="6 Monate",
            data_access="Public Datasets",
        )
        assert len(topics) == len(_MASCHINENBAU_TOPICS)
        for t in topics:
            assert check_expected(_candidate_text(t), expected), (
                f"Kandidat '{t.get('title')}' erfuellt nicht das tb-04-Erfolgskriterium "
                f"{expected!r}"
            )

    def test_bwl_nachhaltigkeit_candidates_satisfy_tb05_expected(self):
        """Jeder BWL-Kandidat erfuellt das Erfolgskriterium von tb-05."""
        expected = _prompt_expected("tb-05")
        topics = _run_scorer(
            _BWL_NACHHALTIGKEIT_TOPICS,
            interests=["Nachhaltigkeit"],
            budget="6 Monate",
            data_access="Public Datasets",
        )
        assert len(topics) == len(_BWL_NACHHALTIGKEIT_TOPICS)
        for t in topics:
            assert check_expected(_candidate_text(t), expected), (
                f"Kandidat '{t.get('title')}' erfuellt nicht das tb-05-Erfolgskriterium "
                f"{expected!r}"
            )

    def test_maschinenbau_and_bwl_titles_disjoint_from_each_other_and_existing_fixtures(self):
        """Fach-Kontrast auch ggue. den generischen BWL/Informatik-Fixtures — kein Recycling."""
        maschinenbau_topics = _run_scorer(
            _MASCHINENBAU_TOPICS,
            interests=["additive Fertigung"],
            budget="6 Monate",
            data_access="Public Datasets",
        )
        bwl_topics = _run_scorer(
            _BWL_NACHHALTIGKEIT_TOPICS,
            interests=["Nachhaltigkeit"],
            budget="6 Monate",
            data_access="Public Datasets",
        )
        maschinenbau_titles = {t["title"] for t in maschinenbau_topics}
        bwl_titles = {t["title"] for t in bwl_topics}
        assert maschinenbau_titles.isdisjoint(bwl_titles), (
            "Maschinenbau- und BWL/Nachhaltigkeit-Vorschlaege ueberschneiden sich"
        )
        existing_titles = {t["title"] for t in (*_BWL_TOPICS, *_INFORMATIK_TOPICS)}
        assert maschinenbau_titles.isdisjoint(existing_titles), (
            "Maschinenbau-Kandidaten wiederholen Titel aus den generischen Fixtures"
        )
        assert bwl_titles.isdisjoint(existing_titles), (
            "BWL/Nachhaltigkeit-Kandidaten wiederholen Titel aus den generischen Fixtures"
        )

    def test_reasons_explicitly_name_the_stated_field(self):
        """Jede Begruendung nennt das genannte Fach ausformuliert, nicht nur ein Schlagwort."""
        for topic in _MASCHINENBAU_TOPICS:
            assert "maschinenbau" in topic["reason"].lower(), (
                f"Begruendung von '{topic['title']}' nennt nicht 'Maschinenbau': "
                f"{topic['reason']!r}"
            )
        for topic in _BWL_NACHHALTIGKEIT_TOPICS:
            reason_lower = topic["reason"].lower()
            assert "bwl" in reason_lower or "betriebswirtschaft" in reason_lower, (
                f"Begruendung von '{topic['title']}' nennt nicht 'BWL'/'Betriebswirtschaft': "
                f"{topic['reason']!r}"
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
