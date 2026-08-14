#!/usr/bin/env python3
"""Shared utilities for academic-research v4 scripts."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Paper:
    """Normalized paper schema used across all modules."""

    doi: str | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    abstract: str | None = None
    venue: str | None = None
    citations: int = 0
    url: str | None = None
    source_module: str = ""
    oa_url: str | None = None
    open_access_pdf: str | None = None
    is_retracted: bool | None = None
    citations_normalized: float | None = None
    found_via_known_item: bool = False
    #: ISO-639-1-Sprachkuerzel der Quelle, falls das Modul eines liefert (#892).
    language: str | None = None
    #: Publikationstyp in der Schreibweise der Quelle (#892), z.B. "journal-article".
    publication_type: str | None = None
    #: Alle Publikationstypen der Quelle, wenn sie mehrere fuehrt (Semantic
    #: Scholar: ["Study", "JournalArticle"]). Die Reihenfolge sagt nichts ueber
    #: den primaeren Typ aus, deshalb zaehlt im Vorfilter die ganze Liste.
    publication_types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Paper:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


def normalize_paper(data: dict[str, Any], source_module: str) -> dict[str, Any]:
    """Normalize source-specific payload to common paper schema dict."""
    return {
        "doi": data.get("doi"),
        "title": data.get("title"),
        "authors": data.get("authors") or [],
        "year": data.get("year"),
        "abstract": data.get("abstract"),
        "venue": data.get("venue"),
        "citations": int(data.get("citations") or 0),
        "url": data.get("url"),
        "source_module": source_module,
        "oa_url": data.get("oa_url"),
        "open_access_pdf": data.get("open_access_pdf"),
        "is_retracted": data.get("is_retracted"),
        "citations_normalized": data.get("citations_normalized"),
        "found_via_known_item": bool(data.get("found_via_known_item", False)),
        # Vorfilter-Metadaten (#892): fehlend bleibt None -- der mechanische
        # Vorfilter schliesst bei Unwissen NIE aus, er legt den Fall dem Modell vor.
        "language": data.get("language") or None,
        "publication_type": data.get("publication_type") or None,
        "publication_types": [str(t) for t in (data.get("publication_types") or []) if t],
    }


@dataclass
class ParsedAuthorName:
    """Ergebnis von :func:`parse_author_name` (Issue #908).

    ``family``/``given`` sind nur gesetzt, wenn der Rohstring zuverlaessig
    zerlegbar war (``parsed=True``). Unklare Faelle (Organisationen,
    mehrteilige/nicht-westliche Namen ohne Komma-Trenner) werden NICHT
    geraten -- sie landen unveraendert in ``literal`` mit ``parsed=False``.
    ``warning`` wird ausschliesslich von :func:`parse_author_names` gesetzt
    (Plausibilitaetscheck ueber ein ganzes Autoren-Datenset hinweg).
    """

    family: str | None = None
    given: str | None = None
    literal: str | None = None
    parsed: bool = False
    warning: str | None = None

    def display_name(self) -> str:
        """Kanonische Anzeigeform ('Given Family'), fuer ``Paper.authors``."""
        if self.given and self.family:
            return f"{self.given} {self.family}".strip()
        if self.family:
            return self.family
        if self.given:
            return self.given
        return self.literal or ""


_ORG_KEYWORDS = (
    "universität",
    "university",
    "universitaet",
    "institut",
    "institute",
    "fakultät",
    "fakultaet",
    "faculty",
    "hochschule",
    "college",
    "akademie",
    "academy",
    "ministerium",
    "ministry",
    "behörde",
    "behoerde",
    "agency",
    "amt",
    "bundesamt",
    "landesamt",
    "kommission",
    "commission",
    "committee",
    "ausschuss",
    "council",
    "gmbh",
    "kgaa",
    "e.v.",
    "inc.",
    "ltd.",
    "llc",
    "corp.",
    "corporation",
    "foundation",
    "stiftung",
    "verband",
    "association",
    "gesellschaft",
    "society",
    "bank",
    "zentrum",
    "center",
    "centre",
    "department",
    "abteilung",
    "büro",
    "buero",
    "office",
    "bureau",
    "verwaltung",
    "administration",
    "organisation",
    "organization",
    "vereinigung",
    "kammer",
    "chamber",
    "senat",
    "senate",
    "parlament",
    "parliament",
    "regierung",
    "government",
    "nations",
    "school of",
    "press",
    "verlag",
    "consortium",
    "konsortium",
    "network",
    "netzwerk",
)

# Kleingeschriebene Namensbestandteile, die auch innerhalb echter
# Personennamen vorkommen (Adelspraedikate, Praepositionen) und daher NICHT
# als Indiz fuer eine Koerperschafts-/Ortsangabe gelten duerfen.
_NAME_CONNECTORS = frozenset(
    {"van", "von", "der", "den", "de", "di", "la", "le", "do", "dos", "da", "bin", "ibn", "al"}
)


def _looks_like_organization(text: str) -> bool:
    """Erkennt Koerperschafts-/Behoerden-Bezeichnungen anhand von
    Schluesselwoertern oder eines Akronym-Musters (z.B. ``OECD``).

    Reine Namensbestandteile (Nach- oder Vornamen) treffen weder auf ein
    Schluesselwort noch auf das Akronym-Muster (2-6 Grossbuchstaben ohne
    Kleinbuchstaben-Mischung)."""
    lowered = text.lower()
    if any(re.search(rf"\b{re.escape(keyword)}\b", lowered) for keyword in _ORG_KEYWORDS):
        return True
    # Akronym-Muster (z.B. "OECD") nur auf EINZELNE, leerzeichenfreie Tokens
    # anwenden. Sonst kollabieren mehrteilige Initialen wie "J. R." zu "JR"
    # und wuerden faelschlich als Organisations-Akronym erkannt (Issue #908
    # P1-Regression, Fall "O'Brien, J. R.").
    if " " not in text.strip():
        compact = text.replace(".", "")
        if compact.isalpha() and compact.isupper() and 2 <= len(compact) <= 6:
            return True
    return False


def _looks_like_given_name_part(given: str) -> bool:
    """Prueft, ob der Teil nach dem Komma wie ein Vorname/Initialen aussieht
    -- und nicht wie eine Organisations- oder Ortsangabe (Issue #908 P1:
    Dublin-Core-``dc:creator`` enthaelt haeufig Koerperschaften/Orte mit
    Komma, z.B. ``"Universität Leipzig, Institut für
    Wirtschaftsinformatik"`` oder ``"OECD, Paris"``). Ein echter Vorname
    besteht aus wenigen (<=3) grossgeschriebenen Woertern/Initialen bzw.
    bekannten Namenspartikeln; institutionelle Zusaetze enthalten dagegen
    Schluesselwoerter oder kleingeschriebene Fuellwoerter wie ``"für"``."""
    if not given or _looks_like_organization(given):
        return False
    tokens = given.split()
    if not tokens or len(tokens) > 3:
        return False
    for token in tokens[1:]:
        bare = token.strip(".,")
        if not bare or bare.lower() in _NAME_CONNECTORS:
            continue
        if not bare[0].isupper():
            return False
    return True


def parse_author_name(raw: str) -> ParsedAuthorName:
    """Zerlegt einen rohen Autoren-String in Vor-/Nachname (Issue #908).

    Erkennt zuverlaessig NUR das Dublin-Core-Komma-Format
    ``"Nachname, Vorname"`` (EconStor/BASE ``dccreator``, DNB MARC 100/700).
    Alles andere (bereits fertige "Vorname Nachname"-Strings, Organisationen,
    mehrteilige Nachnamen ohne Komma) wird NICHT per "letztes Wort =
    Nachname" geraten -- genau dieser Griff hat die drei Falschzitate vom
    12.08.2026 erzeugt, wenn er auf einen noch nicht erkannten Komma-String
    angewendet wurde. Stattdessen bleibt der Rohstring unveraendert in
    ``literal`` mit ``parsed=False``.

    P1-Nachschaerfung (Deep Review zu PR #933): ``dc:creator`` enthaelt in
    EconStor/BASE-Daten haeufig Koerperschafts- oder Ortsangaben, die
    ebenfalls ein Komma enthalten (``"Universität Leipzig, Institut für
    Wirtschaftsinformatik"``, ``"OECD, Paris"``). Ein blindes Komma-Split
    wuerde auch diese umkehren und ein sinnloses "Nachname" fabrizieren, das
    als Falschzitat landet. Deshalb wird zusaetzlich geprueft, ob der Teil
    VOR dem Komma wie eine Organisation aussieht (Schluesselwort oder
    Akronym) und ob der Teil NACH dem Komma wie ein Vorname/Initialen
    aussieht (:func:`_looks_like_given_name_part`). Nur wenn beide Pruefungen
    unauffaellig sind, gilt der Eintrag als zuverlaessig zerlegbar.
    """
    raw = raw.strip()
    if "," in raw:
        family, _, given = raw.partition(",")
        family = family.strip()
        given = given.strip()
        if (
            family
            and not _looks_like_organization(family)
            and (not given or _looks_like_given_name_part(given))
        ):
            return ParsedAuthorName(
                family=family,
                given=given or None,
                parsed=True,
            )
    return ParsedAuthorName(literal=raw, parsed=False)


def _flag_implausible_splits(parsed: list[ParsedAuthorName]) -> list[ParsedAuthorName]:
    """Markiert Eintraege, deren Nachname auch als Vorname im selben
    Datensatz auftaucht (Issue #908 AC4) -- gemeinsame Plausibilitaetslogik
    fuer :func:`parse_author_names` (Roh-Strings) und
    :func:`csl_authors_to_parsed` (bereits zerlegtes CSL-JSON, siehe
    ``scripts/audit_author_names.py``)."""
    given_names_lower = {p.given.strip().lower() for p in parsed if p.given}
    for p in parsed:
        if p.family and p.family.strip().lower() in given_names_lower:
            p.warning = (
                f"Nachname '{p.family}' taucht auch als Vorname im selben "
                "Datensatz auf -- moeglicherweise vertauschte Reihenfolge."
            )
    return parsed


def parse_author_names(raw_names: list[str]) -> list[ParsedAuthorName]:
    """Parst eine ganze Autorenliste und markiert unplausible Zerlegungen.

    Plausibilitaetscheck (Issue #908 AC4): landet der ermittelte Nachname
    eines Eintrags auch als Vorname eines (beliebigen) Eintrags desselben
    Datensatzes, deutet das auf vertauschte Reihenfolge hin -- das Ergebnis
    wird trotzdem zurueckgegeben (kein Raten, kein Verwerfen), nur mit
    ``warning`` versehen.
    """
    return _flag_implausible_splits([parse_author_name(raw) for raw in raw_names])


def csl_authors_to_parsed(csl_authors: list[dict[str, Any]]) -> list[ParsedAuthorName]:
    """Wandelt bereits zerlegte CSL-JSON-Autoren-Dicts in :class:`ParsedAuthorName`
    um und wendet denselben Plausibilitaetscheck an wie :func:`parse_author_names`.

    Fuer den Bestandscheck (Issue #908 AC5, ``scripts/audit_author_names.py``):
    CSL-Autoren liegen im Vault bereits als ``{"family": ..., "given": ...}``
    oder ``{"literal": ...}`` vor (kein Roh-String mehr zu parsen), aber
    derselbe "Nachname == Vorname eines Co-Autors"-Check ist weiterhin
    sinnvoll, um bereits vertauschte Bestandsdaten aufzuspueren.
    """
    parsed: list[ParsedAuthorName] = []
    for entry in csl_authors:
        if not isinstance(entry, dict):
            continue
        family = entry.get("family")
        given = entry.get("given")
        if family:
            parsed.append(ParsedAuthorName(family=str(family), given=given, parsed=True))
        else:
            literal = entry.get("literal") or entry.get("name")
            parsed.append(ParsedAuthorName(literal=literal, parsed=False))
    return _flag_implausible_splits(parsed)


_DOI_PREFIXES = (
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "https://doi.org/",
    "http://doi.org/",
    "dx.doi.org/",
    "doi.org/",
    "urn:doi:",
    "doi:",
)


def normalize_doi(doi: str | None) -> str | None:
    """Normalize DOI to lowercase without URL/URN prefix or trailing punctuation."""
    if not doi:
        return None
    value = doi.strip().lower()
    for prefix in _DOI_PREFIXES:
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    value = value.rstrip(".,;")
    return value or None


def tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase alphanumeric terms."""
    return [t for t in re.split(r"[^a-z0-9äöüß]+", text.lower()) if t]


def safe_filename(text: str, max_length: int = 80) -> str:
    """Create a filesystem-safe filename from text."""
    clean = re.sub(r"[^\w\s-]", "", text.lower())
    clean = re.sub(r"[\s_]+", "_", clean).strip("_")
    return clean[:max_length]


def load_json(path: str | Path) -> Any:
    """Load JSON from file."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_json(data: Any, path: str | Path, indent: int = 2) -> None:
    """Save data as JSON to file."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=indent)


def load_yaml(path: str | Path) -> Any:
    """Load YAML from file."""
    import yaml

    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)
