"""Tests fuer Issue #703: FTS5 findet keine deutschen Komposita-Bestandteile.

TDD: Tests zuerst (RED), dann Implementierung (GREEN).

``papers_fts`` laeuft mit dem FTS5-Default-Tokenizer ``unicode61`` -- kein
Stemming, keine Kompositazerlegung. Eine Suche nach ``Mittelstand`` findet
deshalb kein Paper, dessen Titel ``Mittelstandsdigitalisierung`` lautet. Der
gewaehlte Weg ist eine ZWEITE virtuelle Tabelle ``papers_trgm``
(``tokenize='trigram'``) ueber Titel und Abstract, deren Treffer *hinter* die
exakten angehaengt werden -- ein Tokenizer-Wechsel an ``papers_fts`` scheidet
aus, weil FTS5 keinen Tokenizer je Spalte kennt und der Umbau Ranking,
Prefix-Suche und alle Kurz-Token zerstoeren wuerde.
"""

import json
import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


def _make_db(tmp_path: Path) -> str:
    """Erstellt eine Vault-DB mit Schema und gibt den Pfad zurueck."""
    from academic_vault.db import VaultDB

    db_path = str(tmp_path / "vault.db")
    VaultDB(db_path).init_schema()
    return db_path


def _add_paper(db_path: str, paper_id: str, title: str, abstract: str = "") -> None:
    """Fuegt ein Paper ueber den regulaeren Schreibpfad ein."""
    from academic_vault.server import add_paper

    csl = {"type": "article-journal", "title": title, "abstract": abstract}
    add_paper(db_path, paper_id, json.dumps(csl))


def _ids(results: list[dict]) -> list[str]:
    return [r["paper_id"] for r in results]


def _exact_only(db_path: str, query: str, type_filter: str | None = None, k: int = 5) -> list[dict]:
    """Ruft ausschliesslich den unveraenderten Exakt-Zweig auf."""
    from academic_vault.db import VaultDB, _sanitize_fts5_query
    from academic_vault.server import _fts_exact_hits

    conn = VaultDB._open(db_path)
    try:
        return _fts_exact_hits(conn, _sanitize_fts5_query(query), type_filter, k)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# AK1: Kompositabestandteil findet das Kompositum
# ---------------------------------------------------------------------------


class TestAK1KompositaBestandteil:
    def test_ak1_kompositabestandteil_findet_paper_ueber_titel(self, tmp_path):
        """`Mittelstand` findet ein Paper mit `Mittelstandsdigitalisierung` im Titel."""
        db_path = _make_db(tmp_path)
        _add_paper(db_path, "p_komposita", "Mittelstandsdigitalisierung in KMU", "Governance.")
        _add_paper(db_path, "p_ablenker", "Quantum Computing Primer", "Qubits und Gatter.")

        from academic_vault.server import search_papers

        assert "p_komposita" in _ids(search_papers(db_path, "Mittelstand"))

    def test_ak1_kompositabestandteil_findet_paper_ueber_abstract(self, tmp_path):
        """Dasselbe, wenn das Kompositum nur im Abstract steht."""
        db_path = _make_db(tmp_path)
        _add_paper(
            db_path,
            "p_abstract",
            "Digitale Transformation",
            "Der Beitrag untersucht Mittelstandsdigitalisierung entlang der Wertschoepfung.",
        )
        _add_paper(db_path, "p_ablenker", "Quantum Computing Primer", "Qubits und Gatter.")

        from academic_vault.server import search_papers

        assert "p_abstract" in _ids(search_papers(db_path, "Mittelstand"))

    def test_ak1_trigram_treffer_hat_snippet_und_score(self, tmp_path):
        """Der Rueckgabevertrag (paper_id/snippet/score) gilt auch fuer Trigram-Treffer."""
        db_path = _make_db(tmp_path)
        _add_paper(db_path, "p_komposita", "Mittelstandsdigitalisierung in KMU", "Governance.")

        from academic_vault.server import search_papers

        hit = next(
            r for r in search_papers(db_path, "Mittelstand") if r["paper_id"] == "p_komposita"
        )
        assert set(hit) >= {"paper_id", "snippet", "score"}
        assert isinstance(hit["snippet"], str) and hit["snippet"]

    def test_ak1_upsert_haelt_den_teilwort_index_synchron(self, tmp_path):
        """Ein zweiter add_paper()-Aufruf ersetzt den Trigram-Eintrag, statt ihn zu doppeln."""
        db_path = _make_db(tmp_path)
        _add_paper(db_path, "p_upsert", "Mittelstandsdigitalisierung in KMU", "Governance.")
        _add_paper(db_path, "p_upsert", "Handwerksbetriebsfuehrung heute", "Governance.")

        from academic_vault.server import search_papers

        conn = sqlite3.connect(db_path)
        try:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM papers_trgm WHERE paper_id = 'p_upsert'"
                ).fetchone()[0]
                == 1
            )
        finally:
            conn.close()
        assert "p_upsert" not in _ids(search_papers(db_path, "Mittelstand"))
        assert "p_upsert" in _ids(search_papers(db_path, "Handwerksbetrieb"))

    def test_ak1_type_filter_gilt_auch_fuer_trigram_treffer(self, tmp_path):
        """Der `type_filter` darf im Trigram-Zweig nicht umgangen werden."""
        db_path = _make_db(tmp_path)
        _add_paper(db_path, "p_artikel", "Mittelstandsdigitalisierung in KMU", "Governance.")
        from academic_vault.server import add_paper, search_papers

        add_paper(
            db_path,
            "p_buch",
            json.dumps({"type": "book", "title": "Mittelstandsdigitalisierung kompakt"}),
        )

        results = _ids(search_papers(db_path, "Mittelstand", type_filter="book"))
        assert "p_buch" in results
        assert "p_artikel" not in results


