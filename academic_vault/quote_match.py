"""Wortlaut-Abgleich woertlicher Zitate gegen den Vault-Snapshot (Issue #846).

Bis #846 kannte der Zitat-Zweig von ``hooks/verbatim-guard.mjs`` nur ein
Boolean: :func:`academic_vault.server.search_quote_text` fragte
``verbatim LIKE '%kandidat%'`` und der Hook wertete das Ergebnis als
``bool(...)`` aus. Daraus folgten zwei Fehler mit demselben Ausgang:

* Ein Zitat, das im Kapitel typografisch anders gesetzt ist (deutsche
  Anfuehrungszeichen im Zitatinneren, Zeilenumbruch mitten im Satz,
  Trennstrich am Zeilenende, ``[…]``-Auslassung), traf das LIKE nicht und
  wurde als "nicht im Vault" GEBLOCKT -- ein Falschalarm.
* Ein Zitat mit VERAENDERTEM Wortlaut lieferte dasselbe ``False`` wie ein gar
  nicht vorhandenes -- die Meldung log nicht, aber sie sagte auch nicht, was
  wirklich los war (und half damit nicht, den Wortlaut zu reparieren).

Dieses Modul ersetzt das Boolean durch einen Status je Kandidat:

``exact``
    Der Kandidat steht zeichengleich im Vault-Zitat.
``normalized``
    Gleich bis auf reine Darstellung: Anfuehrungszeichen-/Apostroph-Variante,
    kollabierter Whitespace, NFKC (u. a. Ligaturen), Trennstrich am
    Zeilenumbruch -- oder ausschliesslich Gross-/Kleinschreibung
    (dann zusaetzlich ``case_only=True``, siehe unten).
``ellipsis``
    Auslassungszitat: die Fragmente zwischen ``[…]``/``[...]`` kommen alle und
    IN DIESER REIHENFOLGE im Vault-Zitat vor.
``deviation``
    Der Kandidat ist einem Vault-Zitat eindeutig zuzuordnen, weicht aber im
    Wortlaut ab. ``vault_verbatim`` traegt den Vault-Wortlaut der Fundstelle,
    ``diff`` die abweichenden Woerter.
``absent``
    Kein Vault-Zitat zuordenbar -- inhaltlich derselbe Befund wie das alte
    ``False``.

Bewusste Grenzen (dokumentiert in ``docs/guide/limits.md``):

* Die Fuzzy-Zuordnung laeuft erst ab :data:`MIN_FUZZY_CANDIDATE_LEN`
  normalisierten Zeichen. Kurze Zitate erreichen in langem Text zufaellig hohe
  Aehnlichkeitswerte (dokumentierte Falle aus #520); sie bleiben deshalb beim
  billigen Substring-Pfad und landen sonst bei ``absent`` -- also beim
  bisherigen Verhalten, nicht bei einem erfundenen Wortlaut-Vorwurf.
* Liegen die zwei besten Treffer naeher als :data:`AMBIGUITY_MARGIN`
  beieinander und unterscheiden sich ihre Wortlaute, gilt der Kandidat als
  NICHT zuordenbar (``absent``). Ein Wortlaut-Vorwurf gegen das falsche
  Vault-Zitat waere schlimmer als der unspezifische Bestandsbefund.
* Gross-/Kleinschreibung: die Zuordnung ist case-insensitiv (SQLite-LIKE war
  es fuer ASCII bisher auch), ein REINER Case-Unterschied ist deshalb
  ``normalized`` mit ``case_only=True`` -- ein Hinweis, kein Block. Sonst
  haette #846 nebenbei eine neue Blockklasse eingefuehrt.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from .verbatim import normalize_text, normalize_weak

QuoteWordingStatus = Literal["exact", "normalized", "ellipsis", "deviation", "absent"]

#: Ab dieser Laenge (normalisierte Zeichen) darf ein Kandidat fuzzy zugeordnet
#: werden. Darunter ist die Trefferwahrscheinlichkeit gegen beliebigen Text zu
#: hoch, um daraus einen Wortlaut-Vorwurf abzuleiten (#520).
MIN_FUZZY_CANDIDATE_LEN = 40

#: rapidfuzz ``partial_ratio`` (0-100), ab dem ein Vault-Zitat als "gemeint"
#: gilt. Unverwandte Saetze vergleichbarer Laenge liegen empirisch bei 40-50,
#: ein einzelnes ausgetauschtes Wort bei ueber 90.
WORDING_MATCH_THRESHOLD = 82.0

#: Liegt der zweitbeste Treffer naeher als dieser Abstand am besten, ist die
#: Zuordnung mehrdeutig (siehe Modul-Docstring).
AMBIGUITY_MARGIN = 2.0

#: Untergrenze der Vault-Zitat-Laenge relativ zum Kandidaten fuer die
#: Fuzzy-Zuordnung. Ein deutlich kuerzeres Zitat kann den Kandidaten nicht als
#: Ganzes enthalten; der Wert laesst Raum fuer Auslassungen und Streichungen.
FUZZY_LENGTH_BAND = 0.7

#: Obergrenze der je Write gelesenen Vault-Zitate. Schutz vor einem Vault, der
#: den Hook-Zeitrahmen sprengt -- nicht als fachliche Grenze gedacht.
MAX_SNAPSHOT_QUOTES = 5000

#: Hoechstzahl gemeldeter Wort-Abweichungen je Zitat (Lesbarkeit der Meldung).
MAX_DIFF_ENTRIES = 5

#: Mindestlaenge eines Auslassungs-Fragments, damit es als Beleg zaehlt.
MIN_ELLIPSIS_FRAGMENT_LEN = 6

# Auslassungsmarker. Gepr ueft wird auf dem VOLL normalisierten Text: NFKC
# zerlegt "…" (U+2026) nach "...", deshalb genuegt hier die Punktform.
_ELLIPSIS_RE = re.compile(r"[\[(]\s*\.{2,}\s*[\])]")


@dataclass
class QuoteWordingMatch:
    """Ergebnis des Wortlaut-Abgleichs EINES Kandidaten."""

    status: QuoteWordingStatus
    candidate: str = ""
    vault_verbatim: str = ""
    quote_id: str | None = None
    paper_id: str | None = None
    ratio: float = 0.0
    case_only: bool = False
    quota_capped: bool = False
    diff: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisierbare Form fuer die Hook-Bruecke."""
        return {
            "status": self.status,
            "candidate": self.candidate,
            "vault_verbatim": self.vault_verbatim,
            "quote_id": self.quote_id,
            "paper_id": self.paper_id,
            "ratio": round(self.ratio, 2),
            "case_only": self.case_only,
            "quota_capped": self.quota_capped,
            "diff": self.diff,
        }


