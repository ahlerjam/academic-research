"""Regressionstest fuer Issue #196 — Hardening-Buendel (M2/M6/L5).

Deckt drei der urspruenglich vier Hardening-Punkte ab (M5 — Profile-Owner-Check
im inzwischen als verwaiste Parallellogik entfernten Auth-Helper-Modul —
entfaellt seit Issue #377):
  M2 — FTS5-Query-Sanitizer erweitern (", :, NEAR, AND, OR, NOT)
  M6 — scripts/setup.sh nutzt set -euo pipefail
  L5 — mid-session-reinforcement.mjs schreibt State mit 0600

Alle Tests sind ohne externe Abhaengigkeiten (kein API-Key, keine DB) lauffaehig.

M2-Nachtrag (Issue #841): die urspruengliche Zeichen-Blacklist (``-^/*():"``)
liess ``. , ? '`` unangetastet und stuerzte an genau diesen Zeichen mit
``sqlite3.OperationalError`` ab. Der Fix ersetzt die Blacklist durch
Tokenize+Quote (:func:`academic_vault.db._sanitize_fts5_query`): jedes
FTS5-unsichere Token wird als FTS5-Stringliteral gequotet statt einzelne
Zeichen zu entfernen. Sanitisierte Queries enthalten seither LEGITIM ``"`` und
``:`` -- die drei betroffenen Tests unten pruefen deshalb nicht mehr auf
Abwesenheit einzelner Zeichen, sondern real gegen eine In-Memory-FTS5-Tabelle
auf die eigentliche Schutzeigenschaft: kein Crash, keine Operator-Wirkung.
"""

import re
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _assert_valid_fts5_query(sanitized: str, corpus: str = "irrelevant filler text") -> list:
    """Fuehrt ``sanitized`` als echtes FTS5-MATCH-Argument gegen eine
    In-Memory-FTS5-Tabelle aus und gibt die Treffer zurueck.

    Eine ``sqlite3.OperationalError`` wuerde hier durchschlagen, BEVOR
    irgendeine Zeilen-Assertion greift -- das ist die eigentliche
    Schutzwirkung von Issue #196/#841, eine weit staerkere Pruefung als reine
    String-Inspektion des sanitisierten Ergebnisses.
    """
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(body)")
        conn.execute("INSERT INTO t(body) VALUES (?)", (corpus,))
        return conn.execute("SELECT rowid FROM t WHERE t MATCH ?", (sanitized,)).fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# M2 — FTS5-Sanitizer
# ---------------------------------------------------------------------------


