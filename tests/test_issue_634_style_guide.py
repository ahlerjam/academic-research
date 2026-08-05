"""Akzeptanz-Guards fuer Issue #634 — Schreibregeln und Glossar-Pflicht.

Jeder Test bildet ein Akzeptanzkriterium des Issues ab:

AC1  Das Regeldokument existiert, ist selbst nach seinen eigenen Regeln
     geschrieben (durchgehend "du", keine Werbesprache/leere Steigerungen
     ausserhalb der zitierten Vorher-Beispiele, kein Satz ausserhalb der
     Beispiele ueber dem Satzlaenge-Budget) und passt auf zwei
     Bildschirmseiten (Naeherung: Zeilenbudget, analog zu
     tests/test_issue_402_readme_relaunch.py::README_LINE_BUDGET).
AC2  Die Zielgruppe ist benannt, samt dessen, was sie nicht mitbringt.
AC3  Jede der 5 Regeln hat ein Vorher/Nachher-Beispielpaar aus echtem
     Bestand — beide Zitate werden stichprobenhaft gegen die genannte
     Quelldatei verifiziert, nicht nur gegen das Regeldokument selbst.
AC6  docs/README.md verlinkt das Regeldokument im Abschnitt "Ich will
     beitragen".

Die Pfade kommen aus tests/helpers/docs.py (Issue #402/#452-Muster).
"""

import re
from pathlib import Path

import pytest

from tests.helpers import docs as D

REPO_ROOT = D.REPO_ROOT

#: Naeherung fuer "zwei Bildschirmseiten" (Issue-Wortlaut) — analog zum
#: README-Zeilenbudget aus #402, nur kleiner: das Regeldokument ist eine
#: einzelne fokussierte Seite, keine Produkt-Schaufenster-README.
STYLE_GUIDE_LINE_BUDGET = 130

#: Satzlaengen-Budget (Woerter), das Regel 2 selbst durchsetzt (Selbstanwendung AC1).
MAX_SENTENCE_WORDS = 22

#: Verbotene leere Steigerungen/Werbevokabeln (Regel 5), als Wortstaemme.
BANNED_MARKETING_STEMS = (
    "perfekt",
    "revolution",
    "einzigartig",
    "bahnbrechend",
    "mühelos",
    "muehelos",
    "nahtlos",
    "unschlagbar",
    "weltklasse",
    "innovat",
)