@dataclass
class _PreparedQuote:
    """Ein Vault-Zitat in allen Normalisierungsstufen (einmal je Write)."""

    quote_id: str | None
    paper_id: str | None
    raw: str
    weak: str
    full: str
    folded: str


def prepare_snapshot(rows: list[dict]) -> list[_PreparedQuote]:
    """Normalisiert einen Quotes-Snapshot EINMAL fuer alle Kandidaten.

    ``rows`` sind Zeilen aus
    :meth:`academic_vault.db.VaultDB.quotes_snapshot_for_wording`. Zeilen ohne
    nutzbaren ``verbatim``-Text werden uebersprungen (ein leeres Vault-Zitat
    kann nichts belegen).
    """
    prepared: list[_PreparedQuote] = []
    for row in rows:
        raw = row.get("verbatim")
        if not isinstance(raw, str) or not raw.strip():
            continue
        full = normalize_text(raw)
        prepared.append(
            _PreparedQuote(
                quote_id=row.get("quote_id"),
                paper_id=row.get("paper_id"),
                raw=raw,
                weak=normalize_weak(raw),
                full=full,
                folded=full.casefold(),
            )
        )
    return prepared


def min_snapshot_length(candidates: list[Any]) -> int:
    """Untergrenze fuer ``length(verbatim)`` im SQL-Vorfilter.

    Ein Vault-Zitat, das deutlich kuerzer ist als der kuerzeste Kandidat, kann
    diesen weder enthalten noch ihm aehneln. 60 % des kuerzesten Kandidaten
    laesst Raum fuer Normalisierungseffekte (Trennstrich-Join, Whitespace) und
    fuer Auslassungszitate, deren Marker mitgezaehlt werden.
    """
    lengths = [len(c) for c in candidates if isinstance(c, str) and c.strip()]
    if not lengths:
        return 0
    return max(0, int(min(lengths) * 0.6))


def _split_ellipsis_fragments(normalized: str) -> list[str]:
    """Fragmente eines Auslassungszitats, leere/whitespace-Teile entfernt."""
    return [part.strip() for part in _ELLIPSIS_RE.split(normalized) if part.strip()]


