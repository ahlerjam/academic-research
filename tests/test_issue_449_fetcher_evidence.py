"""
Regressionstest fuer die Fix-Runde zu PR #500 (Issue #449).

Review-Fund: Die Eval-Cases pf-06/07/08 (cambridge-core/oxford-academic/jstor)
pruefen nur, dass ein `status`-Feld existiert -- eine triviale Aussage, die auch
von `no_match`/`captcha` erfuellt wird. Zudem verwies pf-07 auf eine DOI, die
tatsaechlich zu einem regulaeren, bezahlpflichtigen Oxford-Academic-Buch fuehrt
(keine Commit-to-Open-OA-Publikation) -- das Gegenteil dessen, was die Notiz
behauptete.

Nach echter, manueller Verifikation via browser-use (29.07.2026, isolierte
Session, keine Zugangsdaten) haelt dieser Test die konkreten, belegten
Erwartungswerte fest:
- cambridge-core (pf-06): OA-Badge + "Full book PDF" liefert ein echtes,
  vollstaendiges 228-Seiten-PDF ohne Login -> erwartet: success.
- oxford-academic (pf-07): DOI korrigiert auf einen verifizierten realen
  Commit-to-Open-Titel (academic.oup.com/commit-to-open/pages/collections);
  direkter PDF-Download (225 Seiten) ohne Login -> erwartet: success.
- jstor (pf-08): direkter Zugriff auf den PDF-Endpunkt loeste beim allerersten
  Request JSTORs reCAPTCHA "Access Check" aus (Block-Referenz
  #54030350-8b3b-11f1-9e43-eab9a1861140, IP 147.161.231.116,
  29.07.2026 10:50 UTC) -- das dokumentierte, jetzt belegte AC1-Alternativergebnis
  -> erwartet: captcha (nicht success).
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
EVALS_PATH = REPO_ROOT / "evals" / "publisher-fetchers" / "evals.json"

# DOI aus der urspruenglichen PR-#500-Fassung von pf-07. Fuehrt tatsaechlich zu
# "Philosophies of Qualitative Research" (Leavy, Hrsg.) -- ein regulaeres,
# bezahlpflichtiges OSO-Buch ohne jedes OA-/Free-/Unlocked-Badge, keine
# Commit-to-Open-Publikation. Darf nach der Korrektur nicht wieder auftauchen.
WRONG_OXFORD_DOI = "10.1093/oso/9780190247249.001.0001"

EVIDENCE_CASES = ("pf-06", "pf-07", "pf-08")


def _load_cases() -> dict:
    data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
    return {case["id"]: case for case in data["cases"]}


def test_new_publisher_cases_use_non_trivial_status_check():
    """pf-06/07/08 duerfen 'status' nicht nur auf Existenz pruefen.

    'exists' wird auch von no_match/captcha erfuellt und ist damit keine
    Aussage ueber echte Volltext-Aufloesung. Nach echter Verifikation muss
    jeder Case einen konkreten Zielwert (equals:<status>) tragen.
    """
    cases = _load_cases()
    for case_id in EVIDENCE_CASES:
        check = cases[case_id]["expected"]["check"]
        assert check.startswith("equals:"), (
            f"{case_id}: 'check' muss ein konkretes 'equals:<status>' sein, "
            f"nicht die triviale Existenzpruefung ('{check}'), die von jedem "
            f"Status inkl. no_match/captcha erfuellt wird."
        )


def test_cambridge_core_case_expects_verified_success():
    """cambridge-core: real verifiziert (echtes 228-Seiten-PDF, kein Login)."""
    cases = _load_cases()
    assert cases["pf-06"]["expected"]["check"] == "equals:success"


def test_oxford_academic_case_does_not_use_wrong_doi():
    """Regression: die urspruengliche DOI referenziert kein OA-Buch."""
    cases = _load_cases()
    assert cases["pf-07"]["input"]["doi"] != WRONG_OXFORD_DOI


def test_oxford_academic_case_expects_verified_success():
    """oxford-academic: real verifiziert nach DOI-Korrektur (225-Seiten-PDF)."""
    cases = _load_cases()
    assert cases["pf-07"]["expected"]["check"] == "equals:success"


def test_jstor_case_documents_verified_captcha_outcome():
    """jstor: reales, reproduziertes CAPTCHA statt nur behauptetes Risiko.

    AC1 erlaubt fuer JSTOR ausdruecklich `status: captcha` als dokumentierte
    Alternative zu `success` -- vorausgesetzt, sie ist belegt und nicht nur
    behauptet. Das ist jetzt der Fall (siehe Notiz im Case).
    """
    cases = _load_cases()
    assert cases["pf-08"]["expected"]["check"] == "equals:captcha"


def test_evidence_notes_reference_real_verification():
    """Die Notizen muessen den echten Verifikationsnachweis referenzieren,
    nicht nur eine vage Status-Enum-Erwartung -- sonst kann die naechste
    Aenderung stillschweigend zur unbelegten Behauptung zurueckfallen."""
    cases = _load_cases()
    for case_id in EVIDENCE_CASES:
        notes = cases[case_id]["notes"].lower()
        assert "verifiziert" in notes, (
            f"{case_id}: Notiz muss den echten Verifikationsnachweis "
            f"referenzieren ('verifiziert'), nicht nur recherchiert/behauptet."
        )
