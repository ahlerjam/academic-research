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
    """
    raw = raw.strip()
    if "," in raw:
        family, _, given = raw.partition(",")
        family = family.strip()
        given = given.strip()
        if family:
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
