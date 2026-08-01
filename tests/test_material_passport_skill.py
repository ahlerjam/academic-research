"""Tests fuer Material-Passport Skill (Ticket #104 — Skill-Anteil).

TDD-First: Tests schreiben BEVOR die Implementierung existiert.

Setup: temp_vault mit 3 Test-Papern, 3 Decisions, 5 Scores
Test 1: build_passport.py erzeugt material-passport.json
Test 2: methodik.md hat neuen "## Reproduzierbarkeit"-Block
Test 3: vault.lock_passport schaltet auf read-only
Test 4: post-lock try vault.add_paper → Exception
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from academic_vault import server as vault_server
from academic_vault.db import VaultDB

_WORKTREE_ROOT = Path(__file__).parent.parent

_SCRIPT = _WORKTREE_ROOT / "skills" / "material-passport" / "scripts" / "build_passport.py"
_SKILL_MD = _WORKTREE_ROOT / "skills" / "material-passport" / "SKILL.md"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db() -> tuple[str, VaultDB]:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = VaultDB(tmp.name)
    db.init_schema()
    return tmp.name, db


def _seed_vault(db_path: str) -> None:
    """Legt 3 Paper, 3 Decisions und 5 Score-Snapshots an."""
    # 3 Paper
    for i in range(1, 4):
        db = VaultDB(db_path)
        db.add_paper(
            f"p{i}",
            json.dumps({"title": f"Paper {i}", "type": "article-journal", "DOI": f"10.1234/p{i}"}),
            doi=f"10.1234/p{i}",
        )

    # 3 Decisions
    vault_server.add_decision(db_path, "scope", "Nur RCTs einschliessen", "Qualitaetssicherung")
    vault_server.add_decision(db_path, "search", "PubMed + Cochrane", "Coverage")
    vault_server.add_decision(db_path, "exclusion", "Kein graues Material", "Reproduzierbarkeit")

    # 5 Score-Snapshots (fuer die ersten 2 Paper je 2, fuer p3 1)
    scores_base = {"relevance": 4, "quality": 3, "novelty": 3, "reproducibility": 4, "impact": 3}
    for pid in ["p1", "p2"]:
        for _ in range(2):
            db = VaultDB(db_path)
            db.add_score_snapshot(
                paper_id=pid,
                session_id="sess-test",
                scores_json=json.dumps(scores_base),
            )
    db = VaultDB(db_path)
    db.add_score_snapshot(
        paper_id="p3",
        session_id="sess-test",
        scores_json=json.dumps(scores_base),
    )


# ---------------------------------------------------------------------------
# Test 1: build_passport.py erzeugt material-passport.json
# ---------------------------------------------------------------------------


class TestBuildPassportScript:
    """build_passport.py CLI erzeugt material-passport.json im output-dir."""

    def test_script_creates_passport_file(self, tmp_path):
        """Script laeuft ohne Fehler und schreibt material-passport.json."""
        import subprocess

        db_path, _ = _make_db()
        try:
            _seed_vault(db_path)
            methodik = tmp_path / "kapitel" / "methodik.md"
            methodik.parent.mkdir(parents=True)
            methodik.write_text("# Methodik\n\nIrgendein Inhalt.\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(_SCRIPT),
                    "--db",
                    db_path,
                    "--slug",
                    "test-projekt",
                    "--output-dir",
                    str(tmp_path),
                    "--methodik",
                    str(methodik),
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, (
                f"Script exitcode {result.returncode}\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
            )
            passport_file = tmp_path / "material-passport.json"
            assert passport_file.exists(), "material-passport.json wurde nicht erstellt"
        finally:
            os.unlink(db_path)

    def test_passport_json_is_valid(self, tmp_path):
        """material-passport.json enthaelt gueltiges JSON mit Pflichtfeldern."""
        import subprocess

        db_path, _ = _make_db()
        try:
            _seed_vault(db_path)
            methodik = tmp_path / "kapitel" / "methodik.md"
            methodik.parent.mkdir(parents=True)
            methodik.write_text("# Methodik\n", encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(_SCRIPT),
                    "--db",
                    db_path,
                    "--slug",
                    "test-projekt",
                    "--output-dir",
                    str(tmp_path),
                    "--methodik",
                    str(methodik),
                ],
                capture_output=True,
                text=True,
            )
            data = json.loads((tmp_path / "material-passport.json").read_text())
            assert data["slug"] == "test-projekt"
            assert "paper_ids" in data
            assert "passport_hash" in data
            assert len(data["paper_ids"]) == 3
        finally:
            os.unlink(db_path)

    def test_passport_contains_decisions(self, tmp_path):
        """material-passport.json enthaelt die 3 Decisions als Snapshot."""
        import subprocess

        db_path, _ = _make_db()
        try:
            _seed_vault(db_path)
            methodik = tmp_path / "kapitel" / "methodik.md"
            methodik.parent.mkdir(parents=True)
            methodik.write_text("# Methodik\n", encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(_SCRIPT),
                    "--db",
                    db_path,
                    "--slug",
                    "test-projekt",
                    "--output-dir",
                    str(tmp_path),
                    "--methodik",
                    str(methodik),
                ],
                capture_output=True,
                text=True,
            )
            data = json.loads((tmp_path / "material-passport.json").read_text())
            assert len(data["decisions_snapshot"]) == 3
        finally:
            os.unlink(db_path)


# ---------------------------------------------------------------------------
# Test 2: methodik.md bekommt "## Reproduzierbarkeit"-Block
# ---------------------------------------------------------------------------


class TestMethdikUpdate:
    """build_passport.py ergaenzt kapitel/methodik.md um Reproduzierbarkeits-Block."""

    def test_methodik_gets_reproduzierbarkeit_block(self, tmp_path):
        """Nach Script-Aufruf hat methodik.md einen ## Reproduzierbarkeit Abschnitt."""
        import subprocess

        db_path, _ = _make_db()
        try:
            _seed_vault(db_path)
            methodik = tmp_path / "kapitel" / "methodik.md"
            methodik.parent.mkdir(parents=True)
            methodik.write_text("# Methodik\n\nBeschreibung der Methodik.\n", encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(_SCRIPT),
                    "--db",
                    db_path,
                    "--slug",
                    "mein-projekt",
                    "--output-dir",
                    str(tmp_path),
                    "--methodik",
                    str(methodik),
                ],
                capture_output=True,
                text=True,
            )
            content = methodik.read_text(encoding="utf-8")
            assert "## Reproduzierbarkeit" in content, (
                "methodik.md enthaelt keinen '## Reproduzierbarkeit'-Block"
            )
        finally:
            os.unlink(db_path)

    def test_methodik_block_references_passport_file(self, tmp_path):
        """Reproduzierbarkeits-Block in methodik.md verweist auf material-passport.json."""
        import subprocess

        db_path, _ = _make_db()
        try:
            _seed_vault(db_path)
            methodik = tmp_path / "kapitel" / "methodik.md"
            methodik.parent.mkdir(parents=True)
            methodik.write_text("# Methodik\n\nIrgendein Text.\n", encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(_SCRIPT),
                    "--db",
                    db_path,
                    "--slug",
                    "mein-projekt",
                    "--output-dir",
                    str(tmp_path),
                    "--methodik",
                    str(methodik),
                ],
                capture_output=True,
                text=True,
            )
            content = methodik.read_text(encoding="utf-8")
            assert "material-passport.json" in content, (
                "methodik.md verweist nicht auf material-passport.json"
            )
        finally:
            os.unlink(db_path)

    def test_methodik_block_not_duplicated_on_rerun(self, tmp_path):
        """Wiederholter Script-Aufruf ergaenzt den Block nicht doppelt."""
        import subprocess

        db_path, _ = _make_db()
        try:
            _seed_vault(db_path)
            methodik = tmp_path / "kapitel" / "methodik.md"
            methodik.parent.mkdir(parents=True)
            methodik.write_text("# Methodik\n\nIrgendein Text.\n", encoding="utf-8")

            for _ in range(2):
                subprocess.run(
                    [
                        sys.executable,
                        str(_SCRIPT),
                        "--db",
                        db_path,
                        "--slug",
                        "mein-projekt",
                        "--output-dir",
                        str(tmp_path),
                        "--methodik",
                        str(methodik),
                    ],
                    capture_output=True,
                    text=True,
                )
            content = methodik.read_text(encoding="utf-8")
            count = content.count("## Reproduzierbarkeit")
            assert count == 1, f"'## Reproduzierbarkeit' erscheint {count}x — erwartet: 1x"
        finally:
            os.unlink(db_path)

    def test_methodik_created_if_missing(self, tmp_path):
        """Wenn methodik.md nicht existiert, wird sie angelegt."""
        import subprocess

        db_path, _ = _make_db()
        try:
            _seed_vault(db_path)
            methodik = tmp_path / "kapitel" / "methodik.md"
            methodik.parent.mkdir(parents=True)
            # Datei existiert NICHT

            subprocess.run(
                [
                    sys.executable,
                    str(_SCRIPT),
                    "--db",
                    db_path,
                    "--slug",
                    "mein-projekt",
                    "--output-dir",
                    str(tmp_path),
                    "--methodik",
                    str(methodik),
                ],
                capture_output=True,
                text=True,
            )
            assert methodik.exists(), "methodik.md wurde nicht angelegt"
            content = methodik.read_text(encoding="utf-8")
            assert "## Reproduzierbarkeit" in content
        finally:
            os.unlink(db_path)


