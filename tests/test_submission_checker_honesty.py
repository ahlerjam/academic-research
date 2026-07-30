"""Tests fuer die Ehrlichkeitsgrenze der submission-checker-Abgabepruefung (Issue #472, AC1).

Bisher behauptete `submission-checker` Pruefungen (Typografie, Zeilenabstand,
Raender, exakte Seitenzahl), die am reinen Markdown-Material (`kapitel/*.md`,
`writing_state.md`) gar nicht belegbar sind -- Layout entsteht erst beim
Export (`word-export`/`latex-export`). Diese Tests stellen strukturell sicher,
dass SKILL.md die Trennung "am Material pruefbar" vs. "nicht pruefbar ohne
Export/explizite User-Angabe" explizit enthaelt und das Output-Template eine
Pflicht-Sektion "Nicht geprueft" vorschreibt.

Risiko aus dem Plan zu #472: der bestehende Eval `sc-01` (User nennt
Formatwerte explizit im Prompt -> PASS) muss gruen bleiben -- die
Ehrlichkeitsgrenze gilt nur, wenn der Skill die Werte selbst aus dem Material
ableiten muesste, nicht wenn der User sie direkt liefert. Das wird hier nicht
erneut getestet (das deckt der Eval selbst), aber die SKILL.md-Regel dafuer
wird strukturell verifiziert (test_user_supplied_values_still_checkable).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_SKILL_MD = _ROOT / "skills" / "submission-checker" / "SKILL.md"
_SIZES_BASELINE = _ROOT / "tests" / "baselines" / "skill_sizes.json"
_TOKENS_BASELINE = _ROOT / "tests" / "baselines" / "tokens.json"


def _text() -> str:
    return _SKILL_MD.read_text()


_FEWSHOT_HEADING = "## Few-Shot-Beispiele"

# Label-Zeilen der Few-Shot-Beispiele, z. B. "**Gut** (Grund: ...)".
_LABEL_RE = re.compile(r"^\*\*(Schlecht|Gut)\*\*(?P<reason>[^\n]*)$", re.MULTILINE)

# Layout-Eigenschaften, die am reinen Markdown-Material nicht ablesbar sind.
_LAYOUT_TERMS = ("Zeilenabstand", "Seitenrand", "Seitenränder", "Ränder", "Schriftart", "Blocksatz")

# Belege dafuer, dass ein konkreter Layout-Wert vom User stammt statt erfunden zu sein.
_USER_SOURCE_MARKERS = ("von dir", "genannt", "User", "angegeben")

# Konkrete Seiten-Fundstelle ("Seiten 12-18", "S. 12"): am Markdown nie belegbar,
# weil Markdown kein Seitenlayout hat.
_PAGE_LOCATOR_RE = re.compile(r"\bSeiten?\s+\d|\bS\.\s*\d")


def _fewshot_section() -> str:
    text = _text()
    idx = text.find(_FEWSHOT_HEADING)
    assert idx != -1, f"SKILL.md enthaelt keine Sektion {_FEWSHOT_HEADING!r}"
    return text[idx:]


def _labelled_blocks() -> list[tuple[str, str]]:
    """Zerlegt die Few-Shot-Sektion in ``(Label, Block-Text)``-Paare."""
    section = _fewshot_section()
    matches = list(_LABEL_RE.finditer(section))
    assert matches, "Few-Shot-Sektion enthaelt keine **Schlecht**/**Gut**-Beispiele"
    blocks: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(section)
        blocks.append((match.group(1), section[match.start() : end]))
    return blocks


def _good_blocks() -> list[str]:
    return [body for label, body in _labelled_blocks() if label == "Gut"]


def _bad_blocks() -> list[str]:
    return [body for label, body in _labelled_blocks() if label == "Schlecht"]


class TestPruefbarkeitsgrenze:
    def test_seitenzahl_marked_not_checkable_on_material(self):
        text = _text()
        assert "NICHT am Material prüfbar" in text or "nicht am Material prüfbar" in text.lower(), (
            "SKILL.md kennzeichnet die Seitenzahl-Dimension nicht explizit als "
            "am Material nicht pruefbar"
        )
        # Sowohl Seitenzahl- als auch Formatierungs-Dimension muessen die Markierung tragen.
        assert text.count("NICHT am Material prüfbar") >= 2, (
            "Erwartet mind. 2 Dimensionen (Seitenzahl, Formatierung), die explizit als "
            "nicht am Material pruefbar markiert sind"
        )

    def test_layout_entsteht_erst_beim_export_explained(self):
        text = _text()
        assert "word-export" in text and "latex-export" in text, (
            "SKILL.md erklaert nicht, dass Layout erst bei word-export/latex-export entsteht"
        )

    def test_user_supplied_values_still_checkable(self):
        """Nennt der User die Werte explizit, bleibt die Pruefung moeglich (sc-01 muss PASS-faehig bleiben)."""
        text = _text()
        assert "der User" in text and "explizit" in text, (
            "SKILL.md beschreibt keinen Pfad fuer explizit vom User genannte Werte"
        )

    def test_unterschrift_not_verifiable_even_after_export(self):
        text = _text()
        assert "handschriftlich" in text.lower() or "tatsächlich unterzeichnet" in text, (
            "SKILL.md klaert nicht, dass eine tatsaechliche Unterschrift nie pruefbar ist"
        )


class TestNichtGeprueftPflichtsektion:
    def test_output_format_has_nicht_geprueft_section(self):
        text = _text()
        assert "### Nicht geprüft" in text, (
            "Output-Format-Template enthaelt keine '### Nicht geprüft'-Sektion"
        )

    def test_nicht_geprueft_is_mandatory_not_optional(self):
        text = _text()
        assert "Pflicht-Sektion" in text or "ist Pflicht" in text, (
            "SKILL.md macht die 'Nicht geprueft'-Sektion nicht ausdruecklich verpflichtend"
        )

    def test_no_silent_pass_rule_present(self):
        """Regel gegen stillschweigendes PASS bei ungeprueften Dimensionen."""
        text = _text()
        assert "erfundenes PASS" in text or "stillschweigend" in text, (
            "SKILL.md verbietet ein stillschweigendes/erfundenes PASS nicht explizit"
        )

    def test_ergebnis_uebersicht_table_allows_nicht_geprueft_status(self):
        text = _text()
        assert "NICHT GEPRÜFT" in text, (
            "Ergebnis-Uebersicht-Tabelle im Output-Format erlaubt keinen "
            "'NICHT GEPRÜFT'-Status neben PASS/PARTIAL/FAIL"
        )


class TestFewShotBeispieleFolgenDerEhrlichkeitsregel:
    """Few-Shot-Beispiele sind die staerkste Verhaltensvorgabe im Skill.

    Review-Fund zu #472: Die Prosa-Regeln trennten "am Material pruefbar" von
    "nicht pruefbar" korrekt, das Few-Shot-Beispiel demonstrierte aber weiterhin
    als *Gut* genau den verbotenen Fall -- einen erfundenen Layout-Befund mit
    Seiten-Fundstelle ("Zeilenabstand 1.0 statt geforderten 1.5 (Seiten 12-18)").
    Ein Beispiel, das der Regel widerspricht, hebt die Regel praktisch auf.
    """

    def test_positive_example_names_no_layout_value_without_basis(self):
        """Ein *Gut*-Beispiel darf Layout nur als NICHT GEPRÜFT oder mit User-Beleg nennen."""
        offenders = []
        for body in _good_blocks():
            if not any(term in body for term in _LAYOUT_TERMS):
                continue
            declares_unchecked = "NICHT GEPRÜFT" in body or "Nicht geprüft" in body
            cites_user = any(marker in body for marker in _USER_SOURCE_MARKERS)
            if not (declares_unchecked or cites_user):
                offenders.append(body.strip())
        assert not offenders, (
            "Few-Shot-*Gut*-Beispiel nennt einen Layout-Wert, ohne ihn als "
            "'NICHT GEPRÜFT' auszuweisen oder den User als Quelle zu benennen "
            "-- genau der Befund, den die neue Ehrlichkeitsregel verbietet:\n"
            + "\n---\n".join(offenders)
        )

    def test_positive_example_has_no_invented_page_locator(self):
        """Seiten-Fundstellen entstehen erst im Layout und gehoeren in kein *Gut*-Beispiel."""
        offenders = [body.strip() for body in _good_blocks() if _PAGE_LOCATOR_RE.search(body)]
        assert not offenders, (
            "Few-Shot-*Gut*-Beispiel enthaelt eine Seiten-Fundstelle, die am "
            "Markdown-Material nicht belegbar ist:\n" + "\n---\n".join(offenders)
        )

    def test_positive_example_demonstrates_nicht_geprueft_answer(self):
        """Der ehrliche Normalfall (kein Export, keine User-Werte) muss vorgefuehrt werden."""
        assert any("NICHT GEPRÜFT" in body or "Nicht geprüft" in body for body in _good_blocks()), (
            "Kein *Gut*-Beispiel zeigt die ehrliche 'Nicht geprüft'-Antwort -- der "
            "Skill schreibt sie als Pflicht-Sektion vor, demonstriert sie aber nie"
        )

    def test_invented_layout_finding_is_demonstrated_as_negative_example(self):
        """Der verbotene Fall muss als *Schlecht* gezeigt werden, nicht nur weggelassen."""
        assert any(
            any(term in body for term in _LAYOUT_TERMS) and _PAGE_LOCATOR_RE.search(body)
            for body in _bad_blocks()
        ), (
            "Kein *Schlecht*-Beispiel fuehrt den erfundenen Layout-Befund mit "
            "Seiten-Fundstelle vor -- der haeufigste Fehlerfall bleibt unbenannt"
        )

    def test_user_supplied_values_still_yield_a_real_score(self):
        """Eval sc-01-Schutz: mit User-Werten bleibt ein echter PASS/PARTIAL/FAIL richtig."""
        scored_with_user_basis = [
            body
            for body in _good_blocks()
            if any(marker in body for marker in _USER_SOURCE_MARKERS)
            and re.search(r"\b(PASS|PARTIAL|FAIL)\b", body)
        ]
        assert scored_with_user_basis, (
            "Kein *Gut*-Beispiel zeigt, dass bei explizit vom User genannten Werten "
            "weiterhin ein dimensionaler Score vergeben wird -- ohne dieses Beispiel "
            "kippt der Skill ins pauschale 'Nicht geprüft' und Eval sc-01 bricht"
        )


class TestSubmissionCheckerBaselineRaised:
    """Die Ehrlichkeits-Erweiterung wächst den Skill; die Baseline muss ehrlich mitziehen
    (etabliertes Muster, siehe tests/test_issue_395_baseline_honesty.py)."""

    def test_skill_sizes_baseline_still_present_and_positive(self):
        sizes = json.loads(_SIZES_BASELINE.read_text())
        assert "submission-checker" in sizes
        assert sizes["submission-checker"] > 0

    def test_token_reduction_margin_holds(self):
        sizes = json.loads(_SIZES_BASELINE.read_text())
        current_chars = len(_text())
        delta = sizes["submission-checker"] - current_chars
        assert delta >= 1400, (
            f"submission-checker: Reduktionsmarge nur {delta} Zeichen "
            f"(erwartet >= 1400) -- Baseline muss mit dem Ehrlichkeits-Zuwachs mitziehen"
        )
