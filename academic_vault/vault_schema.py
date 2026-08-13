"""Schema-nahe Konstanten des Vaults: erlaubte Werte, Sentinels, vec0-DDL.

Reiner Move aus der frueheren ``academic_vault/db.py`` (Issue #841). Eigenes
Modul, damit sowohl die Fassade (``db.py``) als auch die Repository-Module
dieselben Konstanten benutzen, ohne einander zu importieren.
"""


# vec0-Spiegel der chunk_embeddings-Vektoren (Issue #372). Die DDL steht hier
# statt in schema.sql, weil sie die geladene sqlite-vec-Extension voraussetzt.
# Seit #629 ist die Breite ein Parameter statt einer Konstante: sie kommt aus
# `embedding_meta` (Bestand) und nicht mehr aus dem Modell-Default.
def _chunk_vectors_ddl(dim: int) -> str:
    return (
        "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors "
        f"USING vec0(chunk_id TEXT PRIMARY KEY, embedding FLOAT[{dim}])"
    )


# vec0-Tabelle fuer verifizierte Zitat-Embeddings (Issue #521). Anders als
# chunk_vectors gibt es KEINE BLOB-Basistabelle -- ist die sqlite-vec-
# Extension in diesem Prozess nicht ladbar, ist Embedding fuer Quotes ein
# vollstaendiges No-Op (bewusste Scope-Entscheidung, s. Plan-Kommentar #521).
def _quote_embeddings_ddl(dim: int) -> str:
    return (
        "CREATE VIRTUAL TABLE IF NOT EXISTS quote_embeddings "
        f"USING vec0(quote_id TEXT PRIMARY KEY, embedding FLOAT[{dim}])"
    )


VALID_PAPER_TYPES = frozenset({"article-journal", "book", "chapter"})

# Erlaubte Werte fuer `quotes.stance` (Issue #400): Haltung eines Zitats zur
# zitierenden Aussage. Gespiegelt vom CHECK-Constraint in schema.sql bzw.
# migrate.add_stance_column() -- der Constraint ist die zweite
# Verteidigungslinie fuer Direkt-Inserts, die Python-Validierung in
# `add_quote()` liefert die lesbare Fehlermeldung. Die automatische Befuellung
# per lokaler NLI-Klassifikation ist ein Folge-Issue; bis dahin bleibt das Feld
# NULL, sofern es nicht manuell gesetzt wird.
VALID_STANCES = frozenset({"supports", "contrasts", "mentions"})

# Erlaubte Werte fuer `quotes.extraction_method`: Herkunftsnachweis des
# Wortlauts. Gespiegelt vom CHECK-Constraint in schema.sql bzw.
# migrate.widen_extraction_method_check().
#   citations-api  Wortlaut stammt aus der Anthropic-Citations-API
#                  (`api_response_id` ist Pflicht, geprueft in server.add_quote).
#   manual         Wortlaut von Hand belegt -- keine maschinelle Pruefung.
#                  Bleibt der dokumentierte Ausweichweg, wenn die lokale
#                  Verifikation an ihre Grenzen stoesst (seitenuebergreifende
#                  Zitate, Wort-Auslassungen).
#   local-verbatim Wortlaut gegen den lokalen PDF-Volltext verifiziert
#                  (Issue #512). server.add_quote() prueft fail-closed VOR dem
#                  Schreiben; ein nicht belegbarer Kandidat landet nie im Vault.
# BEWUSST KEINE Python-Validierung dieser Menge in `add_quote()`: fuer
# unbekannte Werte bleibt der CHECK-Constraint zustaendig (sqlite3.IntegrityError),
# sonst verschoebe sich das bestehende Fehlerverhalten der Altpfade.
VALID_EXTRACTION_METHODS = frozenset({"citations-api", "manual", "local-verbatim"})

# Erlaubte Werte fuer `papers.source_kind` (Issue #473): unterscheidet fremde
# Literatur von eigenem Erhebungsmaterial (Transkript, Beobachtungsprotokoll).
# Beides liegt in derselben Tabelle, weil nur so die Belegkette greift
# (`quotes.paper_id` -> `papers`, verbatim-guard ueber `search_quote_text()`) --
# ein Interviewzitat unterliegt damit derselben Nachweispflicht wie ein
# Literaturzitat. Gespiegelt vom CHECK-Constraint in schema.sql bzw.
# migrate.add_source_kind_column(); die Python-Validierung in `add_paper()`
# liefert die lesbare Fehlermeldung.
VALID_SOURCE_KINDS = frozenset({"literature", "primary"})

