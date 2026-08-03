"""Tests fuer den data-management-plan Skill (Issue #609).

TDD-First: Tests schreiben BEVOR die Implementierung existiert.

Deckt die 6 Akzeptanzkriterien aus Issue #609 ab:
- AC1: alle 6 Pflichtabschnitte vorhanden, offene Punkte als [OFFEN: ...]
- AC2: vorhandene Vaultbestaende erscheinen als Ausgangslage
- AC3: Personenbezogene-Daten-Abschnitt mit den 4 Pflichtfragen
- AC4: Rechtsberatungs-Disclaimer + Verweis auf zustaendige Stelle
- AC5: Repositorien/Lizenzen als Optionen, keine Vorgabe
- AC6: Datum der letzten Aktualisierung, idempotent bei Re-Run
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from academic_vault.db import VaultDB

_WORKTREE_ROOT = Path(__file__).parent.parent
_SCRIPT = _WORKTREE_ROOT / "skills" / "data-management-plan" / "scripts" / "build_dmp.py"
_SKILL_MD = _WORKTREE_ROOT / "skills" / "data-management-plan" / "SKILL.md"

_REQUIRED_HEADINGS = [
    "## Datenarten und -umfang",
    "## Erhebung und Dokumentation",
    "## Speicherung und Sicherung während des Projekts",
    "## Rechtliche Aspekte",
    "## Archivierung und Nachnutzung",
    "## Zuständigkeiten",
]


def _make_db() -> str:
    import tempfile

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = VaultDB(tmp.name)
    db.init_schema()
    return tmp.name


def _seed_vault(db_path: str, n_literature: int = 2, n_primary: int = 1) -> None:
    """Legt Literatur- und Primaer-Paper, Transkriptsegmente und Codings an."""
    for i in range(n_literature):
        db = VaultDB(db_path)
        db.add_paper(
            f"lit{i}",
            json.dumps({"title": f"Lit {i}", "type": "article-journal"}),
            source_kind="literature",
        )
    for i in range(n_primary):
        db = VaultDB(db_path)
        db.add_paper(
            f"prim{i}",
            json.dumps({"title": f"Interview {i}", "type": "article-journal"}),
            source_kind="primary",
        )
        db.add_transcript_segment(f"prim{i}", seq=1, text="Erstes Segment.", speaker="I1")
        db.add_transcript_segment(f"prim{i}", seq=2, text="Zweites Segment.", speaker="I1")
        db.add_coding(
            paper_id=f"prim{i}",
            category="Kategorie A",
            category_origin="induktiv",
        )


def _run_script(db_path: str, slug: str, output: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--db",
            db_path,
            "--slug",
            slug,
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# AC1: Alle Pflichtabschnitte vorhanden, offene Punkte als [OFFEN: ...]
# ---------------------------------------------------------------------------


class TestRequiredSections:
    def test_script_creates_dmp_file(self, tmp_path):
        db_path = _make_db()
        output = tmp_path / "datenmanagementplan.md"
        result = _run_script(db_path, "test-projekt", output)
        assert result.returncode == 0, (
            f"exitcode {result.returncode}\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
        assert output.exists(), "datenmanagementplan.md wurde nicht erstellt"

    def test_all_six_required_headings_present(self, tmp_path):
        db_path = _make_db()
        output = tmp_path / "datenmanagementplan.md"
        _run_script(db_path, "test-projekt", output)
        content = output.read_text(encoding="utf-8")
        for heading in _REQUIRED_HEADINGS:
            assert heading in content, f"Pflichtabschnitt '{heading}' fehlt"

    def test_undecided_points_marked_offen_not_fabricated(self, tmp_path):
        """Ohne Vorgaben (z.B. Repository-Wahl) steht [OFFEN: statt eines erfundenen Werts."""
        db_path = _make_db()
        output = tmp_path / "datenmanagementplan.md"
        _run_script(db_path, "test-projekt", output)
        content = output.read_text(encoding="utf-8")
        assert "[OFFEN:" in content, "Kein [OFFEN: ...]-Marker fuer unentschiedene Punkte gefunden"


# ---------------------------------------------------------------------------
# AC2: Vorhandene Vaultbestaende erscheinen als Ausgangslage
# ---------------------------------------------------------------------------


class TestAusgangslage:
    def test_ausgangslage_section_present(self, tmp_path):
        db_path = _make_db()
        output = tmp_path / "datenmanagementplan.md"
        _seed_vault(db_path)
        _run_script(db_path, "test-projekt", output)
        content = output.read_text(encoding="utf-8")
        assert "## Ausgangslage im Vault" in content

    def test_ausgangslage_reports_paper_counts(self, tmp_path):
        db_path = _make_db()
        output = tmp_path / "datenmanagementplan.md"
        _seed_vault(db_path, n_literature=2, n_primary=1)
        _run_script(db_path, "test-projekt", output)
        content = output.read_text(encoding="utf-8")
        ausgangslage_idx = content.find("## Ausgangslage im Vault")
        next_heading_idx = content.find("\n## ", ausgangslage_idx + 1)
        section = content[ausgangslage_idx:next_heading_idx]
        assert "**3 Paper/Quellen**" in section, (
            "Gesamtzahl der Paper (3) nicht in Ausgangslage-Abschnitt"
        )
        assert "**2 Literatur**" in section, (
            "Anzahl Literatur-Paper (2) nicht in Ausgangslage-Abschnitt"
        )

    def test_ausgangslage_reports_segment_and_coding_counts(self, tmp_path):
        db_path = _make_db()
        output = tmp_path / "datenmanagementplan.md"
        _seed_vault(db_path, n_literature=0, n_primary=2)
        _run_script(db_path, "test-projekt", output)
        content = output.read_text(encoding="utf-8")
        ausgangslage_idx = content.find("## Ausgangslage im Vault")
        next_heading_idx = content.find("\n## ", ausgangslage_idx + 1)
        section = content[ausgangslage_idx:next_heading_idx]
        # 2 Paper x 2 Segmente = 4 Segmente, 2 Codings (1 je Paper)
        assert "4" in section, f"Segmentzahl (4) fehlt in Ausgangslage-Abschnitt: {section}"
        assert "2" in section, f"Coding-Zahl (2) fehlt in Ausgangslage-Abschnitt: {section}"

    def test_empty_vault_reports_zero_not_omission(self, tmp_path):
        """Leerer Vault -> Zahlen sind 0, Abschnitt bleibt trotzdem sichtbar (kein stilles Weglassen)."""
        db_path = _make_db()
        output = tmp_path / "datenmanagementplan.md"
        _run_script(db_path, "leeres-projekt", output)
        content = output.read_text(encoding="utf-8")
        ausgangslage_idx = content.find("## Ausgangslage im Vault")
        next_heading_idx = content.find("\n## ", ausgangslage_idx + 1)
        section = content[ausgangslage_idx:next_heading_idx]
        assert "**0 Paper/Quellen**" in section, "Null-Paper nicht in Ausgangslage-Abschnitt"


# ---------------------------------------------------------------------------
# AC3: Personenbezogene-Daten-Abschnitt mit den 4 Pflichtfragen
# ---------------------------------------------------------------------------


class TestPersonenbezogeneDaten:
    def test_section_heading_present(self, tmp_path):
        db_path = _make_db()
        output = tmp_path / "datenmanagementplan.md"
        _run_script(db_path, "test-projekt", output)
        content = output.read_text(encoding="utf-8")
        assert "Personenbezogene Daten" in content

    def test_section_covers_four_required_topics(self, tmp_path):
        db_path = _make_db()
        output = tmp_path / "datenmanagementplan.md"
        _run_script(db_path, "test-projekt", output)
        content = output.read_text(encoding="utf-8")
        idx = content.find("Personenbezogene Daten")
        assert idx != -1
        next_heading_idx = content.find("\n## ", idx + 1)
        section = content[idx:next_heading_idx] if next_heading_idx != -1 else content[idx:]
        for stichwort in ["Einwilligung", "Pseudonymisierung", "Aufbewahrung", "Löschung"]:
            assert stichwort in section, (
                f"Stichwort '{stichwort}' fehlt im Personenbezogene-Daten-Abschnitt"
            )


# ---------------------------------------------------------------------------
# AC4: Rechtsberatungs-Disclaimer + zustaendige Stelle
# ---------------------------------------------------------------------------


class TestDisclaimer:
    def test_no_legal_advice_disclaimer_present(self, tmp_path):
        db_path = _make_db()
        output = tmp_path / "datenmanagementplan.md"
        _run_script(db_path, "test-projekt", output)
        content = output.read_text(encoding="utf-8")
        assert "keine Rechtsberatung" in content

    def test_references_responsible_office(self, tmp_path):
        db_path = _make_db()
        output = tmp_path / "datenmanagementplan.md"
        _run_script(db_path, "test-projekt", output)
        content = output.read_text(encoding="utf-8")
        assert "zuständige Stelle" in content


# ---------------------------------------------------------------------------
# AC5: Repositorien/Lizenzen als Optionen, keine Vorgabe
# ---------------------------------------------------------------------------


class TestRepositoriesAndLicenses:
    def test_at_least_two_repository_options_named(self, tmp_path):
        db_path = _make_db()
        output = tmp_path / "datenmanagementplan.md"
        _run_script(db_path, "test-projekt", output)
        content = output.read_text(encoding="utf-8")
        found = [name for name in ["Zenodo", "OSF", "re3data"] if name in content]
        assert len(found) >= 2, f"Weniger als 2 Repository-Optionen gefunden: {found}"

    def test_at_least_two_license_options_named(self, tmp_path):
        db_path = _make_db()
        output = tmp_path / "datenmanagementplan.md"
        _run_script(db_path, "test-projekt", output)
        content = output.read_text(encoding="utf-8")
        found = [name for name in ["CC-BY", "CC0", "CC-BY-NC"] if name in content]
        assert len(found) >= 2, f"Weniger als 2 Lizenz-Optionen gefunden: {found}"

    def test_no_mandatory_phrasing_for_repository_or_license(self, tmp_path):
        db_path = _make_db()
        output = tmp_path / "datenmanagementplan.md"
        _run_script(db_path, "test-projekt", output)
        content = output.read_text(encoding="utf-8").lower()
        for verboten in [
            "muss verwendet werden",
            "ist zwingend zu nutzen",
            "verpflichtend zu waehlen",
        ]:
            assert verboten not in content, f"Vorgabe-Formulierung gefunden: '{verboten}'"


# ---------------------------------------------------------------------------
# AC6: Datum der letzten Aktualisierung, idempotent bei Re-Run
# ---------------------------------------------------------------------------


class TestLastUpdatedAndIdempotency:
    def test_last_updated_field_present(self, tmp_path):
        db_path = _make_db()
        output = tmp_path / "datenmanagementplan.md"
        _run_script(db_path, "test-projekt", output)
        content = output.read_text(encoding="utf-8")
        assert "Zuletzt aktualisiert" in content
        today = datetime.now(UTC).date().isoformat()
        assert today in content, f"Heutiges Datum ({today}) nicht im Dokument gefunden"

    def test_rerun_does_not_duplicate_headings(self, tmp_path):
        db_path = _make_db()
        output = tmp_path / "datenmanagementplan.md"
        _seed_vault(db_path)
        for _ in range(3):
            result = _run_script(db_path, "test-projekt", output)
            assert result.returncode == 0, result.stderr
        content = output.read_text(encoding="utf-8")
        for heading in _REQUIRED_HEADINGS + ["## Ausgangslage im Vault"]:
            count = content.count(heading)
            assert count == 1, f"'{heading}' erscheint {count}x nach 3 Laeufen — erwartet 1x"

    def test_rerun_refreshes_vault_counts(self, tmp_path):
        """Nach Hinzufuegen neuer Paper spiegelt ein erneuter Lauf den neuen Bestand."""
        db_path = _make_db()
        output = tmp_path / "datenmanagementplan.md"
        _run_script(db_path, "test-projekt", output)
        _seed_vault(db_path, n_literature=1, n_primary=0)
        _run_script(db_path, "test-projekt", output)
        content = output.read_text(encoding="utf-8")
        ausgangslage_idx = content.find("## Ausgangslage im Vault")
        next_heading_idx = content.find("\n## ", ausgangslage_idx + 1)
        section = content[ausgangslage_idx:next_heading_idx]
        assert "1" in section

    def test_rerun_preserves_manually_filled_section(self, tmp_path):
        """Ein von Hand ausgefuellter Abschnitt wird beim Re-Run nicht ueberschrieben."""
        db_path = _make_db()
        output = tmp_path / "datenmanagementplan.md"
        _run_script(db_path, "test-projekt", output)
        content = output.read_text(encoding="utf-8")
        manual_marker = "Speicherort: Instituts-NAS, taegliches Backup um 02:00 Uhr."
        content = content.replace(
            "## Speicherung und Sicherung während des Projekts",
            "## Speicherung und Sicherung während des Projekts\n\n" + manual_marker,
            1,
        )
        output.write_text(content, encoding="utf-8")

        _run_script(db_path, "test-projekt", output)
        content_after = output.read_text(encoding="utf-8")
        assert manual_marker in content_after, (
            "Manuell ausgefuellter Text wurde beim Re-Run ueberschrieben"
        )


# ---------------------------------------------------------------------------
# SKILL.md: Trigger-Abgrenzung gegen material-passport, Abgrenzungs-Sektion
# ---------------------------------------------------------------------------


class TestSkillMdStructure:
    def _frontmatter(self) -> str:
        content = _SKILL_MD.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        assert m, "Kein Frontmatter gefunden"
        return m.group(1)

    def test_frontmatter_has_name_and_description(self):
        fm = self._frontmatter()
        assert "name: data-management-plan" in fm
        assert "description:" in fm

    def test_preamble_reference_present(self):
        content = _SKILL_MD.read_text(encoding="utf-8")
        assert "> **Gemeinsames Preamble laden:**" in content

    def test_no_inline_vorbedingungen_or_fabrikation_sections(self):
        content = _SKILL_MD.read_text(encoding="utf-8")
        assert "\n## Vorbedingungen\n" not in content
        assert "\n## Keine Fabrikation\n" not in content

    def test_abgrenzung_section_present(self):
        content = _SKILL_MD.read_text(encoding="utf-8")
        assert "## Abgrenzung" in content
        abgrenzung_idx = content.find("## Abgrenzung")
        section = content[abgrenzung_idx:]
        for scope_out in ["Rechtsberatung", "Förderer", "archivieren", "Einwilligungserklärung"]:
            assert scope_out.lower() in section.lower(), f"Abgrenzung erwaehnt '{scope_out}' nicht"

    def test_triggers_are_dmp_specific_not_generic_vault_terms(self):
        """Trigger duerfen nicht mit material-passport kollidieren (Plan-Risiko).

        material-passport triggert u.a. auf "Vault sperren" / "Abgabe vorbereiten".
        Diese generischen Phrasen duerfen in der data-management-plan-description
        nicht als eigene Trigger-Phrase auftauchen.
        """
        fm = self._frontmatter()
        desc_m = re.search(r"description:\s*(.*?)(?=^[a-zA-Z_-]+:|\Z)", fm, re.DOTALL | re.M)
        assert desc_m
        desc = " ".join(desc_m.group(1).split())
        for collision_phrase in ["Vault sperren", "Abgabe vorbereiten"]:
            assert collision_phrase.lower() not in desc.lower(), (
                f"Trigger '{collision_phrase}' kollidiert mit material-passport"
            )
        assert "datenmanagementplan" in desc.lower() or "dmp" in desc.lower()


# ---------------------------------------------------------------------------
# skill_sizes.json enthaelt data-management-plan
# ---------------------------------------------------------------------------


class TestSkillSizes:
    def test_skill_sizes_contains_data_management_plan(self):
        sizes_path = _WORKTREE_ROOT / "tests" / "baselines" / "skill_sizes.json"
        sizes = json.loads(sizes_path.read_text())
        assert "data-management-plan" in sizes
        assert sizes["data-management-plan"] > 0
