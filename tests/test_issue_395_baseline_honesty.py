"""Regressionstest fuer PR #439 Fix-Runde (Issue #395) — Guard-Baseline-Ehrlichkeit.

Review-Fund: `tests/baselines/skill_sizes.json` hebt die zotero-import-Baseline von
4524 (E3-Referenzwert vor #395, git-verifiziert ueber den main-Merge-Base-Commit) auf
4565 an. Ohne diese Anhebung waere die Marge fuer `test_token_reduction`
(``tests/test_skills_manifest.py``) nur 4524 - 3129 = 1395 Zeichen — unter dem
geforderten Minimum von 1400, der Test schluege fehl. CHANGELOG.md (und der PR-Body
von #439) behaupten aber woertlich das Gegenteil: "nicht aus einer Anhebung der
Guard-Baseline". Das ist bei diesem konkreten Wert falsifizierbar.

Eine Baseline-Anhebung um den Netto-Zuwachs ist fuer sich genommen kein Fehlverhalten
— sie ist im Repo etabliertes, mehrfach akzeptiertes Muster (89ca331:
reading-list-import +500 Zeichen Zuwachs -> +510 Baseline; d12a976: book-handler
+183 Baseline). Das eigentliche Problem ist die falsche Behauptung, es habe *keine*
Anhebung gegeben, nicht die Anhebung selbst.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
BASELINES_PATH = REPO_ROOT / "tests" / "baselines" / "skill_sizes.json"

# E3-Referenzwert vor Issue #395 — git-verifiziert:
#   git show <merge-base main feat/395-zotero-annotation-import>:tests/baselines/skill_sizes.json
PRE_395_ZOTERO_IMPORT_BASELINE = 4524

FALSE_CLAIM = "nicht aus einer Anhebung der Guard-Baseline"


def _current_zotero_import_baseline() -> int:
    baselines = json.loads(BASELINES_PATH.read_text(encoding="utf-8"))
    assert "zotero-import" in baselines, "zotero-import fehlt in skill_sizes.json"
    return int(baselines["zotero-import"])


def _changelog_395_entry() -> str:
    text = CHANGELOG.read_text(encoding="utf-8")
    marker = "**Zotero-Annotation-Import (#395):**"
    idx = text.find(marker)
    assert idx != -1, "CHANGELOG-Eintrag zu #395 nicht gefunden"
    end = text.find("\n- **", idx + len(marker))
    if end == -1:
        end = len(text)
    return text[idx:end]


def test_zotero_import_baseline_premise_still_holds():
    """Canary: haelt fest, DASS die Baseline vom E3-Referenzwert abweicht.

    Sollte die Baseline irgendwann wieder auf 4524 zurueckgesetzt werden (z.B. weil
    die Annotation-Doku komplett anders geloest wird), ist die eigentliche Pruefung
    unten gegenstandslos -- dieser Test macht die Praemisse explizit statt sie
    stillschweigend vorauszusetzen.
    """
    current = _current_zotero_import_baseline()
    assert current != PRE_395_ZOTERO_IMPORT_BASELINE, (
        f"Praemisse veraendert: Baseline ist wieder {PRE_395_ZOTERO_IMPORT_BASELINE} "
        "-- test_changelog_395_does_not_deny_the_baseline_raise ist dann ueberholt "
        "und kann entfernt werden."
    )


def test_changelog_395_does_not_deny_the_baseline_raise():
    """CHANGELOG darf nicht behaupten, es gebe keine Baseline-Anhebung, solange
    tests/baselines/skill_sizes.json genau das zeigt (4524 -> aktueller Wert)."""
    current = _current_zotero_import_baseline()
    entry = _changelog_395_entry()
    if current != PRE_395_ZOTERO_IMPORT_BASELINE:
        assert FALSE_CLAIM not in entry, (
            f"CHANGELOG behauptet '{FALSE_CLAIM}', aber tests/baselines/skill_sizes.json "
            f"zeigt zotero-import {PRE_395_ZOTERO_IMPORT_BASELINE} -> {current} "
            "(Widerspruch, PR #439 Fix-Runde: Guard-Baseline wurde sehr wohl angehoben, "
            "die Doku muss das benennen statt es zu verneinen)."
        )
