"""Akzeptanz-Guards fuer Issue #452 — docs/ als navigierbare Referenz.

Jeder Test bildet ein Akzeptanzkriterium des Issues mechanisch ab:

AC1  Von der Einstiegsseite ist jede Unterseite in hoechstens zwei Klicks
     erreichbar.
AC2  Keine Datei unter ``docs/`` ist von nirgendwo verlinkt.
AC3  Historische Planungsdokumente sind an ihrem Seitenanfang gekennzeichnet und
     nicht mit gueltiger Referenz vermischt.
AC4  Ein Abschnitt erklaert, welche Dateien unter ``.claude/`` versioniert sind
     und warum ihr Entfernen CI und flowkit brechen wuerde.
AC5  Jede Referenzseite folgt derselben Grundstruktur.

Die Seitenlisten kommen aus ``tests/helpers/docs.py`` und werden aus
``git ls-files`` abgeleitet — neue Seiten fallen automatisch unter die Guards.
"""

import re
from collections import deque
from pathlib import Path

import pytest

from tests.helpers import docs as D

REPO_ROOT = D.REPO_ROOT

#: Klick-Budget von der Einstiegsseite bis zur letzten Unterseite (AC1).
MAX_CLICKS = 2

#: Zeilenfenster, in dem die Historik-Kennzeichnung stehen muss (AC3).
MARKER_LINE_BUDGET = 6

_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _prose_lines(text: str) -> list[str]:
    """Zeilen ausserhalb von Code-Fences; Fence-Inhalt wird zu Leerzeilen.

    Ohne das zaehlt ``# Einmalig einrichten`` in einem Bash-Block als zweite H1.
    Die Zeilennummern bleiben erhalten, damit Zeile 1/3 pruefbar bleiben.
    """
    lines = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            lines.append("")
            continue
        lines.append("" if in_fence else line)
    return lines


def _link_targets(text: str) -> list[str]:
    """Alle relativen Linkziele (ohne http(s):, mailto:, reine Anker)."""
    targets = []
    for m in _LINK_RE.finditer(text):
        target = m.group(1)
        if target.startswith(("http://", "https://", "mailto:", "#", "<")):
            continue
        targets.append(target)
    return targets


def _outgoing(md: Path) -> list[Path]:
    """Aufgeloeste Linkziele einer Markdown-Datei, die real existieren."""
    resolved = []
    for target in _link_targets(_read(md)):
        path_part = target.split("#", 1)[0]
        if not path_part:
            continue
        candidate = (md.parent / path_part).resolve()
        if candidate.exists():
            resolved.append(candidate)
    return resolved


# ---------------------------------------------------------------------------
# AC1 — Einstiegsseite, zwei Klicks bis zu jeder Unterseite
# ---------------------------------------------------------------------------


def test_docs_index_exists() -> None:
    """Ohne Einstiegsseite gibt es keinen Startpunkt fuer die Navigation."""
    assert D.INDEX.exists(), f"Einstiegsseite fehlt: {_rel(D.INDEX)}"


def test_readme_links_docs_index() -> None:
    """Die README fuehrt in die Doku-Uebersicht — sonst ist sie unauffindbar."""
    assert "docs/README.md" in _read(D.README), "README verlinkt docs/README.md nicht."


def _click_depth() -> dict[Path, int]:
    """BFS ueber den Markdown-Linkgraphen ab der Einstiegsseite."""
    start = D.INDEX.resolve()
    depth = {start: 0}
    queue: deque[Path] = deque([start])
    while queue:
        current = queue.popleft()
        if current.suffix != ".md":
            continue
        for target in _outgoing(current):
            if target in depth:
                continue
            depth[target] = depth[current] + 1
            queue.append(target)
    return depth


def test_every_doc_reachable_within_two_clicks() -> None:
    """Jede getrackte Datei unter docs/ liegt <= 2 Klicks von der Uebersicht."""
    depth = _click_depth()
    too_far = []
    for doc in D.repo_docs():
        d = depth.get(doc.resolve())
        if d is None:
            too_far.append(f"{_rel(doc)}: von der Uebersicht aus nicht erreichbar")
        elif d > MAX_CLICKS:
            too_far.append(f"{_rel(doc)}: {d} Klicks")
    assert not too_far, f"Klick-Budget ist {MAX_CLICKS}: {too_far}"


# ---------------------------------------------------------------------------
# AC2 — keine verwaisten Dateien
# ---------------------------------------------------------------------------


def _inbound_links() -> dict[Path, list[Path]]:
    """Wer verlinkt was — ueber alle getrackten Markdown-Dateien des Repos."""
    inbound: dict[Path, list[Path]] = {}
    for md in D.repo_markdown():
        for target in _outgoing(md):
            if target == md.resolve():
                continue
            inbound.setdefault(target, []).append(md)
    return inbound