#: Je Regel ein (Vorher, Nachher)-Paar: (Zitat, Quelldatei relativ zum Repo-Root).
#: Die Zitate sind absichtlich Python-Konstanten statt aus der Markdown-Datei
#: geparst — sie sind die Ground Truth, gegen die sowohl das Regeldokument als
#: auch die genannte Quelldatei geprueft werden (AC3: "nicht erfunden").
RULE_EXAMPLES: dict[str, dict[str, tuple[str, str]]] = {
    "Ansprache": {
        "vorher": (
            "docs/reference/vault.md",
            "Der `verbatim-guard`-Hook prüft jeden `Write`-Aufruf auf "
            "`kapitel/**/*.md` (Unterordner eingeschlossen) und `*.tex`: "
            "enthaltene Zitate werden gegen den Vault geprüft.",
        ),
        "nachher": (
            "docs/guide/getting-started.md",
            "Am Ende jedes Schritts steht, woran du erkennst, dass er geklappt hat.",
        ),
    },
    "Satzlänge": {
        "vorher": (
            "CHANGELOG.md",
            "`run_search()` in `scripts/search.py` wartete bisher unbegrenzt über "
            "`concurrent.futures.as_completed()`, bis alle 7 Modul-Futures fertig "
            "waren — insbesondere der EconStor-OAI-PMH-Fallback aus #236 (bis zu "
            "`OAI_MAX_PAGES=5` × `TIMEOUT=30s` ≈ 150s Worst-Case, laut #456 "
            "aktuell der Live-Normalfall, da `econstor.eu`'s REST-Endpunkt "
            "durchgehend HTTP 405 liefert) konnte den gesamten Lauf um Minuten "
            "verzögern, ohne dass die übrigen, längst fertigen Treffer "
            "ausgeliefert wurden.",
        ),
        "nachher": (
            "docs/guide/getting-started.md",
            "Das Setup ist idempotent: Ein zweiter Aufruf zerstört nichts.",
        ),
    },
    "Fachbegriffe": {
        "vorher": (
            "docs/evals/recall-at-k-model-ab-375.md",
            "FTS5 + vec0-KNN via RRF fusioniert",
        ),
        "nachher": (
            "docs/reference/vault.md",
            "führt die KNN-Treffer per Reciprocal-Rank-Fusion mit dem BM25-Ranking zusammen.",
        ),
    },
    "Zahlen": {
        "vorher": (
            "CHANGELOG.md",
            '„Universal Book Fetcher (8-Tier-Pipeline)"',
        ),
        "nachher": (
            "CHANGELOG.md",
            '„10 Fetcher-Subagenten mit Fallback-Kette"',
        ),
    },
    "Werbesprache": {
        "vorher": (
            "docs/evals/recall-at-k-model-ab-375.md",
            "perfekten Recall@10 = 1.0",
        ),
        "nachher": (
            "docs/evals/recall-at-k-model-ab-375.md",
            "Das ist ein Deckeneffekt (ceiling effect), kein "
            "Qualitaetsunterschied zwischen den Modellen",
        ),
    },
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalize_ws(text: str) -> str:
    """Kollabiert Whitespace/Zeilenumbrueche und entfernt Markdown-Bold (`**`).

    Beides ist Markdown-Praesentation, kein inhaltlicher Unterschied fuer den
    Zitat-Vergleich: ein Zeilenumbruch im Original oder eine Bold-Auszeichnung
    um denselben Wortlaut aendert das Zitat nicht.
    """
    without_bold = text.replace("**", "")
    return re.sub(r"\s+", " ", without_bold).strip()


def _style_guide_text() -> str:
    return _read(D.STYLE_GUIDE_DOC)


def _non_exhibit_lines(text: str) -> str:
    """Prosa des Regeldokuments ohne die zitierten Vorher/Nachher-Beispiele.

    Die Beispiele duerfen (muessen teils) gegen die eigenen Regeln verstossen
    — genau das macht sie zu Belegen. Die Selbstanwendungs-Guards (AC1)
    pruefen deshalb nur die eigene Prosa des Dokuments, nicht die Exhibits.

    Exhibit-Bloecke sind mehrzeilig: von '**Vorher**'/'**Nachher**' bis zur
    naechsten Leerzeile (Absatz-Grenze). Diese absatzweise entfernen statt
    zeilenweise, damit Folgezeilen mit 'nahtlos' oder 'Sie' nicht fuer die
    Selbstanwendungs-Tests zaehlen.
    """
    # Absaetze spletten (doppelte Zeilenumbrueche in der Markdown)
    paragraphs = re.split(r"\n\n+", text)
    # Exhibit-Bloecke herausfiltern: Absaetze, die mit **Vorher** oder **Nachher** beginnen
    filtered = [p for p in paragraphs if not re.match(r"^\s*\*\*(Vorher|Nachher)\*\*", p)]
    # Wieder zusammenfuegen mit Leerzeilen
    return "\n\n".join(filtered)


# ---------------------------------------------------------------------------
# AC1 — Regeldokument existiert, folgt eigenen Regeln, <= 2 Bildschirmseiten
# ---------------------------------------------------------------------------


def test_style_guide_exists() -> None:
    assert D.STYLE_GUIDE_DOC.exists(), f"Regeldokument fehlt: {D.STYLE_GUIDE_DOC}"


def test_style_guide_within_line_budget() -> None:
    lines = _style_guide_text().splitlines()
    assert len(lines) <= STYLE_GUIDE_LINE_BUDGET, (
        f"style-guide.md hat {len(lines)} Zeilen, Budget sind "
        f"{STYLE_GUIDE_LINE_BUDGET} (Naeherung fuer zwei Bildschirmseiten)."
    )


def test_style_guide_never_addresses_reader_formally() -> None:
    """Selbstanwendung Regel 1: kein 'Sie' als foermliche Anrede."""
    prose = _non_exhibit_lines(_style_guide_text())
    assert not re.search(r"\bSie\b", prose), (
        "style-guide.md verwendet 'Sie' statt durchgehend 'du' (Regel 1) "
        "ausserhalb der zitierten Beispiele."
    )


def test_style_guide_prose_has_no_marketing_words() -> None:
    """Selbstanwendung Regel 5: keine Werbevokabeln ausserhalb der Exhibits."""
    prose = _non_exhibit_lines(_style_guide_text()).lower()
    hits = [stem for stem in BANNED_MARKETING_STEMS if stem in prose]
    assert not hits, f"style-guide.md verwendet Werbevokabeln (Regel 5): {hits}"


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def test_style_guide_prose_sentences_stay_short() -> None:
    """Selbstanwendung Regel 2: kein Satz ausserhalb der Exhibits ist zu lang."""
    prose_text = _non_exhibit_lines(_style_guide_text())
    # Absaetze extrahieren (Leerzeilen als Grenze)
    paragraphs = re.split(r"\n\n+", prose_text)
    too_long = []
    for para in paragraphs:
        # Zeilen innerhalb des Absatzes ignorieren, die Markdown-Kopfzeilen oder Referenzen sind
        lines = [ln for ln in para.splitlines() if ln.strip() and not ln.startswith(("#", "["))]
        # Absatz wieder zusammenfuegen (Zeilenumbrueche im Fliesstext sind keine Satzgrenzen)
        paragraph_text = " ".join(lines)
        # Saetze im zusammengefassten Absatz extrahieren
        for sentence in _sentences(paragraph_text):
            words = sentence.split()
            if len(words) > MAX_SENTENCE_WORDS:
                too_long.append((len(words), sentence))
    assert not too_long, f"Zu lange Saetze (Regel 2, Budget {MAX_SENTENCE_WORDS}): {too_long}"


# ---------------------------------------------------------------------------
# AC2 — Zielgruppe benannt, inkl. was sie NICHT mitbringt
# ---------------------------------------------------------------------------


def test_style_guide_names_target_audience() -> None:
    text = _style_guide_text()
    assert re.search(r"^## Zielgruppe\s*$", text, re.M), (
        "style-guide.md hat keinen Abschnitt '## Zielgruppe'."
    )


def test_style_guide_names_what_audience_lacks() -> None:
    """AC2 verlangt explizit, was die Zielgruppe NICHT mitbringt."""
    text = _style_guide_text()
    m = re.search(r"^## Zielgruppe\s*$(.*?)(^## |\Z)", text, re.M | re.S)
    assert m, "Abschnitt 'Zielgruppe' nicht auffindbar."
    section = m.group(1)
    assert re.search(r"nicht mitbring", section, re.I), (
        "Abschnitt 'Zielgruppe' benennt nicht explizit, was die Zielgruppe nicht mitbringt (AC2)."
    )


# ---------------------------------------------------------------------------
# AC3 — Vorher/Nachher je Regel, echter Bestand
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rule", sorted(RULE_EXAMPLES), ids=lambda r: r)
def test_rule_has_vorher_and_nachher_in_style_guide(rule: str) -> None:
    text = _normalize_ws(_style_guide_text())
    pair = RULE_EXAMPLES[rule]
    for label, (_source, quote) in pair.items():
        assert _normalize_ws(quote) in text, (
            f"Regel '{rule}': {label}-Zitat steht nicht (wörtlich) in style-guide.md: {quote!r}"
        )


@pytest.mark.parametrize(
    "rule,label",
    [(rule, label) for rule in RULE_EXAMPLES for label in ("vorher", "nachher")],
    ids=lambda v: str(v),
)
def test_example_quote_is_real_not_invented(rule: str, label: str) -> None:
    """AC3: 'nicht erfunden' — jedes Zitat muss wörtlich in der Quelldatei stehen."""
    source_rel, quote = RULE_EXAMPLES[rule][label]
    source_path = REPO_ROOT / source_rel
    assert source_path.exists(), f"Quelldatei fehlt: {source_rel}"
    source_text = _normalize_ws(_read(source_path))
    assert _normalize_ws(quote) in source_text, (
        f"Regel '{rule}' ({label}): Zitat steht nicht wörtlich in {source_rel}: {quote!r}"
    )


# ---------------------------------------------------------------------------
# AC6 — docs/README.md verlinkt das Regeldokument im Beitragenden-Abschnitt
# ---------------------------------------------------------------------------


def _index_section(heading: str) -> str:
    text = _read(D.INDEX)
    m = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(^## |\Z)", text, re.M | re.S)
    assert m, f"docs/README.md hat keinen Abschnitt '## {heading}'."
    return m.group(1)


def test_index_links_style_guide_under_contributing_section() -> None:
    section = _index_section("Ich will beitragen")
    assert "style-guide.md" in section, (
        "Abschnitt 'Ich will beitragen' verlinkt style-guide.md nicht (AC6)."
    )


def test_style_guide_not_linked_from_other_sections() -> None:
    """Umkehrprobe: der Link steht nur im Beitragenden-Abschnitt."""
    text = _read(D.INDEX)
    contributing = _index_section("Ich will beitragen")
    other = text.replace(contributing, "")
    assert "style-guide.md" not in other, (
        "style-guide.md ist ausserhalb von 'Ich will beitragen' verlinkt — "
        "AC6 verlangt explizit diesen Abschnitt."
    )
