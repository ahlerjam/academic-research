"""Regressionstests fuer Finding 11 (PR fix/code-review-max-findings):

`.github/scripts/flowkit_review/apply_verdicts.py` joint refutierte
Verifier-Verdicts bisher exakt auf dem Tripel ``(file, line, title)`` -- aber
die --json-schema des Verifier-Jobs (``pr-deep-review.yml:686``) macht
``file``/``line`` OPTIONAL und NULLABLE:

    {"required": ["title", "verdict"],
     "properties": {..., "file": {"type": ["string", "null"]},
                    "line": {"type": ["integer", "null"]}}}

Ein schema-konformer Verdict fuer einen gemergten P1-Fund kann also z. B.
``{"title": "...", "verdict": "refuted"}`` ganz ohne ``file``/``line`` sein.
Die alte ``_key()``-Bildung lieferte dann ``(None, None, title)`` -- das
matcht nie das Finding mit ``(file, line, title)``. ``apply_verdicts`` droppte
0 refutierte Funde, ``gate.py`` zaehlte den laengst refutierten Fund weiter
als Blocker, und weder Log noch Sticky-Comment zeigten, dass der Join
fehlgeschlagen war.

Fix: robustes Matching -- der Titel ist Pflicht, ``file``/``line`` werden nur
verglichen, wenn der Verdict sie ueberhaupt mitliefert (nicht ``None``). Ein
Verdict, der auf 0 oder >1 Findings passt, wird NICHT gedroppt (lieber gar
nichts droppen als den falschen Fund entfernen), sondern ueber
``unresolved_verdicts()`` sichtbar gemacht und vom CLI laut auf stderr
geloggt (statt eines stillen No-Op).

Import: analog zu ``test_issue_469_flowkit_review_pipeline.py`` per
``importlib.util``, da ``.github/scripts/flowkit_review/`` kein installiertes
Package ist.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
_FLOWKIT_REVIEW_DIR = ROOT / ".github" / "scripts" / "flowkit_review"
_SCRIPT = _FLOWKIT_REVIEW_DIR / "apply_verdicts.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_flowkit_review_apply_verdicts", _SCRIPT)
    assert spec is not None and spec.loader is not None, "Konnte apply_verdicts.py nicht laden"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_module = _load_module()
apply_verdicts = _module.apply_verdicts
unresolved_verdicts = _module.unresolved_verdicts


def _findings(items: list[dict]) -> dict:
    return {"findings": items}


def _verdicts(items: list[dict]) -> dict:
    return {"verdicts": items}


# ---------------------------------------------------------------------------
# Kernbefund: Verdict ohne file/line (schema-konform) muss trotzdem matchen
# ---------------------------------------------------------------------------


def test_refuted_verdict_without_file_line_drops_finding():
    """Finding 11 Kernszenario: schema-konformer Verdict ohne file/line."""
    findings = _findings(
        [
            {
                "severity": "P1",
                "title": "SQL injection in query builder",
                "file": "academic_vault/db.py",
                "line": 1234,
                "evidence": "...",
            }
        ]
    )
    verdicts = _verdicts([{"title": "SQL injection in query builder", "verdict": "refuted"}])

    result = apply_verdicts(findings, verdicts)

    assert result["findings"] == []
    assert unresolved_verdicts(findings, verdicts) == []


def test_refuted_verdict_with_explicit_null_file_line_drops_finding():
    """Verdict liefert file/line explizit als JSON-null (nicht nur fehlend)."""
    findings = _findings(
        [{"severity": "P0", "title": "hardcoded secret", "file": "app.py", "line": 42}]
    )
    verdicts = _verdicts(
        [{"title": "hardcoded secret", "file": None, "line": None, "verdict": "refuted"}]
    )

    result = apply_verdicts(findings, verdicts)

    assert result["findings"] == []


def test_exact_match_still_drops_as_before():
    """Regression: der vorherige exakte (file, line, title)-Fall bleibt funktionsfaehig."""
    findings = _findings([{"severity": "P1", "title": "leak", "file": "a.py", "line": 10}])
    verdicts = _verdicts([{"title": "leak", "file": "a.py", "line": 10, "verdict": "refuted"}])

    result = apply_verdicts(findings, verdicts)

    assert result["findings"] == []


def test_confirmed_verdict_never_drops():
    findings = _findings([{"severity": "P1", "title": "leak", "file": "a.py", "line": 10}])
    verdicts = _verdicts([{"title": "leak", "verdict": "confirmed"}])

    result = apply_verdicts(findings, verdicts)

    assert result["findings"] == findings["findings"]


def test_no_verdicts_drops_nothing():
    findings = _findings([{"severity": "P1", "title": "leak", "file": "a.py", "line": 10}])

    result = apply_verdicts(findings, {})

    assert result["findings"] == findings["findings"]


# ---------------------------------------------------------------------------
# Mehrdeutigkeit: title-only match auf mehrere Findings darf NICHTS droppen
# ---------------------------------------------------------------------------


def test_ambiguous_title_only_match_refuses_to_drop():
    """Zwei Findings mit gleichem Titel in verschiedenen Dateien: der Verdict
    liefert kein file/line -> Mehrdeutigkeit -> lieber gar nichts droppen als
    den falschen Fund zu entfernen."""
    findings = _findings(
        [
            {"severity": "P1", "title": "unchecked input", "file": "a.py", "line": 1},
            {"severity": "P1", "title": "unchecked input", "file": "b.py", "line": 2},
        ]
    )
    verdicts = _verdicts([{"title": "unchecked input", "verdict": "refuted"}])

    result = apply_verdicts(findings, verdicts)
    unresolved = unresolved_verdicts(findings, verdicts)

    assert len(result["findings"]) == 2
    assert len(unresolved) == 1
    assert unresolved[0]["title"] == "unchecked input"
    assert unresolved[0]["_match_count"] == 2


def test_disambiguated_by_file_when_title_alone_is_ambiguous():
    """Gleicher Titel, aber der Verdict nennt die Datei -> eindeutig, wird gedroppt."""
    findings = _findings(
        [
            {"severity": "P1", "title": "unchecked input", "file": "a.py", "line": 1},
            {"severity": "P1", "title": "unchecked input", "file": "b.py", "line": 2},
        ]
    )
    verdicts = _verdicts([{"title": "unchecked input", "file": "b.py", "verdict": "refuted"}])

    result = apply_verdicts(findings, verdicts)

    remaining = result["findings"]
    assert len(remaining) == 1
    assert remaining[0]["file"] == "a.py"
    assert unresolved_verdicts(findings, verdicts) == []


# ---------------------------------------------------------------------------
# Unmatched: Verdict passt zu keinem Finding -> sichtbar zaehlen, nichts droppen
# ---------------------------------------------------------------------------


def test_unmatched_verdict_is_counted_not_silently_dropped():
    findings = _findings([{"severity": "P1", "title": "leak", "file": "a.py", "line": 10}])
    verdicts = _verdicts([{"title": "some other finding entirely", "verdict": "refuted"}])

    result = apply_verdicts(findings, verdicts)
    unresolved = unresolved_verdicts(findings, verdicts)

    assert result["findings"] == findings["findings"]
    assert len(unresolved) == 1
    assert unresolved[0]["title"] == "some other finding entirely"
    assert unresolved[0]["_match_count"] == 0


# ---------------------------------------------------------------------------
# CLI: unmatched/ambiguous Verdicts erzeugen eine sichtbare Warnung auf stderr
# ---------------------------------------------------------------------------


def test_cli_warns_loudly_when_verdict_cannot_be_matched(tmp_path: Path):
    findings_path = tmp_path / "findings.json"
    verdicts_path = tmp_path / "verdicts.json"
    output_path = tmp_path / "out.json"

    findings_path.write_text(
        json.dumps({"findings": [{"severity": "P1", "title": "leak", "file": "a.py", "line": 10}]})
    )
    verdicts_path.write_text(
        json.dumps({"verdicts": [{"title": "totally unrelated", "verdict": "refuted"}]})
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--findings",
            str(findings_path),
            "--verdicts",
            str(verdicts_path),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "::warning::" in proc.stderr
    assert "1 verdict(s) could not be matched" in proc.stderr
    # Der Fund bleibt erhalten, weil der Verdict nicht sicher zugeordnet werden konnte.
    result = json.loads(output_path.read_text())
    assert len(result["findings"]) == 1


def test_cli_drops_finding_when_verdict_lacks_file_line_end_to_end(tmp_path: Path):
    """End-to-end-Reproduktion des Finding-11-Szenarios ueber die CLI."""
    findings_path = tmp_path / "findings.json"
    verdicts_path = tmp_path / "verdicts.json"
    output_path = tmp_path / "out.json"

    findings_path.write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "severity": "P1",
                        "title": "SQL injection in query builder",
                        "file": "academic_vault/db.py",
                        "line": 1234,
                    }
                ]
            }
        )
    )
    verdicts_path.write_text(
        json.dumps(
            {"verdicts": [{"title": "SQL injection in query builder", "verdict": "refuted"}]}
        )
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--findings",
            str(findings_path),
            "--verdicts",
            str(verdicts_path),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "dropped 1 refuted finding(s)" in proc.stderr
    assert "::warning::" not in proc.stderr
    result = json.loads(output_path.read_text())
    assert result["findings"] == []
