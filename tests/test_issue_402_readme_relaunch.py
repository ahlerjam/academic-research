"""Akzeptanz-Guards fuer Issue #402 — README-Relaunch als Produkt-Schaufenster.

Jeder Test bildet ein Akzeptanzkriterium aus dem Issue ab:

AC1  Quickstart real durchgespielt, Protokoll im Repo und aus der README verlinkt.
AC2  README auf Schaufenster-Format gekuerzt (<= 300 Zeilen), Langreferenz unter
     docs/ erreichbar und verlinkt.
AC3  Jede Feature-Behauptung ist gegen den Repo-Stand belegbar (Zaehlungen,
     Dateiverweise, Hook-Verdrahtung).
AC4  Badges automatisch erzeugt oder nachweislich korrekt — kein manuell
     gepflegter Zahlen-Badge.
AC5  Der Weg durch die Anleitung funktioniert ohne Rueckfragen: alle genannten
     Commands/Skills/Pfade existieren wirklich.
"""

import json
import re
from pathlib import Path

import pytest

from tests.helpers import docs as D

REPO_ROOT = D.REPO_ROOT

#: Zeilenbudget der README laut Issue-Richtwert.
README_LINE_BUDGET = 300


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _readme() -> str:
    return _read(D.README)


# ---------------------------------------------------------------------------
# AC2 — Schaufenster-Format + Auslagerung nach docs/
# ---------------------------------------------------------------------------


def test_readme_within_line_budget() -> None:
    """README bleibt im Schaufenster-Budget (Richtwert <= 300 Zeilen)."""
    lines = _readme().splitlines()
    assert len(lines) <= README_LINE_BUDGET, (
        f"README hat {len(lines)} Zeilen, Budget sind {README_LINE_BUDGET}. "
        "Langreferenz gehoert nach docs/."
    )


@pytest.mark.parametrize("doc", D.LINKED_DOCS, ids=lambda p: p.name)
def test_reference_doc_exists(doc: Path) -> None:
    """Jedes ausgelagerte Referenz-/Guide-Dokument existiert."""
    assert doc.exists(), f"Ausgelagertes Dokument fehlt: {doc.relative_to(REPO_ROOT)}"


@pytest.mark.parametrize("doc", D.LINKED_DOCS, ids=lambda p: p.name)
def test_readme_links_reference_doc(doc: Path) -> None:
    """Die README verlinkt jedes ausgelagerte Dokument (sonst ist es unauffindbar)."""
    rel = doc.relative_to(REPO_ROOT).as_posix()
    assert rel in _readme(), f"README verlinkt {rel} nicht."