# ---------------------------------------------------------------------------
# AK2: bestehende Treffer unveraendert
# ---------------------------------------------------------------------------


def _goldset() -> dict:
    return json.loads((FIXTURES / "retrieval_goldset_de_en.json").read_text(encoding="utf-8"))


@pytest.fixture
def goldset_vault(tmp_path):
    db_path = _make_db(tmp_path)
    for paper in _goldset()["papers"]:
        _add_paper(db_path, paper["paper_id"], paper["title"], paper["abstract"])
    return db_path


class TestAK2BestandsQueriesUnveraendert:
    """Die exakten Treffer bleiben vollstaendig erhalten UND behalten ihren Rang.

    Der Trigram-Zweig haengt seine Treffer als eigenen Block *hinter* die
    exakten an (die bm25-Skalen beider Tabellen sind nicht vergleichbar).
    Die pruefbare Zusage lautet deshalb: die Exakt-Treffer sind ein Praefix
    des Ergebnisses -- dieselben Dicts, dieselbe Reihenfolge.
    """

    @pytest.mark.parametrize("query_id", ["gq01", "gq02", "gq03", "gq06"])
    def test_ak2_exakte_treffer_bleiben_praefix(self, goldset_vault, query_id):
        from academic_vault.server import search_papers

        query = next(q["query"] for q in _goldset()["queries"] if q["query_id"] == query_id)
        exact = _exact_only(goldset_vault, query, k=5)
        results = search_papers(goldset_vault, query, k=5)

        assert results[: len(exact)] == exact

    @pytest.mark.parametrize("query_id", ["gq01", "gq02", "gq03", "gq06"])
    def test_ak2_kein_exakter_treffer_geht_verloren(self, goldset_vault, query_id):
        from academic_vault.server import search_papers

        query = next(q["query"] for q in _goldset()["queries"] if q["query_id"] == query_id)
        exact_ids = _ids(_exact_only(goldset_vault, query, k=5))
        result_ids = _ids(search_papers(goldset_vault, query, k=5))

        assert set(exact_ids) <= set(result_ids)

    def test_ak2_volle_trefferliste_bleibt_bitgleich(self, goldset_vault):
        """Fuellt der Exakt-Zweig `k` bereits aus, ist das Ergebnis unveraendert."""
        from academic_vault.server import search_papers

        query = "Transformer"
        exact = _exact_only(goldset_vault, query, k=2)
        assert len(exact) == 2, "Fixture-Annahme: mindestens zwei exakte Treffer"

        assert search_papers(goldset_vault, query, k=2) == exact

    def test_ak2_type_filter_unveraendert(self, goldset_vault):
        from academic_vault.server import search_papers

        query = "Klimawandel Auswirkungen"
        exact = _exact_only(goldset_vault, query, type_filter="article-journal", k=5)
        results = search_papers(goldset_vault, query, type_filter="article-journal", k=5)

        assert results[: len(exact)] == exact

    def test_ak2_rerank_pfad_laeuft_weiter(self, goldset_vault, fake_embedder):
        """Der RRF-/Rerank-Pfad bleibt funktionsfaehig und behaelt die Exakt-Treffer."""
        from academic_vault.server import search_papers

        query = "Klimawandel Auswirkungen auf Oekosysteme"
        exact_ids = set(_ids(_exact_only(goldset_vault, query, k=5)))
        results = search_papers(goldset_vault, query, k=5, rerank=True)

        assert results
        assert exact_ids <= set(_ids(results))


# ---------------------------------------------------------------------------
# AK3: Bestands-Vault wird migriert, ohne Verlust
# ---------------------------------------------------------------------------


