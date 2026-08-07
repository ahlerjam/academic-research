"""Tests für narrative APA-Belege, Sekundärbelege, Kaskaden-Reweighting und
ungeprüfte Belegformen (Issue #740).

Eigene Fixtures nach dem Muster von test_issue_601_cascade_unavailable_rate.py
— kein Shared-Import zwischen den ``test_issue_*``-Dateien in diesem Repo.

Akzeptanzkriterien (Issue #740):
  AC1  Alle sieben narrativen Formen werden erkannt und gegen den Vault geprüft.
  AC2  Die parenthetischen Formen verhalten sich unverändert (Regression).
  AC3  Kein Falschtreffer bei Orts-/Monatsnamen — die bestehenden
       Ausschlusslisten (NON_AUTHOR_TOKENS) greifen auch im neuen Muster.
  AC4  Sekundärbeleg: beide Werke erfasst, das vorliegende als solches markiert.
  AC5  Familienname+Jahr allein führt in der Kaskade nicht mehr zu ``confirmed``.
  AC6  Ungeprüfte Formen (LaTeX-/Markdown-Fußnote, numerischer Verweis) werden
       erkannt und gemeldet — nicht blockierend.
  AC7  Höchstens ein Hinweis je Write, abstellbar über Env-Schalter.
  AC8  docs/guide/limits.md benennt geprüfte und ungeprüfte Belegformen.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "verbatim-guard.mjs"
LIMITS_DOC = REPO_ROOT / "docs" / "guide" / "limits.md"

_GUARD_LOG_DIR = Path(tempfile.mkdtemp(prefix="vault-guard-test-logs-740-"))


def run_hook(payload: dict, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    for key in [k for k in env if k.startswith("ACADEMIC_CITATION_")]:
        del env[key]
    env["VAULT_DB_PATH"] = str(REPO_ROOT / "nonexistent_vault_for_tests_740.db")
    env["VAULT_GUARD_ENV_SWITCH_LOG"] = str(_GUARD_LOG_DIR / "env-switch.log")
    env["VAULT_GUARD_BYPASS_LOG"] = str(_GUARD_LOG_DIR / "bypass.log")
    env["ACADEMIC_CITATION_CASCADE"] = "off"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["node", str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def write_payload(content: str, file_path: str = "kapitel/kap1.md") -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": file_path, "content": content}}


def updated_content(result: subprocess.CompletedProcess) -> str:
    assert result.stdout.strip(), f"Kein stdout-JSON. stderr: {result.stderr}"
    data = json.loads(result.stdout)
    return data["hookSpecificOutput"]["updatedInput"]["content"]


def run_node(source: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", "--input-type=module", "-e", source],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=60,
    )


def _make_vault(tmp_path, name: str) -> str:
    from academic_vault.db import VaultDB

    db_path = str(tmp_path / name)
    db = VaultDB(db_path)
    db.init_schema()
    return db_path


@pytest.fixture
def empty_vault(tmp_path):
    return _make_vault(tmp_path, "empty_740.db")


@pytest.fixture
def vault_with_mueller(tmp_path):
    from academic_vault.server import add_paper

    db_path = _make_vault(tmp_path, "mueller_740.db")
    add_paper(
        db_path=db_path,
        paper_id="mueller-2021",
        csl_json=json.dumps(
            {
                "title": "Digitale Transformation",
                "type": "article-journal",
                "author": [{"family": "Müller", "given": "Anna"}],
                "issued": {"date-parts": [[2021]]},
            }
        ),
        page_first=40,
        page_last=60,
    )
    return db_path


# ---------------------------------------------------------------------------
# AC1 — sieben narrative Formen
# ---------------------------------------------------------------------------

NARRATIVE_FORMS = [
    "Müller (2021) belegt die These.",
    "Müller (2021, S. 45) belegt die These.",
    "Müller und Schmidt (2019) belegen die These.",
    "Müller et al. (2021) belegen die These.",
    "Wie Müller (2021, S. 45) zeigt, ist der Effekt robust.",
    'Müller (2021, S. 45) schreibt: „Ein wörtliches Zitat."',
]
# "Müller und Schmidt (2019)" hat kein Vault-Paper fuer 2019 im Fixture unten
# -> eigener Fall mit Jahr 2021 fuer den Vault-Treffer-Teil.
NARRATIVE_FORMS_VAULT_YEAR = [
    "Müller (2021) belegt die These.",
    "Müller (2021, S. 45) belegt die These.",
    "Müller et al. (2021) belegen die These.",
    "Wie Müller (2021, S. 45) zeigt, ist der Effekt robust.",
    'Müller (2021, S. 45) schreibt: „Ein wörtliches Zitat."',
]


@pytest.mark.parametrize("content", NARRATIVE_FORMS_VAULT_YEAR)
def test_narrative_forms_with_vault_hit_do_not_block(vault_with_mueller, content):
    """AC1: alle narrativen Formen mit Vault-Treffer -> kein Block."""
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": vault_with_mueller, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 0, (
        f"{content!r} geblockt: exit {result.returncode}. {result.stderr}"
    )


@pytest.mark.parametrize("content", NARRATIVE_FORMS)
def test_narrative_forms_without_vault_hit_block(empty_vault, content):
    """AC1: dieselben Formen ohne Vault-Treffer und ohne Kaskade -> Block."""
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 2, (
        f"{content!r} nicht geblockt: exit {result.returncode}. {result.stderr}"
    )


def test_narrative_coauthor_form_recognized_and_checked():
    """AC1: 'Müller und Schmidt (2019) belegen …' wird ueberhaupt extrahiert."""
    source = """
    import { extractCitations } from './hooks/lib/citation-parse.mjs';
    const content = 'Müller und Schmidt (2019) belegen die These.';
    console.log(JSON.stringify(extractCitations(content).map((c) => ({
      family: c.family, year: c.year, authors: c.authors,
      ok: content.slice(c.start, c.end) === c.raw,
    }))));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    data = json.loads(result.stdout)
    assert len(data) == 1, f"Erwartet genau eine Fundstelle, got {data}"
    assert data[0]["family"] == "Müller"
    assert data[0]["year"] == 2019
    assert "Schmidt" in data[0]["authors"]
    assert data[0]["ok"]


