"""Akzeptanz-Guards fuer Issue #639 — Mermaid-Diagramme und Terminal-Aufzeichnungen.

Jeder Test bildet ein Akzeptanzkriterium aus dem Issue mechanisch ab:

AC1  README enthaelt mindestens ein auf GitHub renderndes Mermaid-Diagramm
     (bereits durch #402 erfuellt; hier zusaetzlich strukturell abgesichert
     ueber ``test_every_mermaid_block_is_structurally_valid``).
AC2  Jedes Vorhaben im Kochbuch (``docs/guide/project-paths.md``) hat ein
     Ablaufbild, das mit der "Reihenfolge:"-Prosa uebereinstimmt.
AC3  Ein Architekturdiagramm zeigt Vault/Hooks/Skills/Agents im Zusammenspiel.
AC4  Zu mindestens zwei Use Cases existiert eine aus dem Cast gerenderte
     Terminal-Aufzeichnung.
AC5  Der Renderer (``scripts/dev/render_quickstart_svg.py``) erzeugt alle
     Casts; keine kopierte zweite Fassung des Skripts.
AC6  Ein Test rendert jedes Asset neu und schlaegt bei Abweichung fehl.
AC7  Ein Test findet Verweise auf fehlende Assets.
AC8  Jeder in einer Aufzeichnung getippte Befehl ist in einem Protokoll belegt.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from scripts.dev import render_quickstart_svg

from tests.helpers import docs as D

REPO_ROOT = D.REPO_ROOT

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
MERMAID_FENCE_RE = re.compile(r"```mermaid\n(.*?)```", re.S)
ASSET_REF_RE = re.compile(r"docs/assets/[A-Za-z0-9_\-./]+\.(?:svg|cast|png)")

#: Gueltige Diagramm-Keywords, mit denen ein Mermaid-Block beginnen darf.
VALID_DIAGRAM_KEYWORDS = (
    "graph",
    "flowchart",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram-v2",
    "stateDiagram",
    "erDiagram",
    "gantt",
    "pie",
    "journey",
    "gitGraph",
    "mindmap",
    "timeline",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalize(text: str) -> str:
    """Whitespace einebnen — Doku bricht Befehle ueber Zeilen um, Casts nicht."""
    return re.sub(r"\s+", " ", text).strip()


def _mermaid_blocks(text: str) -> list[str]:
    return [m.group(1) for m in MERMAID_FENCE_RE.finditer(text)]


# ---------------------------------------------------------------------------
# AC1/AC2 (Struktur) — jeder eingebettete Mermaid-Block ist syntaktisch plausibel
# ---------------------------------------------------------------------------


def _all_mermaid_blocks() -> list[tuple[Path, int, str]]:
    """(Datei, Blockindex, Quelltext) je eingebettetem Mermaid-Block."""
    found: list[tuple[Path, int, str]] = []
    for doc in D.doc_surface():
        if not doc.exists():
            continue
        for i, block in enumerate(_mermaid_blocks(_read(doc))):
            found.append((doc, i, block))
    return found


_MERMAID_CASES = _all_mermaid_blocks()


def test_readme_has_a_mermaid_diagram() -> None:
    """AC1 — mindestens ein Mermaid-Block in der README."""
    assert _mermaid_blocks(_read(D.README)), "README enthaelt keinen ```mermaid-Block."


@pytest.mark.parametrize(
    "case",
    _MERMAID_CASES,
    ids=[f"{doc.relative_to(REPO_ROOT).as_posix()}#{i}" for doc, i, _ in _MERMAID_CASES],
)
def test_every_mermaid_block_is_structurally_valid(case: tuple[Path, int, str]) -> None:
    """Jeder eingebettete Mermaid-Block ist nicht leer, beginnt gueltig und ist balanciert."""
    doc, index, block = case
    label = f"{doc.relative_to(REPO_ROOT).as_posix()} (Block {index})"
    stripped = block.strip()
    assert stripped, f"{label}: leerer Mermaid-Block."

    first_line = stripped.splitlines()[0].strip()
    assert first_line.startswith(VALID_DIAGRAM_KEYWORDS), (
        f"{label}: beginnt mit '{first_line}', kein gueltiges Diagramm-Keyword "
        f"({VALID_DIAGRAM_KEYWORDS})."
    )

    for open_ch, close_ch in (("[", "]"), ("(", ")"), ("{", "}")):
        assert stripped.count(open_ch) == stripped.count(close_ch), (
            f"{label}: '{open_ch}'/'{close_ch}' unbalanciert."
        )


# ---------------------------------------------------------------------------
# AC2 — Vorhaben-Diagramm == Reihenfolge-Prosa
# ---------------------------------------------------------------------------

#: Ueberschriften der vier Vorhaben in docs/guide/project-paths.md, in Dateireihenfolge.
VORHABEN_HEADINGS = (
    "Systematische Übersichtsarbeit",
    "Empirische Qualifikationsarbeit mit eigener Erhebung",
    "Literaturarbeit",
    "Zeitschriftenbeitrag",
)


def _vorhaben_sections() -> dict[str, str]:
    """Abschnittstext je Vorhaben-Ueberschrift (bis zur naechsten '## ')."""
    text = _read(D.PROJECT_PATHS_DOC)
    sections: dict[str, str] = {}
    headings = list(re.finditer(r"^## (.+)$", text, re.M))
    for i, m in enumerate(headings):
        title = m.group(1).strip()
        if title not in VORHABEN_HEADINGS:
            continue
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        sections[title] = text[m.end() : end]
    return sections


def _prose_skill_sequence(section: str) -> list[str]:
    m = re.search(r"Reihenfolge:(.*?)\n\n", section, re.S)
    assert m, "Kein 'Reihenfolge:'-Absatz gefunden."
    return list(dict.fromkeys(re.findall(r"`([a-z][a-z0-9-]*)`", m.group(1))))


def _diagram_node_sequence(section: str) -> list[str]:
    blocks = _mermaid_blocks(section)
    assert blocks, "Kein Mermaid-Block im Abschnitt."
    return list(dict.fromkeys(re.findall(r"\[([a-z][a-z0-9-]*)\]", blocks[0])))


@pytest.mark.parametrize("heading", VORHABEN_HEADINGS)
def test_project_paths_each_vorhaben_has_a_flow_diagram_matching_its_prose(heading: str) -> None:
    """Jedes Vorhaben hat ein Ablaufbild, dessen Knoten die Reihenfolge-Prosa spiegeln."""
    sections = _vorhaben_sections()
    assert heading in sections, f"Abschnitt '{heading}' fehlt in {D.PROJECT_PATHS_DOC.name}."
    section = sections[heading]
    prose_sequence = _prose_skill_sequence(section)
    diagram_sequence = _diagram_node_sequence(section)
    assert diagram_sequence == prose_sequence, (
        f"'{heading}': Diagrammknoten {diagram_sequence} weichen von der Reihenfolge-Prosa "
        f"{prose_sequence} ab."
    )


# ---------------------------------------------------------------------------
# AC3 — Architekturdiagramm nennt Vault/Hooks/Skills/Agents
# ---------------------------------------------------------------------------


def _hook_script_names() -> set[str]:
    """Alle *.mjs-Hooknamen, die docs/reference/hooks.md tatsaechlich nennt."""
    return set(re.findall(r"[a-z][a-z-]*\.mjs", _read(D.HOOKS_DOC)))


def test_architecture_doc_exists_and_is_linked() -> None:
    assert D.ARCHITECTURE_DOC.exists(), f"Architekturseite fehlt: {D.ARCHITECTURE_DOC}"
    assert D.ARCHITECTURE_DOC in D.LINKED_DOCS, "Architekturseite fehlt in D.LINKED_DOCS."


def test_architecture_diagram_names_vault_hooks_skills_agents() -> None:
    """Das Architekturdiagramm zeigt Vault, mehrere echte Hooks, Skills und Agents."""
    text = _read(D.ARCHITECTURE_DOC)
    blocks = _mermaid_blocks(text)
    assert blocks, f"{D.ARCHITECTURE_DOC.name}: kein Mermaid-Block."
    diagram = blocks[0]

    assert "Vault" in diagram, "Architekturdiagramm nennt 'Vault' nicht."
    assert re.search(r"\bSkills\b", diagram), "Architekturdiagramm nennt 'Skills' nicht."
    assert re.search(r"\bAgents\b", diagram), "Architekturdiagramm nennt 'Agents' nicht."

    real_hooks = _hook_script_names()
    named_hooks = set(re.findall(r"[a-z][a-z-]*\.mjs", diagram))
    assert named_hooks, "Architekturdiagramm nennt keinen einzigen Hook."
    assert len(named_hooks) >= 3, f"Nur {len(named_hooks)} Hooks im Diagramm benannt: {named_hooks}"
    unknown = named_hooks - real_hooks
    assert not unknown, f"Diagramm nennt Hooks, die nicht in hooks.md stehen: {unknown}"


# ---------------------------------------------------------------------------
# AC4/AC5/AC6/AC8 — Terminal-Aufzeichnungen (Cast -> SVG -> Protokoll)
# ---------------------------------------------------------------------------

_TRIPLES = D.CAST_SVG_PROTOCOL_TRIPLES
_NEW_USE_CASE_NAMES = [name for name in _TRIPLES if name != "quickstart"]


def test_at_least_two_new_use_case_recordings_exist() -> None:
    """AC4 — mindestens zwei neue Terminal-Aufzeichnungen zusaetzlich zum Quickstart."""
    assert len(_NEW_USE_CASE_NAMES) >= 2, (
        f"Nur {len(_NEW_USE_CASE_NAMES)} neue Use-Case-Casts registriert: {_NEW_USE_CASE_NAMES}"
    )


@pytest.mark.parametrize("name", _NEW_USE_CASE_NAMES)
def test_new_use_case_cast_is_valid_asciicast_v2(name: str) -> None:
    """Analogon zu test_demo_cast_is_valid_asciicast_v2 (#451), parametrisiert."""
    cast_path, _, _ = _TRIPLES[name]
    assert cast_path.exists(), f"Cast fehlt: {cast_path.relative_to(REPO_ROOT)}"
    lines = [ln for ln in _read(cast_path).splitlines() if ln.strip()]
    header = json.loads(lines[0])
    assert header["version"] == 2, f"{name}: asciicast-Version {header['version']}, erwartet 2."
    assert header["width"] > 0 and header["height"] > 0, f"{name}: Cast ohne Terminalgeometrie."

    events = [json.loads(ln) for ln in lines[1:]]
    outputs = [e for e in events if e[1] == "o"]
    assert len(outputs) >= 3, f"{name}: nur {len(outputs)} Ausgabeframes."
    times = [e[0] for e in events]
    assert times == sorted(times), f"{name}: Cast-Zeitstempel laufen nicht monoton."
    assert times[-1] > 0, f"{name}: Cast hat keine Laufzeit."


def _cast_command_lines(cast_path: Path) -> list[str]:
    """Alle im Cast getippten Befehlszeilen (Prompt ``$ `` abgeschnitten)."""
    lines = [ln for ln in _read(cast_path).splitlines() if ln.strip()]
    events = [json.loads(ln) for ln in lines[1:]]
    text = "".join(e[2] for e in events if e[1] == "o")
    text = ANSI_RE.sub("", text).replace("\r\n", "\n")
    return [ln[2:].strip() for ln in text.split("\n") if ln.startswith("$ ")]


@pytest.mark.parametrize("name", sorted(_TRIPLES))
def test_cast_commands_are_covered_by_their_protocol(name: str) -> None:
    """AC8 — jeder getippte Befehl steht (normalisiert) im zugehoerigen Protokoll."""
    cast_path, _, protocol_doc = _TRIPLES[name]
    commands = _cast_command_lines(cast_path)
    assert commands, f"{name}: Cast zeigt keine Befehle."
    protocol = _normalize(_read(protocol_doc))
    missing = [c for c in commands if _normalize(c) not in protocol]
    assert not missing, f"{name}: Befehle nicht im Protokoll belegt: {missing}"


@pytest.mark.parametrize("name", sorted(_TRIPLES))
def test_every_svg_is_rendered_from_its_cast(name: str) -> None:
    """AC6 — jedes SVG ist die Ausgabe des Renderers, nicht handgemalt."""
    cast_path, svg_path, _ = _TRIPLES[name]
    assert svg_path.exists(), f"{name}: SVG fehlt: {svg_path.relative_to(REPO_ROOT)}"
    expected = render_quickstart_svg.render_svg(_read(cast_path))
    assert _read(svg_path) == expected, (
        f"{name}: {svg_path.relative_to(REPO_ROOT)} weicht vom gerenderten Cast ab. "
        f"Neu erzeugen: uv run python scripts/dev/render_quickstart_svg.py "
        f"--cast {cast_path.relative_to(REPO_ROOT)} --out {svg_path.relative_to(REPO_ROOT)}"
    )


# ---------------------------------------------------------------------------
# AC5 — kein zweites Renderer-Skript
# ---------------------------------------------------------------------------


def test_no_second_render_script_exists() -> None:
    """Alle drei Cast/SVG-Paare laufen ueber denselben Renderer, keine Kopie."""
    dev_dir = REPO_ROOT / "scripts" / "dev"
    offenders = []
    for path in sorted(dev_dir.glob("*.py")):
        if path.name == "render_quickstart_svg.py":
            continue
        text = _read(path)
        if "def render_svg(" in text or "def parse_cast(" in text:
            offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert not offenders, f"Zweite Renderer-Fassung gefunden: {offenders}"


# ---------------------------------------------------------------------------
# AC7 — keine Verweise auf fehlende Assets
# ---------------------------------------------------------------------------


def test_no_dangling_asset_references() -> None:
    """Jeder in der Doku genannte docs/assets/-Pfad existiert wirklich."""
    missing = []
    for doc in D.doc_surface():
        if not doc.exists():
            continue
        text = _read(doc)
        for m in ASSET_REF_RE.finditer(text):
            ref = m.group(0)
            if not (REPO_ROOT / ref).exists():
                line = text[: m.start()].count("\n") + 1
                missing.append(f"{doc.relative_to(REPO_ROOT)}:{line}: {ref}")
    assert not missing, f"Verweise auf fehlende Assets: {missing}"
