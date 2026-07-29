"""Tests fuer word-export (Issue #446).

TDD-First: Diese Tests decken die reinen Python-Funktionen aus
skills/word-export/scripts/collect_references.py ab -- die geteilte
Bibliografie-Auswahl mit latex-export, die Zitationsstil-Aufloesung aus den
citation-extraction-Referenzdateien, und die \\cite{}-Marker-Aufloesung fuer
den docx-Pfad. Der eigentliche docx-Rendering-Schritt laeuft ueber den
externen Skill `document-skills:docx` und ist nicht CI-fahrbar (analog zu
xlsx, siehe tests/test_issue_445_xlsx_devendored.py-Docstring) -- dafuer
prueft tests/test_word_export_skill_md.py die dokumentierten Formatvorlagen-
Pflichten strukturell, und tests/test_word_export_docx_render.py fuehrt
collect_references()/resolve_cite_markers() einmal wirklich gegen ein
tatsaechlich gerendertes (Test-only-)Dokument aus (Fixrunde PR #488).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).parent.parent
SCRIPTS_DIR = WORKTREE / "skills" / "word-export" / "scripts"
LATEX_SCRIPTS_DIR = WORKTREE / "skills" / "latex-export" / "scripts"
CITATION_REFERENCES_DIR = WORKTREE / "skills" / "citation-extraction" / "references"
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "word_export"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(LATEX_SCRIPTS_DIR))


# ---------------------------------------------------------------------------
# Import / geteilte Bibliografie-Auswahl (Plan-Risiko #2)
# ---------------------------------------------------------------------------


class TestSharedPaperSelection:
    def test_import(self):
        import collect_references

        assert collect_references

    def test_get_all_papers_is_reexport_of_build_bib(self):
        """collect_references.get_all_papers MUSS build_bib.get_all_papers sein.

        Ein eigenstaendiger Nachbau statt Import wuerde AC3 (Entrymengen-
        Paritaet) lautlos bei kuenftigen Vault-Aenderungen brechen (Plan-
        Risiko #2) -- der Test prueft Objekt-Identitaet, nicht nur Verhalten.
        """
        import build_bib
        import collect_references

        assert collect_references.get_all_papers is build_bib.get_all_papers


# ---------------------------------------------------------------------------
# AC2/AC3 — Reference-Count-Paritaet docx <-> LaTeX ueber denselben Vault
# ---------------------------------------------------------------------------


class TestReferenceCountParity:
    def test_reference_count_parity_with_latex_bib(self, tmp_path):
        """Gleicher Vault -> gleiche Anzahl Eintraege in .bib und collect_references()."""
        from academic_vault.db import VaultDB
        from academic_vault.server import add_paper
        from build_bib import build_bib_from_vault
        from collect_references import collect_references

        db_path = str(tmp_path / "vault.db")
        db = VaultDB(db_path)
        db.init_schema()
        for i in range(3):
            add_paper(
                db_path=db_path,
                paper_id=f"paper-{i}",
                csl_json=json.dumps(
                    {
                        "title": f"Paper {i}",
                        "type": "article-journal",
                        "author": [{"family": f"Autor{i}", "given": "X"}],
                        "issued": {"date-parts": [[2020 + i]]},
                    }
                ),
            )

        bib_path = tmp_path / "refs.bib"
        build_bib_from_vault(db_path, str(bib_path))
        bib_entry_count = len(re.findall(r"^@", bib_path.read_text(encoding="utf-8"), re.MULTILINE))

        academic_context_text = (FIXTURES_DIR / "academic_context_default.md").read_text()
        result = collect_references(db_path, academic_context_text, CITATION_REFERENCES_DIR)

        assert len(result["papers"]) == bib_entry_count == 3

    def test_reference_count_parity_empty_vault(self, tmp_path):
        from academic_vault.db import VaultDB
        from build_bib import build_bib_from_vault
        from collect_references import collect_references

        db_path = str(tmp_path / "empty_vault.db")
        db = VaultDB(db_path)
        db.init_schema()

        bib_path = tmp_path / "refs.bib"
        build_bib_from_vault(db_path, str(bib_path))
        bib_content = bib_path.read_text(encoding="utf-8")

        academic_context_text = (FIXTURES_DIR / "academic_context_default.md").read_text()
        result = collect_references(db_path, academic_context_text, CITATION_REFERENCES_DIR)

        assert bib_content == ""
        assert result["papers"] == []

    def test_payload_without_explicit_db_uses_canonical_vault_resolver(self, tmp_path, monkeypatch):
        """AC3: ohne --vault-db greift derselbe Aufloeser wie im .bib-Pfad.

        Fixrunde PR #488: commands/word.md uebergab ``$VAULT_DB_PATH`` -- eine
        Variable, die im Command nirgends gesetzt wurde. Damit landete ein
        leerer Pfad in der Vault-Query und die Entrymengen-Garantie docx<->LaTeX
        war nie hergestellt. Jetzt faellt das Skript auf
        ``academic_vault.db.default_db_path()`` zurueck -- exakt die Quelle, die
        ``latex-export/scripts/export_thesis.py`` fuer die .bib nutzt (#190).
        """
        from academic_vault.db import VaultDB, default_db_path
        from academic_vault.server import add_paper
        from build_bib import get_all_papers
        from collect_references import build_payload

        db_path = tmp_path / "vault.db"
        monkeypatch.setenv("VAULT_DB_PATH", str(db_path))
        assert default_db_path() == str(db_path)

        db = VaultDB(str(db_path))
        db.init_schema()
        add_paper(
            db_path=str(db_path),
            paper_id="smith2023",
            csl_json=json.dumps(
                {
                    "title": "DevOps Governance",
                    "type": "article-journal",
                    "author": [{"family": "Smith", "given": "John"}],
                    "issued": {"date-parts": [[2023]]},
                }
            ),
        )

        kapitel_dir = tmp_path / "kapitel"
        kapitel_dir.mkdir()
        (kapitel_dir / "1-einleitung.md").write_text("# Einleitung\n\nText.\n", encoding="utf-8")

        payload = build_payload(
            selector="all",
            kapitel_dir=kapitel_dir,
            academic_context_path=FIXTURES_DIR / "academic_context_default.md",
            references_dir=CITATION_REFERENCES_DIR,
        )

        assert payload["vault_db_path"] == default_db_path()
        assert [p["paper_id"] for p in payload["papers"]] == [
            p["paper_id"] for p in get_all_papers(str(db_path))
        ]


# ---------------------------------------------------------------------------
# AC2 — Zitationsstil-Regeln stammen aus citation-extraction/references/*.md
# ---------------------------------------------------------------------------


class TestStyleRulesFromReferenceFile:
    def test_style_rules_loaded_from_reference_file(self):
        from collect_references import load_style_rules, resolve_citation_style

        text = (FIXTURES_DIR / "academic_context_harvard.md").read_text()
        style_file = resolve_citation_style(text)
        assert style_file == "harvard.md"

        rules = load_style_rules(style_file, CITATION_REFERENCES_DIR)
        expected = (CITATION_REFERENCES_DIR / "harvard.md").read_text(encoding="utf-8")
        assert rules == expected, "Stilregeln muessen wortgleich aus der Referenzdatei stammen."

    def test_default_style_is_apa_when_todo_or_missing(self):
        from collect_references import resolve_citation_style

        text = (FIXTURES_DIR / "academic_context_default.md").read_text()
        assert resolve_citation_style(text) == "apa.md"
        assert resolve_citation_style("") == "apa.md"
        assert resolve_citation_style("keine Zitationsstil-Zeile hier") == "apa.md"

    def test_unknown_style_falls_back_to_default(self):
        from collect_references import resolve_citation_style

        text = "- Zitationsstil: Voellig-Unbekannt-3000"
        assert resolve_citation_style(text) == "apa.md"

    def test_style_rules_not_hardcoded_in_module(self):
        """collect_references.py selbst darf keine Stilregel-Strings enthalten (AC2)."""
        source = (SCRIPTS_DIR / "collect_references.py").read_text(encoding="utf-8")
        # Ein paar charakteristische APA-Regel-Fragmente aus apa.md duerfen NICHT
        # im Python-Modul auftauchen -- sonst waeren die Regeln dort dupliziert.
        apa_text = (CITATION_REFERENCES_DIR / "apa.md").read_text(encoding="utf-8")
        telltale = "Nachname, Initiale. (Jahr)."
        assert telltale in apa_text  # Testannahme absichern
        assert telltale not in source

    def test_missing_style_file_raises_clear_error(self, tmp_path):
        from collect_references import StyleRulesNotFoundError, load_style_rules

        with pytest.raises(StyleRulesNotFoundError, match="fehlt"):
            load_style_rules("does-not-exist.md", tmp_path)


# ---------------------------------------------------------------------------
# Review-Fund (PR #488, flowkit-Runde): parse_context_fields() filterte nur
# "[...]"-Platzhalter, nicht das real ausgelieferte "TODO"-Format aus
# scripts/bootstrap/academic_context.stub.md -- Titelblatt zeigte woertlich
# "TODO (Default: Leibniz FH Hannover)" statt "[bitte ergaenzen]".
# ---------------------------------------------------------------------------


class TestParseContextFieldsTodoPlaceholder:
    def test_todo_values_are_filtered_like_bracket_placeholders(self):
        from collect_references import parse_context_fields

        text = (
            "- Universität: TODO (Default: Leibniz FH Hannover)\n"
            "- Studiengang: TODO\n"
            "- Thema: Reale Abschlussarbeit\n"
        )
        fields = parse_context_fields(text)
        assert "Universität" not in fields
        assert "Studiengang" not in fields
        assert fields["Thema"] == "Reale Abschlussarbeit"

    def test_bootstrap_stub_yields_no_todo_context_fields(self):
        """Die tatsaechlich ausgelieferte Vorlage (scripts/bootstrap/
        academic_context.stub.md) hat fuer alle Titelblatt-Felder nur "TODO"
        stehen -- parse_context_fields() darf keinen dieser Werte durchreichen.

        `humanizer_de` ist absichtlich kein TODO-Feld in der Vorlage und bleibt
        deshalb zurecht erhalten (kein Titelblatt-Feld, siehe render_docx.py
        _TITLE_PAGE_FIELDS) -- dieser Test prueft gezielt die TODO-Felder.
        """
        from collect_references import parse_context_fields

        stub_path = WORKTREE / "scripts" / "bootstrap" / "academic_context.stub.md"
        text = stub_path.read_text(encoding="utf-8")
        fields = parse_context_fields(text)
        todo_keys = {"Universität", "Studiengang", "Zitationsstil", "Sprache", "Typ", "Thema"}
        leaked = todo_keys & fields.keys()
        assert not leaked, f"TODO-Platzhalter haetten gefiltert werden muessen, blieb: {leaked}"

    def test_bootstrap_stub_renders_bitte_ergaenzen_not_todo_on_title_page(self, tmp_path):
        """End-to-End (Recommendation aus dem Review-Fund): unausgefuellte
        Bootstrap-Vorlage -> build_payload() -> render_docx() -> Titelblatt zeigt
        den dokumentierten Platzhalter, nicht das rohe TODO-Wort."""
        docx = pytest.importorskip("docx", reason="python-docx nicht installiert (uv sync)")
        from academic_vault.db import VaultDB
        from collect_references import build_payload
        from render_docx import render_docx

        db_path = tmp_path / "vault.db"
        VaultDB(str(db_path)).init_schema()

        kapitel_dir = tmp_path / "kapitel"
        kapitel_dir.mkdir()
        (kapitel_dir / "1-einleitung.md").write_text("# Einleitung\n\nText.\n", encoding="utf-8")

        stub_path = WORKTREE / "scripts" / "bootstrap" / "academic_context.stub.md"

        payload = build_payload(
            selector="all",
            kapitel_dir=kapitel_dir,
            academic_context_path=stub_path,
            references_dir=CITATION_REFERENCES_DIR,
            vault_db_path=str(db_path),
        )
        assert (
            not {"Universität", "Studiengang", "Zitationsstil", "Sprache", "Typ", "Thema"}
            & payload["context"].keys()
        )

        out_path = tmp_path / "export.docx"
        render_docx(payload, out_path)

        reopened = docx.Document(str(out_path))
        body_texts = [p.text for p in reopened.paragraphs]
        joined = "\n".join(body_texts)
        assert "TODO" not in joined, f"Rohes TODO auf dem Titelblatt gelandet:\n{joined}"
        assert "[bitte ergaenzen]" in joined


# ---------------------------------------------------------------------------
# Plan-Risiko #1 — \\cite{key}-Marker-Aufloesung fuer den docx-Pfad
# ---------------------------------------------------------------------------


class TestCiteMarkerResolution:
    PAPERS = [
        {
            "paper_id": "smith2023",
            "csl_json": json.dumps(
                {
                    "author": [{"family": "Smith", "given": "John"}],
                    "issued": {"date-parts": [[2023]]},
                }
            ),
        },
        {
            "paper_id": "jones2022",
            "csl_json": json.dumps(
                {
                    "author": [
                        {"family": "Jones", "given": "Anna"},
                        {"family": "Lee", "given": "Kim"},
                    ],
                    "issued": {"date-parts": [[2022]]},
                }
            ),
        },
    ]

    def test_resolves_simple_cite_marker(self):
        from collect_references import resolve_cite_markers

        result = resolve_cite_markers(r"Belegt durch \cite{smith2023}.", self.PAPERS)
        assert result == "Belegt durch (Smith 2023)."
        assert "\\cite" not in result

    def test_resolves_multi_author_cite_marker(self):
        from collect_references import resolve_cite_markers

        result = resolve_cite_markers(r"Siehe \cite{jones2022}.", self.PAPERS)
        assert result == "Siehe (Jones et al. 2022)."

    def test_resolves_citep_with_locator(self):
        from collect_references import resolve_cite_markers

        result = resolve_cite_markers(r"Beleg \citep[S. 12]{smith2023}.", self.PAPERS)
        assert result == "Beleg (Smith 2023)."

    def test_unknown_key_becomes_visible_placeholder(self):
        from collect_references import resolve_cite_markers

        result = resolve_cite_markers(r"Unbekannt \cite{ghost2099}.", self.PAPERS)
        assert result == "Unbekannt (? ghost2099)."
        assert "\\cite" not in result

    # -- Mehrfachzitate: \cite{a,b} ist gueltiges BibTeX/biblatex und kommt in
    # kapitel/*.md (Issue #386) real vor. Vor der Fixrunde wurde die komplette
    # Key-Liste als EIN Key nachgeschlagen -> "(? smith2023,jones2022)", also
    # ein sichtbar kaputter Platzhalter, obwohl beide Keys im Vault stehen.

    def test_resolves_multi_key_cite_marker(self):
        from collect_references import resolve_cite_markers

        result = resolve_cite_markers(r"Beide \cite{smith2023,jones2022}.", self.PAPERS)
        assert result == "Beide (Smith 2023; Jones et al. 2022)."
        assert "?" not in result

    def test_resolves_multi_key_cite_marker_with_whitespace(self):
        from collect_references import resolve_cite_markers

        result = resolve_cite_markers(r"Beide \citep{smith2023, jones2022}.", self.PAPERS)
        assert result == "Beide (Smith 2023; Jones et al. 2022)."

    def test_multi_key_cite_marks_only_the_unknown_key(self):
        from collect_references import resolve_cite_markers

        result = resolve_cite_markers(r"Gemischt \cite{smith2023,ghost2099}.", self.PAPERS)
        assert result == "Gemischt (Smith 2023; ? ghost2099)."

    def test_multi_key_cite_keeps_key_order_and_drops_empty_entries(self):
        from collect_references import resolve_cite_markers

        result = resolve_cite_markers(r"\cite{jones2022,,smith2023}", self.PAPERS)
        assert result == "(Jones et al. 2022; Smith 2023)"

    def test_fixture_chapter_has_no_raw_cite_after_resolution(self):
        from collect_references import resolve_cite_markers

        text = (FIXTURES_DIR / "kapitel_with_cite.md").read_text(encoding="utf-8")
        result = resolve_cite_markers(text, self.PAPERS)
        assert "\\cite" not in result
        assert "\\citep" not in result
        assert "(Smith 2023)" in result
        assert "(Jones et al. 2022)" in result

    def test_text_without_markers_is_unchanged(self):
        from collect_references import resolve_cite_markers

        text = "Ganz normaler Text ohne Marker."
        assert resolve_cite_markers(text, self.PAPERS) == text