# ---------------------------------------------------------------------------
# Test 3: vault.lock_passport schaltet auf read-only
# ---------------------------------------------------------------------------


class TestLockPassport:
    """vault.lock_passport macht den Vault read-only."""

    def test_lock_passport_sets_locked_flag(self):
        """lock_passport(slug) setzt is_locked(slug) auf True."""
        db_path, _ = _make_db()
        try:
            vault_server.lock_passport(db_path=db_path, slug="proj")
            assert vault_server.is_locked(db_path=db_path, slug="proj") is True
        finally:
            os.unlink(db_path)

    def test_build_passport_with_lock_flag(self, tmp_path):
        """Script mit --lock setzt is_locked=True nach Aufruf."""
        import subprocess

        db_path, _ = _make_db()
        try:
            _seed_vault(db_path)
            methodik = tmp_path / "kapitel" / "methodik.md"
            methodik.parent.mkdir(parents=True)
            methodik.write_text("# Methodik\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(_SCRIPT),
                    "--db",
                    db_path,
                    "--slug",
                    "locked-proj",
                    "--output-dir",
                    str(tmp_path),
                    "--methodik",
                    str(methodik),
                    "--lock",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, (
                f"Script exitcode {result.returncode}\nSTDERR: {result.stderr}"
            )
            assert vault_server.is_locked(db_path=db_path, slug="locked-proj") is True
        finally:
            os.unlink(db_path)


# ---------------------------------------------------------------------------
# Test 4: build_passport.py mit --lock, danach erneut aufrufen → Fehler
# ---------------------------------------------------------------------------


class TestLockedVaultRefusesWrites:
    """Nach Lock verweigert build_passport.py weitere Exports (Vault read-only)."""

    def test_script_exits_nonzero_when_vault_locked(self, tmp_path):
        """build_passport.py ohne --lock auf gesperrtem Vault gibt exitcode != 0."""
        import subprocess

        db_path, _ = _make_db()
        try:
            _seed_vault(db_path)
            methodik = tmp_path / "kapitel" / "methodik.md"
            methodik.parent.mkdir(parents=True)
            methodik.write_text("# Methodik\n", encoding="utf-8")

            # Erst mit --lock sperren
            subprocess.run(
                [
                    sys.executable,
                    str(_SCRIPT),
                    "--db",
                    db_path,
                    "--slug",
                    "sealed-proj",
                    "--output-dir",
                    str(tmp_path),
                    "--methodik",
                    str(methodik),
                    "--lock",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            assert vault_server.is_locked(db_path=db_path, slug="sealed-proj") is True

            # Erneuter Aufruf ohne --lock auf gesperrtem Vault sollte Fehler geben
            result2 = subprocess.run(
                [
                    sys.executable,
                    str(_SCRIPT),
                    "--db",
                    db_path,
                    "--slug",
                    "sealed-proj",
                    "--output-dir",
                    str(tmp_path),
                    "--methodik",
                    str(methodik),
                ],
                capture_output=True,
                text=True,
            )
            assert result2.returncode != 0, (
                "build_passport.py sollte auf gesperrtem Vault Fehler zurueckgeben"
            )
            combined = (result2.stdout + result2.stderr).lower()
            assert "lock" in combined or "gesperrt" in combined or "read-only" in combined, (
                f"Kein Lock-Hinweis in Ausgabe: {result2.stdout} {result2.stderr}"
            )
        finally:
            os.unlink(db_path)


# ---------------------------------------------------------------------------
# Issue #536: Repro-Lock nur nach echtem AskUserQuestion-Gate (Audit R9)
# ---------------------------------------------------------------------------


class TestReproLockAskUserQuestionGate:
    """SKILL.md bindet `--lock` an ein echtes AskUserQuestion-Gate (kein Prosa-Hinweis)."""

    def _step1_text(self, content: str) -> str:
        step1_idx = content.find("### Schritt 1")
        step2_idx = content.find("### Schritt 2")
        assert step1_idx != -1, "Schritt 1 nicht gefunden"
        assert step2_idx != -1, "Schritt 2 nicht gefunden"
        return content[step1_idx:step2_idx]

    def test_allowed_tools_declares_ask_user_question(self):
        """AC1-Voraussetzung: Skill darf AskUserQuestion ueberhaupt aufrufen."""
        content = _SKILL_MD.read_text(encoding="utf-8")
        frontmatter = content.split("---")[1]
        for line in frontmatter.splitlines():
            if line.strip().startswith("allowed-tools:"):
                # Liste kann auf derselben Zeile oder als Folgezeilen stehen.
                break
        assert "AskUserQuestion" in frontmatter, (
            "SKILL.md nutzt AskUserQuestion fuer das Repro-Lock-Gate, "
            "muss es aber auch in allowed-tools deklarieren"
        )

    def test_ask_user_question_gate_precedes_lock_flag_call(self):
        """AC1: --lock wird nie ohne vorheriges, textuell vorangestelltes Gate erreicht."""
        content = _SKILL_MD.read_text(encoding="utf-8")
        step1_text = self._step1_text(content)
        assert "AskUserQuestion" in step1_text, (
            "Schritt 1 muss ein AskUserQuestion-Gate beschreiben, nicht nur Prosa "
            "('immer nachfragen')"
        )

        step2_idx = content.find("### Schritt 2")
        lock_call_idx = content.find("--lock", step2_idx)
        ask_idx = content.find("AskUserQuestion")
        assert lock_call_idx != -1, "Schritt 2 muss den --lock-Aufruf enthalten"
        assert ask_idx < lock_call_idx, (
            "Das AskUserQuestion-Gate muss textuell VOR dem --lock-Aufruf stehen"
        )

    def test_gate_option_names_irreversibility_in_option_label(self):
        """AC2: 'irreversibel' steht in der Optionszeile selbst, nicht nur im Fliesstext."""
        content = _SKILL_MD.read_text(encoding="utf-8")
        step1_text = self._step1_text(content)
        option_lines = [
            line
            for line in step1_text.splitlines()
            if line.strip().startswith("-") and "irreversibel" in line.lower() and "--lock" in line
        ]
        assert option_lines, (
            "Schritt 1 muss eine AskUserQuestion-Optionszeile enthalten, die "
            "sowohl 'irreversibel' als auch '--lock' im Optionstext selbst nennt "
            "(nicht nur im umgebenden Fliesstext)"
        )

    def test_abort_path_maps_to_export_without_lock_not_to_error(self):
        """AC3: Abbruch/'Nein' fuehrt zu Schritt 2 'Ohne Repro-Lock', nicht zum Fehler."""
        content = _SKILL_MD.read_text(encoding="utf-8")
        step1_text = self._step1_text(content)
        assert "ohne Repro-Lock" in step1_text or "Ohne Repro-Lock" in step1_text, (
            "Schritt 1 muss den Abbruch-/Ablehnungs-Pfad explizit auf "
            "'Ohne Repro-Lock' (Schritt 2) verweisen"
        )
        assert "FEHLER" not in step1_text, (
            "Der Abbruch-/Ablehnungs-Pfad des Gates darf keine Fehler-Formulierung "
            "verwenden — Abbruch ist der normale, fehlerfreie Default-Pfad"
        )
        assert "wird abgebrochen" not in step1_text.lower(), (
            "Der Abbruch-/Ablehnungs-Pfad des Gates darf den Skill nicht als "
            "abgebrochen darstellen — er fuehrt zum normalen Export ohne Lock"
        )

    def test_achtung_hinweis_references_gate_instead_of_standalone_prose(self):
        """Konsolidierung: Zeile 92-94 verweist auf das Gate statt eigener Prosa."""
        content = _SKILL_MD.read_text(encoding="utf-8")
        achtung_idx = content.find("**Achtung:**")
        assert achtung_idx != -1, "Achtung-Hinweis vor dem --lock-Codeblock fehlt"
        achtung_block = content[achtung_idx : achtung_idx + 500]
        assert "Schritt 1" in achtung_block or "Gate" in achtung_block, (
            "Der Achtung-Hinweis muss auf das AskUserQuestion-Gate aus Schritt 1 "
            "verweisen statt eine unabhaengige 'explizit bestaetigen lassen'-"
            "Formulierung zu wiederholen"
        )


# ---------------------------------------------------------------------------
# Test 5: skill_sizes.json enthaelt material-passport
# ---------------------------------------------------------------------------


class TestSkillSizes:
    """tests/baselines/skill_sizes.json enthaelt 'material-passport'."""

    def test_skill_sizes_contains_material_passport(self):
        sizes_path = _WORKTREE_ROOT / "tests" / "baselines" / "skill_sizes.json"
        sizes = json.loads(sizes_path.read_text())
        assert "material-passport" in sizes, (
            "skill_sizes.json enthaelt keinen 'material-passport'-Eintrag"
        )
        assert sizes["material-passport"] > 0