# Erlaubte Werte fuer `quotes.audit_verdict` (Issue #737): Urteilsskala des
# quote-fidelity-auditor-Agenten. Gespiegelt vom CHECK-Constraint in
# schema.sql bzw. migrate.add_quote_audit_columns() -- additiv zu
# `stance`/`VALID_STANCES`, nicht deren Ersatz (siehe Kommentar dort).
VALID_AUDIT_VERDICTS = frozenset(
    {"faithful", "overstated", "context-stripped", "polarity-flip", "unsupported"}
)

# Erlaubte Werte fuer `quotes.audit_severity` (Issue #737): feste
# Verdict->Schweregrad-Tabelle aus agents/quote-fidelity-auditor.md. `None`
# ist nur fuer den Verdict `faithful` zulaessig (kein Befund) -- jeder der
# vier Negativ-Verdicts VERLANGT eine dieser drei Stufen, sonst waere ein
# offener Befund in der Pruefbilanz unsortierbar.
VALID_AUDIT_SEVERITIES = frozenset({"kritisch", "hoch", "mittel"})

# Dateisuffix des Sidecar-Markers, mit dem der scihub-fetcher-Agent einen
# erfolgreichen Download kennzeichnet (Issue #627). add_paper() erzwingt
# provenance="scihub" fuer jeden pdf_path, neben dem eine Datei mit diesem
# Suffix liegt -- unabhaengig davon, was der aufrufende Prompt als
# provenance-Parameter uebergibt oder wegläßt. Das verlagert die
# Durchsetzung von einer Prompt-Anweisung (agents/scihub-fetcher.md) an die
# einzige tatsaechliche Schreibstelle fuer die papers-Tabelle. Bewusst kein
# Wildcard-Suffix (z.B. nur ".provenance"), um keine fremden Dateien
# fehlzuinterpretieren.
SCIHUB_PROVENANCE_SIDECAR_SUFFIX = ".provenance-scihub"

# Erlaubte Werte fuer `codings.category_origin` (Issue #473): ob eine Kategorie
# am Material entwickelt (induktiv) oder aus der Theorie abgeleitet (deduktiv)
# wurde. Die Herkunft gehoert zur Methodendokumentation und wird deshalb
# erzwungen statt optional gefuehrt.
VALID_CATEGORY_ORIGINS = frozenset({"induktiv", "deduktiv"})

# Erlaubte Werte fuer `chunk_embeddings.context_source` (Issue #783): Herkunft
# des Kontextsatzes. Gespiegelt vom CHECK-Constraint in schema.sql bzw.
# migrate.add_chunk_context_source_column().
#   metadata  deterministischer Satz aus chunking.default_context_sentence()
#             (Titel/Autor/Jahr/Sektion) -- der Default seit #632, ohne
#             Modellaufruf.
#   model     inhaltlicher Satz, in einer Sitzung ueber
#             vault.enrich_chunk_contexts() geschrieben.
# NULL bleibt fuer Bestandschunks vor dieser Migration -- gleichbedeutend mit
# 'metadata' fuer die Zwecke von pending_context_chunks() (s. dort).
VALID_CHUNK_CONTEXT_SOURCES = frozenset({"metadata", "model"})