def test_no_orphan_files_under_docs() -> None:
    """Keine Datei unter docs/ ist von nirgendwo aus verlinkt."""
    inbound = _inbound_links()
    orphans = [_rel(doc) for doc in D.repo_docs() if not inbound.get(doc.resolve())]
    assert not orphans, (
        "Verwaiste Dateien unter docs/ (kein eingehender Markdown-Link): "
        f"{orphans}. Entweder aus der Uebersicht verlinken oder entfernen."
    )


def test_no_broken_relative_links_under_docs() -> None:
    """Der Umbau hinterlaesst keinen toten relativen Link unter docs/."""
    broken = []
    for md in D.repo_docs():
        if md.suffix != ".md":
            continue
        for target in _link_targets(_read(md)):
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue
            if not (md.parent / path_part).resolve().exists():
                broken.append(f"{_rel(md)}: {target}")
    assert not broken, f"Tote relative Links unter docs/: {broken}"


# ---------------------------------------------------------------------------
# AC3 — historische Dokumente gekennzeichnet und getrennt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "doc", D.historical_docs(), ids=lambda p: p.relative_to(D.DOCS_DIR).as_posix()
)
def test_historical_docs_marked_at_top(doc: Path) -> None:
    """Die Kennzeichnung steht am Seitenanfang, nicht irgendwo im Fliesstext.

    Wer eine Momentaufnahme oeffnet, muss vor dem ersten Inhalt sehen, dass sie
    nicht der Sollzustand ist — ein Hinweis in Zeile 67 leistet das nicht.
    """
    head = _read(doc).splitlines()[:MARKER_LINE_BUDGET]
    assert any(D.HISTORICAL_MARKER in line for line in head), (
        f"{_rel(doc)}: Kennzeichnung '{D.HISTORICAL_MARKER}' fehlt in den ersten "
        f"{MARKER_LINE_BUDGET} Zeilen."
    )


@pytest.mark.parametrize(
    "doc", D.structured_pages(), ids=lambda p: p.relative_to(D.DOCS_DIR).as_posix()
)
def test_current_pages_are_not_marked_historical(doc: Path) -> None:
    """Umkehrprobe: gueltige Referenz traegt die Historik-Kennzeichnung nicht."""
    head = _read(doc).splitlines()[:MARKER_LINE_BUDGET]
    assert not any(D.HISTORICAL_MARKER in line for line in head), (
        f"{_rel(doc)} ist als historisch gekennzeichnet, gilt aber als aktuelle Referenz."
    )


def _index_sections() -> dict[str, str]:
    """Abschnitte der Einstiegsseite: Ueberschriftentext -> Abschnittstext."""
    sections: dict[str, str] = {}
    current = ""
    for line in _prose_lines(_read(D.INDEX)):
        m = re.match(r"^##\s+(.*?)\s*$", line)
        if m:
            current = m.group(1)
            sections[current] = ""
            continue
        if current:
            sections[current] += line + "\n"
    return sections


def test_index_separates_historical_docs_from_current_reference() -> None:
    """Historische Dokumente stehen ausschliesslich im eigenen Abschnitt."""
    sections = _index_sections()
    assert D.HISTORICAL_SECTION in sections, (
        f"Einstiegsseite hat keinen Abschnitt '{D.HISTORICAL_SECTION}'."
    )
    historical = {p.resolve() for p in D.historical_docs()}
    misplaced = []
    for heading, body in sections.items():
        for target in _link_targets(body):
            resolved = (D.INDEX.parent / target.split("#", 1)[0]).resolve()
            is_hist = resolved in historical
            if is_hist and heading != D.HISTORICAL_SECTION:
                misplaced.append(f"'{heading}' verlinkt historisches {target}")
            if not is_hist and heading == D.HISTORICAL_SECTION and resolved.suffix == ".md":
                misplaced.append(f"Historik-Abschnitt verlinkt aktuelles {target}")
    assert not misplaced, f"Einstiegsseite mischt Historik und gueltige Referenz: {misplaced}"


def test_audit_document_does_not_claim_to_be_untracked() -> None:
    """Das Audit-Dokument beschreibt sich selbst korrekt.

    Es behauptete 'untracked Arbeitsdokument', liegt aber im Repo — eine
    Falschaussage ueber die eigene Datei.
    """
    audit = D.DOCS_DIR / "audit" / "2026-06-03-board-audit.md"
    tracked = {p.resolve() for p in D.repo_docs()}
    assert audit.resolve() in tracked, "Vorbedingung geaendert: Audit-Dokument ist nicht getrackt."
    assert "untracked" not in _read(audit), (
        f"{_rel(audit)} nennt sich 'untracked', ist aber im Repo versioniert."
    )


# ---------------------------------------------------------------------------
# AC4 — .claude/ erklaert
# ---------------------------------------------------------------------------