# ---------------------------------------------------------------------------
# AC2 — parenthetische Formen unverändert (Regression)
# ---------------------------------------------------------------------------


def test_parenthetical_forms_unchanged():
    """AC2: die vier bestehenden Klammerformen bleiben identisch (Regression)."""
    source = """
    import { extractCitations } from './hooks/lib/citation-parse.mjs';
    const cases = {
      plain: '(Müller, 2021, S. 45)',
      coauthor: '(Müller & Schmidt, 2019, S. 12)',
      etal: '(Müller et al., 2021, S. 45)',
      bare: '(Müller, 2021)',
    };
    const out = {};
    for (const [name, content] of Object.entries(cases)) {
      const cites = extractCitations(content);
      out[name] = cites.map((c) => ({
        family: c.family, year: c.year, page: c.page,
        start: c.start, end: c.end, confidence: c.confidence,
        ok: content.slice(c.start, c.end) === c.raw,
      }));
    }
    console.log(JSON.stringify(out));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    data = json.loads(result.stdout)
    for name in ("plain", "coauthor", "etal", "bare"):
        assert len(data[name]) == 1, f"{name}: erwartet genau eine Fundstelle, got {data[name]}"
        c = data[name][0]
        assert c["family"] == "Müller", f"{name}: {c}"
        assert c["start"] == 0, f"{name}: {c}"
        assert c["ok"], f"{name}: Span-Invariante verletzt"
    assert data["plain"][0] == {
        "family": "Müller",
        "year": 2021,
        "page": 45,
        "start": 0,
        "end": 21,
        "confidence": "strong",
        "ok": True,
    }
    assert data["coauthor"][0]["confidence"] == "strong"
    assert data["etal"][0]["confidence"] == "strong"
    assert data["bare"][0]["confidence"] == "weak"
    assert data["bare"][0]["page"] is None


# ---------------------------------------------------------------------------
# AC3 — kein Falschtreffer bei bestehenden Ausschluesslisten
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "Wie März (2021) zeigt, war der Winter kalt.",
        "Wie Kapitel (2021) zeigt, ist die Gliederung stimmig.",
        "Die DSGVO (2016) trat in Kraft.",
    ],
)
def test_narrative_form_respects_non_author_tokens(content):
    """AC3: bestehende Ausschlusslisten (Monate, Struktur-Verweise) greifen
    auch im neuen narrativen Muster; ein Berichtsverb allein hebt sie nicht auf.
    """
    source = f"""
    import {{ extractCitations }} from './hooks/lib/citation-parse.mjs';
    console.log(JSON.stringify(extractCitations({content!r})));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    assert json.loads(result.stdout) == [], f"Falschtreffer fuer {content!r}"


