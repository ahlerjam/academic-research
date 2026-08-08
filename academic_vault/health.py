"""Zustandsausgabe fuer optionale Vault-Bestandteile (Issue #624).

``README.md`` fuehrte das Embedding-Modell ``intfloat/multilingual-e5-small``
lange als Pflichtbestandteil. Der Code behandelt es -- ebenso wie
``sqlite-vec`` -- zu Recht als optional: beide Faelle degradieren sauber auf
Stichwortsuche (FTS5-only), aber bislang vollstaendig lautlos. Ein Nutzer ohne
ladbare SQLite-Erweiterungen bekam dauerhaft schlechtere Retrieval-Abdeckung,
ohne davon zu erfahren -- fuer ein Werkzeug, dessen Zweck Zitat-Integritaet
ist, ist "kein Treffer" dann nicht mehr von "der Suchindex ist halbiert" zu
unterscheiden.

:func:`get_component_status` liefert je Bestandteil (Embedding-Modell,
sqlite-vec, FTS5), ob er geladen ist, welche Funktion bei Fehlen ausfaellt
(laienverstaendlicher Klartext, nicht der interne Bezeichner) und -- wo
ermittelbar -- die Fehlerursache. Ergaenzt um den verwendeten
Python-Interpreter und den DB-Pfad.

Bewusst KEIN automatisches Nachinstallieren, KEIN Abschaffen des Fallbacks,
KEINE Warnung bei jeder Sitzung -- der Zustand soll abrufbar sein, nicht
aufdringlich (Scope-Abgrenzung im Issue).
"""

import sqlite3
import sys

from .db import VaultDB
from .embedding_model import get_embedder, get_embedder_error, resolve_embedding_enabled

# Tabellen, deren Existenz FTS5-Verfuegbarkeit belegt (schema.sql). Beide
# werden per CREATE VIRTUAL TABLE ... USING fts5(...) angelegt -- existieren
# sie, hat init_schema() das FTS5-Modul erfolgreich genutzt.
_FTS5_TABLES = ("papers_fts", "notes_fts")


def _fts5_loaded(conn: sqlite3.Connection) -> bool:
    """Prueft pragmatisch ueber ``sqlite_master``, ob die FTS5-Tabellen existieren.

    Kein neuer Fallback-Pfad -- nur eine Lesbarkeits-Abfrage auf eine bereits
    initialisierte DB. Separate Funktion, damit Tests den Fall "FTS5 fehlt"
    per Monkeypatch simulieren koennen: ``init_schema()`` selbst laesst einen
    fehlenden FTS5-Modul-Support in der Praxis kaum kontrolliert beobachten,
    weil ``executescript(ddl)`` ungefangen wirft und den Serverstart abbricht
    (Plan-Risikonotiz #624) -- das ist hier bewusst nicht veraendert.
    """
    present = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?)",
            _FTS5_TABLES,
        ).fetchall()
    }
    return all(table in present for table in _FTS5_TABLES)


def get_component_status(db_path: str) -> dict:
    """Zustandsausgabe fuer die optionalen Vault-Bestandteile (Issue #624).

    Oeffnet/initialisiert die DB unter ``db_path`` (idempotent, s.
    ``VaultDB.init_schema()``-Docstring) und meldet je Bestandteil
    ``loaded`` (bool), ``impact`` (laienverstaendlicher Klartext des
    Funktionsverlusts bei Nichtladen) und ``reason`` (Fehlerursache, sofern
    ermittelbar, sonst ``None``). Ergaenzt um ``python_executable``
    (``sys.executable``) und ``db_path``.

    Aendert am Fallback-Verhalten selbst nichts -- reine Ausgabe.
    """
    db = VaultDB(db_path)
    db.init_schema()

    # Schalter-Check VOR get_embedder() (Issue #719): bei abgeschaltetem
    # Embedding darf component_status() keinen Ladeversuch/Download ausloesen
    # -- get_embedder() gated zwar bereits selbst (liefert None ohne
    # _load_backend_model aufzurufen), aber ohne diesen Check bliebe "reason"
    # leer (kein Fehler wurde je aufgezeichnet, weil keiner auftrat).
    embedding_switch_on = resolve_embedding_enabled()
    embedder = get_embedder() if embedding_switch_on else None
    embedding_loaded = embedder is not None
    embedding_status = {
        "loaded": embedding_loaded,
        "impact": (
            "Semantische Suche ist aktiv: vault.search findet auch inhaltlich "
            "aehnliche, wortlich abweichende Textstellen."
            if embedding_loaded
            else "Semantische Suche ist aus. vault.search laeuft nur noch als "
            "Stichwortsuche -- inhaltlich passende, aber wortlich abweichende "
            "Textstellen werden nicht gefunden."
        ),
        "reason": (
            None
            if embedding_loaded
            else (
                "Embedding-Schalter ist aus (Argument/Env/Config, Issue #719)."
                if not embedding_switch_on
                else get_embedder_error()
            )
        ),
    }

    sqlite_vec_loaded = db.vec_available
    sqlite_vec_status = {
        "loaded": sqlite_vec_loaded,
        "impact": (
            "Der Vektor-Index (sqlite-vec) ist aktiv und traegt die semantische Suche mit."
            if sqlite_vec_loaded
            else "Der Vektor-Index (sqlite-vec) fehlt. Auch ein geladenes "
            "Embedding-Modell kann Ergebnisse dann nicht speichern oder "
            "abfragen -- die Suche bleibt reine Stichwortsuche."
        ),
        "reason": None if sqlite_vec_loaded else db.vec_unavailable_reason,
    }

    conn = VaultDB._open(db_path)
    try:
        fts5_loaded = _fts5_loaded(conn)
    finally:
        conn.close()
    fts5_status = {
        "loaded": fts5_loaded,
        "impact": (
            "Die Stichwortsuche nutzt einen vollen Volltextindex (BM25-Rangfolge)."
            if fts5_loaded
            else "Der Volltextindex fehlt. Die Stichwortsuche faellt auf einfache "
            "Teilstring-Treffer ohne Relevanz-Rangfolge zurueck."
        ),
        "reason": None,
    }

    return {
        "embedding_model": embedding_status,
        "sqlite_vec": sqlite_vec_status,
        "fts5": fts5_status,
        "python_executable": sys.executable,
        "db_path": db_path,
    }
