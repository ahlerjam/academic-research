"""Tests fuer Issue #617 -- model_versions im Material-Passport befuellen.

Befund: Das Feld `model_versions` existierte bereits im Schema, in der Doku
und im Export (`build_passport(model_versions=...)`), wurde aber von keinem
einzigen Aufrufer befuellt -- der Export liefert immer `{}`. Dieses Issue
schliesst die Luecke ueber den vorhandenen `decisions`-Mechanismus:
eine neue Kategorie `model-version` mit Text-Konvention
`"<schritt>: <modell>"` wird beim Export geparst und in `model_versions`
gemergt (symmetrisch zum etablierten `file-change`-Muster aus #527).

AC1 -- Nach einem Lauf mit mindestens einem modellgestuetzten Skill ist
       `model_versions` im exportierten Passport nicht leer.
AC2 -- Schluessel benennt den Arbeitsschritt, Wert die Modellkennung.
AC3 -- Ein Test belegt: befuelltes `model_versions` erreicht den Export.
AC4 -- Unterscheidbarkeit "kein Modell" vs. "Erfassung lueckenhaft" ODER
       ausdrueckliche Klarstellung, dass das nicht geht (Doku-Caveat).
AC5 -- Die vier weiteren KI-Spuren sind geprueft (kein Code-Test, siehe
       PR-Beschreibung).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from academic_vault import server as vault_server
from academic_vault.db import VaultDB
from academic_vault.decision_log import (
    AUTO_CATEGORY,
    MODEL_VERSION_CATEGORY,
    parse_model_version_text,
)

REPO_ROOT = Path(__file__).parent.parent


def make_temp_db() -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = VaultDB(tmp.name)
    db.init_schema()
    return tmp.name


def _seed_paper(db_path: str, paper_id: str = "p1", doi: str = "10.1234/test") -> None:
    db = VaultDB(db_path)
    db.add_paper(
        paper_id,
        f'{{"title": "Test Paper", "type": "article-journal", "DOI": "{doi}"}}',
        doi=doi,
    )


# ---------------------------------------------------------------------------
# parse_model_version_text -- Unit-Tests (AC2)
# ---------------------------------------------------------------------------


def test_parse_model_version_text_valid():
    assert parse_model_version_text("figure-verifier: sonnet") == ("figure-verifier", "sonnet")


def test_parse_model_version_text_malformed_no_separator():
    """Text ohne ': ' ist kein gueltiger model-version-Eintrag -- weicher Fehlschlag."""
    assert parse_model_version_text("kein-trenner-hier") is None


def test_parse_model_version_text_empty_step():
    assert parse_model_version_text(": sonnet") is None


def test_parse_model_version_text_empty_model():
    assert parse_model_version_text("figure-verifier: ") is None


def test_parse_model_version_text_strips_whitespace():
    assert parse_model_version_text("  figure-verifier :  sonnet  ") == (
        "figure-verifier",
        "sonnet",
    )


# ---------------------------------------------------------------------------
# export_material_passport -- model_versions aus Decisions (AC1/AC3)
# ---------------------------------------------------------------------------


def test_export_material_passport_model_versions_from_decisions(tmp_path):
    """AC1/AC3: eine model-version-Decision erreicht model_versions im Export."""
    db_path = make_temp_db()
    try:
        _seed_paper(db_path)
        vault_server.add_decision(
            db_path, MODEL_VERSION_CATEGORY, "figure-verifier: sonnet", "Issue #617"
        )
        vault_server.export_material_passport(
            db_path=db_path,
            slug="proj",
            output_dir=str(tmp_path),
        )
        data = json.loads((tmp_path / "material-passport.json").read_text())
        assert data["model_versions"] == {"figure-verifier": "sonnet"}
    finally:
        os.unlink(db_path)


def test_export_material_passport_model_versions_defaults_empty(tmp_path):
    """Ohne model-version-Decisions bleibt model_versions {} -- kein Absturz."""
    db_path = make_temp_db()
    try:
        _seed_paper(db_path)
        vault_server.export_material_passport(
            db_path=db_path,
            slug="proj",
            output_dir=str(tmp_path),
        )
        data = json.loads((tmp_path / "material-passport.json").read_text())
        assert data["model_versions"] == {}
    finally:
        os.unlink(db_path)


def test_export_material_passport_model_versions_multiple_steps(tmp_path):
    """AC2: mehrere Arbeitsschritte landen als separate Schluessel."""
    db_path = make_temp_db()
    try:
        _seed_paper(db_path)
        vault_server.add_decision(db_path, MODEL_VERSION_CATEGORY, "figure-verifier: sonnet")
        vault_server.add_decision(db_path, MODEL_VERSION_CATEGORY, "relevance_scorer: opus")
        vault_server.export_material_passport(
            db_path=db_path,
            slug="proj",
            output_dir=str(tmp_path),
        )
        data = json.loads((tmp_path / "material-passport.json").read_text())
        assert data["model_versions"] == {
            "figure-verifier": "sonnet",
            "relevance_scorer": "opus",
        }
    finally:
        os.unlink(db_path)


def test_export_material_passport_model_versions_explicit_kwarg_wins_on_collision(tmp_path):
    """Explizit uebergebenes model_versions-Kwarg gewinnt bei Kollision mit Decisions."""
    db_path = make_temp_db()
    try:
        _seed_paper(db_path)
        vault_server.add_decision(db_path, MODEL_VERSION_CATEGORY, "figure-verifier: sonnet")
        vault_server.export_material_passport(
            db_path=db_path,
            slug="proj",
            output_dir=str(tmp_path),
            model_versions={"figure-verifier": "opus"},
        )
        data = json.loads((tmp_path / "material-passport.json").read_text())
        assert data["model_versions"] == {"figure-verifier": "opus"}
    finally:
        os.unlink(db_path)


def test_export_material_passport_ignores_malformed_model_version_decision(tmp_path):
    """Malformed model-version-Decision wird uebersprungen, Export stuerzt nicht ab."""
    db_path = make_temp_db()
    try:
        _seed_paper(db_path)
        vault_server.add_decision(db_path, MODEL_VERSION_CATEGORY, "kein-trenner-hier")
        vault_server.add_decision(db_path, MODEL_VERSION_CATEGORY, "figure-verifier: sonnet")
        vault_server.export_material_passport(
            db_path=db_path,
            slug="proj",
            output_dir=str(tmp_path),
        )
        data = json.loads((tmp_path / "material-passport.json").read_text())
        assert data["model_versions"] == {"figure-verifier": "sonnet"}
    finally:
        os.unlink(db_path)


def test_export_material_passport_model_version_decisions_excluded_from_snapshot(tmp_path):
    """Symmetrie zu file-change (#527): model-version-Decisions bleiben aus
    decisions_snapshot ausgeschlossen -- sie sind Material-Herkunft, keine
    methodische Entscheidung."""
    db_path = make_temp_db()
    try:
        _seed_paper(db_path)
        vault_server.add_decision(db_path, MODEL_VERSION_CATEGORY, "figure-verifier: sonnet")
        vault_server.add_decision(db_path, "scope", "Nur RCTs", "Qualitaet")
        vault_server.export_material_passport(
            db_path=db_path,
            slug="proj",
            output_dir=str(tmp_path),
        )
        data = json.loads((tmp_path / "material-passport.json").read_text())
        assert len(data["decisions_snapshot"]) == 1
        assert data["decisions_snapshot"][0]["text"] == "Nur RCTs"
    finally:
        os.unlink(db_path)


def test_model_version_category_distinct_from_auto_category():
    """model-version und file-change sind unterschiedliche Kategorien (kein Alias)."""
    assert MODEL_VERSION_CATEGORY != AUTO_CATEGORY
    assert MODEL_VERSION_CATEGORY == "model-version"


# ---------------------------------------------------------------------------
# Doku-Caveat (AC4): Schema-Description und SKILL.md machen die
# Teilabdeckung explizit -- "leer" heisst "nicht erfasst", nicht "kein
# Modell beteiligt".
# ---------------------------------------------------------------------------

SCHEMA_FILE = REPO_ROOT / "academic_vault" / "material-passport.schema.json"
SKILL_MD = REPO_ROOT / "skills" / "material-passport" / "SKILL.md"


def test_schema_model_versions_description_documents_source_format():
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    desc = schema["properties"]["model_versions"]["description"]
    assert MODEL_VERSION_CATEGORY in desc, (
        "model_versions-Description muss die Decision-Kategorie 'model-version' nennen"
    )
    assert "<schritt>" in desc or "schritt" in desc.lower(), (
        "model_versions-Description muss das Text-Format erklaeren"
    )


def test_schema_model_versions_description_documents_partial_coverage_caveat():
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    desc = schema["properties"]["model_versions"]["description"].lower()
    assert "lueckenhaft" in desc or "unvollstaendig" in desc, (
        "model_versions-Description muss den Abdeckungs-Caveat aus AC4 explizit "
        "machen: leer heisst 'nicht erfasst', nicht zuverlaessig 'kein Modell "
        "beteiligt'"
    )


def test_skill_md_documents_model_versions_caveat():
    body = SKILL_MD.read_text(encoding="utf-8")
    assert re.search(r"model_versions", body), "SKILL.md muss model_versions erwaehnen"
    # Der Abschnitt rund um model_versions muss den Lueckenhaftigkeits-Caveat
    # tragen (nicht nur "Eingesetzte KI-Modellversionen" ohne Einschraenkung).
    idx = body.index("model_versions")
    window = body[idx : idx + 600].lower()
    assert "lueckenhaft" in window or "nicht alle" in window or "unvollstaendig" in window, (
        "SKILL.md muss in der Naehe von model_versions den Abdeckungs-Caveat "
        "aus AC4 explizit machen"
    )


# ---------------------------------------------------------------------------
# figure-verifier.md -- erster echter Aufrufer (AC1 Beleg fuer "modellgestuetzter
# Skill hat gearbeitet")
# ---------------------------------------------------------------------------

FIGURE_VERIFIER_MD = REPO_ROOT / "agents" / "figure-verifier.md"


def test_figure_verifier_frontmatter_grants_add_decision_tool():
    content = FIGURE_VERIFIER_MD.read_text(encoding="utf-8")
    fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    assert fm_match is not None, "Kein YAML-Frontmatter gefunden"
    fm = fm_match.group(1)
    assert "mcp__academic-vault__vault_add_decision" in fm, (
        "figure-verifier.md muss vault_add_decision als Tool gewaehrt bekommen (Issue #617)"
    )


def test_figure_verifier_protocols_model_version_decision():
    content = FIGURE_VERIFIER_MD.read_text(encoding="utf-8")
    assert "model-version" in content, (
        "figure-verifier.md muss die Kategorie 'model-version' referenzieren"
    )
    assert "figure-verifier: sonnet" in content, (
        "figure-verifier.md muss den konkreten Decision-Text nach dem Format "
        "'<schritt>: <modell>' zeigen"
    )
