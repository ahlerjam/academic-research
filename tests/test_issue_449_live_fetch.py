"""Nachvollzug des Live-Belegs zu AC1 (Issue #449) gegen das echte Netz.

Dieser Lauf ist **opt-in**: ohne ``RUN_LIVE_PUBLISHER_FETCH=1`` skippt jeder
Test. CI faehrt ihn nicht — ein Ausfall bei Cambridge University Press, Oxford
University Press oder JSTOR darf diese Pipeline nicht rot faerben (dieselbe
Begruendung, mit der ``docs/evals/STRATEGY.md`` ``publisher-fetchers`` als
``structural`` fuehrt).

Warum es ihn trotzdem gibt: ``evals/publisher-fetchers/live-verification.json``
behauptet, dass am 2026-07-29 zwei Verlage ein vollstaendiges Buch-PDF ohne Login
herausgegeben haben und JSTOR den Volltext-Endpunkt mit einer Bot-Challenge
beantwortet hat. **Eine Behauptung, die niemand nachfahren kann, ist kein Beleg**
— genau daran ist die erste Fix-Runde zu PR #500 gescheitert. Dieser Test ist der
Nachfahrweg:

    RUN_LIVE_PUBLISHER_FETCH=1 uv run pytest tests/test_issue_449_live_fetch.py -v

Was hart und was weich geprueft wird, ist nicht Geschmack, sondern gemessen:

* **Cambridge Core** — voll hart. Zwei vollstaendige Abrufe lieferten byteweise
  dieselbe Datei, das PDF traegt keinen abruf-abhaengigen Stempel. Hier wird
  ``sha256`` verglichen.
* **Oxford Academic** — ``sha256`` ist hier bewusst *kein* Kriterium: Oxford
  stempelt das Abrufdatum auf Seite 1, die Bytes aendern sich taeglich. Geprueft
  werden Seitenzahl, PDF-Titel und der ``by guest``-Stempel — Letzterer ist
  Oxfords eigene Kennzeichnung fuer eine nicht angemeldete Sitzung und damit der
  eigentliche Beleg fuer den Login-freien Bezug.
* **JSTOR** — geprueft werden Status 403 und die stabilen DOM-Marker der
  Challenge. Block-Referenz, VID, IP und Uhrzeit werden ausdruecklich **nicht**
  verglichen; sie sind pro Request neu. ``test_jstor_block_reference_rotates``
  fuehrt genau das vor, statt es nur zu behaupten.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from pypdf import PdfReader

REPO_ROOT = Path(__file__).parent.parent
RECORD_PATH = REPO_ROOT / "evals" / "publisher-fetchers" / "live-verification.json"

RUN_LIVE = os.environ.get("RUN_LIVE_PUBLISHER_FETCH") == "1"
TIMEOUT_SECONDS = 300
USER_AGENT = "academic-research/publisher-fetchers (Issue #449 live verification)"
GUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")

pytestmark = pytest.mark.skipif(
    not RUN_LIVE,
    reason="Live-Lauf gegen fremde Verlagsseiten — nur mit RUN_LIVE_PUBLISHER_FETCH=1",
)


def _record() -> dict:
    return json.loads(RECORD_PATH.read_text(encoding="utf-8"))


def _run(eval_case: str) -> dict:
    return next(run for run in _record()["runs"] if run["eval_case"] == eval_case)


def _fetch(url: str, referer: str | None = None) -> tuple[int, str, bytes]:
    """Holt ``url`` anonym. Gibt (status, content_type, body) zurueck.

    Ein HTTP-Fehler ist hier ein Ergebnis, kein Abbruch — der JSTOR-Fall
    *erwartet* 403.
    """
    headers = {"User-Agent": USER_AGENT}
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return response.status, response.headers.get_content_type(), response.read()
    except urllib.error.HTTPError as error:  # 403/404 sind auswertbare Antworten
        return error.code, error.headers.get_content_type(), error.read()


def _fetch_recorded_pdf(eval_case: str, tmp_path: Path) -> tuple[dict, bytes]:
    run = _run(eval_case)
    chain = run["url_chain"]
    status, content_type, body = _fetch(chain[-1], referer=chain[-2] if len(chain) > 1 else None)

    assert status == run["artifact"]["http_status"], (
        f"{eval_case}: erwartet HTTP {run['artifact']['http_status']}, bekommen {status}."
    )
    assert content_type == run["artifact"]["content_type"]
    assert body.startswith(b"%PDF-"), (
        f"{eval_case}: Antwort ist kein PDF (beginnt mit {body[:16]!r}) — "
        f"der aufgezeichnete Volltext-Bezug laesst sich so nicht nachfahren."
    )
    (tmp_path / f"{eval_case}.pdf").write_bytes(body)
    return run, body


def _first_page_text(body: bytes, tmp_path: Path, name: str) -> str:
    path = tmp_path / f"{name}.pdf"
    path.write_bytes(body)
    return PdfReader(str(path)).pages[0].extract_text() or ""


# ---------------------------------------------------------------------------
# Cambridge Core — der Beleg ist byteweise reproduzierbar
# ---------------------------------------------------------------------------


def test_cambridge_core_still_serves_the_recorded_pdf(tmp_path: Path):
    run, body = _fetch_recorded_pdf("pf-06", tmp_path)
    artifact = run["artifact"]

    reader = PdfReader(str(tmp_path / "pf-06.pdf"))
    assert len(reader.pages) == artifact["pages"]
    assert body[:8].decode("latin-1") == artifact["magic"]

    assert artifact["sha256_stable"] is True
    assert hashlib.sha256(body).hexdigest() == artifact["sha256"], (
        "Cambridge liefert andere Bytes als aufgezeichnet. Der Beleg ist damit "
        "nicht mehr byteweise nachfahrbar — live-verification.json anpassen und "
        "'sha256_stable' neu bewerten, statt die Assertion zu lockern."
    )

    page_one = _first_page_text(body, tmp_path, "pf-06-p1")
    assert run["item"]["doi"] in page_one, (
        "Seite 1 nennt die DOI des Eval-Falls nicht mehr — das PDF gehoert dann "
        "womoeglich nicht mehr zu diesem Titel."
    )


# ---------------------------------------------------------------------------
# Oxford Academic — sha256 scheidet als Kriterium aus, der Stempel traegt
# ---------------------------------------------------------------------------


def test_oxford_academic_still_serves_the_recorded_pdf(tmp_path: Path):
    run, body = _fetch_recorded_pdf("pf-07", tmp_path)
    artifact = run["artifact"]

    reader = PdfReader(str(tmp_path / "pf-07.pdf"))
    assert len(reader.pages) == artifact["pages"]
    assert body[:8].decode("latin-1") == artifact["magic"]
    assert artifact["sha256_stable"] is False


def test_oxford_academic_pdf_is_served_without_login(tmp_path: Path):
    """``by guest`` ist Oxfords eigene Kennzeichnung der anonymen Sitzung."""
    run, body = _fetch_recorded_pdf("pf-07", tmp_path)
    page_one = _first_page_text(body, tmp_path, "pf-07-p1")
    assert "by guest" in page_one, (
        "Der 'by guest'-Stempel fehlt auf Seite 1. Er ist der eigentliche Beleg "
        f"dafuer, dass der Bezug ohne Login lief — vgl. no_login_evidence im "
        f"Lauf '{run['agent']}'."
    )


# ---------------------------------------------------------------------------
# JSTOR — die Challenge ist der Beleg, ihre Kennnummern sind es nicht
# ---------------------------------------------------------------------------


def test_jstor_fulltext_endpoint_still_answers_with_a_challenge():
    run = _run("pf-08")
    status, _, body = _fetch(run["url_chain"][-1])
    html = body.decode("utf-8", errors="replace")

    assert status == run["artifact"]["http_status"], (
        f"JSTOR antwortet mit {status} statt "
        f"{run['artifact']['http_status']} — die aufgezeichnete Begruendung fuer "
        f"'equals:captcha' traegt dann nicht mehr und AC1 ist neu zu bewerten."
    )
    for marker in run["artifact"]["stable_markers"]:
        assert marker in html, f"Stabil-Marker {marker!r} fehlt in der Live-Antwort."


def test_jstor_block_reference_rotates():
    """Fuehrt vor, warum die Block-Referenz kein Beleg sein kann.

    Die erste Fix-Runde zu PR #500 hat genau diesen Wert als Nachweis in
    evals.json und CHANGELOG.md eingetragen. Zwei Abrufe genuegen, um zu zeigen,
    dass er bei jedem Request neu vergeben wird — niemand kann ihn nachpruefen,
    auch der Autor nicht.
    """
    url = _run("pf-08")["url_chain"][-1]
    references = []
    for _ in range(2):
        _, _, body = _fetch(url)
        found = GUID_RE.search(body.decode("utf-8", errors="replace"))
        assert found, "Challenge-Seite ohne Block-Referenz — Annahme pruefen."
        references.append(found.group(0))

    assert references[0] != references[1], (
        "Beide Abrufe lieferten dieselbe Block-Referenz. Dann waere die Annahme "
        "hinter 'volatile_fields_excluded' falsch und die Begruendung in "
        "live-verification.json muesste korrigiert werden."
    )