def _claude_dir_section() -> str:
    text = _read(D.DEVELOPMENT_DOC)
    pattern = re.compile(r"^##\s+" + re.escape(D.CLAUDE_DIR_SECTION) + r"\s*$", re.M)
    m = pattern.search(text)
    assert m, f"{_rel(D.DEVELOPMENT_DOC)} hat keinen Abschnitt '## {D.CLAUDE_DIR_SECTION}'."
    rest = text[m.end() :]
    nxt = re.search(r"^##\s+", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def _tracked_claude_files() -> list[str]:
    """Nur committete .claude/-Pfade — die Doku beschreibt den Versionsstand."""
    return D.committed_paths(".claude")


def test_claude_dir_section_covers_every_versioned_file() -> None:
    """Jede versionierte .claude/-Datei ist im Abschnitt benannt (driftfest)."""
    section = _claude_dir_section()
    tracked = _tracked_claude_files()
    assert tracked, "Vorbedingung geaendert: unter .claude/ ist nichts versioniert."
    missing = [rel for rel in tracked if rel not in section]
    assert not missing, (
        f"Abschnitt '{D.CLAUDE_DIR_SECTION}' nennt diese versionierten Dateien nicht: {missing}"
    )


def test_claude_dir_section_names_the_concrete_breakage() -> None:
    """Der Abschnitt benennt, was beim Entfernen konkret bricht — CI und flowkit."""
    section = _claude_dir_section()
    for needle in ("scripts/dev/test-pretooluse-blocker.sh", "flowkit-hook-harness", "flowkit"):
        assert needle in section, (
            f"Abschnitt '{D.CLAUDE_DIR_SECTION}' nennt '{needle}' nicht — ohne die "
            "konkrete Bruchstelle bleibt die Warnung folgenlos."
        )


def test_claude_dir_section_matches_gitignore_allowlist() -> None:
    """Die Doku behauptet keine Versionierung, die .gitignore nicht hergibt."""
    gitignore = _read(REPO_ROOT / ".gitignore")
    allowlisted = set(re.findall(r"^!(\.claude/[^\s]*)$", gitignore, re.M))
    assert allowlisted, "Vorbedingung geaendert: .gitignore hat keine .claude/-Allowlist."
    section = _claude_dir_section()
    for rel in _tracked_claude_files():
        covered = any(rel.startswith(entry.rstrip("/")) for entry in allowlisted)
        assert covered, f"{rel} ist getrackt, steht aber in keiner .gitignore-Ausnahme."
    assert ".gitignore" in section, (
        f"Abschnitt '{D.CLAUDE_DIR_SECTION}' nennt die .gitignore-Allowlist nicht als Mechanik."
    )


# ---------------------------------------------------------------------------
# AC5 — einheitliche Grundstruktur
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "doc", D.structured_pages(), ids=lambda p: p.relative_to(D.DOCS_DIR).as_posix()
)
def test_reference_pages_share_layout(doc: Path) -> None:
    """H1 in Zeile 1, Breadcrumb in Zeile 3, Lead-Absatz, mindestens ein ##."""
    lines = _prose_lines(_read(doc))
    rel = _rel(doc)

    assert lines and lines[0].startswith("# "), f"{rel}: Zeile 1 ist keine H1."
    assert sum(1 for ln in lines if ln.startswith("# ")) == 1, f"{rel}: mehr als eine H1."
    assert len(lines) > 2 and D.BREADCRUMB_TEXT in lines[2], (
        f"{rel}: Zeile 3 traegt keinen Breadcrumb '{D.BREADCRUMB_TEXT}'."
    )

    first_section = next((i for i, ln in enumerate(lines) if ln.startswith("## ")), None)
    assert first_section is not None, f"{rel}: keine ##-Abschnitte."
    lead = [
        ln for ln in lines[3:first_section] if ln.strip() and not ln.startswith(("#", "|", ">"))
    ]
    assert lead, f"{rel}: kein Lead-Absatz zwischen Breadcrumb und erstem ##-Abschnitt."


@pytest.mark.parametrize(
    "doc", D.structured_pages(), ids=lambda p: p.relative_to(D.DOCS_DIR).as_posix()
)
def test_breadcrumb_points_at_the_index(doc: Path) -> None:
    """Der Breadcrumb fuehrt wirklich zur Einstiegsseite, nicht zur README."""
    line = _read(doc).splitlines()[2]
    m = _LINK_RE.search(line)
    assert m, f"{_rel(doc)}: Breadcrumb-Zeile enthaelt keinen Link."
    target = (doc.parent / m.group(1).split("#", 1)[0]).resolve()
    assert target == D.INDEX.resolve(), (
        f"{_rel(doc)}: Breadcrumb zeigt auf {target}, erwartet {D.INDEX}."
    )


@pytest.mark.parametrize(
    "doc", D.historical_docs(), ids=lambda p: p.relative_to(D.DOCS_DIR).as_posix()
)
def test_historical_docs_link_back_to_the_index(doc: Path) -> None:
    """Auch historische Seiten fuehren zurueck — sonst ist die Navigation eine Sackgasse."""
    targets = {t.resolve() for t in _outgoing(doc)}
    assert D.INDEX.resolve() in targets, (
        f"{_rel(doc)}: kein Rueckweg zur Doku-Uebersicht ({_rel(D.INDEX)})."
    )
