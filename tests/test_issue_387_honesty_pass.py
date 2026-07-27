"""Regressionstest fuer Issue #387 — Ehrlichkeits-Pass CHANGELOG/SKIP_REASONS.

Die README-Anteile des Issues (Badge, Hybrid-Retrieval-Claim, pyzotero,
SessionStart-Hook-Tabelle) wurden bereits mit PR #413 (README-Relaunch,
Issue #402) korrigiert und dort testgebunden (siehe
``tests/test_issue_402_readme_relaunch.py``). Dieser Test deckt die beiden
verbliebenen Akzeptanzkriterien ab:

- AC5: ``docs/SKIP_REASONS.md`` referenziert nicht mehr das laengst
  geschlossene Issue #217 (der zugehoerige Skip-Grund feuert nicht mehr,
  ``db.py``/``files_api.py`` sind implementiert).
- AC6: Der CHANGELOG-Eintrag zu v6.2.0 widerspricht dem heutigen
  Profil-Bestand unter ``config/library-profiles/`` nicht mehr
  kommentarlos.
"""

import re
from pathlib import Path

from tests.test_library_profiles import PROFILE_SLUGS

REPO_ROOT = Path(__file__).parent.parent
SKIP_REASONS = REPO_ROOT / "docs" / "SKIP_REASONS.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"


def _changelog_section(version: str) -> str:
    """Extrahiert den Textblock eines Release-Eintrags (bis zur naechsten '## [' oder '---')."""
    text = CHANGELOG.read_text(encoding="utf-8")
    m = re.search(
        rf"^##\s+\[{re.escape(version)}\].*?(?=^##\s+\[|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert m, f"Kein CHANGELOG-Eintrag fuer Version {version} gefunden"
    return m.group(0)


def test_skip_reasons_no_stale_217_reference():
    """#217 ist geschlossen; der referenzierte Skip-Grund feuert nicht mehr (0 skipped)."""
    text = SKIP_REASONS.read_text(encoding="utf-8")
    assert "#217" not in text, "docs/SKIP_REASONS.md referenziert noch das geschlossene Issue #217"


def test_skip_reasons_vault_skeleton_todo_removed():
    """Die vestigiale todo:vault-skeleton-Klassifikation ist entfernt, nicht nur umgelabelt."""
    text = SKIP_REASONS.read_text(encoding="utf-8")
    assert "todo:vault-skeleton" not in text, (
        "veraltete todo:vault-skeleton-Klassifikation noch in docs/SKIP_REASONS.md vorhanden"
    )


def test_changelog_v620_acknowledges_profile_discrepancy():
    """v6.2.0 nennt historisch andere Profile als heute unter config/library-profiles/ liegen.

    AC6 verlangt keine rueckwirkende Umschreibung (historisches Log bleibt
    inhaltlich stehen), aber eine Anmerkung, die die Abweichung benennt.
    """
    section = _changelog_section("6.2.0")
    assert "Leibniz FH, TU München, RWTH Aachen, FAU Erlangen-Nürnberg" in section, (
        "Historischer Wortlaut wurde entfernt statt nur kommentiert (AC6 verlangt "
        "Anmerkung, keine rueckwirkende Umschreibung)"
    )
    # Mindestens ein heute tatsaechlich existierendes Profil muss als Klarstellung
    # im selben Abschnitt auftauchen.
    assert any(slug in section for slug in PROFILE_SLUGS), (
        f"v6.2.0-Eintrag enthaelt keine Klarstellung zum heutigen Profil-Bestand ({PROFILE_SLUGS})"
    )


def test_changelog_v620_profiles_differ_from_current_config():
    """Cross-Check: die historisch genannten Profile sind tatsaechlich disjunkt vom Ist-Stand.

    Dokumentiert die Praemisse hinter AC6 als Regressionsguard: sollte sich
    config/library-profiles/ irgendwann wieder zu Leibniz FH/RWTH/FAU aendern,
    muss dieser Test neu bewertet werden statt stillschweigend gruen zu bleiben.
    """
    profiles_dir = REPO_ROOT / "config" / "library-profiles"
    current_slugs = {p.stem for p in profiles_dir.glob("*.yaml") if not p.stem.startswith("_")}
    historic_names = {"leibniz-fh", "rwth-aachen", "fau-erlangen-nuernberg"}
    assert not (current_slugs & historic_names), (
        "Erwartete Praemisse verletzt: historisch genannte Profile existieren wieder "
        "unter config/library-profiles/ — CHANGELOG-Anmerkung ggf. ueberholt"
    )
