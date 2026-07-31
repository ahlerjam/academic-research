"""Tests fuer Topic-Brainstorm Skill (Issue #471 — fachabhaengige Themenfindung).

TDD: scorer.py hat KEINE feste Themen-Datenbank mehr. Kandidaten kommen ueber
`--topics-json` vom Aufrufer (in der Praxis: vom Modell in SKILL.md Schritt 2
entworfen). Diese Tests beweisen die Mechanik:

- Keine feste Themenliste mehr in scorer.py ODER SKILL.md (AC1, grep-pruefbar)
- Fach/Arbeitstyp/Umfang/Interessen sind Pflicht-Eingaben, die unveraendert
  (ohne Normalisierung/Fallback) durchgereicht werden (AC2)
- Die Skill-Anweisung verlangt je Vorschlag eine Begruendung sowie Hinweise
  auf Machbarkeit und Quellenlage (AC3)

Reale LLM-Ausgabequalitaet ("fachlich passende Vorschlaege") ist bewusst kein
Akzeptanzkriterium (kein Eval-Budget, vgl. Issue #55) — geprueft wird
ausschliesslich die Mechanik (Datenfuehrung, Skill-Text, Fixtures).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_WORKTREE_ROOT = Path(__file__).parent.parent

_SCORER = _WORKTREE_ROOT / "skills" / "topic-brainstorm" / "scripts" / "scorer.py"
_SKILL_MD = _WORKTREE_ROOT / "skills" / "topic-brainstorm" / "SKILL.md"

# Die 5 alten, hartkodierten Fix-Titel aus der ehemaligen `_TOPIC_DB` (Issue #471
# Root Cause) — duerfen weder in scorer.py noch in SKILL.md mehr vorkommen.
_OLD_HARDCODED_TITLES = [
    "Cyber Security Awareness in KMU",
    "Ransomware-Resilienz in Kritischen Infrastrukturen",
    "Zero-Trust-Architektur in Cloud-nativen Unternehmensumgebungen",
    "Phishing-Erkennung mittels Machine Learning",
    "Datenschutz und DSGVO-Compliance in agilen Softwareentwicklungsprozessen",
]


# ---------------------------------------------------------------------------
# Fixture-Helper
# ---------------------------------------------------------------------------


def _make_topic(
    title: str,
    *,
    keywords: list[str] | None = None,
    reason: str = "Passt zum genannten Zuschnitt.",
    feasibility_note: str = "Im Zeitbudget mit dem angegebenen Datenzugang machbar.",
    source_note: str = "Ausreichend Literatur zu erwarten.",
    base_feasibility: float = 7.0,
    base_novelty: float = 6.0,
    base_career_fit: float = 7.0,
    research_questions: list[str] | None = None,
    pilot_papers: list[str] | None = None,
) -> dict:
    return {
        "title": title,
        "keywords": keywords or ["stichwort"],
        "reason": reason,
        "feasibility_note": feasibility_note,
        "source_note": source_note,
        "base_feasibility": base_feasibility,
        "base_novelty": base_novelty,
        "base_career_fit": base_career_fit,
        "research_questions": research_questions or ["Forschungsfrage A?", "Forschungsfrage B?"],
        "pilot_papers": pilot_papers or ["Autor (2020): Titel, Venue"],
    }


_DEFAULT_TOPICS = [_make_topic(f"Kandidat {i}", base_career_fit=5.0 + i) for i in range(5)]

_BWL_TOPICS = [
    _make_topic(
        "Preisstrategien im stationären Einzelhandel unter Inflationsdruck",
        keywords=["pricing", "einzelhandel", "inflation"],
        reason="Passt zur BWL, Preistheorie ist Kernkompetenz.",
    ),
    _make_topic(
        "Controlling-Kennzahlen zur Nachhaltigkeitsberichterstattung (CSRD)",
        keywords=["csrd", "controlling", "nachhaltigkeit"],
        reason="Passt zur BWL, CSRD-Pflicht betrifft Unternehmenssteuerung.",
    ),
    _make_topic(
        "Wertschöpfungskettenanalyse in mittelständischen Handelsunternehmen",
        keywords=["wertschöpfung", "handel", "mittelstand"],
        reason="Passt zur BWL-Studienrichtung und zum Interesse Handel.",
    ),
]

_INFORMATIK_TOPICS = [
    _make_topic(
        "Fehlererkennung im Pulverbett-3D-Druck mittels Convolutional Neural Networks",
        keywords=["cnn", "additive fertigung", "pulverbett"],
        reason="Passt zur Informatik, CNN-Methodik ist Kerninhalt des Studiums.",
    ),
    _make_topic(
        "Ressourcenoptimierung verteilter Systeme durch Reinforcement Learning",
        keywords=["reinforcement learning", "verteilte systeme"],
        reason="Passt zur Informatik-Studienrichtung.",
    ),
    _make_topic(
        "Topologieoptimierung von Bauteilen mittels genetischer Algorithmen",
        keywords=["topologieoptimierung", "genetische algorithmen"],
        reason="Passt zur Informatik und zum Interesse an Optimierungsverfahren.",
    ),
]


def _write_topics_json(tmp_path: Path, topics: list[dict], name: str = "topics.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(topics, ensure_ascii=False), encoding="utf-8")
    return path


def _run_scorer_raw(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCORER), *args],
        capture_output=True,
        text=True,
    )


def _run_scorer(
    tmp_path: Path,
    topics: list[dict],
    *,
    interests: str = "Cyber Security",
    field: str = "Wirtschaftsinformatik-Bachelor",
    work_type: str = "Bachelorarbeit",
    scope: str = "60 Seiten",
    budget: str = "6 Monate",
    data_access: str = "Public Datasets",
    output_mode: str = "list",
):
    topics_path = _write_topics_json(tmp_path, topics)
    result = _run_scorer_raw(
        [
            "--topics-json",
            str(topics_path),
            "--interests",
            interests,
            "--field",
            field,
            "--work-type",
            work_type,
            "--scope",
            scope,
            "--budget",
            budget,
            "--data-access",
            data_access,
            "--output-mode",
            output_mode,
        ]
    )
    assert result.returncode == 0, (
        f"scorer.py exitcode {result.returncode}\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# AC1: Keine feste Themenliste mehr im Code oder Skill-Text (grep-pruefbar)
# ---------------------------------------------------------------------------


class TestNoHardcodedTopicDatabase:
    """Keine feste Themen-DB mehr in scorer.py oder SKILL.md (Issue #471 AC1)."""

    def test_no_topic_db_attribute_in_scorer(self):
        text = _SCORER.read_text(encoding="utf-8")
        assert "_TOPIC_DB" not in text, "scorer.py enthaelt noch eine _TOPIC_DB"
        assert "def _normalize_field" not in text, (
            "scorer.py enthaelt noch eine _normalize_field-Funktion"
        )
        assert "_FIELD_NORMALIZE =" not in text, (
            "scorer.py enthaelt noch ein _FIELD_NORMALIZE-Mapping"
        )

        import importlib.util

        spec = importlib.util.spec_from_file_location("_topic_brainstorm_scorer", _SCORER)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert not hasattr(module, "_TOPIC_DB")
        assert not hasattr(module, "_normalize_field")
        assert not hasattr(module, "_FIELD_NORMALIZE")

    def test_old_fixed_titles_absent_from_scorer(self):
        text = _SCORER.read_text(encoding="utf-8")
        for title in _OLD_HARDCODED_TITLES:
            assert title not in text, f"scorer.py enthaelt noch alten Fix-Titel: {title!r}"

    def test_old_fixed_titles_absent_from_skill_md(self):
        text = _SKILL_MD.read_text(encoding="utf-8")
        for title in _OLD_HARDCODED_TITLES:
            assert title not in text, f"SKILL.md enthaelt noch alten Fix-Titel: {title!r}"

    def test_skill_md_states_no_fixed_topic_list(self):
        text = _SKILL_MD.read_text(encoding="utf-8")
        assert "keine feste themenliste" in text.lower(), (
            "SKILL.md muss explizit festhalten, dass es keine feste Themenliste gibt"
        )


# ---------------------------------------------------------------------------
# AC2: Fach, Arbeitstyp, Umfang, Interessen als Pflicht-Eingaben — unveraendert
# ---------------------------------------------------------------------------


class TestRequiredGenerationInputsEnforced:
    """--field/--work-type/--scope/--interests sind Pflicht-CLI-Args ohne Fallback."""

    def test_missing_work_type_fails(self, tmp_path):
        topics_path = _write_topics_json(tmp_path, _DEFAULT_TOPICS)
        result = _run_scorer_raw(
            [
                "--topics-json",
                str(topics_path),
                "--interests",
                "Cyber Security",
                "--field",
                "BWL",
                "--scope",
                "60 Seiten",
                "--budget",
                "6 Monate",
                "--data-access",
                "Public Datasets",
            ]
        )
        assert result.returncode != 0, "scorer.py darf ohne --work-type nicht erfolgreich laufen"

    def test_missing_scope_fails(self, tmp_path):
        topics_path = _write_topics_json(tmp_path, _DEFAULT_TOPICS)
        result = _run_scorer_raw(
            [
                "--topics-json",
                str(topics_path),
                "--interests",
                "Cyber Security",
                "--field",
                "BWL",
                "--work-type",
                "Bachelorarbeit",
                "--budget",
                "6 Monate",
                "--data-access",
                "Public Datasets",
            ]
        )
        assert result.returncode != 0, "scorer.py darf ohne --scope nicht erfolgreich laufen"

    def test_missing_field_fails(self, tmp_path):
        topics_path = _write_topics_json(tmp_path, _DEFAULT_TOPICS)
        result = _run_scorer_raw(
            [
                "--topics-json",
                str(topics_path),
                "--interests",
                "Cyber Security",
                "--work-type",
                "Bachelorarbeit",
                "--scope",
                "60 Seiten",
                "--budget",
                "6 Monate",
                "--data-access",
                "Public Datasets",
            ]
        )
        assert result.returncode != 0, "scorer.py darf ohne --field nicht erfolgreich laufen"

    def test_context_echoes_field_work_type_scope_interests_unchanged(self, tmp_path):
        """Fach/Arbeitstyp/Umfang/Interessen erreichen die Ausgabe unveraendert."""
        data = _run_scorer(
            tmp_path,
            _DEFAULT_TOPICS,
            interests="Additive Fertigung, Robotik",
            field="Maschinenbau",
            work_type="Masterarbeit",
            scope="90 Seiten",
            output_mode="full",
        )
        assert data["context"]["field"] == "Maschinenbau"
        assert data["context"]["work_type"] == "Masterarbeit"
        assert data["context"]["scope"] == "90 Seiten"
        assert data["context"]["interests"] == ["Additive Fertigung", "Robotik"]


class TestTwoFieldFixturesPreserveInputWithoutNormalizing:
    """Zwei disjunkte Fach-Fixtures fuehren zu disjunkten, unveraenderten Titeln (AC2)."""

    def test_bwl_and_informatik_fixtures_yield_disjoint_titles(self, tmp_path):
        bwl_dir = tmp_path / "bwl"
        bwl_dir.mkdir()
        informatik_dir = tmp_path / "informatik"
        informatik_dir.mkdir()

        bwl = _run_scorer(
            bwl_dir,
            _BWL_TOPICS,
            field="BWL",
            work_type="Bachelorarbeit",
            scope="50 Seiten",
            interests="Nachhaltigkeit",
        )
        informatik = _run_scorer(
            informatik_dir,
            _INFORMATIK_TOPICS,
            field="Maschinenbau",  # bislang silent auf "Wirtschaftsinformatik" normalisiert
            work_type="Masterarbeit",
            scope="90 Seiten",
            interests="Additive Fertigung",
        )

        bwl_titles = {t["title"] for t in bwl}
        informatik_titles = {t["title"] for t in informatik}

        assert bwl_titles == {t["title"] for t in _BWL_TOPICS}, (
            "Scorer darf Input-Titel nicht veraendern"
        )
        assert informatik_titles == {t["title"] for t in _INFORMATIK_TOPICS}, (
            "Scorer darf Input-Titel nicht veraendern"
        )
        assert bwl_titles.isdisjoint(informatik_titles), (
            "Zwei fachlich unterschiedliche Kandidaten-Sets muessen disjunkt bleiben "
            "statt auf eine Domäne normalisiert zu werden"
        )

    def test_unknown_field_maschinenbau_is_not_silently_remapped(self, tmp_path):
        """'Maschinenbau' wurde frueher still auf 'Wirtschaftsinformatik' gemappt."""
        data = _run_scorer(
            tmp_path,
            _INFORMATIK_TOPICS,
            field="Maschinenbau",
            work_type="Masterarbeit",
            scope="90 Seiten",
            output_mode="full",
        )
        assert data["context"]["field"] == "Maschinenbau", (
            "'Maschinenbau' darf nicht mehr still auf einen anderen Wert gemappt werden"
        )


# ---------------------------------------------------------------------------
# AC3: Skill-Anweisung verlangt Begruendung + Machbarkeit + Quellenlage
# ---------------------------------------------------------------------------


class TestSkillMdRequiresReasonAndHints:
    """SKILL.md verlangt je Vorschlag reason + Machbarkeits-/Quellenlage-Hinweis."""

    def test_skill_md_requires_reason_field(self):
        text = _SKILL_MD.read_text(encoding="utf-8")
        assert "`reason`" in text and "Pflichtfeld" in text, (
            "SKILL.md muss 'reason' als Pflichtfeld je Kandidat fordern"
        )

    def test_skill_md_requires_feasibility_hint(self):
        text = _SKILL_MD.read_text(encoding="utf-8")
        assert "feasibility_note" in text and "Machbarkeit" in text, (
            "SKILL.md muss einen Machbarkeitshinweis je Kandidat fordern"
        )

    def test_skill_md_requires_source_hint(self):
        text = _SKILL_MD.read_text(encoding="utf-8")
        assert "source_note" in text and "Quellenlage" in text, (
            "SKILL.md muss einen Quellenlage-Hinweis je Kandidat fordern"
        )


class TestEachTopicHasReasonFeasibilitySourceNote:
    """scorer.py reicht reason/feasibility_note/source_note nicht-leer durch."""

    def test_each_topic_has_reason_feasibility_source_note(self, tmp_path):
        topics = _run_scorer(tmp_path, _BWL_TOPICS)
        for t in topics:
            for field in ("reason", "feasibility_note", "source_note"):
                assert field in t, f"Kandidat '{t.get('title')}' fehlt '{field}'"
                assert isinstance(t[field], str) and t[field].strip(), (
                    f"'{field}' von '{t.get('title')}' muss ein nicht-leerer String sein"
                )

    def test_missing_reason_in_input_rejected(self, tmp_path):
        """scorer.py darf keinen Kandidaten ohne 'reason' akzeptieren."""
        broken = [_make_topic("Ohne Begruendung")]
        del broken[0]["reason"]
        topics_path = _write_topics_json(tmp_path, broken)
        result = _run_scorer_raw(
            [
                "--topics-json",
                str(topics_path),
                "--interests",
                "Cyber Security",
                "--field",
                "BWL",
                "--work-type",
                "Bachelorarbeit",
                "--scope",
                "60 Seiten",
                "--budget",
                "6 Monate",
                "--data-access",
                "Public Datasets",
            ]
        )
        assert result.returncode != 0, "scorer.py darf Kandidaten ohne 'reason' nicht annehmen"


# ---------------------------------------------------------------------------
# Score-Ranges und Struktur (weiterhin gueltig — jetzt mit uebergebenen Kandidaten)
# ---------------------------------------------------------------------------


class TestScoreRanges:
    """Feasibility, Novelty, Career-Fit sind normiert auf 0-10."""

    def test_all_three_scores_present(self, tmp_path):
        topics = _run_scorer(tmp_path, _DEFAULT_TOPICS)
        for t in topics:
            for score_key in ("feasibility", "novelty", "career_fit"):
                assert score_key in t, f"Kandidat '{t.get('title')}' fehlt '{score_key}'"

    def test_scores_normalized_0_to_10(self, tmp_path):
        topics = _run_scorer(tmp_path, _DEFAULT_TOPICS)
        for t in topics:
            for score_key in ("feasibility", "novelty", "career_fit"):
                val = t[score_key]
                assert isinstance(val, (int, float)), (
                    f"Score '{score_key}' in '{t.get('title')}' ist kein Zahlenwert: {val}"
                )
                assert 0 <= val <= 10, (
                    f"Score '{score_key}' in '{t.get('title')}' ausserhalb [0,10]: {val}"
                )


class TestResearchQuestionsAndPapers:
    """Jeder Kandidat hat Forschungsfragen und ein Pilot-Paper-Set."""

    def test_each_topic_has_research_questions(self, tmp_path):
        topics = _run_scorer(tmp_path, _DEFAULT_TOPICS)
        for t in topics:
            assert "research_questions" in t
            rqs = t["research_questions"]
            assert isinstance(rqs, list) and len(rqs) >= 1
            for rq in rqs:
                assert isinstance(rq, str) and rq.strip()

    def test_each_topic_has_pilot_papers(self, tmp_path):
        topics = _run_scorer(tmp_path, _DEFAULT_TOPICS)
        for t in topics:
            assert "pilot_papers" in t
            pp = t["pilot_papers"]
            assert isinstance(pp, list) and len(pp) >= 1


class TestTopTopicIdentification:
    """Das Top-Topic ist das mit der hoechsten Summe der drei Scores."""

    def test_top_topic_has_highest_total_score(self, tmp_path):
        data = _run_scorer(tmp_path, _DEFAULT_TOPICS, output_mode="full")
        assert "topics" in data
        assert "top_topic" in data
        topics = data["topics"]
        top_title = data["top_topic"]
        top_candidate = next((t for t in topics if t["title"] == top_title), None)
        assert top_candidate is not None
        top_score = (
            top_candidate["feasibility"] + top_candidate["novelty"] + top_candidate["career_fit"]
        )
        for t in topics:
            t_score = t["feasibility"] + t["novelty"] + t["career_fit"]
            assert top_score >= t_score


# ---------------------------------------------------------------------------
# Context-Datei schreiben
# ---------------------------------------------------------------------------


class TestAcademicContextWrite:
    """scorer.py --write-context schreibt das Top-Topic in academic_context.md."""

    def test_writes_top_topic_to_academic_context(self, tmp_path):
        ctx_file = tmp_path / "academic_context.md"
        ctx_file.write_text(
            "---\nname: academic-context\n---\n\n### Profil\n- Studiengang: Wirtschaftsinformatik\n\n### Arbeit\n- Thema: [noch offen]\n",
            encoding="utf-8",
        )
        topics_path = _write_topics_json(tmp_path, _DEFAULT_TOPICS, name="topics_write.json")
        result = _run_scorer_raw(
            [
                "--topics-json",
                str(topics_path),
                "--interests",
                "Cyber Security",
                "--field",
                "Wirtschaftsinformatik-Bachelor",
                "--work-type",
                "Bachelorarbeit",
                "--scope",
                "60 Seiten",
                "--budget",
                "6 Monate",
                "--data-access",
                "Public Datasets",
                "--output-mode",
                "full",
                "--write-context",
                str(ctx_file),
            ]
        )
        assert result.returncode == 0, f"STDERR: {result.stderr}"
        content = ctx_file.read_text(encoding="utf-8")
        assert "[noch offen]" not in content

    def test_creates_context_file_if_missing(self, tmp_path):
        ctx_file = tmp_path / "academic_context.md"
        topics_path = _write_topics_json(tmp_path, _DEFAULT_TOPICS, name="topics_create.json")
        result = _run_scorer_raw(
            [
                "--topics-json",
                str(topics_path),
                "--interests",
                "Cyber Security",
                "--field",
                "Wirtschaftsinformatik-Bachelor",
                "--work-type",
                "Bachelorarbeit",
                "--scope",
                "60 Seiten",
                "--budget",
                "6 Monate",
                "--data-access",
                "Public Datasets",
                "--output-mode",
                "full",
                "--write-context",
                str(ctx_file),
            ]
        )
        assert result.returncode == 0, f"STDERR: {result.stderr}"
        assert ctx_file.exists()
        assert "Thema:" in ctx_file.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# SKILL.md dupliziert KEINE Scoring-Tabellen (Issue #180)
# ---------------------------------------------------------------------------


class TestNoScoringTableDuplication:
    """SKILL.md darf die Scoring-Tabellen nicht duplizieren (Progressive Disclosure).

    Die Modifikator-Tabellen (Datenverfuegbarkeit, Zeitbudget, Studienrichtung)
    leben kanonisch in references/scoring-criteria.md. SKILL.md verweist nur darauf.
    """

    _SCORING_REF = (
        _WORKTREE_ROOT / "skills" / "topic-brainstorm" / "references" / "scoring-criteria.md"
    )

    def test_skill_md_has_no_data_access_table_rows(self):
        text = _SKILL_MD.read_text(encoding="utf-8")
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
        text = _SKILL_MD.read_text(encoding="utf-8")
        for forbidden in (
            "| 3 Monate | -1.0 |",
            "| 6 Monate | 0.0 |",
            "| 12 Monate | +1.0 |",
        ):
            assert forbidden not in text, (
                f"SKILL.md dupliziert Zeitbudget-Tabelle (gefunden: {forbidden!r})"
            )

    def test_skill_md_has_no_field_modifier_table(self):
        text = _SKILL_MD.read_text(encoding="utf-8")
        assert "| Modifier-Referenz |" not in text, (
            "SKILL.md dupliziert Studienrichtung-Modifier-Tabelle "
            "— gehoert nach references/scoring-criteria.md"
        )

    def test_skill_md_references_scoring_criteria(self):
        text = _SKILL_MD.read_text(encoding="utf-8")
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
        assert "topic-brainstorm" in sizes
        assert sizes["topic-brainstorm"] > 0