def _fragments_in_order(fragments: list[str], haystack: str) -> bool:
    """True, wenn alle ``fragments`` NACHEINANDER in ``haystack`` vorkommen."""
    position = 0
    for fragment in fragments:
        index = haystack.find(fragment, position)
        if index == -1:
            return False
        position = index + len(fragment)
    return True


def _expand_to_word_bounds(text: str, start: int, end: int) -> str:
    """Erweitert [start, end) auf Wortgrenzen.

    ``partial_ratio_alignment`` richtet auf Zeichen aus, nicht auf Woertern --
    ohne diese Erweiterung stuende im gemeldeten Vault-Wortlaut ein
    abgeschnittenes Wortfragment (Falle aus #511).
    """
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    while end < len(text) and not text[end].isspace():
        end += 1
    return text[start:end].strip()


def _word_diff(chapter: str, vault: str) -> list[dict[str, str]]:
    """Abweichende Woerter zwischen Kapitel- und Vault-Wortlaut.

    Verglichen wird casefolded (der reine Case-Unterschied ist an anderer
    Stelle bereits als ``normalized`` abgefangen), gemeldet wird der
    Originaltext. ``kind``: ``replaced`` (anderes Wort), ``added`` (im Kapitel
    zusaetzlich), ``missing`` (im Kapitel ausgelassen).
    """
    chapter_words = chapter.split()
    vault_words = vault.split()
    matcher = difflib.SequenceMatcher(
        a=[w.casefold() for w in chapter_words],
        b=[w.casefold() for w in vault_words],
        autojunk=False,
    )
    kinds = {"replace": "replaced", "delete": "added", "insert": "missing"}
    entries: list[dict[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        entries.append(
            {
                "kind": kinds[tag],
                "chapter": " ".join(chapter_words[i1:i2]),
                "vault": " ".join(vault_words[j1:j2]),
            }
        )
        if len(entries) >= MAX_DIFF_ENTRIES:
            break
    return entries


def _substring_match(candidate: str, entries: list[_PreparedQuote]) -> QuoteWordingMatch | None:
    """Die vier billigen Stufen: exakt, schwach, voll, casefolded."""
    weak = normalize_weak(candidate)
    full = normalize_text(candidate)
    folded = full.casefold()
    if not full:
        return None

    for entry in entries:
        if candidate in entry.raw:
            return QuoteWordingMatch(
                status="exact",
                candidate=full,
                vault_verbatim=entry.full,
                quote_id=entry.quote_id,
                paper_id=entry.paper_id,
                ratio=100.0,
            )
    for entry in entries:
        if weak and weak in entry.weak:
            return QuoteWordingMatch(
                status="normalized",
                candidate=full,
                vault_verbatim=entry.full,
                quote_id=entry.quote_id,
                paper_id=entry.paper_id,
                ratio=100.0,
            )
    for entry in entries:
        if full in entry.full:
            return QuoteWordingMatch(
                status="normalized",
                candidate=full,
                vault_verbatim=entry.full,
                quote_id=entry.quote_id,
                paper_id=entry.paper_id,
                ratio=100.0,
            )
    for entry in entries:
        if folded in entry.folded:
            return QuoteWordingMatch(
                status="normalized",
                candidate=full,
                vault_verbatim=entry.full,
                quote_id=entry.quote_id,
                paper_id=entry.paper_id,
                ratio=100.0,
                case_only=True,
            )
    return None


def _ellipsis_match(candidate: str, entries: list[_PreparedQuote]) -> QuoteWordingMatch | None:
    """Auslassungszitat: Fragmente in Reihenfolge belegt."""
    full = normalize_text(candidate)
    fragments = _split_ellipsis_fragments(full)
    if len(fragments) < 2:
        return None
    if sum(len(f) for f in fragments) < MIN_FUZZY_CANDIDATE_LEN:
        return None
    if any(len(f) < MIN_ELLIPSIS_FRAGMENT_LEN for f in fragments):
        return None
    folded_fragments = [f.casefold() for f in fragments]
    for entry in entries:
        if _fragments_in_order(folded_fragments, entry.folded):
            return QuoteWordingMatch(
                status="ellipsis",
                candidate=full,
                vault_verbatim=entry.full,
                quote_id=entry.quote_id,
                paper_id=entry.paper_id,
                ratio=100.0,
            )
    return None


def _fuzzy_match(candidate: str, entries: list[_PreparedQuote]) -> QuoteWordingMatch | None:
    """Zuordnung ueber rapidfuzz; ``None``, wenn nichts eindeutig passt."""
    # Lazy import (#846-Folgefix): NUR dieser Fuzzy-Zweig braucht rapidfuzz.
    # _substring_match()/_ellipsis_match() (davor in match_candidate()
    # versucht) kommen mit reinem difflib/String-Vergleich aus -- ein
    # exaktes oder Auslassungs-Zitat wird also verifiziert, selbst wenn
    # rapidfuzz im aktiven venv fehlt. Erst ein Kandidat, der WIRKLICH
    # Fuzzy-Zuordnung braucht, loest hier ModuleNotFoundError aus -- und nur
    # DESSEN Eintrag wird dadurch in server.py::match_quote_wording() (dort
    # per-Kandidat try/except) zu {"error": ...}, nicht der ganze Batch.
    from rapidfuzz import fuzz, process

    full = normalize_text(candidate)
    folded = full.casefold()
    if len(folded) < MIN_FUZZY_CANDIDATE_LEN or not entries:
        return None

    # Laengenband je Kandidat (der SQL-Vorfilter kennt nur den KUERZESTEN
    # Kandidaten des Writes): ein Vault-Zitat, das deutlich kuerzer ist als der
    # Kandidat, kann ihn nicht als Ganzes enthalten. Das haelt die Zahl der
    # Fuzzy-Vergleiche klein — sie ist der teure Teil des Aufrufs.
    lower_bound = int(len(folded) * FUZZY_LENGTH_BAND)
    pool = [entry for entry in entries if len(entry.folded) >= lower_bound]
    if not pool:
        return None

    ranked = process.extract(
        folded,
        [entry.folded for entry in pool],
        scorer=fuzz.partial_ratio,
        score_cutoff=WORDING_MATCH_THRESHOLD,
        limit=2,
    )
    if not ranked:
        return None
    _, best_score, best_index = ranked[0]
    best = pool[best_index]
    if len(ranked) > 1:
        _, second_score, second_index = ranked[1]
        different_text = pool[second_index].folded != best.folded
        if different_text and best_score - second_score <= AMBIGUITY_MARGIN:
            return None

    alignment = fuzz.partial_ratio_alignment(folded, best.folded)
    excerpt = (
        _expand_to_word_bounds(best.full, alignment.dest_start, alignment.dest_end)
        if alignment is not None
        else best.full
    )
    diff = _word_diff(full, excerpt)
    if not diff:
        # Kein Wort weicht ab -> reine Darstellungsvariante, die die billigen
        # Stufen nur wegen der Fenstergrenzen verfehlt haben.
        return QuoteWordingMatch(
            status="normalized",
            candidate=full,
            vault_verbatim=excerpt,
            quote_id=best.quote_id,
            paper_id=best.paper_id,
            ratio=float(best_score),
        )
    return QuoteWordingMatch(
        status="deviation",
        candidate=full,
        vault_verbatim=excerpt,
        quote_id=best.quote_id,
        paper_id=best.paper_id,
        ratio=float(best_score),
        diff=diff,
    )


def match_candidate(
    entries: list[_PreparedQuote], candidate: str, allow_fuzzy: bool = True
) -> QuoteWordingMatch:
    """Bestimmt den Wortlaut-Status EINES Kandidaten gegen den Snapshot.

    Args:
        entries: vorbereiteter Snapshot aus :func:`prepare_snapshot`.
        candidate: der Zitat-Text aus dem Kapitel (roh, wie im Write).
        allow_fuzzy: ``False`` schaltet nur die teure Zuordnungsstufe ab
            (Pruefkontingent) -- die billigen Stufen laufen weiter, ein nicht
            belegtes Zitat bleibt also ``absent`` und wird NICHT still
            durchgewunken.

    Raises:
        TypeError: wenn ``candidate`` kein String ist (der Aufrufer faengt das
            je Eintrag ab, damit ein kaputter Eintrag den Batch nicht entwertet).
    """
    if not isinstance(candidate, str):
        raise TypeError(f"Kandidat muss ein String sein, nicht {type(candidate).__name__}")
    full = normalize_text(candidate)
    if not full:
        return QuoteWordingMatch(status="absent", candidate=full)

    match = _substring_match(candidate, entries) or _ellipsis_match(candidate, entries)
    if match is not None:
        return match
    if allow_fuzzy:
        fuzzy = _fuzzy_match(candidate, entries)
        if fuzzy is not None:
            return fuzzy
    return QuoteWordingMatch(status="absent", candidate=full, quota_capped=not allow_fuzzy)