class TestFts5SanitizerHardening:
    """_sanitize_fts5_query muss FTS5-Operatoren neutralisieren."""

    def _sanitize(self, query: str) -> str:
        from academic_vault.server import _sanitize_fts5_query

        return _sanitize_fts5_query(query)

    def test_double_quote_query_executes_as_valid_fts5(self):
        """Ein eingebettetes Anfuehrungszeichen darf die FTS5-Query nicht
        syntaktisch brechen. Seit #841 wird das Token NICHT mehr entfernt,
        sondern als FTS5-Stringliteral gequotet (ein eingebettetes ``"`` wird
        dabei verdoppelt) -- die Query bleibt dadurch fuer JEDE Eingabe
        gueltig. Verifiziert wird das real gegen eine In-Memory-FTS5-Tabelle,
        nicht per String-Inspektion (die alte Assertion ``'"' not in out``
        gilt nicht mehr, weil das Anfuehrungszeichen jetzt Teil des
        gueltigen, gequoteten Ergebnisses ist)."""
        out = self._sanitize('foo "bar baz')
        _assert_valid_fts5_query(out)

    def test_colon_query_executes_as_valid_fts5_and_is_not_a_column_filter(self):
        """Doppelpunkt (Column-Filter-Operator in FTS5, z.B. ``title:foo``)
        darf nicht als Operator wirken. Seit #841 wird ``title:foo`` als
        Stringliteral ``"title:foo"`` gequotet statt den Doppelpunkt zu
        entfernen -- das neutralisiert die Operator-Bedeutung, OHNE das
        Zeichen zu tilgen (die alte Assertion ``':' not in out`` gilt nicht
        mehr). Verifiziert wird das an einer echten Mehrspalten-FTS5-Tabelle:
        ein UNSANITISIERTES ``title:foo`` faende eine Zeile allein ueber
        deren ``title``-Spalte (Zeile 1); die sanitisierte Query darf das
        NICHT tun, muss aber eine Zeile finden, die den literalen Text
        ``title:foo`` enthaelt (Zeile 2) -- der Beweis, dass der Doppelpunkt
        nur noch literaler Text ist, kein Operator mehr."""
        out = self._sanitize("title:foo")
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE t USING fts5(title, body)")
            conn.execute("INSERT INTO t(title, body) VALUES ('foo', 'irrelevant filler text')")
            conn.execute(
                "INSERT INTO t(title, body) VALUES "
                "('something else', 'contains literal title:foo right here')"
            )
            rows = conn.execute("SELECT rowid FROM t WHERE t MATCH ?", (out,)).fetchall()
        finally:
            conn.close()
        assert rows == [(2,)], (
            "sanitisierte Query darf NICHT ueber den Spalten-Filter 'title:' "
            "matchen (Zeile 1, kein literales 'title:foo' enthalten), sondern "
            "nur den literalen Text 'title:foo' finden (Zeile 2)"
        )

    def test_near_operator_neutralised(self):
        """NEAR als Operator-Keyword darf nicht als Operator durchkommen."""
        out = self._sanitize("foo NEAR bar")
        # NEAR darf nicht als eigenstaendiges Operator-Token uebrig bleiben
        assert not re.search(r"\bNEAR\b", out)

    def test_and_or_not_neutralised(self):
        """Boolesche FTS5-Operatoren AND/OR/NOT werden neutralisiert."""
        out = self._sanitize("foo AND bar OR baz NOT qux")
        assert not re.search(r"\bAND\b", out)
        assert not re.search(r"\bOR\b", out)
        assert not re.search(r"\bNOT\b", out)

    def test_lowercase_words_preserved(self):
        """Normale Begriffe (auch 'and'/'or' klein) bleiben erhalten — nur
        Operator-Keywords in Grossschreibung sind FTS5-Operatoren."""
        out = self._sanitize("android oregon notation")
        assert "android" in out
        assert "oregon" in out
        assert "notation" in out

    def test_combined_query_does_not_crash_fts5(self):
        """Eine boese Query mit allen Operatoren PLUS den #841-Sonderzeichen
        (Punkt, Komma, Fragezeichen, Apostroph, die die alte Blacklist
        durchliess) ergibt eine syntaktisch gueltige FTS5-MATCH-Query.
        Verifiziert wird das real gegen eine In-Memory-FTS5-Tabelle statt per
        String-Inspektion auf Abwesenheit von ``"``/``:`` -- die seit #841
        legitim im gequoteten Ergebnis vorkommen. Die Operator-Keywords
        AND/OR/NOT/NEAR muessen als eigenstaendige Tokens weiterhin
        verschwinden (unveraendertes Verhalten seit #462)."""
        out = self._sanitize(
            '"climate" AND change NEAR* (x) OR y NOT z col:val, it\'s DevOps-Governance?'
        )
        for op in ("AND", "OR", "NOT", "NEAR"):
            assert not re.search(rf"\b{op}\b", out)
        _assert_valid_fts5_query(out)


# ---------------------------------------------------------------------------
# M6 — setup.sh pipefail
# ---------------------------------------------------------------------------


class TestSetupShPipefail:
    """scripts/setup.sh muss set -euo pipefail enthalten."""

    def test_setup_has_euo_pipefail(self):
        src = (REPO_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
        assert re.search(r"^set -euo pipefail\s*$", src, re.MULTILINE), (
            "scripts/setup.sh muss 'set -euo pipefail' setzen"
        )


# ---------------------------------------------------------------------------
# L5 — reinforcement-state.json 0600
# ---------------------------------------------------------------------------


class TestReinforcementStatePerms:
    """mid-session-reinforcement.mjs muss State mit 0600 schreiben."""

    def test_writefilesync_uses_0600_mode(self):
        src = (REPO_ROOT / "hooks" / "mid-session-reinforcement.mjs").read_text(encoding="utf-8")
        # writeFileSync-Aufruf fuer den State muss ein mode:0o600/0600 setzen
        assert re.search(r"mode:\s*0o?600", src), (
            "writeFileSync fuer State-Datei muss mode 0600 setzen"
        )

    def test_mkdir_uses_0700_mode(self):
        """Das State-Verzeichnis sollte ebenfalls restriktiv (0700) angelegt werden."""
        src = (REPO_ROOT / "hooks" / "mid-session-reinforcement.mjs").read_text(encoding="utf-8")
        assert re.search(r"mode:\s*0o?700", src), (
            "mkdirSync fuer State-Verzeichnis sollte mode 0700 setzen"
        )