def _degrade_to_legacy(db_path: str, version: int = 11) -> None:
    """Versetzt eine aktuelle DB in den Zustand vor dieser Migration."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS papers_trgm")
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
    finally:
        conn.close()


def _counts(db_path: str) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("papers", "notes", "quotes")
        }
    finally:
        conn.close()


def _table_exists(db_path: str, name: str) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
            is not None
        )
    finally:
        conn.close()


def _user_version(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


@pytest.fixture
def legacy_vault(tmp_path):
    """Gefuellter Vault, danach auf den Stand vor `papers_trgm` zurueckgesetzt."""
    from academic_vault.server import add_note, add_quote

    db_path = _make_db(tmp_path)
    _add_paper(db_path, "p_komposita", "Mittelstandsdigitalisierung in KMU", "Governance im Haus.")
    _add_paper(db_path, "p_zweit", "Prozessdokumentation im Betrieb", "Ablaeufe und Rollen.")
    add_note(db_path, "p_komposita", "Erste Notiz zur Digitalisierung", tags="setup")
    add_note(db_path, "p_zweit", "Zweite Notiz zur Dokumentation", tags="setup")
    add_quote(db_path, "p_komposita", "Governance im Haus.", "manual", pdf_page=1)
    _degrade_to_legacy(db_path)
    return db_path


class TestAK3BestandsVaultMigration:
    def test_ak3_legacy_vault_bekommt_tabelle(self, legacy_vault):
        from academic_vault.db import VaultDB

        assert not _table_exists(legacy_vault, "papers_trgm")
        VaultDB(legacy_vault).init_schema()
        assert _table_exists(legacy_vault, "papers_trgm")

    def test_ak3_keine_daten_gehen_verloren(self, legacy_vault):
        from academic_vault.db import VaultDB

        before = _counts(legacy_vault)
        VaultDB(legacy_vault).init_schema()
        assert _counts(legacy_vault) == before

    def test_ak3_backfill_erfasst_bestandspaper(self, legacy_vault):
        """Vor der Migration eingefuegte Paper sind danach ueber Komposita findbar."""
        from academic_vault.db import VaultDB
        from academic_vault.server import search_papers

        VaultDB(legacy_vault).init_schema()
        assert "p_komposita" in _ids(search_papers(legacy_vault, "Mittelstand"))

    def test_ak3_user_version_wird_hochgestempelt(self, legacy_vault):
        from academic_vault.db import CURRENT_SCHEMA_VERSION, VaultDB

        VaultDB(legacy_vault).init_schema()
        assert _user_version(legacy_vault) == CURRENT_SCHEMA_VERSION

    def test_ak3_migration_idempotent(self, legacy_vault):
        """Ein zweiter Lauf dupliziert keine Zeilen im Trigram-Index."""
        from academic_vault.db import VaultDB
        from academic_vault.migrate import add_papers_trgm_table

        VaultDB(legacy_vault).init_schema()
        conn = sqlite3.connect(legacy_vault)
        try:
            first = conn.execute("SELECT COUNT(*) FROM papers_trgm").fetchone()[0]
        finally:
            conn.close()

        add_papers_trgm_table(legacy_vault)
        VaultDB(legacy_vault).init_schema()

        conn = sqlite3.connect(legacy_vault)
        try:
            assert conn.execute("SELECT COUNT(*) FROM papers_trgm").fetchone()[0] == first
        finally:
            conn.close()

    def test_ak3_lesepfad_repariert_bestands_vault(self, legacy_vault):
        """`search_papers()` auf dem Legacy-Vault wirft nicht, sondern liefert Treffer."""
        from academic_vault.server import search_papers

        assert "p_komposita" in _ids(search_papers(legacy_vault, "Mittelstand"))

    def test_ak3_trigram_zweig_faellt_ohne_tabelle_zurueck(self, legacy_vault):
        """Fehlt `papers_trgm`, liefert der Zweig [] statt sqlite3.OperationalError."""
        from academic_vault.db import VaultDB
        from academic_vault.server import _fts_trigram_hits

        conn = VaultDB._open(legacy_vault)
        try:
            assert _fts_trigram_hits(conn, "Mittelstand", None, 5) == []
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# AK4: Der gewaehlte Weg ist mit seinem Preis begruendet
# ---------------------------------------------------------------------------


class TestAK4BegruendungUndPreis:
    def test_ak4_schema_begruendet_den_weg(self):
        schema = (REPO_ROOT / "academic_vault" / "schema.sql").read_text(encoding="utf-8")
        block = schema.split("CREATE VIRTUAL TABLE IF NOT EXISTS papers_trgm")[0][-2500:]
        for marker in ("#703", "Indexgroesse", "Tokenizer", "fulltext"):
            assert marker in block, f"Begruendung im schema.sql nennt '{marker}' nicht"

    def test_ak4_doku_nennt_preis_und_grenze(self):
        doc = (REPO_ROOT / "docs" / "reference" / "vault.md").read_text(encoding="utf-8")
        for marker in ("papers_trgm", "Trigram", "Indexgröße", "#703"):
            assert marker in doc, f"docs/reference/vault.md nennt '{marker}' nicht"

    def test_ak4_trigram_index_ohne_fulltext_spalte(self, tmp_path):
        """Der Preis wird mechanisch festgenagelt: kein Volltext im Trigram-Index."""
        db_path = _make_db(tmp_path)
        conn = sqlite3.connect(db_path)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(papers_trgm)")}
        finally:
            conn.close()
        assert "fulltext" not in columns
        assert {"paper_id", "title", "abstract"} <= columns

    def test_ak4_volltext_bleibt_ausserhalb_des_trigram_index(self, tmp_path):
        """Ein Kompositum, das NUR im PDF-Volltext steht, wird bewusst nicht gefunden."""
        from academic_vault.db import VaultDB
        from academic_vault.server import search_papers

        db_path = _make_db(tmp_path)
        _add_paper(db_path, "p_vt", "Ein neutraler Titel", "Ein neutraler Abstract.")
        VaultDB(db_path).set_fulltext("p_vt", "Der Volltext handelt von Betriebsraetestrukturen.")

        # Ganzes Wort: der bestehende unicode61-Pfad findet es weiterhin.
        assert "p_vt" in _ids(search_papers(db_path, "Betriebsraetestrukturen"))
        # Bestandteil: bewusste Grenze, der Trigram-Index kennt den Volltext nicht.
        assert "p_vt" not in _ids(search_papers(db_path, "Betriebsraete"))


# ---------------------------------------------------------------------------
# AK5: Kurzsuchen unter vier Zeichen bleiben unveraendert
# ---------------------------------------------------------------------------


@pytest.fixture
def kurzsuche_vault(tmp_path):
    """Enthaelt je Kurzbegriff einen echten Wort-Treffer und einen Wortmitte-Kandidaten."""
    db_path = _make_db(tmp_path)
    _add_paper(db_path, "p_kmu", "KMU im Wandel", "Kleine und mittlere Unternehmen.")
    _add_paper(db_path, "p_werkmuseum", "Werkmuseum und Sammlung", "Ein Haus der Technik.")
    _add_paper(db_path, "p_iot", "IoT Sensorik in der Fertigung", "Vernetzte Maschinen.")
    _add_paper(db_path, "p_biotech", "Biotechnologie im Labor", "Enzyme und Fermentation.")
    return db_path


class TestAK5KurzeQueriesUnveraendert:
    @pytest.mark.parametrize("query", ["K", "KM", "KMU", "IoT", "Wan"])
    def test_ak5_kurze_queries_identisch(self, kurzsuche_vault, query):
        """Unter vier Zeichen ist das Ergebnis bitgleich mit dem reinen Exakt-Zweig."""
        from academic_vault.server import search_papers

        assert search_papers(kurzsuche_vault, query, k=5) == _exact_only(
            kurzsuche_vault, query, k=5
        )

    def test_ak5_kein_wortmitten_rauschen_bei_drei_zeichen(self, kurzsuche_vault):
        """`KMU` darf `Werkmuseum` nicht einsammeln (ein 3-Zeichen-Token ist ein Trigram)."""
        from academic_vault.server import search_papers

        results = _ids(search_papers(kurzsuche_vault, "KMU", k=5))
        assert "p_kmu" in results
        assert "p_werkmuseum" not in results

    def test_ak5_kein_wortmitten_rauschen_bei_iot(self, kurzsuche_vault):
        from academic_vault.server import search_papers

        results = _ids(search_papers(kurzsuche_vault, "IoT", k=5))
        assert "p_iot" in results
        assert "p_biotech" not in results

    def test_ak5_schwelle_greift_ab_vier_zeichen(self, kurzsuche_vault):
        """Gegenprobe: ein 4-Zeichen-Token aktiviert den Trigram-Zweig."""
        from academic_vault.server import search_papers

        assert "p_kmu" in _ids(search_papers(kurzsuche_vault, "Wand", k=5))

    def test_ak5_schwelle_ist_eine_benannte_konstante(self):
        from academic_vault.server import _TRIGRAM_MIN_TOKEN_LEN

        assert _TRIGRAM_MIN_TOKEN_LEN == 4

    def test_ak5_kurze_tokens_in_gemischter_query_verschwinden(self, kurzsuche_vault):
        """In `KMU Wandel` traegt nur das lange Token zum Trigram-Zweig bei."""
        from academic_vault.server import _trigram_match_expression

        assert _trigram_match_expression("KMU Wandel") == "Wandel"
        assert _trigram_match_expression("KMU IoT") == ""
