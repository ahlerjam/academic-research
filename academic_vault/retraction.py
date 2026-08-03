"""retraction.py — geteilte Crossref-Retraction-Pruefung (Issue #604).

Extrahiert aus ``skills/reading-list-import/scripts/parse_list.py`` (Issue
#383), wo die Pruefung urspruenglich als fail-safe ``-> bool`` lebte. Der
vault-weite Check (``academic_vault.server.check_retractions``, #604) braucht
bei Crossref-Ausfall eine sichtbare Fehlermeldung (AC7) statt eines leeren
"keine Rueckzuege"-Ergebnisses -- mit einem ``bool``-Rueckgabewert sind
"sauber" und "Fehler" nicht unterscheidbar. Der neue Rueckgabetyp
``RetractionCheckResult`` trennt ``retracted``/``clean``/``error`` explizit
(vgl. Plan-Kommentar zu #604, Widerspruch 2 aus der Gegenpruefung).

``reading-list-import`` bleibt an seinem alten Vertrag (fail-safe ``-> bool``,
automatisches ``excluded_sources``, Issue #383 AC3) -- der dortige
``check_retraction()``-Wrapper adaptiert nur die Signatur, ohne das Verhalten
zu aendern (Widerspruch 1, bewusst nicht aufgeloest -- ausserhalb des Scopes
von #604).

Die Crossref-Semantik selbst (``updated-by`` vs. ``update-to``) ist unter
Issue #419 einmal falsch herum implementiert und wieder korrigiert worden:
``message.updated-by`` mit ``type == "retraction"`` haengt Crossref an den
ZURUECKGEZOGENEN Artikel; das Gegenstueck ``message.update-to`` gehoert zur
Retraction-NOTIZ und zeigt von dieser auf den Artikel.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

try:
    import requests

    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

CROSSREF_WORKS_URL = "https://api.crossref.org/works/{doi}"
_DOI_URL_RE = re.compile(r"(?:https?://)?(?:dx\.)?doi\.org/(.+)")

RetractionStatus = Literal["retracted", "clean", "error"]


@dataclass(frozen=True)
class RetractionCheckResult:
    """Ergebnis einer Crossref-Retraction-Pruefung fuer einen DOI.

    Attributes:
        status: ``"retracted"`` wenn Crossref ``updated-by`` mit
            ``type == "retraction"`` ausweist; ``"clean"`` wenn Crossref
            antwortet, aber ohne Retraction-Update; ``"error"`` bei
            Netzwerk-/Parse-Fehler, Nicht-200-Antwort oder leerem DOI --
            bewusst NICHT gleich ``"clean"``, damit ein Crossref-Ausfall
            sichtbar bleibt (AC7, Issue #604).
        doi: der gepruefte DOI (unveraendert wie uebergeben).
        source: bei ``status == "retracted"`` die Fundstelle -- der
            Crossref-DOI der Retraction-Notiz aus ``updated-by[].DOI``
            (Fallback: ``label`` bzw. ein generischer Hinweistext), damit die
            Entscheidung des Nutzers nachvollziehbar bleibt. Sonst ``None``.
        error_message: bei ``status == "error"`` die Fehlerursache in
            Klartext. Sonst ``None``.
    """

    status: RetractionStatus
    doi: str
    source: str | None = None
    error_message: str | None = None


def normalize_doi(doi: str) -> str:
    """Normalisiert DOI: entfernt doi.org-Praefix."""
    doi = doi.strip()
    m = _DOI_URL_RE.match(doi)
    if m:
        doi = m.group(1)
    return doi


def _retraction_source(updated_by: object) -> str | None:
    """Gibt die Fundstelle (Crossref-DOI der Retraction-Notiz) zurueck oder None.

    Robust gegen fehlendes Feld und gegen explizites JSON-null: Crossref
    liefert ``updated-by`` nur bei tatsaechlich aktualisierten Werken.
    """
    if not isinstance(updated_by, list):
        return None
    for entry in updated_by:
        if isinstance(entry, dict) and entry.get("type") == "retraction":
            return (
                entry.get("DOI")
                or entry.get("label")
                or "Crossref: updated-by mit type=retraction (keine DOI/Label-Angabe)"
            )
    return None


def check_retraction(doi: str) -> RetractionCheckResult:
    """Prueft via Crossref ob ein DOI als zurueckgezogen (retracted) markiert ist.

    Nutzt die seit 09/2023 in Crossref integrierten Retraction-Watch-Daten.
    Ausgewertet wird ``message.updated-by`` mit ``type == "retraction"`` (s.
    Modul-Docstring zur Relation ``updated-by``/``update-to``, Regression PR
    #419).

    Anders als die fail-safe Vorgaengerfunktion (``-> bool``, Issue #383)
    unterscheidet der Rueckgabetyp hier ``"clean"`` von ``"error"``: ein
    leerer DOI, eine nicht-200-Antwort, ein Netzwerk- oder Parse-Fehler
    liefern ``"error"`` mit Klartext-Ursache statt stillschweigend als
    "kein Rueckzug" durchzugehen.
    """
    doi = (doi or "").strip()
    if not doi:
        return RetractionCheckResult(status="error", doi=doi, error_message="Kein DOI angegeben.")
    if not _REQUESTS_AVAILABLE:
        return RetractionCheckResult(
            status="error",
            doi=doi,
            error_message="Python-Paket 'requests' ist nicht verfuegbar.",
        )

    doi_clean = normalize_doi(doi)
    url = CROSSREF_WORKS_URL.format(doi=doi_clean)

    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "academic-research/1.0"})
    except Exception as exc:
        return RetractionCheckResult(
            status="error", doi=doi, error_message=f"Crossref-Anfrage fehlgeschlagen: {exc}"
        )

    if resp.status_code != 200:
        return RetractionCheckResult(
            status="error",
            doi=doi,
            error_message=f"Crossref antwortete mit HTTP {resp.status_code}.",
        )

    try:
        msg = resp.json().get("message", {})
    except Exception as exc:
        return RetractionCheckResult(
            status="error", doi=doi, error_message=f"Crossref-Antwort nicht auswertbar: {exc}"
        )

    source = _retraction_source(msg.get("updated-by"))
    if source is not None:
        return RetractionCheckResult(status="retracted", doi=doi, source=source)
    return RetractionCheckResult(status="clean", doi=doi)
