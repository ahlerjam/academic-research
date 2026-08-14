"""Aggregat-Repositories des Vaults (Issue #841).

Jedes Modul buendelt die CRUD-Methoden genau eines Aggregats als Mixin. Die
Fassade ``academic_vault.db.VaultDB`` komponiert sie und liefert ihnen ueber
:class:`~academic_vault.repositories._base.ConnectionHost` das gemeinsame
Connection-, Transaktions- und Lock-Handling.
"""

from ._base import ConnectionHost
from .appraisal import AppraisalRepo
from .chunks import ChunksRepo
from .decisions import DecisionsRepo
from .empirics import EmpiricsRepo
from .figures import FiguresRepo
from .fulltext import FulltextRepo
from .notes import NotesRepo
from .papers import PapersRepo
from .quotes import QuotesRepo
from .tables import TablesRepo
from .vectors import VectorsRepo

__all__ = [
    "AppraisalRepo",
    "ChunksRepo",
    "ConnectionHost",
    "DecisionsRepo",
    "EmpiricsRepo",
    "FiguresRepo",
    "FulltextRepo",
    "NotesRepo",
    "PapersRepo",
    "QuotesRepo",
    "TablesRepo",
    "VectorsRepo",
]