# Schema-Versions-Gate (Issue #368): ueber PRAGMA user_version verfolgt.
# Unversionierte/Legacy-DBs haben user_version=0 (SQLite-Default) und liegen
# damit garantiert unter diesem Wert. Hochzaehlen, sobald schema.sql um
# Spalten/Tabellen erweitert wird, die eine Bestands-Migration brauchen --
# und der neue migrate.py-Helfer in apply_pending_migrations() ergaenzt wird.
# 2 = quotes.stance (Issue #400).
# 3 = notes.page + notes_fts-Backfill fuer Bestandsnotizen (Issue #462).
# 4 = Drop der toten Tabellen aus migrate.DEAD_TABLES (Issue #539).
# 5 = papers.source_kind + transcript_segments/codings (Issue #473).
#     Dieser Zweig entstand parallel zu #539 und beanspruchte urspruenglich
#     ebenfalls die 4. Beim Zusammenfuehren muss er eine Generation
#     hoeherruecken: eine DB, die #539 bereits auf 4 gestempelt hat, wuerde
#     `apply_pending_migrations()` sonst nie wieder betreten und bliebe ohne
#     source_kind und ohne die Empirie-Tabellen zurueck.
# 6 = quotes.extraction_method CHECK um 'local-verbatim' erweitert (Issue #512).
#     Erste Migration, die KEINE Spalte hinzufuegt, sondern einen Constraint
#     aendert -- verifiziert wird sie deshalb nicht ueber
#     `_LEGACY_MIGRATION_COLUMNS`, sondern ueber die CHECK-SQL der Tabelle
#     (siehe `init_schema()`).
# 7 = quotes.context_source (Issue #520): Herkunftsnachweis fuer
#     context_before/context_after ('fulltext' oder NULL), gesetzt von
#     server.resolve_quote_context().
# 8 = papers.retraction_checked_at (Issue #604): Zeitpunkt der letzten
#     Crossref-Retraction-Pruefung, Grundlage fuer server.check_retractions().
# 9 = embedding_meta (Issue #629): Modell-ID und Dimension des Bestands.
#     Beanspruchte urspruenglich ebenfalls die 8 (Entwicklung parallel zu
#     #604) und musste beim Zusammenfuehren eine Generation hoeherruecken --
#     sonst wuerde eine DB, die #604 bereits auf 8 gestempelt hat,
#     `apply_pending_migrations()` nie wieder betreten und bliebe ohne
#     embedding_meta zurueck (derselbe Fall wie #473 vs. #539 oben, Version 5).
#     Erste Migration, die eine ganze TABELLE nachtraegt statt einer Spalte --
#     verifiziert wird sie deshalb ueber `_REQUIRED_MIGRATION_TABLES`
#     (siehe `init_schema()`), nicht ueber `_LEGACY_MIGRATION_COLUMNS`.
# 10 = quotes.audited_at + quotes.audit_verdict + quotes.audit_severity
#      (Issue #737): Audit-Historie fuer die Kapitel-Pruefbilanz
#      (`vault.chapter_quote_balance`), additiv zu `stance` und unabhaengig
#      davon persistiert -- siehe Kommentar bei `quotes.stance` in schema.sql.
# 11 = table_values (Issue #741): belegte Kennzahlen aus Tabellenzellen, der
#      Weg von einer Zahl in `paper_tables` in den Kapiteltext, analog zu
#      quotes fuer Wortlaut. Wie schon bei Version 9 (embedding_meta) eine
#      ganze TABELLE statt einer Spalte -- verifiziert ueber
#      `_REQUIRED_MIGRATION_TABLES`, nicht ueber `_LEGACY_MIGRATION_COLUMNS`.
# 12 = papers_trgm (Issue #703): Teilwort-Index (tokenize='trigram') ueber
#      Titel+Abstract, damit `Mittelstand` auch
#      `Mittelstandsdigitalisierung` findet. Ebenfalls eine ganze TABELLE
#      (Verifikation ueber `_REQUIRED_MIGRATION_TABLES`); der Backfill fuer
#      Bestandspaper steckt in `migrate.add_papers_trgm_table()`.
# 13 = chunk_fts (Issue #726): FTS5-Index ueber chunk_embeddings.chunk_text,
#      dieselbe Tokenizer-Entscheidung wie papers_fts (unicode61, kein
#      Trigram-Pendant -- der Auftrag ist ausdruecklich EIN Index). Ebenfalls
#      eine ganze TABELLE (Verifikation ueber `_REQUIRED_MIGRATION_TABLES`);
#      der Backfill fuer Bestandschunks steckt in `migrate.add_chunk_fts()`.
# 14 = chunk_embeddings.section_title + .page_start + .page_end (Issue #728):
#      Fundstelle des Gewinner-Chunks, additiv und nullable -- Bestandschunks
#      vor dieser Migration haben keine Lokation (kein Backfill aus Text
#      moeglich). Bis #728 lieferte `chunking.chunk_pages()` diese Felder
#      pro Chunk bereits (seit #708), sie wurden aber nur in den
#      Kontextsatz-Text hineingerechnet statt strukturiert gespeichert.
#      Migrationshelfer: `migrate.add_chunk_location_columns()`.
# 15 = chunk_embeddings.context_source (Issue #783): Herkunft des Kontextsatzes
#      (`'metadata'`/`'model'`/NULL fuer Bestand), additiv und nullable --
#      Grundlage fuer den Schreibweg `vault.enrich_chunk_contexts()` und die
#      Bestandsabfrage `vault.pending_context_chunks()`. Migrationshelfer:
#      `migrate.add_chunk_context_source_column()`.
CURRENT_SCHEMA_VERSION = 15