# ---------------------------------------------------------------------------
# Regression — Review-Fund P1 (PR #749): NARRATIVE_PAREN_YEAR blockte
# gewoehnliche deutsche Prosa ueber den Co-Autoren-Bypass bzw. ueber
# Berichtsverben nach nicht-personalen Substantiven.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        # Szenario (a): COAUTHORS matcht "und Frankreich" wie einen
        # Co-Autoren-Marker; ohne Berichtsverb-Gate wurde daraus ein
        # 'strong'-Beleg und damit ein Falsch-Block.
        "Deutschland und Frankreich (2016) unterzeichneten das Abkommen.",
        # Szenario (b): gaengige deutsche Rechts-/Institutionsbegriffe treffen
        # zufaellig auf ein REPORTING_VERBS-Wort.
        "Das Gesetz (2019) sieht Ausnahmen vor.",
        "Der Bericht (2020) beschreibt die Lage.",
    ],
)
def test_narrative_paren_year_does_not_false_positive_on_prose(content):
    """Review-Fund P1: Prosa ohne echten narrativen Beleg erzeugt keinen
    Treffer — weder ueber den Co-Autoren-Bypass noch ueber ein
    Berichtsverb nach einem nicht-personalen Substantiv.
    """
    source = f"""
    import {{ extractCitations }} from './hooks/lib/citation-parse.mjs';
    console.log(JSON.stringify(extractCitations({content!r})));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    assert json.loads(result.stdout) == [], f"Falschtreffer fuer {content!r}"


# ---------------------------------------------------------------------------
# AC4 — Sekundärbeleg
# ---------------------------------------------------------------------------


def test_secondary_citation_extracts_both_works():
    """AC4: 'Schmidt, 2015, zitiert nach Müller, 2021, S. 45' -> zwei Belege,
    das vorliegende Werk (Müller) trägt viaSecondary."""
    source = """
    import { extractCitations } from './hooks/lib/citation-parse.mjs';
    const content = '(Schmidt, 2015, zitiert nach Müller, 2021, S. 45)';
    console.log(JSON.stringify(extractCitations(content).map((c) => ({
      family: c.family, year: c.year, page: c.page, via: !!c.viaSecondary,
      ok: content.slice(c.start, c.end) === c.raw,
    }))));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    data = json.loads(result.stdout)
    assert len(data) == 2, f"Erwartet zwei Belege, got {data}"
    schmidt = next(c for c in data if c["family"] == "Schmidt")
    mueller = next(c for c in data if c["family"] == "Müller")
    assert schmidt["year"] == 2015 and not schmidt["via"]
    assert mueller["year"] == 2021 and mueller["page"] == 45 and mueller["via"]
    assert schmidt["ok"] and mueller["ok"]


