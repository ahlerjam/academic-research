"""Tests fuer die produktive Anbindung des NLI-Zitatscans (Issue #717).

Der Scan selbst existiert seit #592 (``academic_vault/nli_prefilter.py``),
hatte aber keinen produktiven Aufrufer. Diese Datei deckt die
Akzeptanzkriterien der Anbindung ab:

  AC1  Nach einem Kapitel-Write werden ALLE im Vault belegten Zitate des
       Kapitels gescannt, ohne den Write zu verzoegern oder zu blockieren.
  AC2  Kein Zitat wird aus dem Pruefpfad entfernt (Detektor statt Filter) --
       als "treu" eingestufte Zitate werden lediglich nicht gemeldet.
  AC3  Verdaechtige Fundstellen tragen Zitat, Paper und Kapitelsatz.
  AC4  Default aktiv, ueber einen dokumentierten Schalter abschaltbar.
  AC5  Fehlendes/kaputtes Modell -> einmal sichtbar gemeldet, Sitzung laeuft.
  AC6  50 Zitate unter 10 s; die gemessene Laufzeit steht in der Doku.
  AC7  Ein Hook-Harness deckt den neuen Hook ab.

Kein Modell-Download, kein Netz: der Scorer wird ausschliesslich gestubbt.
Die Node-Seite des Hooks pruefen ``scripts/dev/test-nli-quote-scan-hook.sh``
(Verhalten) und die Strukturtests hier (Verdrahtung).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from academic_vault.nli_prefilter import (
    resolve_nli_prefilter_enabled,
    run_batch_prefilter,
)
from academic_vault.nli_scan_worker import main as worker_main
from academic_vault.nli_scan_worker import scan_chapter, scan_to_spool

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_FILE = REPO_ROOT / "hooks" / "nli-quote-scan.mjs"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
HARNESS = REPO_ROOT / "scripts" / "dev" / "test-nli-quote-scan-hook.sh"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
HOOKS_DOC = REPO_ROOT / "docs" / "reference" / "hooks.md"


class StubScorer:
    """Deterministischer Scorer ohne Modell: Urteil je Hypothese."""

    name = "stub"

    def __init__(self, verdict_by_hypothesis: dict[str, str], latency: float = 0.0) -> None:
        self._verdicts = verdict_by_hypothesis
        self._latency = latency
        self.calls = 0

    def predict(self, premise: str, hypothesis: str) -> tuple[str, float]:
        self.calls += 1
        if self._latency:
            time.sleep(self._latency)
        verdict = self._verdicts.get(hypothesis, "verzerrend")
        return verdict, 0.9 if verdict == "faithful" else 0.1


class ExplodingScorer:
    """Steht fuer ein fehlendes/kaputtes Modell (AC5)."""

    name = "exploding"

    def predict(self, premise: str, hypothesis: str) -> tuple[str, float]:
        raise OSError("Modellgewichte nicht gefunden: MoritzLaurer/mDeBERTa-v3-base-xnli")


def _items(n: int = 3) -> list[dict]:
    return [
        {
            "quote_id": f"q{i}",
            "chapter_claim": f"Behauptung {i}",
            "paper_id": "paper-1",
            "context_before": "vor",
            "verbatim": f"verbatim {i}",
            "context_after": "nach",
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# AC2 -- Detektor statt Filter
# ---------------------------------------------------------------------------


def test_batch_prefilter_detector_forwards_every_item_regardless_of_verdict():
    """AC2: nichts wird uebersprungen; treue Items werden nur nicht gemeldet."""
    items = _items(3)
    scorer = StubScorer(
        {
            "Behauptung 0": "faithful",
            "Behauptung 1": "verzerrend",
            "Behauptung 2": "faithful",
        }
    )
    result = run_batch_prefilter(items, scorer=scorer, enabled=True)

    assert result["enabled"] is True
    assert len(result["forwarded"]) == len(items), (
        "Detektor-Modus darf kein Zitat aus dem Pruefpfad entfernen."
    )
    assert {f["quote_id"] for f in result["forwarded"]} == {"q0", "q1", "q2"}
    assert result["skipped"] == [], "Detektor-Modus kennt keine uebersprungenen Items."
    assert {s["quote_id"] for s in result["suspicious"]} == {"q1"}


def test_batch_prefilter_forwarded_shape_is_identical_enabled_and_disabled():
    """Der Auditor-Input bleibt in beiden Schalterstellungen bytegleich."""
    items = _items(2)
    scorer = StubScorer({"Behauptung 0": "faithful", "Behauptung 1": "verzerrend"})
    on = run_batch_prefilter(items, scorer=scorer, enabled=True)
    off = run_batch_prefilter(items, enabled=False)
    assert on["forwarded"] == off["forwarded"]


def test_batch_prefilter_disabled_reports_nothing_suspicious():
    """AC4: abgeschaltet == heutiger Zustand ohne Scan, keine Meldung."""
    result = run_batch_prefilter(_items(3), enabled=False)
    assert result["enabled"] is False
    assert result["suspicious"] == []
    assert result["skipped"] == []
    assert len(result["forwarded"]) == 3


def test_no_skip_marker_symbol_remains_in_prefilter_module():
    """AC2: Der Filter-Marker darf nicht als toter Pfad zurueckbleiben."""
    source = (REPO_ROOT / "academic_vault" / "nli_prefilter.py").read_text(encoding="utf-8")
    assert "SKIP_MARKER" not in source
    assert "vorgefiltert, nicht inhaltlich geprueft" not in source


# ---------------------------------------------------------------------------
# AC4 -- Schalter, Default an
# ---------------------------------------------------------------------------


def test_prefilter_enabled_by_default_without_config_and_without_env(tmp_path, monkeypatch):
    monkeypatch.delenv("ACADEMIC_RESEARCH_NLI_PREFILTER", raising=False)
    assert resolve_nli_prefilter_enabled(config_path=tmp_path / "fehlt.json") is True


def test_env_off_beats_config_on(tmp_path, monkeypatch):
    monkeypatch.setenv("ACADEMIC_RESEARCH_NLI_PREFILTER", "0")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"nli_prefilter_enabled": True}), encoding="utf-8")
    assert resolve_nli_prefilter_enabled(config_path=config) is False


def test_shipped_config_has_prefilter_true():
    from academic_vault.nli_prefilter import DEFAULT_CONFIG_PATH

    data = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    assert data["nli_prefilter_enabled"] is True


def test_switch_documented_in_hooks_reference():
    """AC4: 'dokumentierter Schalter' — Configschluessel UND Env-Variable."""
    doc = HOOKS_DOC.read_text(encoding="utf-8")
    assert "nli_prefilter_enabled" in doc
    assert "ACADEMIC_RESEARCH_NLI_PREFILTER" in doc


# ---------------------------------------------------------------------------
# AC1/AC3 -- Worker gegen einen echten Vault
# ---------------------------------------------------------------------------


def _seed_chapter(db_path: str, tmp_path: Path, verbatims: list[str]) -> tuple[Path, list[str]]:
    from academic_vault.server import add_paper, add_quote

    add_paper(
        db_path=db_path,
        paper_id="paper-717",
        csl_json=json.dumps(
            {
                "title": "Governance in DevOps-Organisationen",
                "type": "article-journal",
                "issued": {"date-parts": [[2021]]},
                "author": [{"family": "Mueller", "given": "Anna"}],
            }
        ),
    )
    quote_ids = [
        add_quote(
            db_path=db_path,
            paper_id="paper-717",
            verbatim=v,
            context_before="Kontext davor aus der Quelle.",
            context_after="Kontext danach aus der Quelle.",
            extraction_method="manual",
        )
        for v in verbatims
    ]
    chapter_dir = tmp_path / "kapitel"
    chapter_dir.mkdir(exist_ok=True)
    chapter = chapter_dir / "03.md"
    body = ["Einleitender Satz ohne jeden Beleg."]
    for i, v in enumerate(verbatims):
        body.append(f'Befund {i} laut Mueller (2021): "{v}" — das stuetzt These {i}.')
    body.append(
        'Ein nicht im Vault vorhandenes Fantasiezitat: "Dieses Zitat existiert nirgendwo im Bestand."'
    )
    chapter.write_text(" ".join(body), encoding="utf-8")
    return chapter, quote_ids


def test_worker_scans_all_vault_backed_quotes_of_chapter(temp_vault_db, tmp_path):
    """AC1: alle belegten Zitate des Kapitels, nicht nur die mit Drift-Warnung."""
    verbatims = [
        "Der erste Befund zeigt einen deutlichen Zusammenhang zwischen beiden Variablen.",
        "Der zweite Befund widerspricht dieser Interpretation in wesentlichen Teilen.",
        "Der dritte Befund bleibt in der Stichprobe statistisch nicht signifikant.",
    ]
    chapter, quote_ids = _seed_chapter(temp_vault_db, tmp_path, verbatims)
    spool = tmp_path / "spool"

    scorer = StubScorer({})  # alles verzerrend -> alles gemeldet
    written = scan_to_spool(chapter, temp_vault_db, spool, scorer=scorer, enabled=True)

    assert written is not None
    record = json.loads(written.read_text(encoding="utf-8"))
    assert record["scanned"] == len(quote_ids)
    assert scorer.calls == len(quote_ids)
    assert {f["quote_id"] for f in record["findings"]} == set(quote_ids)
    # Das erfundene Zitat darf nicht auftauchen (keine Fabrikation).
    assert all("nirgendwo im Bestand" not in f["verbatim"] for f in record["findings"])


def test_worker_reports_only_suspicious_but_scans_all(temp_vault_db, tmp_path):
    """AC2 am Worker: treue Zitate werden gescannt, aber nicht gemeldet."""
    verbatims = [
        "Der erste Befund zeigt einen deutlichen Zusammenhang zwischen beiden Variablen.",
        "Der zweite Befund widerspricht dieser Interpretation in wesentlichen Teilen.",
    ]
    chapter, _ = _seed_chapter(temp_vault_db, tmp_path, verbatims)
    content = chapter.read_text(encoding="utf-8")
    # Beide Kapitelsaetze als "treu" einstufen -> Scan laeuft, Meldung leer.
    from academic_vault.nli_prefilter import claim_sentence_for_span, extract_quote_spans

    claims = {claim_sentence_for_span(content, s): "faithful" for s in extract_quote_spans(content)}
    scorer = StubScorer(claims)

    record = scan_chapter(chapter, temp_vault_db, scorer=scorer, enabled=True)

    assert record is not None
    assert record["scanned"] == 2, "Beide Zitate muessen bewertet worden sein."
    assert scorer.calls == 2
    assert record["findings"] == []

    # Nichts Verdaechtiges -> kein Spool-Eintrag, also auch keine Meldung.
    spool = tmp_path / "spool"
    assert (
        scan_to_spool(chapter, temp_vault_db, spool, scorer=StubScorer(claims), enabled=True)
        is None
    )
    assert not spool.exists() or list(spool.glob("*.json")) == []


def test_finding_record_contains_verbatim_paper_and_claim_sentence(temp_vault_db, tmp_path):
    """AC3: nachvollziehbar ohne Nachschlagen im Vault."""
    verbatim = "Der Befund war in der Replikationsstudie durchgehend reproduzierbar."
    chapter, _ = _seed_chapter(temp_vault_db, tmp_path, [verbatim])
    content = chapter.read_text(encoding="utf-8")

    written = scan_to_spool(
        chapter, temp_vault_db, tmp_path / "spool", scorer=StubScorer({}), enabled=True
    )
    assert written is not None
    finding = json.loads(written.read_text(encoding="utf-8"))["findings"][0]

    assert finding["verbatim"].strip()
    assert verbatim in finding["verbatim"]
    assert finding["paper_id"] == "paper-717"
    assert "Mueller" in finding["paper_ref"], "Kurzbeleg muss ohne Vault-Lookup lesbar sein."
    assert "2021" in finding["paper_ref"]
    assert finding["chapter_claim"].strip()
    assert finding["chapter_claim"] in content
    assert isinstance(finding["raw_score"], float)


def test_worker_writes_nothing_when_switch_is_off(temp_vault_db, tmp_path):
    """AC4 am Worker: abgeschaltet -> kein Spool-Eintrag, kein Scorer-Aufruf."""
    verbatim = "Der Befund war in der Replikationsstudie durchgehend reproduzierbar."
    chapter, _ = _seed_chapter(temp_vault_db, tmp_path, [verbatim])
    scorer = StubScorer({})
    spool = tmp_path / "spool"

    assert scan_to_spool(chapter, temp_vault_db, spool, scorer=scorer, enabled=False) is None
    assert scorer.calls == 0
    assert not spool.exists() or list(spool.glob("*.json")) == []


def test_worker_writes_nothing_when_chapter_has_no_vault_quotes(temp_vault_db, tmp_path):
    chapter = tmp_path / "kapitel" / "leer.md"
    chapter.parent.mkdir(parents=True, exist_ok=True)
    chapter.write_text("Ein Kapitel ganz ohne woertliche Zitate.", encoding="utf-8")
    spool = tmp_path / "spool"
    assert scan_to_spool(chapter, temp_vault_db, spool, scorer=StubScorer({}), enabled=True) is None


# ---------------------------------------------------------------------------
# AC5 -- Fehlerpfad
# ---------------------------------------------------------------------------


def test_worker_writes_error_record_when_model_load_raises(temp_vault_db, tmp_path):
    """AC5: kein Traceback, sondern ein sichtbarer Fehler-Datensatz."""
    verbatim = "Der Befund war in der Replikationsstudie durchgehend reproduzierbar."
    chapter, _ = _seed_chapter(temp_vault_db, tmp_path, [verbatim])

    written = scan_to_spool(
        chapter, temp_vault_db, tmp_path / "spool", scorer=ExplodingScorer(), enabled=True
    )
    assert written is not None
    record = json.loads(written.read_text(encoding="utf-8"))
    assert "error" in record
    assert "Modellgewichte" in record["error"]
    assert record["findings"] == []


def test_worker_main_returns_zero_even_on_error(temp_vault_db, tmp_path, monkeypatch):
    """AC5: der Worker beendet sich nie mit einem Fehlercode."""
    spool = tmp_path / "spool"
    assert worker_main(["nicht/vorhanden.db", str(tmp_path / "fehlt.md"), str(spool)]) == 0
    assert worker_main([]) == 0


def test_worker_main_scans_via_cli(temp_vault_db, tmp_path, monkeypatch):
    """Der CLI-Einstieg schreibt denselben Datensatz wie scan_to_spool."""
    verbatim = "Der Befund war in der Replikationsstudie durchgehend reproduzierbar."
    chapter, _ = _seed_chapter(temp_vault_db, tmp_path, [verbatim])
    spool = tmp_path / "spool"
    monkeypatch.setenv("ACADEMIC_RESEARCH_NLI_PREFILTER", "1")
    monkeypatch.setattr(
        "academic_vault.nli_scan_worker.build_default_scorer", lambda: StubScorer({})
    )

    assert worker_main([temp_vault_db, str(chapter), str(spool)]) == 0
    files = list(spool.glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["findings"]


def test_spool_files_are_owner_only(temp_vault_db, tmp_path):
    """Kapiteltext im Spool ist Nutzerinhalt -- 0600/0700 wie das Decision-Log."""
    verbatim = "Der Befund war in der Replikationsstudie durchgehend reproduzierbar."
    chapter, _ = _seed_chapter(temp_vault_db, tmp_path, [verbatim])
    spool = tmp_path / "spool"
    written = scan_to_spool(chapter, temp_vault_db, spool, scorer=StubScorer({}), enabled=True)
    assert written is not None
    assert written.stat().st_mode & 0o077 == 0
    assert spool.stat().st_mode & 0o077 == 0


def test_concurrent_workers_for_same_chapter_do_not_clobber_each_other(tmp_path, monkeypatch):
    """Regression: der Hook startet je Kapitel-Write einen neuen, detachten
    Worker ohne Lock -- ein deterministischer Temp-Pfad liesse den zweiten
    Worker denselben ``.tmp``-Puffer wie der erste treffen und dessen
    ``replace()`` mit FileNotFoundError scheitern (Befunde gehen still
    verloren, siehe Code-Review PR #754). Der Temp-Name muss deshalb je
    Prozess eindeutig sein."""
    from academic_vault.nli_scan_worker import _write_record

    chapter = tmp_path / "kapitel" / "03.md"
    spool_dir = tmp_path / "spool"

    pids = iter([111, 222])
    monkeypatch.setattr("os.getpid", lambda: next(pids))

    target_a = _write_record(spool_dir, chapter, {"schema": 1, "scanned": 1, "findings": []})
    target_b = _write_record(spool_dir, chapter, {"schema": 1, "scanned": 2, "findings": []})

    assert target_a == target_b, "beide Worker schreiben dasselbe Kapitel-Ziel"
    assert json.loads(target_b.read_text())["scanned"] == 2, (
        "juengerer Lauf gewinnt, ohne zu scheitern"
    )
    assert not list(spool_dir.glob("*.tmp")), "keine liegen gebliebenen Temp-Dateien"


# ---------------------------------------------------------------------------
# AC6 -- Laufzeit
# ---------------------------------------------------------------------------

#: Gemessene Pro-Zitat-Latenz von ``MDebertaScorer`` bei warmem Modell
#: (Apple M-Serie, CPU) -- siehe docs/reference/hooks.md. Der Stub bildet sie
#: nach, damit die Budget-Aussage ohne Modell-Download pruefbar bleibt.
MEASURED_SECONDS_PER_QUOTE = 0.127


def test_scan_of_50_quotes_under_10s_with_stub_scorer(temp_vault_db, tmp_path):
    """AC6: 50 Zitate < 10 s bei der gemessenen Pro-Zitat-Latenz."""
    verbatims = [
        f"Befund Nummer {i:02d} zeigt einen belastbaren Zusammenhang in der Stichprobe."
        for i in range(50)
    ]
    chapter, quote_ids = _seed_chapter(temp_vault_db, tmp_path, verbatims)
    assert len(quote_ids) == 50

    scorer = StubScorer({}, latency=MEASURED_SECONDS_PER_QUOTE)
    started = time.monotonic()
    written = scan_to_spool(chapter, temp_vault_db, tmp_path / "spool", scorer=scorer, enabled=True)
    elapsed = time.monotonic() - started

    assert written is not None
    assert scorer.calls == 50
    assert elapsed < 10.0, f"50 Zitate brauchten {elapsed:.1f} s (Budget 10 s)"


def test_measured_runtime_documented():
    """AC6: die gemessene Laufzeit steht in der Doku, nicht nur im Test."""
    import re

    doc = HOOKS_DOC.read_text(encoding="utf-8")
    section = doc[doc.index("nli-quote-scan.mjs") :]
    matches = re.findall(r"50 Zitate[^\n]*?([0-9]+[,.][0-9]+)\s*s", section)
    assert matches, "Doku nennt keine gemessene Sekundenzahl fuer den 50-Zitate-Fall."
    assert any(float(m.replace(",", ".")) < 10.0 for m in matches)


# ---------------------------------------------------------------------------
# AC1/AC7 -- Verdrahtung
# ---------------------------------------------------------------------------


def test_hook_registered_for_post_tool_use_and_prompt_drain():
    """AC1: der Hook haengt am PostToolUse-Write, nicht an PreToolUse."""
    data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    hooks = data["hooks"]

    def commands(event: str) -> list[str]:
        return [h["command"] for block in hooks.get(event, []) for h in block.get("hooks", [])]

    assert any("nli-quote-scan.mjs" in c for c in commands("PostToolUse"))
    assert any("nli-quote-scan.mjs" in c for c in commands("UserPromptSubmit"))
    assert not any("nli-quote-scan.mjs" in c for c in commands("PreToolUse")), (
        "Der Scan darf den Write nicht blockieren (Scope-Abgrenzung im Issue)."
    )
    assert HOOK_FILE.exists()


def test_post_tool_use_matcher_covers_write_like_tools():
    data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    blocks = [
        b
        for b in data["hooks"]["PostToolUse"]
        if any("nli-quote-scan.mjs" in h["command"] for h in b["hooks"])
    ]
    assert blocks, "Kein PostToolUse-Block fuer nli-quote-scan.mjs"
    assert blocks[0]["matcher"] == "Write|Edit|MultiEdit"


def test_harness_exists_and_is_wired_in_ci():
    """AC7: Hook-Harness analog test-pretooluse-blocker.sh, CI-blockierend."""
    assert HARNESS.exists()
    assert HARNESS.stat().st_mode & 0o100, "Harness ist nicht ausfuehrbar"
    assert "scripts/dev/test-nli-quote-scan-hook.sh" in CI_WORKFLOW.read_text(encoding="utf-8")


def test_hook_documented_in_hooks_reference():
    doc = HOOKS_DOC.read_text(encoding="utf-8")
    assert "nli-quote-scan.mjs" in doc


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
