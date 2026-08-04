"""Regression-Guard für Issue #174: README-Badges dürfen nicht veralten.

Akzeptanzkriterien (Stand nach dem README-Relaunch #402):
- Skills-Badge zeigt die tatsächliche Anzahl der SKILL.md (Claude-Code-Discovery-Count).
- Es gibt KEINEN handgepflegten Test-Zahlen-Badge mehr. Der ursprüngliche Fix von #174
  hatte die Zahl im Badge nur aktualisiert; sie ist danach zweimal erneut veraltet
  ("~60", dann "963 passing / 1111 collected" bei real 1809 bestandenen Tests). Die
  Lehre daraus: eine Zahl, die niemand automatisch nachzieht, gehört nicht in ein Badge.
  Den Status liefert jetzt der CI-Workflow-Badge, die Zahl ermittelt man selbst.
- Die Skill-Zahl steht in der Skills-Referenz (früher: README-Inhaltsverzeichnis).
- Die Entwickler-Doku nennt nicht mehr "~60 Tests" und weist auf Network/External-
  abhängige Tests hin.
"""

import re
from pathlib import Path

from tests.helpers import docs as D

REPO_ROOT = Path(__file__).parent.parent
README = D.README


def _skill_count() -> int:
    """Zahl der SKILL.md unter skills/ — entspricht dem Claude-Code-Discovery-Count."""
    return len(list((REPO_ROOT / "skills").rglob("SKILL.md")))


def test_skills_badge_matches_actual_skill_count():
    text = README.read_text(encoding="utf-8")
    count = _skill_count()
    # Stand Issue #607 (preregistration neu, nach bereits gemergten #608/#391): 44.
    # Steigt die Zahl der SKILL.md-Verzeichnisse weiter, hier mitziehen (Test ggf. anpassen).
    assert count == 44, f"Erwartet 44 SKILL.md, gefunden {count} (Test ggf. anpassen)."
    # Veraltetes "skills-23+"-Badge darf nicht mehr vorkommen.
    assert "skills-23+" not in text, "Veraltetes skills-23+-Badge noch vorhanden."
    badge = re.search(r"!\[Skills\]\(https://img\.shields\.io/badge/skills-(\d+)", text)
    assert badge is not None, "Skills-Badge nicht gefunden."
    assert int(badge.group(1)) == count, (
        f"Skills-Badge zeigt {badge.group(1)}, tatsächlich {count} SKILL.md."
    )


def test_skill_count_stated_in_skills_reference():
    """Die Skills-Referenz nennt dieselbe Zahl wie das Badge."""
    text = D.SKILLS_DOC.read_text(encoding="utf-8")
    count = _skill_count()
    assert "23+" not in text, "Veraltete Skill-Zahl '23+' in der Skills-Referenz."
    assert re.search(rf"\*\*{count} Skills\*\*", text), (
        f"Skills-Referenz nennt nicht '**{count} Skills**'."
    )


def test_no_handmaintained_tests_badge():
    """Kein Test-Zahlen-Badge mehr — er veraltet schneller, als ihn jemand pflegt."""
    text = README.read_text(encoding="utf-8")
    assert "tests-~60" not in text, "Veraltetes tests-~60-Badge noch vorhanden."
    badge = re.search(r"!\[Tests\]\(https://img\.shields\.io/badge/tests-([^)]+)\)", text)
    assert badge is None, (
        f"Handgepflegter Tests-Badge wieder eingeführt: {badge.group(0) if badge else ''}. "
        "Der CI-Workflow-Badge zeigt den Status ohne Pflegeaufwand."
    )


def test_ci_status_badge_present():
    """Statt der Zahl steht der automatische CI-Status im README-Kopf."""
    text = README.read_text(encoding="utf-8")
    assert "actions/workflows/ci.yml/badge.svg" in text, (
        "CI-Status-Badge fehlt — ohne ihn sagt der README-Kopf nichts über die Testlage."
    )


def test_dev_doc_no_stale_sixty_and_mentions_external():
    """Die Entwickler-Doku (früher README-Sektion) bleibt bei den Fakten."""
    section = D.DEVELOPMENT_DOC.read_text(encoding="utf-8")
    assert "~60 Tests" not in section, "Doku nennt noch '~60 Tests'."
    lowered = section.lower()
    assert any(
        token in lowered
        for token in ("network", "netzwerk", "external", "extern", "api-key", "api_key")
    ), "Kein Hinweis auf Network/External-abhängige Tests in der Entwickler-Doku."
    assert "--collect-only" in section, (
        "Doku sagt nicht, wie man die aktuelle Testzahl selbst ermittelt."
    )
