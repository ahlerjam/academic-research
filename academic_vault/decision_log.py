"""Schreibpfad des Decision-Logs fuer den PostToolUse-Hook (Issue #527).

Bis #527 schrieb ``hooks/post-tool-use-decisions.mjs`` in die Textdatei
``~/.academic-research/decisions.log``, waehrend
``hooks/mid-session-reinforcement.mjs`` die SQLite-Tabelle ``decisions`` las —
die niemand befuellte. Dieses Modul ist die fehlende Bruecke: es schreibt die
vom Hook beobachteten Datei-Aenderungen in dieselbe Tabelle, aus der das
Reinforcement liest.

Zwei Eigenschaften bestimmen den Zuschnitt:

* **Import-Kosten.** Der Hook feuert bei *jedem* Write/Edit auf eine
  ``.md``-Datei. ``academic_vault.server`` zieht die fastmcp/pydantic-Kette
  nach (~1,2 s CPU) und ist hier tabu; importiert wird ausschliesslich
  ``academic_vault.db`` (~0,06 s).
* **Verdraengung.** Datei-Aenderungen sind keine echten Entscheidungen. Sie
  tragen deshalb die feste Kategorie ``file-change`` und bleiben pro Datei auf
  genau einen aktiven Eintrag begrenzt (Idempotenz per Hash, Supersede des
  Vorgaengers). Das Reinforcement kann sie so getrennt von den manuell
  gepflegten Decisions ausgeben.

Privacy (#191) bleibt gewahrt: gespeichert werden nur relativer Pfad,
Tool-Name und SHA-256 des Inhalts — kein Klartext.
"""

from __future__ import annotations

import sqlite3

from .db import VaultDB, VaultLockedError

#: Kategorie aller automatisch protokollierten Datei-Aenderungen. Einzige
#: Definition — Hook und Reinforcement lesen sie von hier.
AUTO_CATEGORY = "file-change"

#: Praefix des Decision-Textes. Der Text ist zugleich der Schluessel, ueber den
#: der Vorgaenger-Eintrag derselben Datei gefunden wird.
_TEXT_PREFIX = "Datei geaendert: "


def decision_text(rel_path: str) -> str:
    """Der Decision-Text zu einer Datei — stabil, damit er als Schluessel taugt."""
    return f"{_TEXT_PREFIX}{rel_path}"


def decision_rationale(tool: str, sha256: str) -> str:
    """Rationale-Feld: Tool und Inhalts-Hash, kein Klartext."""
    return f"tool={tool}; sha256={sha256}"


def content_hash(rationale: str | None) -> str | None:
    """Zieht den Inhalts-Hash aus einem Rationale-Feld (``None`` wenn keiner drin steht).

    Der Hash allein entscheidet ueber Idempotenz — nicht das Tool: dieselbe
    Datei mit demselben Inhalt einmal per ``Write`` und einmal per ``Edit``
    geschrieben ist eine Aenderung, keine zwei.
    """
    if not rationale:
        return None
    marker = "sha256="
    index = rationale.rfind(marker)
    if index < 0:
        return None
    return rationale[index + len(marker) :].strip() or None


def record_file_change(
    db_path: str,
    tool: str,
    rel_path: str,
    sha256: str,
) -> str | None:
    """Protokolliert eine Datei-Aenderung als Decision der Kategorie ``file-change``.

    Idempotent: derselbe Hash fuer dieselbe Datei legt keinen neuen Eintrag an,
    sondern liefert die vorhandene ``decision_id``. Ein anderer Hash legt einen
    neuen Eintrag an und markiert den bisherigen aktiven Eintrag derselben
    Datei per ``superseded_by`` als abgeloest — es bleibt hoechstens ein
    aktiver Auto-Eintrag pro Datei.

    Fail-open: Ist der Vault gesperrt (Material-Passport-Lock, #380), fehlt die
    ``decisions``-Tabelle oder ist die DB gerade belegt, gibt die Funktion
    ``None`` zurueck statt zu werfen. Ein PostToolUse-Hook darf an einem
    Logging-Problem nicht scheitern.

    Args:
        db_path: Pfad zur Vault-DB. Wird NICHT angelegt — existiert sie nicht,
            legt SQLite zwar eine leere Datei an, die fehlende Tabelle fuehrt
            aber zum fail-open-Pfad.
        tool: Name des ausloesenden Tools (``Write``/``Edit``/``MultiEdit``).
        rel_path: Projekt-relativer Pfad der geaenderten Datei.
        sha256: SHA-256 des geschriebenen Inhalts (kein Klartext).

    Returns:
        Die ``decision_id`` des aktiven Eintrags oder ``None`` im Fehlerfall.
    """
    text = decision_text(rel_path)
    rationale = decision_rationale(tool, sha256)

    try:
        db = VaultDB(db_path)
        existing = [
            d
            for d in db.list_decisions(category=AUTO_CATEGORY, active_only=True)
            if d.get("text") == text
        ]
        for decision in existing:
            if content_hash(decision.get("rationale")) == sha256:
                # Unveraenderter Inhalt: nichts zu tun (Idempotenz).
                return str(decision["decision_id"])

        new_id = db.add_decision(category=AUTO_CATEGORY, text=text, rationale=rationale)
        for decision in existing:
            db.supersede_decision(str(decision["decision_id"]), new_id)
        return new_id
    except (sqlite3.Error, VaultLockedError, OSError):
        return None
