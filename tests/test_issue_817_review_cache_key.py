"""Tests fuer Issue #817: Review-Cache-Schluessel jenseits der 200-KB-Diffgrenze.

Befund (PR #816, #820, #827): `.github/scripts/flowkit_review/cache_check.py`
hashte bisher die auf 200 KB gekuerzte Diff-Kopie
(`head -c 204800`, `pr-deep-review.yml`), die ausschliesslich fuer das
Kontextbudget der LLM-Reviewer gedacht ist. Grosse Eval-Rohdaten- und
Vektor-Fixture-Dateien unter `docs/evals/` und `tests/fixtures/` fuellen diese
200 KB oft als einzelne Datei aus. Aendert ein Folge-Commit nur Dateien
dahinter, blieb der gekuerzte Diff byte-identisch -> falscher Cache-Treffer ->
Reviewer-Jobs uebersprungen -> `coordinator` wendet die Befunde des vorigen,
laengst behobenen Standes erneut an.

Fix: Der Cache-Schluessel wird jetzt aus dem vollstaendigen, ungekuerzten Diff
gebildet (`diff.patch` statt `diff.bounded.patch` in `pr-deep-review.yml`).
Die 200-KB-Grenze fuer die Reviewer-Uebergabe selbst bleibt unveraendert.

AC1: Ein Folge-Commit, der ausschliesslich Dateien jenseits der 200-KB-Grenze
     aendert, fuehrt zu einem Cache-Miss.
AC2: Ein Lauf ohne jede Aenderung am Diff fuehrt weiterhin zu einem
     Cache-Treffer.
AC3 (dieses Modul): beide Faelle sind maschinell belegt, nicht behauptet.

Import: analog zu `test_issue_469_flowkit_review_pipeline.py` per
`importlib.util`, da `.github/scripts/flowkit_review/` kein installiertes
Package ist und keiner der zentralen `sys.path`-Ausnahmen in `conftest.py`
entspricht.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent
_FLOWKIT_REVIEW_DIR = ROOT / ".github" / "scripts" / "flowkit_review"
PR_DEEP_REVIEW_WORKFLOW = ROOT / ".github" / "workflows" / "pr-deep-review.yml"

BOUND = 204_800  # head -c 204800 in pr-deep-review.yml


def _load_module(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _FLOWKIT_REVIEW_DIR / filename)
    assert spec is not None and spec.loader is not None, f"Konnte {filename} nicht laden"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_cache_check = _load_module("_flowkit_review_cache_check", "cache_check.py")
check = _cache_check.check
JSON_MARKER_OPEN = _cache_check.JSON_MARKER_OPEN
JSON_MARKER_CLOSE = _cache_check.JSON_MARKER_CLOSE


def _sticky_comment(diff_hash: str) -> str:
    """Baut einen Sticky-Comment-Body wie ihn render.py erzeugt."""
    payload = {"diffHash": diff_hash, "findings": [{"severity": "P2", "title": "x"}]}
    return f"{JSON_MARKER_OPEN}\n{json.dumps(payload)}\n{JSON_MARKER_CLOSE}"


def _filler_diff(marker: bytes) -> bytes:
    """Ein Diff, dessen erste >200 KB aus einer grossen Fixture-Datei bestehen
    (z. B. `docs/evals/*.json`) und der DANACH noch einen kleinen Hunk traegt,
    der sich je nach `marker` unterscheidet -- der von #817 beschriebene
    Folge-Commit, der nur Dateien jenseits der Grenze aendert."""
    header = b"diff --git a/docs/evals/big-fixture.json b/docs/evals/big-fixture.json\n"
    # Reichlich Fuellinhalt, deutlich ueber der 200-KB-Grenze.
    filler = b"+" + b"x" * 60 + b"\n"
    filler_block = filler * 5000  # ~ 5000 * 61 Bytes > 300 KB
    assert len(header) + len(filler_block) > BOUND, (
        "Testaufbau muss die 200-KB-Grenze ueberschreiten"
    )
    tail = b"diff --git a/tests/fixtures/vec.json b/tests/fixtures/vec.json\n+" + marker + b"\n"
    return header + filler_block + tail


# --------------------------------------------------------------------------- #
# AC1: Aenderung ausschliesslich jenseits der 200-KB-Grenze -> Cache-Miss
# --------------------------------------------------------------------------- #


def test_cache_miss_when_only_content_beyond_200kb_changes(tmp_path: Path):
    """Ein Folge-Commit, der nur Dateien hinter der 200-KB-Grenze aendert,
    muss den Cache-Schluessel aendern (AC1)."""
    diff_before = _filler_diff(marker=b"OLD_VALUE")
    diff_after = _filler_diff(marker=b"NEW_VALUE")

    # Die ersten 200 KB sind tatsaechlich identisch -- das ist genau der Fehler,
    # den #817 beschreibt: der gekuerzte Diff allein kann die Aenderung nicht
    # sehen.
    assert diff_before[:BOUND] == diff_after[:BOUND]
    assert diff_before != diff_after

    # Regressionsbeleg: mit der ALTEN, auf 200 KB gekuerzten Hash-Basis waeren
    # beide Staende ununterscheidbar gewesen (der eigentliche Bug).
    bounded_hash_before = hashlib.sha256(diff_before[:BOUND]).hexdigest()
    bounded_hash_after = hashlib.sha256(diff_after[:BOUND]).hexdigest()
    assert bounded_hash_before == bounded_hash_after, (
        "Testaufbau ungueltig: die gekuerzten Diffs muessten identisch hashen "
        "(das ist der historische Fehler, den #817 belegt)."
    )

    diff_before_path = tmp_path / "diff_before.patch"
    diff_after_path = tmp_path / "diff_after.patch"
    diff_before_path.write_bytes(diff_before)
    diff_after_path.write_bytes(diff_after)

    # Sticky-Comment aus dem vorigen Lauf traegt den Hash des VOLLEN Vorher-Diffs.
    full_hash_before = hashlib.sha256(diff_before).hexdigest()
    previous_path = tmp_path / "previous-comment.md"
    previous_path.write_text(_sticky_comment(full_hash_before))

    # Der aktuelle Lauf bekommt (nach dem Fix) den VOLLEN Nachher-Diff uebergeben.
    hit, diff_hash, payload = check(diff_after_path, previous_path)

    assert hit is False, (
        "Aenderung jenseits der 200-KB-Grenze haette einen Cache-Miss ausloesen muessen."
    )
    assert diff_hash == hashlib.sha256(diff_after).hexdigest()
    assert payload == {}


# --------------------------------------------------------------------------- #
# AC2: keinerlei Aenderung am Diff -> weiterhin Cache-Treffer
# --------------------------------------------------------------------------- #


def test_cache_hit_when_diff_unchanged(tmp_path: Path):
    """Ein Lauf ohne jede Aenderung am (vollen) Diff bleibt ein Cache-Treffer (AC2)."""
    diff_bytes = _filler_diff(marker=b"UNCHANGED_VALUE")
    diff_path = tmp_path / "diff.patch"
    diff_path.write_bytes(diff_bytes)

    full_hash = hashlib.sha256(diff_bytes).hexdigest()
    previous_path = tmp_path / "previous-comment.md"
    previous_path.write_text(_sticky_comment(full_hash))

    hit, diff_hash, payload = check(diff_path, previous_path)

    assert hit is True, "Unveraenderter Diff haette einen Cache-Treffer ergeben muessen."
    assert diff_hash == full_hash
    assert payload.get("diffHash") == full_hash
    assert payload.get("findings") == [{"severity": "P2", "title": "x"}]


# --------------------------------------------------------------------------- #
# Alter, vor dem Fix gespeicherter diffHash: sauberer Miss, kein Fehler
# --------------------------------------------------------------------------- #


def test_stale_pre_fix_hash_degrades_to_clean_miss(tmp_path: Path):
    """Ein diffHash aus einem Sticky-Comment von VOR diesem Fix (gebildet aus
    dem gekuerzten statt dem vollen Diff) passt nach dem Fix nicht mehr zum neu
    berechneten Hash. Das muss ein sauberer Miss sein, kein Fehler/Crash --
    cache_check.py ist "any anomaly is a MISS" per Design."""
    diff_bytes = _filler_diff(marker=b"SOME_VALUE")
    diff_path = tmp_path / "diff.patch"
    diff_path.write_bytes(diff_bytes)

    stale_hash = hashlib.sha256(diff_bytes[:BOUND]).hexdigest()  # alte, gekuerzte Basis
    previous_path = tmp_path / "previous-comment.md"
    previous_path.write_text(_sticky_comment(stale_hash))

    hit, diff_hash, payload = check(diff_path, previous_path)

    assert hit is False
    assert diff_hash == hashlib.sha256(diff_bytes).hexdigest()
    assert payload == {}


# --------------------------------------------------------------------------- #
# Workflow-Verdrahtung: cache_check.py bekommt den vollen, nicht den
# gekuerzten Diff uebergeben (Regressionsschutz gegen erneutes Vertauschen).
# --------------------------------------------------------------------------- #


def test_workflow_passes_full_diff_to_cache_check_not_bounded_copy():
    data = yaml.safe_load(PR_DEEP_REVIEW_WORKFLOW.read_text(encoding="utf-8"))
    prep_steps = data["jobs"]["prep"]["steps"]
    cache_steps = [
        step for step in prep_steps if isinstance(step, dict) and step.get("id") == "cache"
    ]
    assert len(cache_steps) == 1, "Erwarte genau einen Step mit id: cache im prep-Job."
    run = str(cache_steps[0].get("run", ""))

    assert "cache_check.py" in run
    # Das --diff-Argument selbst muss den vollen Diff referenzieren. Die
    # Kommentarzeilen im Step duerfen "diff.bounded.patch" zwar zur Erklaerung
    # erwaehnen, aber nicht als tatsaechlich uebergebenes Argument.
    assert '--diff "$RUNNER_TEMP/diff.patch"' in run, (
        "cache_check.py muss den vollen Diff (diff.patch) bekommen, nicht die "
        "auf 200 KB gekuerzte Reviewer-Kopie (diff.bounded.patch) -- sonst "
        "lebt der #817-Fehler in der Workflow-Verdrahtung weiter."
    )
    assert '--diff "$RUNNER_TEMP/diff.bounded.patch"' not in run
