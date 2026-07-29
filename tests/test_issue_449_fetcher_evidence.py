"""
Beleg-Kopplung fuer die drei neuen Verlags-Fetcher (Issue #449, PR #500).

Diese Datei ist das Ergebnis zweier Review-Runden, und die zweite ist der
eigentliche Grund fuer ihre heutige Form.

**Erste Runde** bemaengelte zu Recht, dass pf-06/07/08 in
``evals/publisher-fetchers/evals.json`` nur die Existenz eines ``status``-Felds
prueften — eine Aussage, die auch ``no_match`` erfuellt.

**Zweite Runde** bemaengelte, dass die Antwort darauf keinen pruefbaren Beleg
schuf, sondern nur Prosa: Die Notizen behaupteten reale Laeufe (228-Seiten-PDF,
225-Seiten-PDF, JSTOR-CAPTCHA) und untermauerten sie mit JSTOR-Block-Referenz,
Client-IP und Uhrzeit. Diese drei Angaben sind pro Request neu — zwei Abrufe im
Abstand von Sekunden liefern zwei verschiedene Block-Referenzen. Sie sind damit
per Konstruktion von niemandem nachpruefbar, auch nicht vom Autor selbst.
Abgesichert war die Behauptung ausgerechnet durch einen Test, der pruefte, ob das
Wort ``verifiziert`` in der Notiz vorkommt. Der blieb gruen, wenn man die Notiz
durch eine beliebige Unwahrheit ersetzte — ein Test ueber den Wortlaut einer
Behauptung, nicht ueber die behauptete Tatsache.

Die Laeufe selbst waren echt; falsch war die Form des Belegs. Deshalb gilt hier:

* Der Beleg liegt als maschinell pruefbares Artefakt in
  ``evals/publisher-fetchers/live-verification.json`` (URL-Kette, HTTP-Status,
  Bytes, SHA-256, Seitenzahl) — nachfahrbar mit
  ``RUN_LIVE_PUBLISHER_FETCH=1 uv run pytest tests/test_issue_449_live_fetch.py``.
* Der JSTOR-Fall haengt an einer **echt aufgezeichneten** Challenge-Seite
  (``tests/fixtures/publisher_fetchers/jstor_access_check.html``), die hermetisch
  gegen die Captcha-Erkennung des Repos gefahren wird. Das prueft die behauptete
  Tatsache, nicht ihre Formulierung.
* Einmalige Bezeichner (Block-Referenz, IP, Uhrzeit) sind als Beleg ausdruecklich
  verboten — ``test_no_single_use_identifiers_are_presented_as_evidence`` faellt
  um, wenn sie zurueckkehren.

Keine Assertion hier prueft, ob ein bestimmtes Wort in einer Notiz steht.
"""

import json
import re
from pathlib import Path

import pytest

from tests.helpers.generic_fetcher_nav import GenericFetcherNavigator

REPO_ROOT = Path(__file__).parent.parent
EVALS_PATH = REPO_ROOT / "evals" / "publisher-fetchers" / "evals.json"
RECORD_PATH = REPO_ROOT / "evals" / "publisher-fetchers" / "live-verification.json"
JSTOR_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "publisher_fetchers" / "jstor_access_check.html"

#: DOI aus der urspruenglichen PR-#500-Fassung von pf-07. Sie loest real auf
#: academic.oup.com/book/5107 auf und gehoert zu "Philosophies of Qualitative
#: Research" (Svend Brinkmann, 2017) — ein kostenpflichtiges OSO-Buch, keine
#: Open-Access-Publikation. Gegengeprueft ueber Crossref-Content-Negotiation.
WRONG_OXFORD_DOI = "10.1093/oso/9780190247249.001.0001"

EVIDENCE_CASES = ("pf-06", "pf-07", "pf-08")

