"""Akzeptanz-Guards fuer Issue #451 — README-Relaunch: Schaufenster statt Textwueste.

Jeder Test bildet ein Akzeptanzkriterium aus dem Issue ab:

AC1  Auf der ersten Bildschirmseite steht, was das Plugin tut, fuer wen es ist
     und wodurch es sich unterscheidet — vor den Warnbloecken.
AC2  Die README zeigt eine visuelle Demonstration eines echten Durchlaufs.
AC3  Der Quickstart fuehrt bis zum ersten Suchergebnis und zeigt, wie Erfolg
     aussieht.
AC4  Die Voraussetzungstabelle nennt Node.js und die Modell-Downloadgroesse und
     trennt Pflicht sauber von Optional.
AC5  Jede Zahlenangabe stimmt mit dem Code ueberein (Browser-Module, Quellen,
     Score-Dimensionen, Python-Mindestversion).
AC6  Kein Abschnitt dupliziert Referenzmaterial aus ``docs/``.

Die Zahlen-Guards haengen bewusst an der jeweiligen Code-Quelle (``commands/``,
``pyproject.toml``, ``academic_vault/``), nicht an einer zweiten Doku-Stelle —
sonst driften beide gemeinsam ab.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from scripts.dev import render_quickstart_svg

from tests.helpers import docs as D

REPO_ROOT = D.REPO_ROOT

#: Proxy fuer "erste Bildschirmseite" — so viele Zeilen sieht man ohne Scrollen.
FIRST_SCREEN_LINES = 40

DEMO_CAST = D.DOCS_DIR / "assets" / "quickstart.cast"
DEMO_SVG = D.DOCS_DIR / "assets" / "quickstart.svg"

QUICKSTART_START = "<!-- QUICKSTART-START -->"
QUICKSTART_END = "<!-- QUICKSTART-END -->"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _readme() -> str:
    return _read(D.README)


def _normalize(text: str) -> str:
    """Whitespace einebnen — Doku bricht Befehle ueber Zeilen um, Casts nicht."""
    return re.sub(r"\s+", " ", text).strip()


def _quickstart_block() -> str:
    text = _readme()
    assert QUICKSTART_START in text and QUICKSTART_END in text, (
        "README markiert den Quickstart nicht mit den bekannten Markern."
    )
    return text.split(QUICKSTART_START, 1)[1].split(QUICKSTART_END, 1)[0]


# ---------------------------------------------------------------------------
# AC1 — Positionierung auf der ersten Bildschirmseite
# ---------------------------------------------------------------------------


def _first_line_matching(pattern: str) -> int:
    """1-basierte Zeilennummer des ersten Treffers, sonst -1."""
    for i, line in enumerate(_readme().splitlines(), 1):
        if re.search(pattern, line, re.I):
            return i
    return -1


#: (Bezeichnung, Suchmuster) der drei Aussagen, die oben stehen muessen.
POSITIONING_CLAIMS = {
    "was": r"Claude-Code-Plugin",
    "fuer wen": r"Studierende",
    "unterschied": r"Modellged(ae|ä)chtnis",
}


@pytest.mark.parametrize("claim", sorted(POSITIONING_CLAIMS))
def test_first_screen_states_positioning(claim: str) -> None:
    """Was / fuer wen / wodurch anders steht auf der ersten Bildschirmseite."""
    line = _first_line_matching(POSITIONING_CLAIMS[claim])
    assert line != -1, f"README sagt nirgends '{claim}' ({POSITIONING_CLAIMS[claim]})."
    assert line <= FIRST_SCREEN_LINES, (
        f"'{claim}' steht erst in Zeile {line}, muss aber in den ersten "
        f"{FIRST_SCREEN_LINES} Zeilen stehen."
    )


@pytest.mark.parametrize("claim", sorted(POSITIONING_CLAIMS))
def test_positioning_precedes_the_warning_blocks(claim: str) -> None:
    """Die Positionierung steht vor Zitat-Warnung und SciHub-Block.

    Die Warnbloecke bleiben unveraendert erhalten — sie duerfen nur nicht das
    Erste sein, was ein Interessent liest.
    """
    warning = _first_line_matching(r"\[!WARNING\]")
    scihub = _first_line_matching(r"SCIHUB-DISCLAIMER-BLOCK")
    assert warning != -1, "Zitat-Warnblock fehlt in der README."
    assert scihub != -1, "SciHub-Disclaimer fehlt in der README."

    line = _first_line_matching(POSITIONING_CLAIMS[claim])
    assert 0 < line < warning, f"'{claim}' (Zeile {line}) steht hinter dem Warnblock ({warning})."
    assert line < scihub, f"'{claim}' (Zeile {line}) steht hinter dem SciHub-Block ({scihub})."


# ---------------------------------------------------------------------------
# AC2 — visuelle Demonstration eines echten Durchlaufs
# ---------------------------------------------------------------------------


def test_readme_embeds_the_demo_asset() -> None:
    """Die README bettet die Demo als Bild ein, nicht bloss als Link."""
    assert DEMO_SVG.exists(), f"Demo-Asset fehlt: {DEMO_SVG.relative_to(REPO_ROOT)}"
    assert re.search(r"!\[[^\]]*\]\(docs/assets/quickstart\.svg\)", _readme()), (
        "README bettet docs/assets/quickstart.svg nicht als Bild ein."
    )


def _cast_events() -> list[list]:
    lines = [ln for ln in _read(DEMO_CAST).splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines[1:]]


def test_demo_cast_is_valid_asciicast_v2() -> None:
    """Die Quelle der Demo ist ein abspielbarer asciicast-v2-Mitschnitt."""
    assert DEMO_CAST.exists(), f"Demo-Quelle fehlt: {DEMO_CAST.relative_to(REPO_ROOT)}"
    lines = [ln for ln in _read(DEMO_CAST).splitlines() if ln.strip()]
    header = json.loads(lines[0])
    assert header["version"] == 2, f"asciicast-Version {header['version']}, erwartet 2."
    assert header["width"] > 0 and header["height"] > 0, "Cast ohne Terminalgeometrie."

    events = _cast_events()
    outputs = [e for e in events if e[1] == "o"]
    assert len(outputs) >= 5, f"Nur {len(outputs)} Ausgabeframes — das ist keine Demonstration."
    times = [e[0] for e in events]
    assert times == sorted(times), "Cast-Zeitstempel laufen nicht monoton."
    assert times[-1] > 0, "Cast hat keine Laufzeit."


def _cast_command_lines() -> list[str]:
    """Alle im Cast getippten Befehlszeilen (Prompt ``$ `` abgeschnitten)."""
    text = "".join(e[2] for e in _cast_events() if e[1] == "o")
    text = ANSI_RE.sub("", text).replace("\r\n", "\n")
    return [ln[2:].strip() for ln in text.split("\n") if ln.startswith("$ ")]


def test_demo_commands_are_covered_by_the_protocol() -> None:
    """Jeder Befehl der Demo steht im Protokoll des realen Durchlaufs.

    Anti-Fake-Kopplung: die Demo darf nichts zeigen, was nie gelaufen ist.
    """
    commands = _cast_command_lines()
    assert len(commands) >= 5, f"Demo zeigt nur {len(commands)} Befehle."
    protocol = _normalize(_read(D.QUICKSTART_PROTOCOL_DOC))
    missing = [c for c in commands if _normalize(c) not in protocol]
    assert not missing, f"Demo zeigt Befehle, die nicht im Protokoll belegt sind: {missing}"


def test_demo_svg_is_rendered_from_the_cast() -> None:
    """Das eingebettete SVG ist die Ausgabe des Renderers, nicht handgemalt."""
    expected = render_quickstart_svg.render_svg(_read(DEMO_CAST))
    assert _read(DEMO_SVG) == expected, (
        "docs/assets/quickstart.svg weicht vom gerenderten Cast ab. "
        "Neu erzeugen: uv run python scripts/dev/render_quickstart_svg.py"
    )


def test_demo_is_linked_from_the_protocol() -> None:
    """Das Protokoll weist aus, wie die Demo entstanden ist."""
    text = _read(D.QUICKSTART_PROTOCOL_DOC)
    assert "assets/quickstart.cast" in text, (
        "Protokoll dokumentiert die Herkunft des Demo-Casts nicht."
    )


# ---------------------------------------------------------------------------
# AC3 — Quickstart fuehrt bis zum ersten Suchergebnis
# ---------------------------------------------------------------------------


def test_quickstart_shows_what_a_search_result_looks_like() -> None:
    """Der Quickstart zeigt die reale Erfolgsausgabe der ersten Suche.

    Ohne sie kann ein Erstnutzer Erfolg nicht von Fehlschlag unterscheiden.
    """
    block = _quickstart_block()
    assert "/academic-research:search" in block, "Quickstart ruft die Suche nicht auf."
    m = re.search(r"Found \d+ papers", block)
    assert m, "Quickstart zeigt keine Ausgabe der Suche — nur den Aufruf."
    assert m.group(0) in _read(D.QUICKSTART_PROTOCOL_DOC), (
        f"Die gezeigte Suchausgabe '{m.group(0)}' steht nicht im Protokoll."
    )


# ---------------------------------------------------------------------------
# AC4 — Voraussetzungstabelle
# ---------------------------------------------------------------------------


def _prerequisite_rows() -> list[list[str]]:
    """Zellen der Voraussetzungstabelle vor dem ersten Befehl des Quickstarts."""
    block = _quickstart_block()
    first_fence = block.find("```")
    assert first_fence != -1, "Quickstart enthaelt keinen Befehlsblock."
    preamble = block[:first_fence]
    rows = []
    for line in preamble.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
            continue
        rows.append(cells)
    return rows


def test_prerequisites_table_exists_before_the_first_command() -> None:
    """Die Voraussetzungen stehen als Tabelle, nicht als Fliesstext-Halbsatz."""
    rows = _prerequisite_rows()
    assert len(rows) >= 5, (
        f"Voraussetzungstabelle hat nur {len(rows)} Zeilen (inkl. Kopf) — zu duenn."
    )


@pytest.mark.parametrize(
    "component", ["Claude Code", "Python 3.11+", "Node.js", "Git", "multilingual-e5-small"]
)
def test_prerequisites_table_names_component(component: str) -> None:
    """Jede tragende Voraussetzung steht in der Tabelle."""
    joined = "\n".join(" | ".join(row) for row in _prerequisite_rows())
    assert component in joined, f"Voraussetzungstabelle nennt '{component}' nicht."


def test_prerequisites_table_separates_mandatory_from_optional() -> None:
    """Pflicht und Optional sind in einer eigenen Spalte auseinandergehalten."""
    rows = _prerequisite_rows()
    body = rows[1:]
    mandatory = [r for r in body if any(c.startswith("Pflicht") for c in r)]
    optional = [r for r in body if any(c.startswith("Optional") for c in r)]
    assert len(mandatory) >= 4, f"Nur {len(mandatory)} als Pflicht markierte Zeilen."
    assert optional, "Keine als Optional markierte Zeile — die Trennung fehlt."


def test_node_requirement_is_backed_by_the_hook_wiring() -> None:
    """Node.js steht nur deshalb in der Tabelle, weil hooks.json ``node`` aufruft."""
    hooks = json.dumps(json.loads(_read(REPO_ROOT / "hooks" / "hooks.json")))
    assert re.search(r"node \$\{CLAUDE_PLUGIN_ROOT\}/hooks/[a-z-]+\.mjs", hooks), (
        "Vorbedingung geaendert: hooks.json ruft keine node-Hooks mehr auf — "
        "dann gehoert Node.js auch nicht mehr in die Voraussetzungstabelle."
    )
    joined = "\n".join(" | ".join(row) for row in _prerequisite_rows())
    assert "Node.js" in joined, "hooks.json braucht node, die Tabelle verschweigt es."


def _model_download_size_mb() -> int:
    """Groessenangabe aus der Code-Quelle (academic_vault/embedding_model.py)."""
    src = _read(REPO_ROOT / "academic_vault" / "embedding_model.py")
    m = re.search(r"~(\d+)\s*MB", src)
    assert m, "academic_vault/embedding_model.py nennt keine Modellgroesse."
    return int(m.group(1))


def test_model_download_size_matches_the_code_comment() -> None:
    """Jede Modellgroessen-Angabe in der Doku stimmt mit der Code-Quelle ueberein."""
    expected = _model_download_size_mb()
    wrong: list[str] = []
    for doc in D.doc_surface():
        if not doc.exists():
            continue
        text = _read(doc)
        for m in re.finditer(r"~?(\d+)\s*MB", text):
            context = text[max(0, m.start() - 200) : m.end() + 200]
            if "Modell" not in context and "e5-small" not in context:
                continue  # andere MB-Angabe (z. B. Log-Rotation)
            if int(m.group(1)) != expected:
                line = text[: m.start()].count("\n") + 1
                wrong.append(f"{doc.relative_to(REPO_ROOT)}:{line}: {m.group(0)} != ~{expected} MB")
    assert not wrong, f"Modell-Downloadgroesse driftet: {wrong}"


# ---------------------------------------------------------------------------
# AC5 — Zahlenangaben stimmen mit dem Code ueberein
# ---------------------------------------------------------------------------


def _browser_module_names() -> list[str]:
    """Browser-Module aus der massgeblichen Reihenfolge in commands/search.md."""
    text = _read(REPO_ROOT / "commands" / "search.md")
    m = re.search(r"F(?:ue|ü)r jedes Browser-Modul in fester Reihenfolge:\n(.*?)\n\n", text, re.S)
    assert m, "Reihenfolge der Browser-Module in commands/search.md nicht gefunden."
    return re.findall(r"`([a-z_]+)`", m.group(1))


def _api_module_names() -> list[str]:
    """API-Module aus dem MODULES-Dispatch in scripts/search.py."""
    src = _read(REPO_ROOT / "scripts" / "search.py")
    m = re.search(r"^MODULES\s*[:=][^{]*\{(.*?)^\}", src, re.S | re.M)
    assert m, "MODULES-Dispatch in scripts/search.py nicht gefunden."
    return re.findall(r'^\s*"([a-z_]+)":', m.group(1), re.M)


def _score_dimension_count() -> int:
    """Zeilen der 5D-Gewichtstabelle in commands/score.md."""
    text = _read(REPO_ROOT / "commands" / "score.md")
    m = re.search(r"\|\s*Dimension\s*\|.*?\n(.*?)\n\n", text, re.S)
    assert m, "Gewichtstabelle in commands/score.md nicht gefunden."
    rows = [
        ln
        for ln in m.group(1).splitlines()
        if ln.strip().startswith("|") and not re.fullmatch(r"\|[-|: ]+\|", ln.strip())
    ]
    return len(rows)


#: Zahlwort -> Wert, damit auch ausgeschriebene Zahlen gepruefte Zahlen sind.
GERMAN_NUMERALS = {
    "drei": 3,
    "vier": 4,
    "fünf": 5,
    "sechs": 6,
    "sieben": 7,
    "acht": 8,
    "neun": 9,
    "zehn": 10,
}

_NUM = r"\d+|" + "|".join(GERMAN_NUMERALS)

COUNT_CLAIMS = {
    "Browser-Module": (
        [rf"({_NUM})\s+Browser-Module"],
        lambda: len(_browser_module_names()),
    ),
    "Suchquellen": (
        [rf"({_NUM})\s+Quellen\b", rf"Suchquellen\s*\(({_NUM})\)"],
        lambda: len(_api_module_names()) + len(_browser_module_names()),
    ),
    "Score-Dimensionen": (
        [
            rf"({_NUM})D-(?:Score|Scoring|bewertet|Relevanz|Dimension)",
            rf"(?:auf|nach|in)\s+({_NUM})\s+Dimensionen",
        ],
        _score_dimension_count,
    ),
}


def _as_int(token: str) -> int:
    return int(token) if token.isdigit() else GERMAN_NUMERALS[token.lower()]


@pytest.mark.parametrize("label", sorted(COUNT_CLAIMS))
def test_count_claims_match_the_code(label: str) -> None:
    """Jede Zahl in der Nutzerdoku ist gegen ihre Code-Quelle gedeckt."""
    patterns, actual_fn = COUNT_CLAIMS[label]
    actual = actual_fn()
    wrong: list[str] = []
    for doc in D.doc_surface():
        if not doc.exists():
            continue
        text = _read(doc)
        for pattern in patterns:
            for m in re.finditer(pattern, text, re.I):
                if _as_int(m.group(1)) != actual:
                    line = text[: m.start()].count("\n") + 1
                    wrong.append(f"{doc.relative_to(REPO_ROOT)}:{line}: '{m.group(0)}' != {actual}")
    assert not wrong, f"{label}: Doku-Zahlen weichen vom Code-Stand ({actual}) ab: {wrong}"


def test_python_version_claim_matches_pyproject() -> None:
    """Die in der Doku genannte Python-Mindestversion steht so in pyproject.toml."""
    pyproject = _read(REPO_ROOT / "pyproject.toml")
    m = re.search(r'requires-python\s*=\s*">=\s*([0-9]+\.[0-9]+)"', pyproject)
    assert m, "requires-python in pyproject.toml nicht gefunden."
    minimum = m.group(1)
    wrong: list[str] = []
    for doc in D.doc_surface():
        if not doc.exists():
            continue
        text = _read(doc)
        for hit in re.finditer(r"Python\s*([0-9]+\.[0-9]+)\+", text):
            if hit.group(1) != minimum:
                line = text[: hit.start()].count("\n") + 1
                wrong.append(f"{doc.relative_to(REPO_ROOT)}:{line}: {hit.group(0)} != {minimum}+")
    assert not wrong, f"Python-Versionsangaben weichen von requires-python ab: {wrong}"


# ---------------------------------------------------------------------------
# AC6 — keine Duplikate aus docs/
# ---------------------------------------------------------------------------


def test_readme_does_not_list_mcp_tool_names() -> None:
    """MCP-Toolnamen gehoeren in docs/reference/vault.md, nicht ins Schaufenster."""
    hits = re.findall(r"vault\.[a-z_]+\s*\(", _readme())
    assert not hits, f"README nennt MCP-Toolnamen statt zu verlinken: {sorted(set(hits))}"


def test_readme_does_not_duplicate_reference_blocks() -> None:
    """Kein Block von >=3 Zeilen steht wortgleich in einem docs/reference-Dokument."""
    readme_lines = [ln.rstrip() for ln in _readme().splitlines()]
    reference_texts = {
        doc: _read(doc) for doc in sorted(D.REFERENCE_DIR.glob("*.md")) if doc.exists()
    }
    duplicates: list[str] = []
    window = 3
    for i in range(len(readme_lines) - window + 1):
        chunk = readme_lines[i : i + window]
        if sum(1 for ln in chunk if ln.strip()) < window:
            continue
        needle = "\n".join(chunk)
        for doc, text in reference_texts.items():
            if needle in text:
                duplicates.append(f"README:{i + 1}-{i + window} == {doc.relative_to(REPO_ROOT)}")
                break
    assert not duplicates, f"README dupliziert Referenzmaterial statt zu verlinken: {duplicates}"
