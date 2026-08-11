"""Regressionstests fuer den Code-Review-Fund #5 und #10 (db.py).

#5: ``_sanitize_fts5_query`` (geteilt von ``server.search_papers()`` und
``VaultDB.search_notes()``) entfernte nur ``-^/*():"`` aus der Query, liess
aber ``. , ? ' ! % ; = [ @ # & | ~ \\ < >`` unangetastet -- alles Zeichen,
die in einem FTS5-Bareword einen Syntaxfehler ausloesen. Verifiziert war das
u.a. an ``"Was ist DevOps-Governance?"`` (-> Fehler bei ``?``), ``"Web 2.0"``
(-> Fehler bei ``.``), ``"Governance, Praxis"`` (-> Fehler bei ``,``) und
``"it's governance"`` (-> Fehler bei ``'``). Fix: die Query wird in
Wort-Tokens zerlegt statt Zeichen aus einer Blacklist zu entfernen --
dadurch ist sie fuer beliebigen User-Input syntaktisch immer gueltig.

#5-Nachtrag (Review-Runde 2): der erste Fix quotete das GANZE
Whitespace-Token (``DevOps-Governance`` -> ``"DevOps-Governance"``). Ein
FTS5-Stringliteral mit mehreren Tokens ist aber eine PHRASE mit
Adjazenz-Zwang -- die Query fand danach nur noch Dokumente, in denen die
Woerter unmittelbar hintereinander stehen. Treffer wie ``Governance von
DevOps in KMU`` (bei der alten, crashenden Blacklist noch gefunden, weil sie
den Bindestrich zu Whitespace machte) fielen weg, ``Mueller/Schmidt`` fand
``Schmidt und Mueller`` nicht mehr, und im Trigram-Zweig wurde aus
``Governance, Praxis`` ein Pflicht-Substring inklusive Komma. Der korrigierte
Fix zerlegt an Satzzeichen in Wort-Tokens (implizites UND, gleiches Recall
wie vor #841) und laesst die #196-Schutzwirkung intakt, weil jedes
operatorwirksame Zeichen (``:``, ``*``, ``(``, ``)``, ``^``, ``"``) beim
Zerlegen verschwindet.

#10 (db-Teil): ``set_page_offset``, ``update_pdf_path``, ``set_ocr_done`` und
``update_retraction_checked_at`` riefen ``_raise_if_locked()`` nicht auf --
ein per ``vault.lock_passport`` gesperrter Vault akzeptierte damit weiterhin
Schreiboperationen, die zitierte Seitenzahlen gegen den bereits
hash-versiegelten Passport verschieben (Issue #380/#407). Zusaetzlich fehlte
bei allen vieren die Rowcount-Pruefung: ein nicht existierendes ``paper_id``
liess die Methode still "erfolgreich" durchlaufen, ohne dass irgendetwas
geschrieben wurde.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from academic_vault.db import VaultDB, VaultLockedError, _sanitize_fts5_query


@pytest.fixture
def vault(tmp_path: Path) -> VaultDB:
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    return db


def _add_paper(db: VaultDB, paper_id: str = "mueller2021") -> None:
    csl = json.dumps(
        {
            "type": "article-journal",
            "title": "Governance-Studie",
            "author": [{"family": "Mueller", "given": "Petra"}],
            "issued": {"date-parts": [[2021]]},
        }
    )
    db.add_paper(paper_id, csl)


# ---------------------------------------------------------------------------
# Finding 5 -- _sanitize_fts5_query muss fuer JEDEN Input FTS5-syntaktisch
# gueltig bleiben (keine Blacklist-Luecken mehr).
# ---------------------------------------------------------------------------


class TestSanitizeFts5Query:
    @pytest.mark.parametrize(
        "raw",
        [
            "Was ist DevOps-Governance?",
            "Web 2.0",
            "Governance, Praxis",
            "it's governance",
            "Führung und Ökonomie",  # Umlaute muessen erhalten bleiben
            "Preis: 5% Rabatt!",
            "a; b = c [d] @e #f & g | h ~ i \\ j < k > l",
            '"quoted" (parens) *star* -dash-',
        ],
    )
    def test_produces_syntactically_valid_fts5_query(self, raw: str) -> None:
        """Jede sanitisierte Query muss sich als FTS5 MATCH-Argument nutzen
        lassen, ohne ``sqlite3.OperationalError: fts5: syntax error`` --
        unabhaengig davon, ob echte Treffer existieren."""
        sanitized = _sanitize_fts5_query(raw)
        assert sanitized, f"Sanitierung ergab leeren String fuer {raw!r}"

        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE t USING fts5(body)")
            conn.execute("INSERT INTO t(body) VALUES ('governance devops fuehrung 2 0')")
            # Wirft NICHT sqlite3.OperationalError -- das ist der eigentliche Test.
            conn.execute("SELECT * FROM t WHERE t MATCH ?", (sanitized,)).fetchall()
        finally:
            conn.close()

    def test_umlauts_still_match(self) -> None:
        """Umlaute duerfen durch die Sanitierung nicht kaputtgehen (Fund
        verlangt explizit, dass deutsche Umlaute weiter funktionieren)."""
        sanitized = _sanitize_fts5_query("Führung")
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE t USING fts5(body)")
            conn.execute("INSERT INTO t(body) VALUES ('Führung und Kontrolle')")
            rows = conn.execute("SELECT * FROM t WHERE t MATCH ?", (sanitized,)).fetchall()
            assert rows, "Umlaut-Suche liefert keinen Treffer mehr nach Sanitierung"
        finally:
            conn.close()

    def test_empty_input_yields_empty_string(self) -> None:
        assert _sanitize_fts5_query("") == ""
        assert _sanitize_fts5_query("   ") == ""

    def test_only_punctuation_yields_empty_string(self) -> None:
        """Eine Query, die nur aus Satzzeichen besteht, enthaelt kein
        Wort-Token mehr -- das Ergebnis ist leer und die Aufrufer brechen
        VOR dem MATCH ab (Muster Issue #369), statt einen FTS5-Syntaxfehler
        auszuloesen."""
        assert _sanitize_fts5_query("???!!!") == ""

    def test_operator_keywords_still_neutralized(self) -> None:
        """Grossgeschriebene NEAR/AND/OR/NOT bleiben weiterhin unwirksam
        (Bestandsverhalten aus Issue #462) -- Kleinschreibung bleibt Suchwort."""
        sanitized = _sanitize_fts5_query("governance AND android")
        # "AND" (Operator) verschwindet, "android" (Kleinschreibung) bleibt
        # als literaler Suchbegriff erhalten.
        assert "android" in sanitized.lower()
        assert '"AND"' not in sanitized


def _fts5_hit_rowids(sanitized: str, corpus: list[str], tokenize: str = "") -> list[int]:
    """Fuehrt ``sanitized`` real gegen eine In-Memory-FTS5-Tabelle aus.

    Gibt die rowids der Treffer zurueck (1-basiert in Reihenfolge von
    ``corpus``). Ein ``sqlite3.OperationalError`` schlaegt hier durch -- damit
    prueft jeder Aufrufer zugleich die Syntax-Gueltigkeit (Fund 5) und die
    tatsaechliche Trefferwirkung (Regression + #196).
    """
    conn = sqlite3.connect(":memory:")
    try:
        opts = f", tokenize='{tokenize}'" if tokenize else ""
        conn.execute(f"CREATE VIRTUAL TABLE t USING fts5(body{opts})")
        conn.executemany("INSERT INTO t(body) VALUES (?)", [(doc,) for doc in corpus])
        rows = conn.execute("SELECT rowid FROM t WHERE t MATCH ?", (sanitized,)).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


class TestSanitizeFts5QueryKeepsRecall:
    """Regression zu Fund 5: das Quoten ganzer Tokens erzeugte FTS5-PHRASEN
    mit Adjazenz-Zwang und warf damit Treffer weg, die die alte (crashende)
    Blacklist noch fand. Alle Faelle laufen real gegen FTS5."""

    def test_hyphen_query_matches_both_word_orders(self) -> None:
        """``DevOps-Governance`` muss beide Dokumente finden (implizites UND),
        nicht nur das mit der woertlichen Wortfolge."""
        corpus = ["Governance von DevOps in KMU", "DevOps Governance Modell"]
        hits = _fts5_hit_rowids(_sanitize_fts5_query("DevOps-Governance"), corpus)
        assert hits == [1, 2], (
            "Bindestrich-Query darf keine Phrase erzwingen -- 'Governance von "
            "DevOps in KMU' muss weiterhin gefunden werden"
        )

    def test_slash_query_matches_reordered_authors(self) -> None:
        """``Mueller/Schmidt`` findet ein Paper mit 'Schmidt und Mueller'."""
        corpus = ["Ein Beitrag von Schmidt und Mueller", "Ganz anderes Thema"]
        hits = _fts5_hit_rowids(_sanitize_fts5_query("Mueller/Schmidt"), corpus)
        assert hits == [1]

    def test_comma_query_does_not_require_the_comma(self) -> None:
        """``Governance, Praxis`` darf das Komma nicht zum Pflichtbestandteil
        machen -- im Trigram-Zweig war das Komma sonst Pflicht-Substring."""
        sanitized = _sanitize_fts5_query("Governance, Praxis")
        assert "," not in sanitized
        corpus = ["Praxis der Governance im Mittelstand"]
        assert _fts5_hit_rowids(sanitized, corpus) == [1]
        # Trigram-Tokenizer (der Zweig aus Issue #703) sieht dasselbe:
        assert _fts5_hit_rowids(sanitized, corpus, tokenize="trigram") == [1]

    def test_parens_and_colon_do_not_force_adjacency(self) -> None:
        """Auch Klammern und Doppelpunkt trennen nur, sie binden nicht."""
        sanitized = _sanitize_fts5_query("(Governance):Reifegrad")
        corpus = ["Reifegrad und Governance getrennt betrachtet"]
        assert _fts5_hit_rowids(sanitized, corpus) == [1]

    def test_short_barewords_stay_unquoted(self) -> None:
        """Bareword-sichere Tokens bleiben unquotiert -- ``server.
        _trigram_match_expression()`` misst die Tokenlaenge der sanitisierten
        Query (Issue #703 AK5); ein gequotetes ``"KMU"`` waere zwei Zeichen
        laenger und wuerde die 4-Zeichen-Schwelle falsch ueberspringen."""
        assert _sanitize_fts5_query("KMU Governance") == "KMU Governance"
        assert _sanitize_fts5_query("KMU-Governance") == "KMU Governance"

    def test_umlauts_survive_tokenisation(self) -> None:
        """Unicode-Woerter duerfen beim Zerlegen nicht zerbrechen."""
        assert _sanitize_fts5_query("Führung/Größe-Maßstab") == "Führung Größe Maßstab"
        corpus = ["Maßstab der Größe bei der Führung"]
        assert _fts5_hit_rowids(_sanitize_fts5_query("Führung/Größe-Maßstab"), corpus) == [1]


class TestSanitizeFts5QueryKeepsIssue196Protection:
    """Die Schutzabsicht aus #196 muss trotz Recall-Fix erhalten bleiben:
    kein FTS5-Operator darf durchgereicht werden."""

    def test_column_filter_is_not_an_operator(self) -> None:
        """``title:foo`` darf nicht als Spaltenfilter wirken."""
        sanitized = _sanitize_fts5_query("body:foo")
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE t USING fts5(title, body)")
            conn.execute("INSERT INTO t(title, body) VALUES ('nichts', 'foo')")
            rows = conn.execute("SELECT rowid FROM t WHERE t MATCH ?", (sanitized,)).fetchall()
        finally:
            conn.close()
        assert rows == [], (
            "Doppelpunkt darf nicht als Spaltenfilter wirken -- die Zeile "
            "enthaelt kein Wort 'body', der Treffer waere reine Operator-Wirkung"
        )

    def test_prefix_star_is_not_an_operator(self) -> None:
        """``Govern*`` darf keine Praefix-Suche ausloesen."""
        sanitized = _sanitize_fts5_query("Govern*")
        assert "*" not in sanitized
        assert _fts5_hit_rowids(sanitized, ["Governance im Mittelstand"]) == []

    def test_not_operator_does_not_exclude(self) -> None:
        """``NOT`` darf kein Ausschluss-Operator bleiben (Bestand seit #462)."""
        sanitized = _sanitize_fts5_query("Governance NOT DevOps")
        corpus = ["Governance und DevOps zusammen", "Nur Governance allein"]
        assert _fts5_hit_rowids(sanitized, corpus) == [1], (
            "NOT muss verschwinden; uebrig bleibt das implizite UND aus 'Governance DevOps'"
        )

    def test_or_operator_does_not_widen(self) -> None:
        """``OR`` darf die Query nicht aufweiten."""
        sanitized = _sanitize_fts5_query("Governance OR DevOps")
        corpus = ["Governance und DevOps zusammen", "Nur Governance allein"]
        assert _fts5_hit_rowids(sanitized, corpus) == [1]

    def test_near_and_caret_are_not_operators(self) -> None:
        """``NEAR(...)`` und der Spaltenanfangs-Operator ``^`` wirken nicht.

        Der NEAR-Abstandsparameter ``2`` bleibt wie schon vor #841 als
        literaler Suchbegriff uebrig -- er ist nach dem Entfernen des
        Keywords blosser User-Text, keine Syntax mehr."""
        sanitized = _sanitize_fts5_query("NEAR(Governance DevOps, 2) ^Modell")
        assert "^" not in sanitized and "(" not in sanitized
        assert _fts5_hit_rowids(sanitized, ["Modell 2 fuer DevOps und Governance"]) == [1]

    @pytest.mark.parametrize(
        "hostile",
        [
            '" OR 1=1 --',
            "NEAR(a b, 3) AND (c OR d) NOT e^ f*",
            "col:*^\"()-/ ',.;",
            "a" * 200 + "-" + "b" * 200,
            "😀 emoji-token",
        ],
    )
    def test_hostile_input_never_raises(self, hostile: str) -> None:
        """Fund 5 bleibt behoben: beliebige feindliche Eingabe erzeugt nie
        mehr ``sqlite3.OperationalError``."""
        _fts5_hit_rowids(_sanitize_fts5_query(hostile), ["irgendein text"])


class TestSearchNotesSpecialChars:
    """End-to-End ueber VaultDB.search_notes -- derselbe Fund, db.py:1532."""

    def _add_note(self, db: VaultDB, paper_id: str, text: str) -> str:
        return db.add_note(paper_id, text)

    @pytest.mark.parametrize(
        "query",
        [
            "Was ist DevOps-Governance?",
            "Web 2.0",
            "Governance, Praxis",
            "it's governance",
        ],
    )
    def test_search_notes_does_not_raise_on_punctuation(self, vault: VaultDB, query: str) -> None:
        _add_paper(vault)
        self._add_note(vault, "mueller2021", "Ein Exzerpt ueber Governance-Fragen.")
        # Vorher: sqlite3.OperationalError: fts5: syntax error near "..."
        result = vault.search_notes(query)
        assert isinstance(result, list)

    def test_search_notes_hyphen_query_still_finds_reordered_note(self, vault: VaultDB) -> None:
        """Regression: ``DevOps-Governance`` darf keine Phrase erzwingen --
        eine Notiz mit 'Governance von DevOps' muss weiterhin auftauchen."""
        _add_paper(vault)
        note_id = self._add_note(vault, "mueller2021", "Governance von DevOps in KMU.")
        result = vault.search_notes("DevOps-Governance")
        assert any(r["note_id"] == note_id for r in result), (
            "search_notes verliert bindestrichhaltige Anfragen -- der Nutzer "
            "haelt die Quelle faelschlich fuer nicht erfasst"
        )

    def test_search_notes_punctuation_only_returns_empty(self, vault: VaultDB) -> None:
        """Rein satzzeichenhaltige Query: leeres Ergebnis, kein Crash."""
        _add_paper(vault)
        self._add_note(vault, "mueller2021", "Governance-Fragen.")
        assert vault.search_notes("???!!!") == []

    def test_search_notes_umlauts_find_hit(self, vault: VaultDB) -> None:
        _add_paper(vault)
        note_id = self._add_note(vault, "mueller2021", "Führung braucht klare Prozesse.")
        result = vault.search_notes("Führung")
        assert any(r["note_id"] == note_id for r in result)


# ---------------------------------------------------------------------------
# Finding 10 (db-Teil) -- Lock-Gate + Rowcount-Ehrlichkeit fuer
# set_page_offset, update_pdf_path, set_ocr_done, update_retraction_checked_at
# ---------------------------------------------------------------------------


class TestPapersWriteMethodsRespectLock:
    def test_set_page_offset_raises_when_locked(self, vault: VaultDB) -> None:
        _add_paper(vault)
        vault.lock_vault("projekt")
        with pytest.raises(VaultLockedError):
            vault.set_page_offset("mueller2021", 12)
        # Beweis, dass NICHTS geschrieben wurde (kein stilles Teil-Update):
        assert vault.get_page_offset("mueller2021") == 0

    def test_update_pdf_path_raises_when_locked(self, vault: VaultDB) -> None:
        _add_paper(vault)
        vault.lock_vault("projekt")
        with pytest.raises(VaultLockedError):
            vault.update_pdf_path("mueller2021", "/neu/pfad.pdf")

    def test_set_ocr_done_raises_when_locked(self, vault: VaultDB) -> None:
        _add_paper(vault)
        vault.lock_vault("projekt")
        with pytest.raises(VaultLockedError):
            vault.set_ocr_done("mueller2021", 1)

    def test_update_retraction_checked_at_raises_when_locked(self, vault: VaultDB) -> None:
        _add_paper(vault)
        vault.lock_vault("projekt")
        with pytest.raises(VaultLockedError):
            vault.update_retraction_checked_at("mueller2021", 123456)


class TestPapersWriteMethodsReportMissingPaper:
    def test_set_page_offset_missing_paper_raises(self, vault: VaultDB) -> None:
        with pytest.raises(ValueError, match="nicht gefunden"):
            vault.set_page_offset("does-not-exist", 5)

    def test_update_pdf_path_missing_paper_raises(self, vault: VaultDB) -> None:
        with pytest.raises(ValueError, match="nicht gefunden"):
            vault.update_pdf_path("does-not-exist", "/x.pdf")

    def test_set_ocr_done_missing_paper_raises(self, vault: VaultDB) -> None:
        with pytest.raises(ValueError, match="nicht gefunden"):
            vault.set_ocr_done("does-not-exist", 1)

    def test_update_retraction_checked_at_missing_paper_raises(self, vault: VaultDB) -> None:
        with pytest.raises(ValueError, match="nicht gefunden"):
            vault.update_retraction_checked_at("does-not-exist", 1)


class TestPapersWriteMethodsHappyPath:
    """Bestandsverhalten bei existierendem Paper und ungesperrtem Vault
    bleibt unveraendert."""

    def test_set_page_offset_still_works(self, vault: VaultDB) -> None:
        _add_paper(vault)
        vault.set_page_offset("mueller2021", 7)
        assert vault.get_page_offset("mueller2021") == 7

    def test_update_pdf_path_still_works(self, vault: VaultDB) -> None:
        _add_paper(vault)
        vault.update_pdf_path("mueller2021", "/neu/pfad.pdf")
        paper = vault.get_paper("mueller2021")
        assert paper is not None
        assert paper["pdf_path"] == "/neu/pfad.pdf"

    def test_set_ocr_done_still_works(self, vault: VaultDB) -> None:
        _add_paper(vault)
        vault.set_ocr_done("mueller2021", 1)
        paper = vault.get_paper("mueller2021")
        assert paper is not None
        assert paper["ocr_done"] == 1

    def test_update_retraction_checked_at_still_works(self, vault: VaultDB) -> None:
        _add_paper(vault)
        vault.update_retraction_checked_at("mueller2021", 999)
        paper = vault.get_paper("mueller2021")
        assert paper is not None
        assert paper["retraction_checked_at"] == 999