#: Muster fuer Angaben, die sich pro Request aendern. Als Beleg wertlos, weil
#: niemand — auch der Autor nicht — sie ein zweites Mal erzeugen kann.
SINGLE_USE_PATTERNS = {
    "Block-Referenz/GUID": re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
    ),
    "IPv4-Adresse": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "Uhrzeit-Stempel": re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:UTC|GMT)\b", re.IGNORECASE),
}


def _cases() -> dict:
    return {
        case["id"]: case for case in json.loads(EVALS_PATH.read_text(encoding="utf-8"))["cases"]
    }


def _record() -> dict:
    return json.loads(RECORD_PATH.read_text(encoding="utf-8"))


def _runs() -> dict:
    return {run["eval_case"]: run for run in _record()["runs"]}


# ---------------------------------------------------------------------------
# Die Eval-Faelle tragen konkrete Zielwerte (Fund der ersten Runde)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", EVIDENCE_CASES)
def test_evidence_cases_use_non_trivial_status_check(case_id: str):
    """``exists`` wird auch von ``no_match`` erfuellt und ist keine Aussage."""
    check = _cases()[case_id]["expected"]["check"]
    assert check.startswith("equals:"), (
        f"{case_id}: 'check' muss ein konkretes 'equals:<status>' sein, nicht die "
        f"triviale Existenzpruefung ('{check}'), die jeder Status erfuellt."
    )


def test_oxford_case_does_not_use_the_paywalled_doi():
    """Regression: die urspruengliche DOI referenziert kein OA-Buch."""
    assert _cases()["pf-07"]["input"]["doi"] != WRONG_OXFORD_DOI


# ---------------------------------------------------------------------------
# Jeder Zielwert haengt an einem nachfahrbaren Artefakt (Fund der zweiten Runde)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", EVIDENCE_CASES)
def test_every_evidence_case_has_a_live_verification_run(case_id: str):
    """Ein Zielwert ohne hinterlegten Lauf ist wieder nur eine Behauptung."""
    runs = _runs()
    assert case_id in runs, (
        f"{case_id}: kein Eintrag in {RECORD_PATH.name}. Ein 'equals:<status>' "
        f"ohne nachfahrbaren Lauf ist eine Behauptung, kein Beleg."
    )
    case = _cases()[case_id]
    expected = case["expected"]["check"].split(":", 1)[1]
    assert runs[case_id]["expected_status"] == expected, (
        f"{case_id}: Eval erwartet '{expected}', der aufgezeichnete Lauf aber "
        f"'{runs[case_id]['expected_status']}' — Beleg und Erwartung sind entkoppelt."
    )
    assert runs[case_id]["agent"] == case["agent"]


@pytest.mark.parametrize("case_id", ("pf-06", "pf-07"))
def test_pdf_runs_record_a_checkable_artifact(case_id: str):
    """Volltext-Erfolg heisst: empfangene Bytes, benannt und pruefsummiert."""
    run = _runs()[case_id]
    assert run["verdict"] == "pdf_verified"
    artifact = run["artifact"]
    assert artifact["http_status"] == 200
    assert artifact["content_type"] == "application/pdf"
    assert artifact["magic"].startswith("%PDF-")
    assert artifact["bytes"] > 10_000
    assert artifact["pages"] > 0
    assert re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]), (
        f"{case_id}: 'sha256' muss eine echte Pruefsumme der empfangenen Bytes "
        f"sein — der einzige Wert, an dem sich ein Nachfahrer festhalten kann."
    )
    assert run["url_chain"], f"{case_id}: ohne URL-Kette ist der Lauf nicht nachfahrbar."
    assert run["url_chain"][-1].startswith("https://")


def test_recorded_doi_matches_the_eval_input():
    """Der Beleg muss zu dem Titel gehoeren, den der Eval-Fall anfordert."""
    for case_id in ("pf-06", "pf-07"):
        assert _runs()[case_id]["item"]["doi"] == _cases()[case_id]["input"]["doi"]


