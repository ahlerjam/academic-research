"""Tests fuer den Kontexttreue-Hook ``hooks/context-fidelity-guard.mjs`` (Issue #522).

Der Hook laeuft additiv neben ``verbatim-guard.mjs`` und ``claim-drift-guard.mjs``
und MARKIERT (nie: blockiert) Zitate, deren echter Quellkontext im Vault
nahelegt, dass die Kapitelverwendung den Kontext abschneidet ("Quote-Mining").

Geprueft werden die Akzeptanzkriterien aus #522:
  AC1  Zitat, dessen ``context_after`` mit einem Kontrastmarker beginnt, wird
       markiert und der Marker in der Begruendung genannt.
  AC2  Bewusst kontrastive Zitation (Kapitel-Prosa traegt selbst ein
       Kontrastsignal) erzeugt KEINEN Marker.
  AC3  Exit ist immer 0, die Abdeckung wird ausgewiesen, nicht pruefbare Zitate
       erscheinen namentlich mit Grund statt still uebersprungen zu werden.
  AC4  Nutzung des Bypass-Markers wird geloggt wie beim verbatim-guard.

Dazu kommen die Vault-Unit-Tests der Kosinus-Strecke
(``server.quote_context_similarity``) mit injiziertem Embedder — der Hook
selbst wird nie gegen ein echtes Embedding-Modell getestet.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "context-fidelity-guard.mjs"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
HOOKS_DOC = REPO_ROOT / "docs" / "reference" / "hooks.md"

# Markertext der Fundstellen-Meldung. Bewusst NICHT nur "[KONTEXT-PRÜFEN]":
# dieselbe Klammer traegt auch die Abdeckungszeile, die in AC2 erscheinen darf.
FINDING_PHRASE = "weicht vom Quellkontext ab"

VAULT_VERBATIM = "Der Effekt war in allen untersuchten Kohorten nachweisbar."
NEUTRAL_CONTEXT_BEFORE = "Die Stichprobe umfasste 1200 Schuelerinnen und Schueler."
NEUTRAL_CONTEXT_AFTER = " Die Effektstaerke lag bei d = 0.31 und blieb stabil."
CONTRAST_CONTEXT_AFTER = " Allerdings gilt dieser Befund nur fuer die staedtische Teilstichprobe."
FRAMING_CONTEXT_BEFORE = "Kritiker behaupten in diesem Zusammenhang immer wieder:"

PAPER_ID = "mueller-2021"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def run_hook(payload: dict, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    """Startet den Hook als Node-Subprocess mit JSON-Payload auf stdin."""
    env = os.environ.copy()
    env["VAULT_DB_PATH"] = str(REPO_ROOT / "nonexistent_vault_for_tests.db")
    # Derselbe Interpreter wie die Testsuite — sonst greift die Kaskade auf ein
    # System-Python zu, das academic_vault nicht importieren kann (#382).
    env["ACADEMIC_PYTHON"] = sys.executable
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


def output(result: subprocess.CompletedProcess) -> str:
    return result.stdout + result.stderr


def write_payload(content: str, file_path: str = "kapitel/kap1.md") -> dict:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
    }


def chapter(prose_before: str = "", prose_after: str = "") -> str:
    """Kapiteltext mit dem Vault-Zitat in der Mitte."""
    return f'## Ergebnisse\n\n{prose_before}"{VAULT_VERBATIM}" (Mueller 2021, S. 45){prose_after}\n'


def _make_vault(
    tmp_path,
    *,
    context_before: str,
    context_after: str,
    context_source: str | None,
    name: str = "context_fidelity_vault.db",
) -> str:
    from academic_vault.db import VaultDB
    from academic_vault.server import add_paper, add_quote

    db_path = str(tmp_path / name)
    db = VaultDB(db_path)
    db.init_schema()
    add_paper(
        db_path=db_path,
        paper_id=PAPER_ID,
        csl_json=json.dumps({"title": "Lesekompetenz", "type": "article-journal"}),
    )
    quote_id = add_quote(
        db_path=db_path,
        paper_id=PAPER_ID,
        verbatim=VAULT_VERBATIM,
        extraction_method="manual",
        printed_page=45,
        context_before=context_before,
        context_after=context_after,
    )
    if context_source is not None:
        db.update_quote_context(quote_id, context_before, context_after, context_source)
    return db_path


@pytest.fixture
def vault_contrast_after(tmp_path):
    """Zitat mit echtem Quellkontext, dessen Fortsetzung kontrastiert (AC1)."""
    return _make_vault(
        tmp_path,
        context_before=NEUTRAL_CONTEXT_BEFORE,
        context_after=CONTRAST_CONTEXT_AFTER,
        context_source="fulltext",
    )


@pytest.fixture
def vault_neutral(tmp_path):
    """Zitat mit echtem, aber unauffaelligem Quellkontext (Gegenprobe)."""
    return _make_vault(
        tmp_path,
        context_before=NEUTRAL_CONTEXT_BEFORE,
        context_after=NEUTRAL_CONTEXT_AFTER,
        context_source="fulltext",
    )


@pytest.fixture
def vault_framing_before(tmp_path):
    """Zitat, das im Original eine referierte Fremdposition ist (Signal 2)."""
    return _make_vault(
        tmp_path,
        context_before=FRAMING_CONTEXT_BEFORE,
        context_after=NEUTRAL_CONTEXT_AFTER,
        context_source="fulltext",
    )


@pytest.fixture
def vault_unresolved_context(tmp_path):
    """Kontextfelder gefuellt, aber ``context_source IS NULL`` (#520-Lehre).

    Der No-Op-Pfad von ``resolve_quote_context`` laesst modellgenerierte
    Kontextfelder stehen — nichtleerer Kontext ist deshalb KEIN Beleg fuer
    echten Quellkontext.
    """
    return _make_vault(
        tmp_path,
        context_before=NEUTRAL_CONTEXT_BEFORE,
        context_after=CONTRAST_CONTEXT_AFTER,
        context_source=None,
    )


# ---------------------------------------------------------------------------
# AC1 — Kontrastmarker im Quellkontext danach wird markiert und benannt
# ---------------------------------------------------------------------------


def test_contrast_marker_in_context_after_is_flagged(vault_contrast_after):
    result = run_hook(
        write_payload(chapter()),
        {"VAULT_DB_PATH": vault_contrast_after},
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    combined = output(result)
    assert FINDING_PHRASE in combined, f"Keine Fundstelle gemeldet: {combined!r}"
    assert "Allerdings" in combined, f"Gefundener Kontrastmarker wird nicht genannt: {combined!r}"
    assert VAULT_VERBATIM[:40] in combined, f"Betroffenes Zitat wird nicht genannt: {combined!r}"


def test_framing_marker_in_context_before_is_flagged(vault_framing_before):
    result = run_hook(
        write_payload(chapter()),
        {"VAULT_DB_PATH": vault_framing_before},
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    combined = output(result)
    assert FINDING_PHRASE in combined, f"Keine Fundstelle gemeldet: {combined!r}"
    assert "Kritiker behaupten" in combined, (
        f"Gefundener Rahmen-Marker wird nicht genannt: {combined!r}"
    )


# ---------------------------------------------------------------------------
# AC2 — bewusst kontrastive Zitation erzeugt keinen Marker
# ---------------------------------------------------------------------------


def test_chapter_own_contrast_marker_suppresses_flag(vault_contrast_after):
    """Das Kapitel legt die Einschraenkung selbst offen — kein Quote-Mining."""
    result = run_hook(
        write_payload(
            chapter(prose_before="Allerdings ist der Befund nur eingeschraenkt uebertragbar: ")
        ),
        {"VAULT_DB_PATH": vault_contrast_after},
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    combined = output(result)
    assert FINDING_PHRASE not in combined, (
        f"Offengelegte Kontrastivitaet darf keine Fundstelle erzeugen: {combined!r}"
    )
    assert "Abdeckung: 1 von 1 Zitaten prüfbar" in combined, (
        f"Abdeckungszeile fehlt trotz pruefbarem Zitat: {combined!r}"
    )


def test_neutral_context_after_is_not_flagged(vault_neutral):
    result = run_hook(
        write_payload(chapter()),
        {"VAULT_DB_PATH": vault_neutral},
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    combined = output(result)
    assert FINDING_PHRASE not in combined, (
        f"Unauffaelliger Quellkontext darf keine Fundstelle erzeugen: {combined!r}"
    )


def test_non_chapter_path_stays_silent(vault_contrast_after):
    result = run_hook(
        write_payload(chapter(), file_path="notizen/entwurf.md"),
        {"VAULT_DB_PATH": vault_contrast_after},
    )

    assert result.returncode == 0
    assert output(result).strip() == "", f"Nicht-Kapitelpfad darf nichts melden: {output(result)!r}"


def test_nested_chapter_path_is_checked(vault_contrast_after):
    """Unterordner unter kapitel/ zaehlen mit (#516)."""
    result = run_hook(
        write_payload(chapter(), file_path="kapitel/teil-a/kap1.md"),
        {"VAULT_DB_PATH": vault_contrast_after},
    )

    assert result.returncode == 0
    assert FINDING_PHRASE in output(result)


# ---------------------------------------------------------------------------
# AC3 — immer Exit 0, Abdeckung ausgewiesen, nichts still uebersprungen
# ---------------------------------------------------------------------------


def test_exit_zero_and_coverage_line_reported(vault_contrast_after):
    result = run_hook(
        write_payload(chapter()),
        {"VAULT_DB_PATH": vault_contrast_after},
    )

    assert result.returncode == 0
    assert "Abdeckung: 1 von 1 Zitaten prüfbar" in output(result)


def test_quote_without_fulltext_context_is_reported_as_unpruefbar(vault_unresolved_context):
    """``context_source IS NULL`` ist nicht pruefbar — auch mit gefuellten Feldern."""
    result = run_hook(
        write_payload(chapter()),
        {"VAULT_DB_PATH": vault_unresolved_context},
    )

    assert result.returncode == 0
    combined = output(result)
    assert "Abdeckung: 0 von 1 Zitaten prüfbar" in combined, (
        f"Abdeckung falsch ausgewiesen: {combined!r}"
    )
    assert "Nicht prüfbar" in combined, f"Grund fehlt: {combined!r}"
    assert "context_source" in combined, (
        f"Grund benennt den fehlenden Quellkontext nicht: {combined!r}"
    )
    assert FINDING_PHRASE not in combined, (
        f"Ohne echten Quellkontext darf nicht gewertet werden: {combined!r}"
    )


def test_quote_unknown_to_vault_is_reported_as_unpruefbar(vault_neutral):
    content = (
        '## Ergebnisse\n\n"Diese Aussage steht nirgends im Vault und ist frei erfunden." (X 2020)\n'
    )
    result = run_hook(write_payload(content), {"VAULT_DB_PATH": vault_neutral})

    assert result.returncode == 0
    combined = output(result)
    assert "Abdeckung: 0 von 1 Zitaten prüfbar" in combined, (
        f"Abdeckung falsch ausgewiesen: {combined!r}"
    )
    assert "kein Eintrag im Vault" in combined, f"Grund fehlt: {combined!r}"


def test_missing_vault_db_is_reported_not_silent(tmp_path):
    result = run_hook(
        write_payload(chapter()),
        {"VAULT_DB_PATH": str(tmp_path / "gibt-es-nicht.db")},
    )

    assert result.returncode == 0
    combined = output(result)
    assert "Abdeckung: 0 von 1 Zitaten prüfbar" in combined, (
        f"Ohne Vault muss die Abdeckung 0 gemeldet werden: {combined!r}"
    )
    assert "Vault nicht erreichbar" in combined, f"Grund fehlt: {combined!r}"


def test_malformed_stdin_exits_zero():
    env = os.environ.copy()
    env["ACADEMIC_PYTHON"] = sys.executable
    result = subprocess.run(
        ["node", str(HOOK_PATH)],
        input="{ kein JSON",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_chapter_without_quotes_stays_silent(vault_contrast_after):
    result = run_hook(
        write_payload("## Ergebnisse\n\nEin Absatz ganz ohne Zitat.\n"),
        {"VAULT_DB_PATH": vault_contrast_after},
    )

    assert result.returncode == 0
    assert output(result).strip() == ""


def test_hook_never_sets_permission_decision(vault_contrast_after):
    """Der Hook informiert, er entscheidet nicht ueber die Berechtigung."""
    result = run_hook(
        write_payload(chapter()),
        {"VAULT_DB_PATH": vault_contrast_after},
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "permissionDecision" not in json.dumps(payload), (
        f"Warn-Hook darf kein permissionDecision setzen: {payload!r}"
    )
    assert payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"


# ---------------------------------------------------------------------------
# AC4 — Bypass-Nutzung wird geloggt wie beim verbatim-guard
# ---------------------------------------------------------------------------


def test_bypass_marker_skips_check(vault_contrast_after, tmp_path):
    log_path = tmp_path / "bypass.log"
    content = "<!-- vault-guard: skip -->\n" + chapter()
    result = run_hook(
        write_payload(content),
        {
            "VAULT_DB_PATH": vault_contrast_after,
            "VAULT_GUARD_BYPASS_LOG": str(log_path),
        },
    )

    assert result.returncode == 0
    assert FINDING_PHRASE not in output(result), "Bypass-Marker muss die Pruefung abschalten"


def test_bypass_marker_logs_usage_like_verbatim_guard(vault_contrast_after, tmp_path):
    log_path = tmp_path / "bypass.log"
    content = "<!-- vault-guard: skip -->\n" + chapter()
    result = run_hook(
        write_payload(content),
        {
            "VAULT_DB_PATH": vault_contrast_after,
            "VAULT_GUARD_BYPASS_LOG": str(log_path),
        },
    )

    assert result.returncode == 0
    assert log_path.exists(), "Bypass-Nutzung wurde nicht geloggt"
    lines = [ln for ln in log_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1, f"Genau eine Logzeile erwartet: {lines!r}"
    fields = lines[0].split(" | ")
    assert len(fields) == 3, f"Logformat '<ts> | <label> | <pfad>' erwartet: {lines[0]!r}"
    assert fields[0].endswith("Z") and "T" in fields[0], (
        f"Erstes Feld ist kein ISO-Timestamp: {fields[0]!r}"
    )
    assert fields[1] == "context-fidelity-guard: skip", (
        f"Label identifiziert den Hook nicht: {fields[1]!r}"
    )
    assert fields[2] == "kapitel/kap1.md", f"Dateipfad fehlt: {fields[2]!r}"
    assert oct(log_path.stat().st_mode)[-3:] == "600", (
        f"Bypass-Log muss 0600 sein: {oct(log_path.stat().st_mode)}"
    )


# ---------------------------------------------------------------------------
# Signal 3 — Hedge-Verlust Quelle → Kapitel
# ---------------------------------------------------------------------------

HEDGED_VERBATIM = "Die Daten deuten darauf hin, dass der Effekt fortbesteht."


@pytest.fixture
def vault_hedged_quote(tmp_path):
    from academic_vault.db import VaultDB
    from academic_vault.server import add_paper, add_quote

    db_path = str(tmp_path / "hedge_vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    add_paper(
        db_path=db_path,
        paper_id=PAPER_ID,
        csl_json=json.dumps({"title": "Lesekompetenz", "type": "article-journal"}),
    )
    quote_id = add_quote(
        db_path=db_path,
        paper_id=PAPER_ID,
        verbatim=HEDGED_VERBATIM,
        extraction_method="manual",
        printed_page=45,
        context_before=NEUTRAL_CONTEXT_BEFORE,
        context_after=NEUTRAL_CONTEXT_AFTER,
    )
    db.update_quote_context(quote_id, NEUTRAL_CONTEXT_BEFORE, NEUTRAL_CONTEXT_AFTER, "fulltext")
    return db_path


def test_hedge_loss_between_source_and_chapter_is_flagged(vault_hedged_quote):
    content = (
        "## Ergebnisse\n\n"
        "Die Untersuchung beweist den Zusammenhang durchweg und ohne Einschraenkung: "
        f'"{HEDGED_VERBATIM}" (Mueller 2021, S. 45)\n'
    )
    result = run_hook(write_payload(content), {"VAULT_DB_PATH": vault_hedged_quote})

    assert result.returncode == 0
    combined = output(result)
    assert FINDING_PHRASE in combined, f"Hedge-Verlust nicht gemeldet: {combined!r}"
    assert "Hedge" in combined, f"Signal wird nicht benannt: {combined!r}"


def test_hedge_kept_in_chapter_is_not_flagged(vault_hedged_quote):
    content = (
        "## Ergebnisse\n\n"
        "Die Untersuchung legt nahe, dass ein Zusammenhang moeglicherweise besteht: "
        f'"{HEDGED_VERBATIM}" (Mueller 2021, S. 45)\n'
    )
    result = run_hook(write_payload(content), {"VAULT_DB_PATH": vault_hedged_quote})

    assert result.returncode == 0
    assert FINDING_PHRASE not in output(result), (
        "Erhaltene Relativierung darf keine Fundstelle erzeugen"
    )


# ---------------------------------------------------------------------------
# Verdrahtung + Doku
# ---------------------------------------------------------------------------


def test_hook_is_wired_in_hooks_json():
    data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    entries = data["hooks"]["PreToolUse"]
    matchers = [
        entry.get("matcher")
        for entry in entries
        if any("context-fidelity-guard.mjs" in h.get("command", "") for h in entry["hooks"])
    ]
    assert matchers == ["Write|Edit|MultiEdit"], (
        f"context-fidelity-guard haengt an unerwarteten Matchern: {matchers}"
    )


def test_hooks_doc_lists_new_hook():
    doc = HOOKS_DOC.read_text(encoding="utf-8")
    assert "context-fidelity-guard.mjs" in doc, (
        "docs/reference/hooks.md fuehrt context-fidelity-guard.mjs nicht auf."
    )
    assert "**6 Skript-Dateien**" not in doc, (
        "docs/reference/hooks.md behauptet weiter 6 Skript-Dateien."
    )


def test_setup_sh_hook_count_is_current():
    setup = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert "5 der 7 Hooks" not in setup, "scripts/setup.sh behauptet weiter '5 der 7 Hooks'."
    assert "6 der 8 Hooks" not in setup, (
        "scripts/setup.sh nennt veraltete Hook-Anzahl '6 der 8 Hooks'."
    )
    assert "7 der 9 Hooks" not in setup, (
        "scripts/setup.sh nennt veraltete Hook-Anzahl '7 der 9 Hooks'."
    )
    assert "8 der 10 Hooks" in setup, (
        "scripts/setup.sh nennt die aktuelle Hook-Anzahl nicht ('8 der 10 Hooks')."
    )


# ---------------------------------------------------------------------------
# Kosinus-Strecke: server.quote_context_similarity (injizierter Embedder)
# ---------------------------------------------------------------------------


def _quote_with_embedding(tmp_path, vector):
    from academic_vault.db import VaultDB
    from academic_vault.embedding_model import serialize_f32
    from academic_vault.server import add_paper, add_quote

    db_path = str(tmp_path / "similarity_vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    if not db.vec_extension_loadable():
        pytest.skip("sqlite-vec-Extension nicht ladbar (optionales Feature)")
    add_paper(
        db_path=db_path,
        paper_id=PAPER_ID,
        csl_json=json.dumps({"title": "Lesekompetenz", "type": "article-journal"}),
    )
    quote_id = add_quote(
        db_path=db_path,
        paper_id=PAPER_ID,
        verbatim=VAULT_VERBATIM,
        extraction_method="manual",
    )
    assert db.add_quote_embedding(quote_id, serialize_f32(vector)), (
        "Embedding konnte nicht gespeichert werden"
    )
    return db_path, quote_id


class _FixedEmbedder:
    """Embedder mit fest vorgegebenem Query-Vektor (kein Modell-Load)."""

    dim = 384

    def __init__(self, vector):
        self._vector = list(vector)

    def embed_documents(self, texts):
        return [list(self._vector) for _ in texts]

    def embed_query(self, text):
        return list(self._vector)


def test_quote_context_similarity_identical_vectors_is_one(tmp_path):
    from academic_vault.server import quote_context_similarity

    vector = [0.0] * 384
    vector[0] = 1.0
    db_path, quote_id = _quote_with_embedding(tmp_path, vector)

    score = quote_context_similarity(
        db_path, quote_id, "beliebiger Kapiteltext", embedder=_FixedEmbedder(vector)
    )
    assert score == pytest.approx(1.0, abs=1e-5)


def test_quote_context_similarity_orthogonal_vectors_is_zero(tmp_path):
    from academic_vault.server import quote_context_similarity

    stored = [0.0] * 384
    stored[0] = 1.0
    query = [0.0] * 384
    query[1] = 1.0
    db_path, quote_id = _quote_with_embedding(tmp_path, stored)

    score = quote_context_similarity(
        db_path, quote_id, "beliebiger Kapiteltext", embedder=_FixedEmbedder(query)
    )
    assert score == pytest.approx(0.0, abs=1e-5)


def test_quote_context_similarity_without_embedding_is_none(vault_neutral):
    """Kein gespeichertes Embedding — ``None`` statt geratener Zahl."""
    from academic_vault.db import VaultDB
    from academic_vault.server import quote_context_similarity

    db = VaultDB(vault_neutral)
    quote_id = db.search_quote_text(VAULT_VERBATIM, 1)[0]["quote_id"]

    vector = [0.0] * 384
    vector[0] = 1.0
    assert (
        quote_context_similarity(
            vault_neutral, quote_id, "Kapiteltext", embedder=_FixedEmbedder(vector)
        )
        is None
    )


def test_quote_context_similarity_unknown_quote_is_none(vault_neutral):
    from academic_vault.server import quote_context_similarity

    vector = [0.0] * 384
    vector[0] = 1.0
    assert (
        quote_context_similarity(
            vault_neutral, "gibt-es-nicht", "Kapiteltext", embedder=_FixedEmbedder(vector)
        )
        is None
    )


def test_get_quote_embedding_roundtrip(tmp_path):
    from academic_vault.db import VaultDB

    vector = [0.0] * 384
    vector[3] = 1.0
    db_path, quote_id = _quote_with_embedding(tmp_path, vector)

    stored = VaultDB(db_path).get_quote_embedding(quote_id)
    assert stored is not None
    assert len(stored) == 384
    assert stored[3] == pytest.approx(1.0, abs=1e-6)


def test_get_quote_embedding_unknown_quote_is_none(temp_vault_db):
    from academic_vault.db import VaultDB

    assert VaultDB(temp_vault_db).get_quote_embedding("gibt-es-nicht") is None


def test_similarity_not_checked_is_reported_in_coverage(vault_neutral):
    """Signal 4 läuft nicht im PreToolUse-Pfad (#522); Abdeckungszeile wird trotzdem gemeldet."""
    result = run_hook(write_payload(chapter()), {"VAULT_DB_PATH": vault_neutral})

    assert result.returncode == 0
    # Abdeckungszeile wird trotzdem ausgegeben, auch wenn Signal 4 nicht läuft
    assert "Abdeckung:" in output(result), (
        f"Abdeckungszeile wird nicht ausgegeben: {output(result)!r}"
    )
