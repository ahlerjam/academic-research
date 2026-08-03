"""Material Passport Builder und JSON-Schema-Validation (v6.4, Ticket #104).

Erstellt einen Material-Passport-Dict und validiert ihn gegen das JSON-Schema
in material-passport.schema.json.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

_SCHEMA_FILE = Path(__file__).parent / "material-passport.schema.json"
_MANIFEST_FILE = Path(__file__).parent.parent / ".claude-plugin" / "plugin.json"


def read_plugin_version() -> str:
    """Liest die Plugin-Version aus .claude-plugin/plugin.json.

    Wird bei jedem Aufruf frisch gelesen (kein Modul-Import-Caching), damit ein
    lang laufender MCP-Server-Prozess ueber ein Plugin-Upgrade hinweg nicht mit
    einer veralteten Version antwortet. Wirft eine sprechende Fehlermeldung statt
    still auf einen Platzhalter zurueckzufallen (#616): ein Passport, der falsch
    aussieht statt sichtbar zu scheitern, ist genau die Fehlerklasse, die dieser
    Fix beheben soll.
    """
    try:
        data = json.loads(_MANIFEST_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Plugin-Manifest nicht gefunden: {_MANIFEST_FILE}. "
            "plugin_version kann nicht ermittelt werden."
        ) from exc
    try:
        return data["version"]
    except KeyError as exc:
        raise RuntimeError(
            f"Plugin-Manifest {_MANIFEST_FILE} enthaelt kein 'version'-Feld."
        ) from exc


def build_passport(
    slug: str,
    paper_ids: list[str],
    dois: list[str],
    scores_5d: dict[str, Any],
    score_algo_version: str,
    plugin_version: str,
    model_versions: dict[str, str],
    per_uni_profile_hash: str | None,
    decisions_snapshot: list[dict],
    pdf_hashes: dict[str, str],
) -> dict:
    """Erstellt den Material-Passport-Dict.

    Der passport_hash wird ueber alle uebrigen Felder berechnet.
    """
    passport: dict[str, Any] = {
        "slug": slug,
        "paper_ids": paper_ids,
        "dois": dois,
        "download_tier": "full" if pdf_hashes else "metadata-only",
        "scores_5d": scores_5d,
        "score_algo_version": score_algo_version,
        "plugin_version": plugin_version,
        "model_versions": model_versions,
        "per_uni_profile_hash": per_uni_profile_hash,
        "decisions_snapshot": decisions_snapshot,
        "pdf_sha256_hashes": pdf_hashes,
        "created_at": int(time.time()),
    }
    # Hash ueber serialisiertes Passport-Dict (ohne passport_hash selbst)
    passport_bytes = json.dumps(passport, sort_keys=True, ensure_ascii=False).encode("utf-8")
    passport["passport_hash"] = hashlib.sha256(passport_bytes).hexdigest()
    return passport


def validate_passport(data: dict) -> None:
    """Validiert passport-Dict gegen das JSON-Schema.

    Wirft jsonschema.ValidationError bei Fehler.
    Wirft ImportError wenn jsonschema nicht installiert ist — dann wird
    Validierung uebersprungen (soft-fail).
    """
    try:
        import jsonschema
    except ImportError:
        # jsonschema nicht installiert — Validierung uebersprungen
        return

    schema = json.loads(_SCHEMA_FILE.read_text(encoding="utf-8"))
    jsonschema.validate(instance=data, schema=schema)