def test_secondary_citation_short_form_extracts_both_works():
    """Review-Fund P2 (PR #749): die Kurzform 'zit. nach' (statt 'zitiert
    nach') wird ebenfalls als Sekundärbeleg mit zwei Werken erkannt."""
    source = """
    import { extractCitations } from './hooks/lib/citation-parse.mjs';
    const content = '(Schmidt, 2015, zit. nach Müller, 2021, S. 45)';
    console.log(JSON.stringify(extractCitations(content).map((c) => ({
      family: c.family, year: c.year, page: c.page, via: !!c.viaSecondary,
      ok: content.slice(c.start, c.end) === c.raw,
    }))));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    data = json.loads(result.stdout)
    assert len(data) == 2, f"Erwartet zwei Belege, got {data}"
    schmidt = next(c for c in data if c["family"] == "Schmidt")
    mueller = next(c for c in data if c["family"] == "Müller")
    assert schmidt["year"] == 2015 and not schmidt["via"]
    assert mueller["year"] == 2021 and mueller["page"] == 45 and mueller["via"]
    assert schmidt["ok"] and mueller["ok"]


def test_secondary_citation_hook_shows_present_work_verified_and_original_open(vault_with_mueller):
    """AC4: gegen einen Vault mit Müller 2021 wird der Sekundärbeleg nicht
    stillschweigend verschluckt — Schmidt bleibt sichtbar offen/[UNVERIFIED]
    statt komplett zu verschwinden, waehrend Müller nicht blockiert."""
    content = "Der Befund (Schmidt, 2015, zitiert nach Müller, 2021, S. 45) gilt."
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": vault_with_mueller, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    # Müller ist im Vault -> kein Hard-Block durch diesen Beleg. Schmidt ist
    # NICHT im Vault und mehrdeutig (kein Signalwort/Seite/Co-Autor) -> je
    # nach Default-Policy (block) waere das ein Hard-Block; entscheidend fuer
    # AC4 ist, dass Schmidt ueberhaupt als eigener Beleg auftaucht (exit 2
    # mit "Schmidt" in der Meldung), statt lautlos zu verschwinden.
    if result.returncode == 2:
        assert "Schmidt" in result.stderr, (
            f"Schmidt wurde nicht als offener Beleg gemeldet: {result.stderr}"
        )
    else:
        assert "[UNVERIFIED]" in updated_content(result)


# ---------------------------------------------------------------------------
# AC5 — Familienname+Jahr allein reicht nicht mehr fuer "confirmed"
# ---------------------------------------------------------------------------


def test_score_candidate_family_and_year_alone_stays_below_confirmed():
    """AC5: scoreCandidate() mit reinem Familienname+Jahr-Treffer (kein echter
    Co-Autoren-Ueberlapp) bleibt unter dem Default confirmedMin (80)."""
    source = """
    import { scoreCandidate } from './hooks/lib/citation-cascade.mjs';
    const citation = { family: 'Zufall', year: 2021, authors: ['Zufall'] };
    const candidate = { year: 2021, authors: ['Erika Zufall'] };
    console.log(JSON.stringify({ score: scoreCandidate(citation, candidate) }));
    """
    result = run_node(source)
    assert result.returncode == 0, f"Node-Fehler: {result.stderr}"
    score = json.loads(result.stdout)["score"]
    assert score < 80, f"Familienname+Jahr allein erreicht noch 'confirmed'-Niveau: Score {score}"


def test_invented_citation_with_coincidental_author_year_match_is_flagged(empty_vault):
    """AC5 (Hook-Ebene): ein erfundener Beleg, zu dem die Kaskade zufaellig
    EIN Paper mit passendem Nachnamen und Jahr kennt (aber ohne echten
    Co-Autoren-Ueberlapp), wird NICHT still durchgewunken — [UNVERIFIED]
    statt stillem Allow."""
    content = "Der Befund (Zufall 2021) ist umstritten."
    port_env = {
        "VAULT_DB_PATH": empty_vault,
        "ACADEMIC_CITATION_CASCADE": "on",
        "ACADEMIC_CITATION_ARXIV_URL": "http://127.0.0.1:1/arxiv",
        "ACADEMIC_CITATION_CROSSREF_URL": "http://127.0.0.1:1/crossref",
        "ACADEMIC_CITATION_S2_URL": "http://127.0.0.1:1/s2",
    }
    # Kein echter Stub-Server noetig: ECONNREFUSED liefert "unavailable" fuer
    # alle drei Stufen -> [UNVERIFIED], nie stiller Allow. Das allein beweist
    # AC5 nicht (unavailable != confirmed war schon vorher so) — die
    # eigentliche Behauptung steckt in test_score_candidate_* oben; dieser
    # Test belegt zusaetzlich, dass der Hook-Pfad in jedem Fall markiert statt
    # schweigt.
    result = run_hook(write_payload(content), env_overrides=port_env)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "[UNVERIFIED]" in updated_content(result)


# ---------------------------------------------------------------------------
# AC6/AC7 — ungeprüfte Belegformen: Hinweis, kein Block
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "\\footnote{Vgl. Müller 2021, S. 45.}",
        # Bewusst OHNE eigenständig gültige Autor/Jahr-Form im Fliesstext (das
        # waere ein zweiter, unabhaengiger Treffer des GEPRUEFTEN narrativen
        # Musters und wuerde diesen Test mit dem falschen Mechanismus koppeln
        # — hier geht es ausschliesslich um die Fussnoten-FORM).
        "[^1]: Weiterführende Anmerkung ohne eigene Jahreszahl.\n",
        "Der Effekt ist belegt [12].",
    ],
)
def test_unchecked_forms_reported_not_blocked(empty_vault, content):
    """AC6: je eine ungeprüfte Form erzeugt einen stderr-Hinweis, exit bleibt 0."""
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 0, f"Ungeprüfte Form blockiert: {result.stderr}"
    assert "ungeprüft" in result.stderr, f"Kein Hinweis auf ungeprüfte Form: {result.stderr!r}"


def test_unchecked_forms_notice_appears_once_and_is_switchable(empty_vault):
    """AC7: drei ungeprüfte Formen im selben Write -> genau EIN Hinweis;
    ACADEMIC_CITATION_UNCHECKED_NOTICE=off unterdrückt ihn vollständig."""
    content = (
        "\\footnote{Vgl. Müller 2021, S. 45.}\n"
        "[^1]: Weiterführende Anmerkung ohne eigene Jahreszahl.\n"
        "Der Effekt ist belegt [12].\n"
    )
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert result.stderr.count("[Citation-Guard] Hinweis:") == 1, (
        f"Erwartet genau einen Hinweis, got: {result.stderr!r}"
    )

    off_result = run_hook(
        write_payload(content),
        env_overrides={
            "VAULT_DB_PATH": empty_vault,
            "ACADEMIC_CITATION_CASCADE": "off",
            "ACADEMIC_CITATION_UNCHECKED_NOTICE": "off",
        },
    )
    assert off_result.returncode == 0, f"stderr: {off_result.stderr}"
    assert "[Citation-Guard] Hinweis:" not in off_result.stderr, (
        f"Schalter unterdrückt Hinweis nicht: {off_result.stderr!r}"
    )


def test_unchecked_forms_independent_of_checked_citations(empty_vault):
    """AC6: der Hinweis erscheint auch dann, wenn GAR KEIN geprüfter Beleg im
    Text steht (occurrences.length === 0) — genau der Fall aus dem Issue-Text:
    ein wörtliches Zitat mit AUSSCHLIESSLICH ungeprüfter Belegform."""
    content = "Ein Satz ohne jeden geprüften Beleg [12]."
    result = run_hook(
        write_payload(content),
        env_overrides={"VAULT_DB_PATH": empty_vault, "ACADEMIC_CITATION_CASCADE": "off"},
    )
    assert result.returncode == 0
    assert "ungeprüft" in result.stderr


# ---------------------------------------------------------------------------
# AC8 — docs/guide/limits.md dokumentiert geprüfte/ungeprüfte Formen
# ---------------------------------------------------------------------------


def test_limits_doc_documents_checked_and_unchecked_forms():
    """AC8: limits.md benennt geprüfte (Klammer, narrativ, Sekundärbeleg) und
    ungeprüfte Formen (Fußnote, numerisch) ausdrücklich."""
    text = LIMITS_DOC.read_text(encoding="utf-8")
    for token in (
        "narrative Form",
        "Sekundärbelege",
        "footnote",
        "numerische Verweise",
        "ACADEMIC_CITATION_UNCHECKED_NOTICE",
    ):
        assert token in text, f"docs/guide/limits.md dokumentiert '{token}' nicht (AC8)."
