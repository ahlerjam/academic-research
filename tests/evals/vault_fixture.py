"""Test-Vault fuer das ``vault``-Sitzungsprofil der Verhaltens-Evals (Issue #824).

Issue #830 lieferte die vier Achsen (``cwd``/``allowed_tools``/``mcp_config``/
``env``) und die Profiltabelle; die Fixture-Seite des ``vault``-Profils blieb
ausdruecklich offen (docs/evals/STRATEGY.md, Abschnitt "Sitzungsprofile").
Dieses Modul liefert sie:

1. **Seeder** -- baut in einem Wegwerf-Verzeichnis eine frische
   ``vault.db`` per ``VaultDB``/``init_schema()`` und legt darin genau die
   Papers und Quotes an, auf die sich ``evals/quote-extractor/evals.json``
   und ``evals/chapter-writer/evals.json`` beziehen.
2. **PDF-Fixtures** -- zu jedem Paper ein minimales PDF-1.4 mit echtem
   Text-Layer (stdlib-only, Muster ``tests/fixtures/verbatim/create_fixtures.py``),
   damit der fail-closed-Verbatim-Pfad von ``vault.add_quote``
   (``extraction_method="local-verbatim"``, Issue #512) ueberhaupt bestehen
   kann. Die PDFs liegen im selben Wegwerf-Verzeichnis, das als ``cwd`` der
   CLI-Sitzung dient -- der Agent liest sie ueber den ``pdf_path`` aus
   ``vault.get_paper`` mit dem nativen ``Read``-Tool.
3. **MCP-Config** -- genau ein Server (``academic-vault``), gestartet als
   ``sys.executable -m academic_vault.server`` mit ``PYTHONPATH`` auf den
   Repo-Root und ``VAULT_DB_PATH`` auf die Wegwerf-Datenbank. Identisch zum
   Weg, der sich in ``scripts/eval/measure_context_enrichment_710.py``
   ueber 12 Live-Sitzungen bewaehrt hat
   (``docs/evals/2026-08-09-context-enrichment-710.md``).

Bewusst **kein** Zugriff auf die Operator-Vault: ``VAULT_DB_PATH`` steht nur
im ``env``-Block der MCP-Config (der Serverprozess erbt es beim Start), die
Prozessumgebung von pytest bleibt unangetastet. ``default_db_path()``
(``academic_vault/db.py``) gibt ``VAULT_DB_PATH`` Vorrang -- ohne die Variable
laege die DB unter ``~/.academic-research/...``, also in echten Forschungsdaten.

Die PDFs werden zur Laufzeit erzeugt statt als Binaerdateien eingecheckt:
so kann eine Aenderung an den Seed-Quotes nicht von einem veralteten PDF
still ausgehebelt werden (der Verbatim-Check laeuft gegen genau den Text,
der auch in der DB steht).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Servername in der MCP-Config -- bestimmt das Tool-Praefix
#: ``mcp__academic-vault__*`` in ``SESSION_PROFILES["vault"]``.
MCP_SERVER_NAME = "academic-vault"

#: Dateiname der MCP-Config im Wegwerf-Verzeichnis.
MCP_CONFIG_FILENAME = "mcp_config.json"

#: Dateiname der Wegwerf-Vault im selben Verzeichnis.
VAULT_DB_FILENAME = "vault.db"


# ---------------------------------------------------------------------------
# Seed-Daten
# ---------------------------------------------------------------------------
#
# Eine Quelle fuer beides: den in-memory ``MockVault`` (tests/evals/conftest.py)
# und die echte Wegwerf-Vault dieses Moduls. Vorher lagen die Fake-Papers nur
# im MockVault -- ein Live-Fall haette dort andere Daten gesehen als der
# Mock-Test daneben.
#
# ``_seed_quotes`` sind zugleich die Zeilen des erzeugten PDFs: was in der DB
# steht, steht wortgleich im Text-Layer. Damit besteht ein Zitat aus dem
# Seed-Bestand die serverseitige Verbatim-Pruefung.
SEED_PAPERS: dict[str, dict[str, Any]] = {
    "devops2022": {
        "paper_id": "devops2022",
        "title": "DevOps Governance Frameworks",
        "doi": "10.1109/MS.2022.1234567",
        "pdf_path": "/fake/devops2022.pdf",
        "pdf_name": "devops2022.pdf",
        "authors": [{"family": "Schneider", "given": "Anna"}],
        "year": 2022,
        "container_title": "IEEE Software",
        "has_text_layer": True,
        "_seed_quotes": [
            {
                "verbatim": "Governance frameworks ensure DevOps compliance across distributed teams.",
                "pdf_page": 1,
                "section": "Introduction",
            },
            {
                "verbatim": "Policy definition and shared accountability are central to DevOps governance.",
                "pdf_page": 1,
                "section": "Results",
            },
        ],
        "pdf_extra_lines": [
            "Audit trails make DevOps governance decisions reviewable after each release.",
        ],
    },
    "zerotrust2024": {
        "paper_id": "zerotrust2024",
        "title": "Zero Trust Networks",
        "doi": "10.1109/MS.2024.9876543",
        "pdf_path": "/fake/zerotrust2024.pdf",
        "pdf_name": "zerotrust2024.pdf",
        "authors": [{"family": "Okafor", "given": "Daniel"}],
        "year": 2024,
        "container_title": "IEEE Software",
        "has_text_layer": True,
        "_seed_quotes": [
            {
                "verbatim": "Zero trust assumes no implicit trust in any access request.",
                "pdf_page": 1,
                "section": "Abstract",
            },
        ],
        "pdf_extra_lines": [
            "Every zero trust request is authenticated, authorized and continuously verified.",
        ],
    },
    "mlops_scan_only": {
        "paper_id": "mlops_scan_only",
        "title": "Machine Learning Ops",
        "doi": None,
        "pdf_path": "/fake/mlops_scan.pdf",
        "pdf_name": "mlops_scan.pdf",
        "authors": [{"family": "Iversen", "given": "Lena"}],
        "year": 2023,
        "container_title": "Journal of Systems and Software",
        # Scan ohne Text-Layer: pypdf liefert leeren String -- der Fall, den
        # qe-03 misst (extraction_quality failed/low statt erfundener Zitate).
        "has_text_layer": False,
        "_seed_quotes": [],
        "pdf_extra_lines": [],
    },
    "agile2023": {
        "paper_id": "agile2023",
        "title": "Agile at Scale",
        "doi": "10.1109/MS.2023.1122334",
        "pdf_path": "/fake/agile2023.pdf",
        "pdf_name": "agile2023.pdf",
        "authors": [{"family": "Berg", "given": "Sofia"}],
        "year": 2023,
        "container_title": "IEEE Software",
        "has_text_layer": True,
        "_seed_quotes": [
            {
                "verbatim": "Scaled agile frameworks coordinate multiple teams through quarterly planning.",
                "pdf_page": 1,
                "section": "Introduction",
            },
        ],
        "pdf_extra_lines": [],
    },
    "quantum2021": {
        "paper_id": "quantum2021",
        "title": "Quantum Computing",
        "doi": None,
        "pdf_path": "/fake/quantum2021.pdf",
        "pdf_name": "quantum2021.pdf",
        "authors": [{"family": "Novak", "given": "Petr"}],
        "year": 2021,
        "container_title": "Physics Reports",
        # Text-Layer vorhanden, aber thematisch fremd: qe-05 fragt nach
        # Post-Quantum-Kryptografie und muss LEER zurueckkommen statt zu
        # halluzinieren. Der Text darf deshalb keinen Kryptografie-Bezug haben.
        "has_text_layer": True,
        "_seed_quotes": [
            {
                "verbatim": "Lorem ipsum dolor sit amet.",
                "pdf_page": 1,
                "section": "Body",
            },
        ],
        "pdf_extra_lines": [
            "Consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore.",
        ],
    },
    "mayring2022": {
        "paper_id": "mayring2022",
        "title": "Qualitative Inhaltsanalyse nach Mayring",
        "doi": None,
        "pdf_path": "/fake/mayring2022.pdf",
        "pdf_name": "mayring2022.pdf",
        "authors": [{"family": "Mayring", "given": "Philipp"}],
        "year": 2022,
        "container_title": "Beltz",
        "has_text_layer": True,
        "_seed_quotes": [
            {
                "verbatim": "Qualitative Inhaltsanalyse ermoeglicht systematische Textinterpretation.",
                "pdf_page": 1,
                "section": "Methode",
            },
        ],
        "pdf_extra_lines": [],
    },
    "smith2023": {
        "paper_id": "smith2023",
        "title": "DevOps Governance",
        "doi": "10.1109/MS.2023.1234567",
        "pdf_path": "/fake/smith2023.pdf",
        "pdf_name": "smith2023.pdf",
        "authors": [{"family": "Smith", "given": "Jordan"}],
        "year": 2023,
        "container_title": "IEEE Software",
        "has_text_layer": True,
        "_seed_quotes": [
            {
                "verbatim": "Smith (2023) zeigt, dass DevOps Governance Incidents signifikant reduziert.",
                "pdf_page": 1,
                "section": "Results",
            },
        ],
        "pdf_extra_lines": [],
    },
    "mueller2021": {
        "paper_id": "mueller2021",
        "title": "Agile Entscheidungsfindung",
        "doi": "10.1109/MS.2021.7654321",
        "pdf_path": "/fake/mueller2021.pdf",
        "pdf_name": "mueller2021.pdf",
        "authors": [{"family": "Mueller", "given": "Katrin"}],
        "year": 2021,
        "container_title": "IEEE Software",
        "has_text_layer": True,
        "_seed_quotes": [
            {
                "verbatim": "Mueller (2021) beschreibt agile Entscheidungsprozesse in verteilten Teams.",
                "pdf_page": 1,
                "section": "Discussion",
            },
        ],
        "pdf_extra_lines": [],
    },
    "tanaka2024": {
        "paper_id": "tanaka2024",
        "title": "Machine Learning Ops",
        "doi": None,
        "pdf_path": "/fake/tanaka2024.pdf",
        "pdf_name": "tanaka2024.pdf",
        "authors": [{"family": "Tanaka", "given": "Hiro"}],
        "year": 2024,
        "container_title": "Journal of Systems and Software",
        "has_text_layer": True,
        "_seed_quotes": [
            {
                "verbatim": "Tanaka (2024) definiert MLOps als Disziplin zur Produktivierung von ML-Modellen.",
                "pdf_page": 1,
                "section": "Introduction",
            },
        ],
        "pdf_extra_lines": [],
    },
}


# ---------------------------------------------------------------------------
# Minimaler PDF-1.4-Writer (stdlib-only)
# ---------------------------------------------------------------------------
#
# Muster: tests/fixtures/verbatim/create_fixtures.py (Issue #511) bzw.
# tests/fixtures/fulltext/create_fixtures.py (Issue #373) -- bewusst ohne
# reportlab, damit die Evals keine zusaetzliche Abhaengigkeit bekommen.
# Hier reicht reines ASCII: eine /ToUnicode-CMap ist nicht noetig, weil die
# Seed-Texte keine Ligaturen oder typografischen Anfuehrungszeichen enthalten.


def _escape_literal(line: str) -> bytes:
    """Encodet eine Zeile als Body eines PDF-Literal-Strings.

    Nicht-ASCII wird verlustfrei ausgeschlossen: die Seed-Texte sind bewusst
    ASCII (``ermoeglicht`` statt ``ermöglicht``), weil ein Type1-Helvetica
    ohne eigene Encoding-Tabelle sonst andere Zeichen zurueckliefern wuerde,
    als in der DB stehen -- und der Verbatim-Check exakt vergleicht.
    """
    out = bytearray()
    for ch in line:
        if not (0x20 <= ord(ch) <= 0x7E):
            raise ValueError(
                f"Seed-Text enthaelt Nicht-ASCII {ch!r} -- der PDF-Fixture-Writer "
                f"kann das nicht verlustfrei abbilden: {line!r}"
            )
        if ch in ("\\", "(", ")"):
            out += f"\\{ch}".encode("ascii")
        else:
            out += ch.encode("ascii")
    return bytes(out)


def _content_stream(lines: list[str]) -> bytes:
    parts = [b"BT", b"/F1 12 Tf", b"14 TL", b"72 720 Td"]
    for line in lines:
        parts.append(b"(" + _escape_literal(line) + b") Tj")
        parts.append(b"T*")
    parts.append(b"ET")
    return b"\n".join(parts)


def build_pdf(pages: list[list[str]]) -> bytes:
    """Baut ein minimales PDF mit einer Textseite je Eintrag in ``pages``.

    Eine leere Zeilenliste erzeugt eine Seite ohne Text-Layer
    (Scan-Simulation) -- ``pypdf`` liefert dort einen leeren String.
    """
    page_count = len(pages)
    first_page_obj = 4
    page_obj_ids = [first_page_obj + 2 * i for i in range(page_count)]

    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            "<< /Type /Pages /Kids ["
            + " ".join(f"{oid} 0 R" for oid in page_obj_ids)
            + f"] /Count {page_count} >>"
        ).encode("latin-1"),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }

    for index, lines in enumerate(pages):
        page_id = page_obj_ids[index]
        contents_id = page_id + 1
        objects[page_id] = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {contents_id} 0 R >>"
        ).encode("latin-1")
        stream = _content_stream(lines)
        objects[contents_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for obj_id in sorted(objects):
        offsets[obj_id] = len(out)
        out += f"{obj_id} 0 obj\n".encode("latin-1")
        out += objects[obj_id]
        out += b"\nendobj\n"

    xref_offset = len(out)
    max_id = max(objects)
    out += f"xref\n0 {max_id + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for obj_id in range(1, max_id + 1):
        out += f"{offsets[obj_id]:010d} 00000 n \n".encode("latin-1")
    out += f"trailer\n<< /Size {max_id + 1} /Root 1 0 R >>\n".encode("latin-1")
    out += f"startxref\n{xref_offset}\n%%EOF\n".encode("latin-1")
    return bytes(out)


def paper_pdf_lines(paper: dict[str, Any]) -> list[str]:
    """Textzeilen des Fixture-PDFs zu einem Seed-Paper.

    Zeile 1 ist der Papertitel -- ``agents/quote-extractor.md`` setzt
    ``possible_pdf_mismatch: true`` (und blockiert dann die Persistenz), wenn
    weniger als drei Titelwoerter mit mindestens vier Zeichen in den ersten
    200 Zeichen des PDFs stehen.
    """
    lines = [paper["title"]]
    lines += [q["verbatim"] for q in paper["_seed_quotes"]]
    lines += list(paper.get("pdf_extra_lines", []))
    return lines


def build_paper_pdf(paper: dict[str, Any]) -> bytes:
    """PDF-Bytes zu einem Seed-Paper (leere Seite, wenn kein Text-Layer)."""
    if not paper["has_text_layer"]:
        return build_pdf([[]])
    return build_pdf([paper_pdf_lines(paper)])


# ---------------------------------------------------------------------------
# Seeder + MCP-Config
# ---------------------------------------------------------------------------


def csl_json(paper: dict[str, Any]) -> str:
    """CSL-JSON eines Seed-Papers (Autor + Jahr, damit APA7-Zitate moeglich sind).

    ``chapter-writer`` soll laut ``cw-01``/``cw-04`` ``(Smith, 2023)`` bzw.
    ``Mueller`` ausgeben -- ohne Autor/Jahr in den Vault-Metadaten koennte der
    Skill das nur raten.
    """
    return json.dumps(
        {
            "id": paper["paper_id"],
            "type": "article-journal",
            "title": paper["title"],
            "author": [{"family": a["family"], "given": a["given"]} for a in paper["authors"]],
            "issued": {"date-parts": [[paper["year"]]]},
            "container-title": paper["container_title"],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def seed_vault(db_path: Path, pdf_dir: Path) -> Path:
    """Legt eine frische Wegwerf-Vault an und schreibt die Fixture-PDFs daneben.

    Args:
        db_path: Zielpfad der SQLite-Datei (wird angelegt, nicht wiederverwendet).
        pdf_dir: Verzeichnis fuer die PDF-Fixtures -- in der Regel dasselbe
            Wegwerf-Verzeichnis, das als ``cwd`` der CLI-Sitzung dient.

    Returns:
        Den ``db_path``, damit Aufrufer verketten koennen.
    """
    from academic_vault.db import VaultDB

    pdf_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    db = VaultDB(str(db_path))
    db.init_schema()

    for paper in SEED_PAPERS.values():
        pdf_path = pdf_dir / paper["pdf_name"]
        pdf_path.write_bytes(build_paper_pdf(paper))
        db.add_paper(
            paper_id=paper["paper_id"],
            csl_json=csl_json(paper),
            doi=paper["doi"],
            pdf_path=str(pdf_path),
        )
        for index, quote in enumerate(paper["_seed_quotes"]):
            db.add_quote(
                quote_id=f"seed-{paper['paper_id']}-{index}",
                paper_id=paper["paper_id"],
                verbatim=quote["verbatim"],
                extraction_method="manual",
                pdf_page=quote["pdf_page"],
                section=quote["section"],
            )
    return db_path


def write_mcp_config(db_path: Path, config_dir: Path) -> Path:
    """Schreibt eine MCP-Config mit genau einem Server (``academic-vault``).

    ``VAULT_DB_PATH`` steht ausschliesslich im ``env``-Block dieser Config --
    der Serverprozess erbt es beim Start. Die Prozessumgebung von pytest bleibt
    unberuehrt; ``subprocess.run(env=...)`` wird bewusst NICHT genutzt, weil das
    ``PATH``/``HOME``/``CLAUDE_CODE_OAUTH_TOKEN`` aus der Sitzung entfernen und
    den ganzen Lauf reissen wuerde.
    """
    config = {
        "mcpServers": {
            MCP_SERVER_NAME: {
                "command": sys.executable,
                "args": ["-m", "academic_vault.server"],
                "env": {
                    "PYTHONPATH": str(REPO_ROOT),
                    "VAULT_DB_PATH": str(db_path),
                },
            }
        }
    }
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / MCP_CONFIG_FILENAME
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


@dataclass(frozen=True)
class VaultSession:
    """Alles, was eine ``vault``-Profil-Sitzung braucht.

    ``root`` ist zugleich das ``cwd`` der CLI-Sitzung: Datenbank, MCP-Config
    und die Fixture-PDFs liegen darin, damit der Agent das PDF ueber einen
    Pfad innerhalb seines Arbeitsverzeichnisses liest (statt ueber einen
    absoluten Pfad ausserhalb, der eine Freigabefrage ausloesen wuerde).
    """

    root: Path
    db_path: Path
    mcp_config_path: Path


def build_vault_session(root: Path) -> VaultSession:
    """Baut eine vollstaendige Wegwerf-Vault-Sitzung unter ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / VAULT_DB_FILENAME
    seed_vault(db_path, root)
    mcp_config_path = write_mcp_config(db_path, root)
    return VaultSession(root=root, db_path=db_path, mcp_config_path=mcp_config_path)
