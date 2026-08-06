"""Akzeptanz-Guards fuer Issue #641 — keine toten Verweise in der Doku.

Das Issue hat zwei Haelften. Die kleinere ist die Loeschung von
``docs/superpowers/``; die groessere ist dieser Guard: Jeder relative
Markdown-Link in README, ``AGENTS.md`` und ``docs/`` zeigt auf eine Datei, die
es wirklich gibt.

Vorher pruefte ``tests/test_cross_references.py`` ausschliesslich
Title-Case-Skillnamen in Prosa — kein einziger Test hielt ein Linkziel gegen das
Dateisystem. Eine geloeschte oder umbenannte Seite riss die Verweise darauf
stillschweigend, und gemerkt hat es der Leser.

AC3 des Issues verlangt ausdruecklich, den Guard gegen einen kuenstlich
eingefuegten toten Link gegenzupruefen. ``test_dead_link_is_detected`` tut genau
das: Es legt eine Wegwerf-Seite mit kaputtem Ziel an und besteht darauf, dass die
Pruef-Funktion sie meldet. Ohne diesen Meta-Test waere nicht belegt, dass der
Guard ueberhaupt etwas faengt.

Grenze (bewusst benannt): Geprueft werden relative Ziele im Repo. Externe URLs
bleiben aussen vor — die haengen am Netz und wuerden die Suite unzuverlaessig
machen.
"""

import re
from pathlib import Path

import pytest

from tests.helpers import docs as D

REPO_ROOT = D.REPO_ROOT

#: Markdown-Links ``[Text](ziel)`` samt optionalem Titel — dieselbe Form, die
#: auch ``tests/test_issue_461_practice_guide.py`` liest.
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

#: Ziele, die kein Repo-Pfad sind und darum nicht gegen das Dateisystem gehen.
_EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "#", "tel:")


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def link_sources() -> list[Path]:
    """Die Dateien, deren Links der Guard prueft: README, AGENTS.md, docs/.

    Quelle ist ``git ls-files`` (ueber ``tests.helpers.docs``), inklusive noch
    nicht committeter Seiten — eine gerade angelegte Doku faellt damit sofort
    unter den Guard und nicht erst in CI.
    """
    roots = [REPO_ROOT / "README.md", REPO_ROOT / "AGENTS.md"]
    pages = [p for p in roots if p.exists()]
    pages += [p for p in D.repo_docs() if p.suffix == ".md"]
    return sorted(set(pages))


def dead_links(page: Path) -> list[str]:
    """Alle relativen Linkziele einer Seite, die auf nichts zeigen.

    Anker (``datei.md#abschnitt``) werden am ``#`` abgeschnitten: Geprueft wird
    die Datei, nicht die Ueberschrift. Ein reiner Anker (``#abschnitt``) zeigt
    auf die Seite selbst und ist kein Dateiverweis.
    """
    text = page.read_text(encoding="utf-8")
    missing = []
    for target in _LINK_RE.findall(text):
        if target.startswith(_EXTERNAL_PREFIXES):
            continue
        path_part = target.split("#", 1)[0]
        if not path_part:
            continue
        if not (page.parent / path_part).exists():
            missing.append(target)
    return missing


@pytest.mark.parametrize(
    "page", link_sources(), ids=lambda p: p.relative_to(D.REPO_ROOT).as_posix()
)
def test_no_dead_relative_links(page: Path) -> None:
    """Jeder relative Verweis zeigt auf eine existierende Datei (AC3/AC4)."""
    missing = dead_links(page)
    assert not missing, (
        f"{_rel(page)}: Verweise ins Leere: {missing} — eine geloeschte oder "
        "umbenannte Seite reisst ihre Verweise mit; repariert wird der Verweis, "
        "nicht der Guard."
    )


def test_link_sources_cover_readme_agents_and_docs() -> None:
    """Vorbedingung: Der Guard schaut wirklich auf alle drei Orte (AC3).

    Ohne diese Zusicherung koennte ``link_sources()`` still auf eine leere Liste
    schrumpfen — parametrisierte Tests ueber eine leere Liste sind gruen, ohne
    etwas geprueft zu haben.
    """
    sources = {_rel(p) for p in link_sources()}
    assert "README.md" in sources
    assert "AGENTS.md" in sources
    assert sum(1 for s in sources if s.startswith("docs/")) >= 20, (
        f"Nur {sum(1 for s in sources if s.startswith('docs/'))} Doku-Seiten erfasst."
    )


def test_dead_link_is_detected(tmp_path: Path) -> None:
    """Gegenprobe: Ein kuenstlich eingefuegter toter Link wird gemeldet (AC3).

    Das ist der Beweis, dass der Guard faengt und nicht nur gruen leuchtet.
    """
    page = tmp_path / "seite.md"
    page.write_text(
        "# Testseite\n\n"
        "[existiert](seite.md)\n"
        "[existiert nicht](gibt-es-nicht.md)\n"
        "[Anker](seite.md#abschnitt)\n"
        "[extern](https://example.org/fehlt.md)\n",
        encoding="utf-8",
    )
    assert dead_links(page) == ["gibt-es-nicht.md"]
