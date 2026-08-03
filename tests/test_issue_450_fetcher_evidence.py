"""Beleg-Kopplung fuer die drei freien Archiv-Fetcher (Issue #450, PR #557).

Der Review-Fund, der diese Datei ausgeloest hat, war kein Detailfehler, sondern
eine fehlende Aussage: AC1 verlangt einen Live-Nachweis pro Archiv als PDF, und
PR #557 hat darauf mit dem Satz "Realer Live-Lauf bleibt Operator-Sache"
geantwortet. Belegt war damit nichts. ``evals/free-archive-fetchers/evals.json``
ist in ``docs/evals/STRATEGY.md`` als ``structural`` gefuehrt, was dasselbe
Dokument ausdruecklich als "kein gruen" definiert, und
``tests/test_free_archive_fetchers.py::TestOutputSchema`` fuehrt vom Testautor
selbst geschriebene Beispiel-Dicts gegen ein Schema — eine Aussage ueber den
Testautor, nicht ueber HathiTrust, Internet Archive oder MDZ.

Das Repo hat fuer genau diese Lage schon ein Muster: Issue #449 hat den
AC1-Beleg als nachfahrbares Artefakt abgelegt
(``evals/publisher-fetchers/live-verification.json`` plus opt-in Live-Test plus
hermetischer Kopplungstest). Diese Datei wendet es auf #450 an. Es gilt darum:

* Der Beleg liegt als maschinell pruefbares Artefakt in
  ``evals/free-archive-fetchers/live-verification.json`` (URL-Kette,
  HTTP-Status, Bytes, Pruefsumme, Seitenzahl) — nachfahrbar mit
  ``RUN_LIVE_FREE_ARCHIVE_FETCH=1 uv run pytest tests/test_issue_450_live_fetch.py``.
* Der HathiTrust-Fall haengt an einer **echt aufgezeichneten** Sperrseite
  (``tests/fixtures/free_archive_fetchers/hathitrust_page_blocked.html``), die
  hermetisch gegen die Captcha-Erkennung des Repos gefahren wird — mit dem
  Ergebnis, dass sie eben **kein** Captcha ist und ``status: captcha`` fuer
  diesen Fall die falsche Meldung waere.
* Einmalige Bezeichner (Client-IP, Cloudflare Ray ID, MDZ-Job-Praefix) sind als
  Beleg verboten; ``test_no_single_use_identifiers_are_presented_as_evidence``
  faellt um, wenn sie zurueckkehren.

Keine Assertion hier prueft, ob ein bestimmtes Wort in einer Notiz steht.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.helpers.generic_fetcher_nav import GenericFetcherNavigator
from tests.test_issue_450_live_fetch import IA_NODE_HOST_RE

REPO_ROOT = Path(__file__).parent.parent
EVALS_PATH = REPO_ROOT / "evals" / "free-archive-fetchers" / "evals.json"
RECORD_PATH = REPO_ROOT / "evals" / "free-archive-fetchers" / "live-verification.json"
BLOCK_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "free_archive_fetchers" / "hathitrust_page_blocked.html"
)

EVIDENCE_CASES = ("fa-01", "fa-02", "fa-03")

#: AC1 verlangt reale Belege fuer mindestens zwei der drei Anbieter.
AC1_MIN_PDF_PROOFS = 2

#: Muster fuer Angaben, die sich pro Request aendern. Als Beleg wertlos, weil
#: niemand — auch der Autor nicht — sie ein zweites Mal erzeugen kann.
SINGLE_USE_PATTERNS = {
    "IPv4-Adresse": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "Cloudflare-Ray-ID": re.compile(r"\b[0-9a-f]{16}-[A-Z]{3}\b"),
    "MDZ-Job-Praefix": re.compile(r"/pdf/\d+bsb\d+\.pdf"),
    # Beide real beobachteten Praefixe (Issue #612 Fix-Runde, 2026-08-03) --
    # siehe IA_NODE_HOST_RE in tests/test_issue_450_live_fetch.py.
    "archive.org-CDN-Knoten": re.compile(r"\b(?:ia|dn)\d+\.[a-z]{2}\.archive\.org\b"),
}


def _cases() -> dict:
    return {case["id"]: case for case in json.loads(EVALS_PATH.read_text(encoding="utf-8"))}


def _record() -> dict:
    return json.loads(RECORD_PATH.read_text(encoding="utf-8"))


def _runs() -> dict:
    return {run["eval_case"]: run for run in _record()["runs"]}


# ---------------------------------------------------------------------------
# Jeder Eval-Fall haengt an einem nachfahrbaren Lauf
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", EVIDENCE_CASES)
def test_every_eval_case_has_a_live_verification_run(case_id: str):
    """Ein Eval-Fall ohne hinterlegten Lauf ist eine Behauptung, kein Beleg."""
    runs = _runs()
    assert case_id in runs, (
        f"{case_id}: kein Eintrag in {RECORD_PATH.name}. Genau das war der "
        f"Review-Fund zu PR #557 — AC1 verlangt einen Live-Nachweis, nicht eine "
        f"Zusage, dass jemand ihn spaeter erbringt."
    )
    assert runs[case_id]["agent"] == _cases()[case_id]["agent"], (
        f"{case_id}: der aufgezeichnete Lauf gehoert zu einem anderen Agenten "
        f"als der Eval-Fall — Beleg und Erwartung sind entkoppelt."
    )


@pytest.mark.parametrize("case_id", EVIDENCE_CASES)
def test_recorded_status_is_reachable_from_the_eval_case(case_id: str):
    """Der belegte Ausgang muss einer sein, den der Eval-Fall zulaesst."""
    run = _runs()[case_id]
    case = _cases()[case_id]
    allowed = {case["expected"]["status"], case.get("fallback_acceptable")}
    assert run["expected_status"] in allowed, (
        f"{case_id}: der Lauf belegt '{run['expected_status']}', der Eval-Fall "
        f"laesst aber nur {sorted(a for a in allowed if a)} zu."
    )


# ---------------------------------------------------------------------------
# AC1: mindestens 2 von 3 Anbietern real als PDF belegt
# ---------------------------------------------------------------------------


def test_at_least_two_providers_are_proven_with_a_real_pdf():
    """Der Kern von AC1, als Zaehlung statt als Zusage."""
    verified = [run["eval_case"] for run in _record()["runs"] if run["verdict"] == "pdf_verified"]
    assert len(verified) >= AC1_MIN_PDF_PROOFS, (
        f"AC1 verlangt reale PDF-Belege fuer mindestens {AC1_MIN_PDF_PROOFS} der "
        f"drei Anbieter, belegt sind aber nur {verified}. Ein 'structural'-Eval "
        f"ersetzt diesen Nachweis ausdruecklich nicht "
        f"(docs/evals/STRATEGY.md: 'structural ist ausdruecklich kein gruen')."
    )


def test_ledger_matches_the_recorded_runs():
    """Die Zusammenfassung darf nicht guenstiger sein als die Laeufe."""
    ledger = _record()["ac1_ledger"]
    by_verdict: dict[str, list[str]] = {}
    for run in _record()["runs"]:
        by_verdict.setdefault(run["verdict"], []).append(run["eval_case"])
    for verdict, cases in by_verdict.items():
        assert sorted(ledger.get(verdict, [])) == sorted(cases), (
            f"ac1_ledger['{verdict}'] listet {ledger.get(verdict)}, die Laeufe "
            f"tragen aber {sorted(cases)}."
        )


@pytest.mark.parametrize("case_id", ("fa-02", "fa-03"))
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
    assert run["url_chain"], f"{case_id}: ohne URL-Kette ist der Lauf nicht nachfahrbar."
    assert all(url.startswith("https://") for url in run["url_chain"])


@pytest.mark.parametrize("case_id", ("fa-02", "fa-03"))
def test_every_pdf_run_carries_exactly_one_hard_checksum(case_id: str):
    """Instabile Pruefsumme ist ein Grund zum Normalisieren, nicht zum Weglassen.

    Bei Internet Archive ist die rohe Pruefsumme stabil. Bei MDZ ist sie es
    nicht — dort ist aber gemessen, *warum* (das ``/ID``-Array im Trailer wird
    pro Zusammenstellung neu vergeben), und der normalisierte Wert traegt.
    Was hier nicht durchgeht, ist der dritte Weg: gar keine Pruefsumme.
    """
    artifact = _runs()[case_id]["artifact"]
    hexdigest = re.compile(r"[0-9a-f]{64}")
    if artifact["sha256_stable"]:
        assert hexdigest.fullmatch(artifact["sha256"])
    else:
        assert hexdigest.fullmatch(artifact["sha256_normalized"]), (
            f"{case_id}: 'sha256_stable' ist false, aber es gibt keinen "
            f"normalisierten Ersatzwert — dann haelt sich niemand mehr an "
            f"irgendetwas fest."
        )
        assert artifact["sha256_normalization_rule"].strip(), (
            f"{case_id}: eine normalisierte Pruefsumme ohne angegebene "
            f"Normalisierungsregel kann niemand nachrechnen."
        )


def test_internet_archive_run_proves_access_control_with_a_counter_example():
    """ "Ohne Login geladen" ist nur eine Aussage, wenn Login je etwas sperrt.

    archive.org fuehrt sowohl frei herunterladbare als auch
    Controlled-Digital-Lending-Titel. Ohne Gegenprobe an einem gesperrten Item
    bliebe offen, ob der Erfolg oben eine Eigenschaft dieses Items ist oder
    schlicht die Abwesenheit jeder Zugriffskontrolle.
    """
    counter = _runs()["fa-02"]["access_control_counter_example"]
    assert counter["http_status"] == 401
    assert counter["identifier"] != _runs()["fa-02"]["item"]["identifier"]
    assert counter["signals"]["access-restricted-item"] == "true"


# ---------------------------------------------------------------------------
# Der HathiTrust-Fall: die Sperre ist der Beleg, ihre Kennnummern sind es nicht
# ---------------------------------------------------------------------------


def test_hathitrust_run_is_pinned_to_the_fulltext_endpoint():
    """Die Sperre muss am Download-Endpunkt haengen, nicht irgendwo."""
    run = _runs()["fa-01"]
    assert run["verdict"] == "blocked_verified"
    assert run["artifact"]["http_status"] == 403
    assert "imgsrv/download" in run["url_chain"][-1]
    assert run["why_this_still_satisfies_ac1"].strip()


def test_block_fixture_is_a_real_captured_page():
    """Die Fixture muss die echte Sperrseite sein — mit neutralisierten Feldern."""
    html = BLOCK_FIXTURE.read_text(encoding="utf-8")
    artifact = _runs()["fa-01"]["artifact"]
    assert artifact["page_title"] in html
    for marker in artifact["stable_markers"]:
        assert marker in html, (
            f"Fixture enthaelt das aufgezeichnete Stabil-Signal {marker!r} nicht — "
            f"Beleg und Aufzeichnung sind auseinandergelaufen."
        )
    assert "REDACTED-CLIENT-IP" in html, "Client-IP muss in der Fixture neutralisiert sein."
    assert "REDACTED-CF-RAY-ID" in html, "Ray ID muss in der Fixture neutralisiert sein."
    for label, pattern in SINGLE_USE_PATTERNS.items():
        assert not pattern.search(html), f"Fixture enthaelt noch {label} im Klartext."


def test_block_page_is_not_a_captcha():
    """Die Kernaussage von fa-01, gegen echtes DOM statt gegen einen Satz.

    Die Sperrseite sieht einer Bot-Challenge aehnlich, ist aber keine: sie
    bietet keine loesbare Aufgabe, sondern nennt IP-Reputation als Grund. Wuerde
    die Captcha-Erkennung des Repos hier anschlagen, waere ``status: captcha``
    vertretbar — sie tut es nicht, und darum braucht der Agent eine eigene
    Regel fuer diesen Ausgang.
    """
    navigator = GenericFetcherNavigator(profile={}, pages={})
    signal = navigator.detect_captcha(BLOCK_FIXTURE.read_text(encoding="utf-8"))
    assert signal is None, (
        f"Die Sperrseite wird als Captcha erkannt ({signal!r}). Dann waere die "
        f"Begruendung in 'not_a_captcha' falsch und die Statuszuordnung in "
        f"agents/hathitrust-fetcher.md neu zu bewerten."
    )


def test_hathitrust_metadata_path_stays_open():
    """Warum metadata_only und nicht no_match der ehrliche Ausgang ist."""
    also = _runs()["fa-01"]["also_measured"]["bib_api_stays_open"]
    assert also["http_status"] == 200
    assert _runs()["fa-01"]["expected_status"] == "metadata_only"


# ---------------------------------------------------------------------------
# MDZ: das Pflichtfeld, das die erste Fassung des Guides nicht kannte
# ---------------------------------------------------------------------------


def test_mdz_run_records_the_rights_statement_gate():
    """Der PDF-Bezug haengt an einer Pflicht-Bestaetigung, nicht an einem Link."""
    gate = _runs()["fa-03"]["rights_gate"]
    assert gate["mechanism"].strip()
    assert "xdfz=2" in _runs()["fa-03"]["url_chain"][-1], (
        "Die aufgezeichnete Kette umgeht die Bestaetigung — dann belegt sie "
        "nicht den Weg, den der Agent gehen muss."
    )


# ---------------------------------------------------------------------------
# Die Regel aus Issue #449, hier erneut durchgesetzt
# ---------------------------------------------------------------------------


def test_no_single_use_identifiers_are_presented_as_evidence():
    """Werte, die pro Request neu vergeben werden, sind kein Beleg.

    Client-IP, Cloudflare Ray ID, das MDZ-Job-Praefix im Dateinamen und der
    CDN-Knoten von archive.org wirken wie harte Evidenz, kann aber niemand
    nachpruefen — auch der Autor nicht. Dass sie rotieren, wird deshalb nicht
    aufgeschrieben, sondern in tests/test_issue_450_live_fetch.py gefahren.
    """
    text = json.dumps(_record(), ensure_ascii=False)
    for label, pattern in SINGLE_USE_PATTERNS.items():
        found = pattern.search(text)
        assert not found, (
            f"{RECORD_PATH.name}: {label} '{found.group(0)}' wird als Beleg "
            f"gefuehrt. Solche Werte sind pro Request neu und von niemandem "
            f"nachpruefbar. Beleg gehoert an stabile Signale — siehe "
            f"'volatile_fields_excluded' in derselben Datei."
        )


@pytest.mark.parametrize("case_id", EVIDENCE_CASES)
def test_every_run_names_its_volatile_fields_instead_of_using_them(case_id: str):
    excluded = _runs()[case_id]["volatile_fields_excluded"]
    assert excluded["fields"], f"{case_id}: kein einziges fluechtiges Feld benannt."
    assert excluded["reason"].strip()
    assert excluded["evidence_is_instead"].strip()


# ---------------------------------------------------------------------------
# Issue #612 Fix-Runde: archive.org vergibt Speicherknoten unter mehr als
# einem Praefix -- die urspruengliche Annahme (nur "dn") war zu eng.
# ---------------------------------------------------------------------------


#: Echte Umleitungsziele der stabilen fa-02-Download-URL, beobachtet am
#: 2026-08-03 in zwei unabhaengigen Netzen: GitHub-Actions-Runner (Workflow-Lauf
#: https://github.com/ahlerjam/academic-research/actions/runs/30851138735) und
#: ein zweites, unabhaengiges Netz derselben Session. Zwei verschiedene
#: Praefixe ("ia", "dn") fuer denselben stabilen Einstiegspunkt -- genau das
#: "verschiedene Regionen"-Verhalten, das 'volatile_fields_excluded' in
#: live-verification.json schon 2026-07-31 beschrieb, nur eben nicht als
#: konkretes Hostnamen-Muster.
OBSERVED_IA_NODE_HOSTS = ("ia800108.us.archive.org", "dn720200.ca.archive.org")


@pytest.mark.parametrize("host", OBSERVED_IA_NODE_HOSTS)
def test_ia_node_host_pattern_accepts_both_observed_node_prefixes(host: str):
    """Regression Issue #612: die urspruengliche Annahme war nur ``dn``-Knoten.

    ``tests/test_issue_450_live_fetch.py::test_internet_archive_redirects_to_an_assigned_node``
    schlug am 2026-08-03 fehl, weil archive.org mit 'ia800108.us.archive.org'
    antwortete -- einem real beobachteten, aber vom Muster nicht abgedeckten
    Knotennamen. Der eigentliche archive.org-Fetcher (agents/internetarchive-fetcher.md)
    war davon nicht betroffen: derselbe Lauf lieferte das PDF byteweise korrekt
    (test_internet_archive_still_serves_the_recorded_pdf PASSED). Das Muster
    muss beide real beobachteten Praefixe abdecken, sonst ist der Live-Test
    flaky ueber etwas, das kein Fetcher-Fehler ist.
    """
    assert IA_NODE_HOST_RE.match(host), (
        f"{host!r} wurde real als Umleitungsziel beobachtet, matcht aber nicht "
        f"IA_NODE_HOST_RE. Das Muster ist zu eng fuer die tatsaechliche "
        f"Knoten-Namensvielfalt von archive.org."
    )