# Spalten, die `migrate.apply_pending_migrations()` je Tabelle nachziehen muss
# (Review-Fund zu PR #427, `db.py`-Zeile bei der `user_version`-Stempelung):
# jeder Helfer kapselt sein `ALTER TABLE` in `except sqlite3.OperationalError:
# pass` (migrate.py) -- das faengt nicht nur "duplicate column name", sondern
# z. B. auch "database is locked". Vor dem Stempeln wird deshalb per
# `PRAGMA table_info(<tabelle>)` verifiziert, dass die Migration tatsaechlich
# gegriffen hat, statt dem Rueckgabewert (`None`, kein Erfolgssignal) blind zu
# vertrauen -- sonst schliesst sich das Versions-Gate unwiderruflich, obwohl
# die Spalten weiterhin fehlen.
_LEGACY_MIGRATION_COLUMNS: dict[str, frozenset[str]] = {
    "papers": frozenset(
        {
            "parent_paper_id",
            "provenance",
            "source_kind",
            "editor",
            "chapter",
            "page_first",
            "page_last",
            "container_title",
            "retraction_checked_at",
        }
    ),
    "quotes": frozenset(
        {"stance", "context_source", "audited_at", "audit_verdict", "audit_severity"}
    ),
    "notes": frozenset({"page"}),
    "chunk_embeddings": frozenset({"section_title", "page_start", "page_end", "context_source"}),
}

# Tabellen, die `migrate.apply_pending_migrations()` auf einer Bestands-DB
# anlegen muss (Issue #629). Eigene Verifikationsart neben
# `_LEGACY_MIGRATION_COLUMNS` (Spalten) und `DEAD_TABLES` (Drops): eine fehlende
# Tabelle waere ueber `PRAGMA table_info()` unsichtbar, und der
# `user_version`-Stempel wuerde sich irrtuemlich schliessen -- exakt der
# Review-Fund aus PR #427, nur eine Ebene hoeher.
_REQUIRED_MIGRATION_TABLES = frozenset(
    {"embedding_meta", "table_values", "papers_trgm", "chunk_fts"}
)


class _Unset:
    """Sentinel-Typ fuer optionale ``add_paper()``-Parameter (Issue #455).

    Unterscheidet "Parameter nicht uebergeben" (Wert bleibt beim Upsert
    unangetastet) von "bewusst auf None/0 gesetzt" (Wert wird explizit
    geleert). Ein nacktes ``object()`` waere hierfuer ungeeignet, weil sich
    damit kein praeziser Typ (``str | None | _Unset``) fuer mypy formulieren
    laesst. Muss durch alle drei Aufrufebenen durchgereicht werden
    (``VaultDB.add_paper`` -> ``server.add_paper`` -> MCP-Tool-Wrapper
    ``_vault_add_paper``), sonst geht die Unterscheidung auf einer
    Zwischenschicht verloren.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "<UNSET>"


_UNSET = _Unset()

# Optionale papers-Spalten, die von add_paper()'s Sentinel-Logik erfasst
# werden, in der Reihenfolge, in der sie im INSERT/UPDATE auftauchen.
_OPTIONAL_PAPER_COLUMNS: tuple[str, ...] = (
    "doi",
    "isbn",
    "pdf_path",
    "page_offset",
    "editor",
    "chapter",
    "page_first",
    "page_last",
    "container_title",
    "parent_paper_id",
    "provenance",
    "source_kind",
)

# Defaults fuer eine echte Neuanlage (Sentinel -> dieser Wert), identisch zu
# den frueheren Funktions-Defaults -- bei einer Erstanlage ohne uebergebenen
# Wert soll sich am Ergebnis nichts aendern.
_OPTIONAL_PAPER_DEFAULTS: dict[str, object] = {
    "doi": None,
    "isbn": None,
    "pdf_path": None,
    "page_offset": 0,
    "editor": None,
    "chapter": None,
    "page_first": None,
    "page_last": None,
    "container_title": None,
    "parent_paper_id": None,
    "provenance": None,
    "source_kind": "literature",
}
