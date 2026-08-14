"""Kontrakt zwischen der Fassade ``VaultDB`` und den Aggregat-Repositories.

Die Repositories sind Mixins, keine eigenstaendigen Objekte: sie bekommen ihre
Connection ausschliesslich von der Fassade und oeffnen selbst nie eine (Issue
#841, AK2). ``ConnectionHost`` deklariert genau die Primitive, auf die sie sich
dabei verlassen duerfen -- implementiert werden alle fuenf in
``academic_vault/db.py::VaultDB``.

Warum Mixins statt Objekt-Delegation: so bleibt **jede** Methode direkt an
``VaultDB`` erreichbar. Bestehende Aufrufer (``server.py``, ``ingest.py``,
``migrate.py``, die Evals und rund 40 Testdateien) aendern sich dadurch nicht,
und Patches auf die Klasse -- etwa
``monkeypatch.setattr(db_module.VaultDB, "_papers_snapshot", ...)`` in
``tests/test_issue_378_citation_guard.py`` -- greifen unveraendert.
"""

import sqlite3
from contextlib import AbstractContextManager


class ConnectionHost:
    """Was ein Repository von seiner Fassade erwarten darf.

    Die Methodenkoerper hier werden nie ausgefuehrt: ``VaultDB`` steht in der
    MRO vor jedem Repository und ueberschreibt sie alle. Sie stehen fuer mypy
    da (die Repositories rufen ``self._connection()`` & Co. auf) und machen den
    Kontrakt an einer Stelle lesbar.
    """

    #: Pfad der SQLite-Datei, die die Fassade verwaltet.
    db_path: str
    #: Ob die sqlite-vec-Extension in diesem Prozess geladen werden konnte.
    vec_available: bool
    #: Fehlerursache des letzten fehlgeschlagenen Ladeversuchs.
    vec_unavailable_reason: str | None

    def _connection(self, commit: bool = False) -> AbstractContextManager[sqlite3.Connection]:
        """Stellt die geteilte Connection bereit und schliesst sie garantiert."""
        raise NotImplementedError

    def _raise_if_locked(self, conn: sqlite3.Connection) -> None:
        """Wirft ``VaultLockedError``, falls der Material-Passport gesperrt ist."""
        raise NotImplementedError

    def load_vec_extension(self, conn: sqlite3.Connection | None = None) -> bool:
        """Laedt die sqlite-vec-Extension auf der uebergebenen Connection."""
        raise NotImplementedError

    def _expected_embedding_dim(self, conn: sqlite3.Connection) -> int:
        """Vektorbreite des Bestands (``embedding_meta``) auf dieser Connection."""
        raise NotImplementedError

    def _assert_vector_dim(self, conn: sqlite3.Connection, embedding_vector: bytes) -> None:
        """Wirft, wenn ein Vektor nicht die Breite des Bestands hat."""
        raise NotImplementedError


__all__ = ["ConnectionHost"]