def _relative_links(text: str) -> list[str]:
    """Alle relativen Markdown-Linkziele (ohne http(s):, mailto:, reine Anker)."""
    targets = []
    for m in re.finditer(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", text):
        target = m.group(1)
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        targets.append(target)
    return targets


@pytest.mark.parametrize(
    "doc", [D.README, *D.LINKED_DOCS], ids=lambda p: p.name if hasattr(p, "name") else str(p)
)
def test_relative_links_resolve(doc: Path) -> None:
    """Kein toter relativer Link in README oder ausgelagerten Dokumenten."""
    if not doc.exists():
        pytest.skip(f"{doc.name} existiert noch nicht (eigener Test deckt das ab)")
    broken = []
    for target in _relative_links(_read(doc)):
        path_part = target.split("#", 1)[0]
        if not path_part:
            continue
        resolved = (doc.parent / path_part).resolve()
        if not resolved.exists():
            broken.append(target)
    assert not broken, f"{doc.relative_to(REPO_ROOT)}: tote relative Links: {broken}"


# ---------------------------------------------------------------------------
# AC3 — Feature-Behauptungen sind belegbar
# ---------------------------------------------------------------------------


def _skill_count() -> int:
    return len(list((REPO_ROOT / "skills").rglob("SKILL.md")))


def _agent_count() -> int:
    return len(list((REPO_ROOT / "agents").glob("*.md")))


def _command_count() -> int:
    return len(list((REPO_ROOT / "commands").glob("*.md")))


def _mcp_tool_count() -> int:
    server = _read(REPO_ROOT / "academic_vault" / "server.py")
    return len(re.findall(r'@mcp\.tool\(name="(vault\.[a-z_]+)"\)', server))


def _profile_count() -> int:
    return len(list((REPO_ROOT / "config" / "library-profiles").glob("*.yaml")))


def _api_module_count() -> int:
    """Anzahl der in scripts/search.py registrierten API-Suchmodule."""
    src = _read(REPO_ROOT / "scripts" / "search.py")
    m = re.search(r"^MODULES\s*[:=][^{]*\{(.*?)^\}", src, re.S | re.M)
    assert m, "MODULES-Dispatch in scripts/search.py nicht gefunden"
    return len(re.findall(r'^\s*"([a-z_]+)":', m.group(1), re.M))


COUNT_CLAIMS = {
    "Skills": (r"(\d+)\s+Skills\b", _skill_count),
    "Agents": (r"(\d+)\s+Agents\b", _agent_count),
    "Slash-Commands": (r"(\d+)\s+Slash-Commands\b", _command_count),
    "MCP-Tools": (r"(\d+)\s+MCP-Tools\b", _mcp_tool_count),
    "Uni-Profile": (r"(\d+)\s+Uni-Profile\b", _profile_count),
    "API-Quellen": (r"(\d+)\s+API-Quellen\b", _api_module_count),
}


@pytest.mark.parametrize("label", sorted(COUNT_CLAIMS))
def test_count_claims_match_repo_state(label: str) -> None:
    """Jede Zahl-Behauptung in der Nutzerdoku stimmt mit dem Repo-Stand ueberein.

    Guard gegen genau die Doku-Drift, die Issue #387 fuer die alte README
    nachgewiesen hat (Badge/Text-Zahlen liefen auseinander).
    """
    pattern, actual_fn = COUNT_CLAIMS[label]
    actual = actual_fn()
    wrong: list[str] = []
    for path in D.doc_surface():
        if not path.exists():
            continue
        for m in re.finditer(pattern, _read(path)):
            if int(m.group(1)) != actual:
                line = _read(path)[: m.start()].count("\n") + 1
                wrong.append(f"{path.relative_to(REPO_ROOT)}:{line}: '{m.group(0)}' != {actual}")
    assert not wrong, f"{label}: Doku-Zahlen weichen vom Repo-Stand ({actual}) ab: {wrong}"


def test_hooks_doc_attributes_sessionstart_correctly() -> None:
    """SessionStart ist ein Inline-Bash-venv-Check, kein Skript-Hook (Befund aus #387).

    hooks/onboard-project-uni-prompt.sh liegt zwar im Repo, ist aber in
    hooks/hooks.json NICHT verdrahtet. Die Doku darf es nicht als aktiven
    SessionStart-Hook ausgeben.
    """
    hooks = json.loads(_read(REPO_ROOT / "hooks" / "hooks.json"))
    session_start = json.dumps(hooks["hooks"]["SessionStart"])
    assert "onboard-project-uni-prompt.sh" not in session_start, (
        "Vorbedingung geaendert: SessionStart ruft das Skript inzwischen doch auf."
    )

    text = _read(D.HOOKS_DOC) if D.HOOKS_DOC.exists() else ""
    hook_rows = [ln for ln in text.splitlines() if ln.strip().startswith("|")]
    offending = [
        ln for ln in hook_rows if "onboard-project-uni-prompt.sh" in ln and "SessionStart" in ln
    ]
    assert not offending, (
        "Hooks-Tabelle schreibt SessionStart faelschlich onboard-project-uni-prompt.sh zu "
        f"(real: Inline-Bash-venv-Check): {offending}"
    )


def test_hooks_doc_lists_every_wired_event() -> None:
    """Jedes in hooks/hooks.json verdrahtete Event steht in der Hooks-Doku."""
    hooks = json.loads(_read(REPO_ROOT / "hooks" / "hooks.json"))
    text = _read(D.HOOKS_DOC) if D.HOOKS_DOC.exists() else ""
    missing = [event for event in hooks["hooks"] if event not in text]
    assert not missing, f"Hook-Events fehlen in {D.HOOKS_DOC.name}: {missing}"


def test_referenced_repo_paths_exist() -> None:
    """Jeder in der Nutzerdoku genannte Repo-Pfad existiert wirklich."""
    path_re = re.compile(
        r"`((?:scripts|skills|agents|commands|hooks|config|academic_vault|docs|tests)"
        r"/[A-Za-z0-9_./<>-]+)`"
    )
    missing: list[str] = []
    for doc in D.doc_surface():
        if not doc.exists():
            continue
        text = _read(doc)
        for m in path_re.finditer(text):
            raw = m.group(1)
            # Platzhalter-Pfade (<uni>.yaml, <name>/) sind bewusst generisch.
            if "<" in raw or raw.endswith("*"):
                continue
            if not (REPO_ROOT / raw).exists():
                line = text[: m.start()].count("\n") + 1
                missing.append(f"{doc.relative_to(REPO_ROOT)}:{line}: {raw}")
    assert not missing, f"Doku nennt nicht existierende Repo-Pfade: {missing}"


def test_no_claim_of_automatic_pyzotero_install() -> None:
    """pyzotero wird ueber requirements.txt installiert, nicht 'bei Bedarf automatisch'.

    Befund aus #387: der Code wirft nur eine Installationsaufforderung.
    """
    offenders = []
    for doc in D.doc_surface():
        if not doc.exists():
            continue
        for i, line in enumerate(_read(doc).splitlines(), 1):
            if "pyzotero" in line and re.search(r"automatisch.*install|install.*automatisch", line):
                offenders.append(f"{doc.relative_to(REPO_ROOT)}:{i}")
    assert not offenders, (
        f"Doku behauptet automatische pyzotero-Installation bei Bedarf: {offenders}"
    )


# ---------------------------------------------------------------------------
# AC4 — Badges
# ---------------------------------------------------------------------------


def _badges() -> list[tuple[str, str]]:
    """(alt-text, url) aller Badges im README-Kopf."""
    return re.findall(r"!\[([^\]]*)\]\((https://[^)]+)\)", _readme())


def test_no_manually_maintained_test_count_badge() -> None:
    """Kein hartkodierter Test-Zahlen-Badge mehr (AC4).

    Der alte Badge behauptete '963 passing / 1111 collected' — real sind es
    inzwischen weit ueber 1800. Solche Zahlen veralten zwischen zwei Commits.
    """
    for alt, url in _badges():
        if "shields.io/badge" in url and re.search(r"tests?-", url, re.I):
            pytest.fail(
                f"Manuell gepflegter Test-Zahlen-Badge gefunden: ![{alt}]({url}). "
                "Stattdessen den automatischen CI-Workflow-Badge nutzen."
            )
    for _alt, url in _badges():
        if re.search(r"\d{3,}\s*(passing|collected)", url):
            pytest.fail(f"Badge enthaelt hartkodierte Testzahlen: {url}")


def test_ci_badge_points_to_existing_workflow() -> None:
    """Der automatische Status-Badge zeigt auf einen real existierenden Workflow."""
    found = False
    for _alt, url in _badges():
        m = re.search(r"/actions/workflows/([A-Za-z0-9_.-]+)/badge\.svg", url)
        if m:
            found = True
            workflow = REPO_ROOT / ".github" / "workflows" / m.group(1)
            assert workflow.exists(), f"Badge zeigt auf fehlenden Workflow: {m.group(1)}"
    assert found, "Kein automatischer GitHub-Actions-Status-Badge im README."


def test_version_badge_matches_plugin_manifest() -> None:
    """Der Versions-Badge stimmt mit .claude-plugin/plugin.json ueberein."""
    manifest = json.loads(_read(REPO_ROOT / ".claude-plugin" / "plugin.json"))
    version = manifest["version"]
    m = re.search(r"shields\.io/badge/version-([0-9][^-]*)-", _readme())
    assert m, "Kein Versions-Badge im README gefunden."
    shown = m.group(1).replace("%20", " ")
    assert shown == version, f"Versions-Badge zeigt {shown}, plugin.json sagt {version}."


def test_skills_badge_matches_filesystem() -> None:
    """Der Skills-Badge stimmt mit der Zahl der SKILL.md ueberein."""
    m = re.search(r"shields\.io/badge/skills-(\d+)", _readme())
    assert m, "Kein Skills-Badge im README gefunden."
    assert int(m.group(1)) == _skill_count(), (
        f"Skills-Badge zeigt {m.group(1)}, real sind es {_skill_count()} SKILL.md."
    )


# ---------------------------------------------------------------------------
# AC1 — Quickstart real durchgespielt, Protokoll verlinkt
# ---------------------------------------------------------------------------

QUICKSTART_START = "<!-- QUICKSTART-START -->"
QUICKSTART_END = "<!-- QUICKSTART-END -->"


def _quickstart_block() -> str:
    text = _readme()
    assert QUICKSTART_START in text and QUICKSTART_END in text, (
        "README markiert den Quickstart nicht mit "
        f"{QUICKSTART_START} / {QUICKSTART_END} — ohne Marker ist er nicht pruefbar."
    )
    return text.split(QUICKSTART_START, 1)[1].split(QUICKSTART_END, 1)[0]


def test_quickstart_protocol_is_linked_from_readme() -> None:
    """Das Protokoll des realen Durchlaufs ist aus der README erreichbar."""
    assert D.QUICKSTART_PROTOCOL_DOC.exists(), "docs/quickstart-protocol.md fehlt."
    assert "docs/quickstart-protocol.md" in _readme(), (
        "README verlinkt das Quickstart-Protokoll nicht."
    )


def test_quickstart_protocol_records_environment_and_date() -> None:
    """Ein Protokoll ohne Umgebungsangabe ist nicht nachvollziehbar."""
    text = _read(D.QUICKSTART_PROTOCOL_DOC)
    assert re.search(r"20\d{2}-\d{2}-\d{2}", text), "Protokoll nennt kein Ausfuehrungsdatum."
    for marker in ("Python", "Commit", "Plattform"):
        assert marker in text, f"Protokoll nennt '{marker}' nicht in der Umgebungsangabe."


def test_quickstart_protocol_shows_real_output() -> None:
    """Das Protokoll enthaelt echte Ausgabe, nicht nur die Befehlsliste."""
    text = _read(D.QUICKSTART_PROTOCOL_DOC)
    blocks = re.findall(r"```[a-z]*\n(.*?)```", text, re.S)
    assert len(blocks) >= 5, f"Protokoll hat nur {len(blocks)} Codebloecke — zu wenig Evidenz."
    assert "Setup complete" in text, (
        "Protokoll belegt den setup.sh-Lauf nicht (Marker 'Setup complete' fehlt)."
    )


def test_every_quickstart_step_is_covered_by_the_protocol() -> None:
    """Jeder Quickstart-Befehl aus der README taucht im Protokoll auf.

    Verhindert, dass die Anleitung Schritte enthaelt, die nie gelaufen sind.
    """
    protocol = _read(D.QUICKSTART_PROTOCOL_DOC)
    commands = []
    for block in re.findall(r"```(?:bash|console|text)?\n(.*?)```", _quickstart_block(), re.S):
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("→"):
                continue
            commands.append(line)
    assert commands, "Quickstart-Block enthaelt keine Befehle."
    missing = [c for c in commands if c not in protocol]
    assert not missing, f"Quickstart-Schritte fehlen im Protokoll: {missing}"


# ---------------------------------------------------------------------------
# AC5 — Walkthrough ohne Rueckfragen
# ---------------------------------------------------------------------------


def test_every_mentioned_slash_command_exists() -> None:
    """Jeder in der Nutzerdoku genannte Slash-Command hat eine commands/-Datei."""
    known = {p.stem for p in (REPO_ROOT / "commands").glob("*.md")}
    unknown: list[str] = []
    for doc in D.doc_surface():
        if not doc.exists():
            continue
        text = _read(doc)
        for m in re.finditer(r"/academic-research:([a-z-]+)", text):
            name = m.group(1)
            if name not in known:
                line = text[: m.start()].count("\n") + 1
                unknown.append(f"{doc.relative_to(REPO_ROOT)}:{line}: /{name}")
    assert not unknown, f"Doku nennt nicht existierende Commands: {unknown}"


def test_quickstart_names_prerequisites_before_first_command() -> None:
    """Der Quickstart nennt seine Voraussetzungen, bevor der erste Befehl kommt."""
    block = _quickstart_block()
    first_fence = block.find("```")
    assert first_fence != -1, "Quickstart enthaelt keinen Befehlsblock."
    preamble = block[:first_fence]
    assert re.search(r"Python\s*3\.11\+", preamble), (
        "Quickstart nennt die Python-Mindestversion nicht vor dem ersten Befehl."
    )
    assert "Claude Code" in preamble, "Quickstart nennt Claude Code nicht als Voraussetzung."


def test_quickstart_reaches_a_verified_quote() -> None:
    """Der Quickstart endet nicht bei der Installation, sondern beim ersten Zitat."""
    block = _quickstart_block().lower()
    assert "zitat" in block, "Quickstart fuehrt nicht bis zum ersten verifizierten Zitat."
    assert "vault" in block, "Quickstart erwaehnt den Vault nicht."