def test_no_single_use_identifiers_are_presented_as_evidence():
    """Der Kernfund der zweiten Runde, als Regel festgehalten.

    Block-Referenz, Client-IP und Uhrzeit wirken wie harte Evidenz, sind aber
    pro Request neu und darum unpruefbar — und die IP hat in einem oeffentlichen
    Repo ohnehin nichts verloren. Beleg gehoert an stabile Signale (HTTP-Status,
    Seitentitel, DOM-Marker, Pruefsumme).
    """
    haystacks = {
        "evals.json (Notizen der Faelle)": "\n".join(
            _cases()[case_id]["notes"] for case_id in EVIDENCE_CASES
        ),
        RECORD_PATH.name: json.dumps(
            [run for run in _record()["runs"] if run["eval_case"] != "pf-08"],
            ensure_ascii=False,
        ),
    }
    for where, text in haystacks.items():
        for label, pattern in SINGLE_USE_PATTERNS.items():
            found = pattern.search(text)
            assert not found, (
                f"{where}: {label} '{found.group(0)}' wird als Beleg gefuehrt. "
                f"Solche Werte sind pro Request neu und von niemandem nachpruefbar. "
                f"Beleg gehoert an stabile Signale — siehe "
                f"'volatile_fields_excluded' in {RECORD_PATH.name}."
            )


def test_jstor_run_names_its_volatile_fields_instead_of_using_them():
    """Der JSTOR-Lauf darf die fluechtigen Felder nur als Ausschluss fuehren."""
    excluded = _runs()["pf-08"]["volatile_fields_excluded"]
    assert set(excluded["fields"]) >= {"Block Reference", "IP", "Date and time"}
    assert excluded["reason"].strip()


# ---------------------------------------------------------------------------
# Die behauptete Tatsache selbst, hermetisch gegen echtes aufgezeichnetes DOM
# ---------------------------------------------------------------------------


def test_jstor_fixture_is_a_real_captured_challenge():
    """Die Fixture muss die echte Challenge sein — mit neutralisierten Feldern."""
    html = JSTOR_FIXTURE.read_text(encoding="utf-8")
    for marker in _runs()["pf-08"]["artifact"]["stable_markers"]:
        assert marker in html, (
            f"Fixture enthaelt das aufgezeichnete Stabil-Signal {marker!r} nicht — "
            f"Beleg und Aufzeichnung sind auseinandergelaufen."
        )
    assert "REDACTED-CLIENT-IP" in html, "Client-IP muss in der Fixture neutralisiert sein."
    for label, pattern in SINGLE_USE_PATTERNS.items():
        assert not pattern.search(html), f"Fixture enthaelt noch {label} im Klartext."


def test_repo_captcha_detection_recognises_the_real_jstor_page():
    """Die Kernaussage von pf-08, gegen echtes DOM statt gegen einen Satz.

    ``status: captcha`` ist nur dann der richtige Ausgang, wenn die
    Captcha-Erkennung des Repos die reale JSTOR-Challenge auch wirklich als
    solche erkennt. Faellt diese Assertion, ist entweder die Erkennung kaputt
    oder JSTOR hat die Seite umgebaut — beides muss auffallen.
    """
    navigator = GenericFetcherNavigator(profile={}, pages={})
    signal = navigator.detect_captcha(JSTOR_FIXTURE.read_text(encoding="utf-8"))
    assert signal is not None, (
        "Die reale JSTOR-Challenge wird von detect_captcha() nicht erkannt — "
        "damit waere 'equals:captcha' fuer pf-08 nicht belegt."
    )


def test_jstor_challenge_answers_the_fulltext_endpoint_with_403():
    """Die Challenge muss am Volltext-Endpunkt haengen, nicht irgendwo."""
    run = _runs()["pf-08"]
    assert run["artifact"]["http_status"] == 403
    assert run["url_chain"][-1].endswith(".pdf")
    assert run["why_this_still_satisfies_ac1"].strip()
