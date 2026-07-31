#!/usr/bin/env python3
"""Deterministischer Teil des qualitative-coding-Skills (Issue #473).

Drei Subcommands:

``import``
    Segmentiert eine Transkriptdatei und schreibt sie belegfaehig in den Vault.
    Das Transkript selbst wird als ``papers``-Zeile mit
    ``source_kind='primary'`` gefuehrt -- nur so greift die bestehende
    Belegkette (``quotes.paper_id`` -> ``papers``, ``verbatim-guard``). Die
    Absatznummer ``seq`` ist die zitierfaehige Stellenangabe ("Abs. 12").

``overview``
    Rendert die Kodier-Uebersicht (Kategorie, Herkunft, Haeufigkeit,
    Ankerzitat) als Markdown -- Grundlage des Ergebniskapitels.

``codebook``
    Schreibt den Kodierleitfaden nach ``empirie/kodierleitfaden.md`` und
    haelt das Vorgehen (Verfahrensreferenz, Abstraktionsniveau,
    Selektionskriterium) als Decision-Log-Eintrag fest.

Alles Urteilende -- welche Kategorie eine Stelle traegt, wie sie definiert
ist -- bleibt bewusst ausserhalb dieses Skripts (Skill-Prosa). Hier passiert
nur, was deterministisch und wiederholbar sein muss.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Repo-Root in den Pfad, damit ``academic_vault`` importierbar ist, wenn das
# Skript direkt aus dem Skill-Verzeichnis gestartet wird (Muster wie in den
# uebrigen Skill-Skripten).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from academic_vault import server as vault_server  # noqa: E402
from academic_vault.db import VaultDB  # noqa: E402

# Timecode am Absatzanfang: [00:12:35] / (12:35) / [12:35]
_TIMECODE_RE = re.compile(r"^[\[(](\d{1,2}:\d{2}(?::\d{2})?)[\])]\s*")
# Sprecherkuerzel am Absatzanfang: "B1:", "I:", "IP_2:". Bewusst kurz und ohne
# Leerzeichen -- ein Doppelpunkt mitten im Satz darf nicht als Sprecher gelten.
_SPEAKER_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]{0,11}):\s+")

# Maximale Laenge eines Ankerzitats in der Uebersicht.
_ANCHOR_MAX_CHARS = 200

NO_ANCHOR = "— kein Ankerzitat hinterlegt —"
NO_RULE = "— Kodierregel noch nicht festgehalten —"


# ---------------------------------------------------------------------------
# Segmentierung
# ---------------------------------------------------------------------------


def parse_transcript(text: str) -> list[dict]:
    """Zerlegt einen Transkript-Text in Segmente.

    Segmentgrenze ist die Leerzeile (ein Absatz = eine zitierfaehige Stelle).
    Sprecherkuerzel und Timecode werden in eigene Felder gezogen, statt im
    Zitattext stehen zu bleiben -- sonst enthielte jedes woertliche Zitat
    Metadaten, die die Befragte nie gesagt hat.

    Returns:
        Liste von ``{"seq", "speaker", "timecode", "text"}`` mit ``seq`` ab 1.
    """
    segments: list[dict] = []
    for block in re.split(r"\n\s*\n", text):
        raw = " ".join(block.split())
        if not raw:
            continue

        timecode: str | None = None
        speaker: str | None = None

        tc_match = _TIMECODE_RE.match(raw)
        if tc_match:
            timecode = tc_match.group(1)
            raw = raw[tc_match.end() :]

        sp_match = _SPEAKER_RE.match(raw)
        if sp_match:
            speaker = sp_match.group(1)
            raw = raw[sp_match.end() :]

        if not raw:
            continue

        segments.append(
            {
                "seq": len(segments) + 1,
                "speaker": speaker,
                "timecode": timecode,
                "text": raw,
            }
        )
    return segments


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


def import_transcript(
    db_path: str,
    paper_id: str,
    transcript_path: str,
    title: str | None = None,
) -> dict:
    """Importiert eine Transkriptdatei in den Vault. Idempotent.

    Das Paper wird mit ``source_kind='primary'`` angelegt bzw. aktualisiert.
    Der CSL-``type`` bleibt ``article-journal``: ``papers.type`` traegt einen
    CHECK-Constraint auf die drei unterstuetzten CSL-Typen, und ein
    Schema-Rebuild nur fuer ein Label waere unverhaeltnismaessig. Erkennbar
    ist Primaermaterial an ``source_kind``, nicht am CSL-Typ.

    Returns:
        ``{"paper_id", "segments", "path"}``.
    """
    path = Path(transcript_path)
    if not path.exists():
        raise FileNotFoundError(f"Transkriptdatei nicht gefunden: {transcript_path}")

    segments = parse_transcript(path.read_text(encoding="utf-8"))
    if not segments:
        raise ValueError(f"Transkript enthaelt keine lesbaren Absaetze: {transcript_path}")

    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(
        paper_id=paper_id,
        csl_json=json.dumps(
            {"title": title or paper_id, "type": "article-journal"},
            ensure_ascii=False,
        ),
        source_kind="primary",
    )
    for segment in segments:
        db.add_transcript_segment(
            paper_id=paper_id,
            seq=segment["seq"],
            text=segment["text"],
            speaker=segment["speaker"],
            timecode=segment["timecode"],
        )

    return {"paper_id": paper_id, "segments": len(segments), "path": str(path)}


# ---------------------------------------------------------------------------
# Aggregation fuer overview/codebook
# ---------------------------------------------------------------------------


def _shorten(text: str, limit: int = _ANCHOR_MAX_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def collect_categories(db_path: str, paper_id: str | None = None) -> list[dict]:
    """Aggregiert Kodierungen je Kategorie.

    Returns:
        Liste von ``{"category", "origins", "count", "anchor", "rule"}``,
        alphabetisch nach Kategorie. ``anchor`` ist ``None``, solange kein
        Ankerzitat im Vault haengt -- es wird keines erfunden.
    """
    # Bewusst ueber die server-Schicht statt direkt ueber VaultDB: dort haengt
    # `_ensure_schema_for_read()`, das die Empirie-Tabellen auf einem vor #473
    # angelegten Vault einmalig nachzieht. Direkt auf VaultDB gelesen, endete
    # `overview` dort in `sqlite3.OperationalError: no such table: codings`
    # statt in der Leermeldung (Review-P1 zu PR #561). Ein `init_schema()` an
    # dieser Stelle waere die falsche Abhilfe -- es macht aus dem Lesepfad
    # einen DDL-Schreibvorgang, genau das, was der Guard vermeidet.
    grouped: dict[str, dict] = {}

    for coding in vault_server.list_codings(db_path, paper_id=paper_id):
        entry = grouped.setdefault(
            coding["category"],
            {
                "category": coding["category"],
                "origins": [],
                "count": 0,
                "anchor": None,
                "rule": None,
            },
        )
        entry["count"] += 1
        if coding["category_origin"] not in entry["origins"]:
            entry["origins"].append(coding["category_origin"])
        if entry["rule"] is None and coding["memo"]:
            entry["rule"] = coding["memo"]
        if entry["anchor"] is None and coding["quote_id"]:
            quote = vault_server.get_quote(db_path, coding["quote_id"])
            if quote is not None:
                entry["anchor"] = {
                    "quote_id": quote["quote_id"],
                    "verbatim": quote["verbatim"],
                    "section": quote["section"],
                }

    for entry in grouped.values():
        entry["origins"].sort()
    return [grouped[key] for key in sorted(grouped)]


def _anchor_cell(anchor: dict | None) -> str:
    if anchor is None:
        return NO_ANCHOR
    location = f", {anchor['section']}" if anchor.get("section") else ""
    return f'„{_shorten(anchor["verbatim"])}" (`{anchor["quote_id"]}`{location})'


# ---------------------------------------------------------------------------
# overview
# ---------------------------------------------------------------------------


def render_overview(db_path: str, paper_id: str | None = None) -> str:
    """Rendert die Kodier-Uebersicht als Markdown."""
    categories = collect_categories(db_path, paper_id)
    scope = paper_id or "alle Erhebungen"
    lines = [f"# Kodier-Übersicht — {scope}", ""]

    if not categories:
        lines += ["> Noch keine Kodierungen im Vault.", ""]
        return "\n".join(lines)

    lines += [
        "| Kategorie | Herkunft | Häufigkeit | Ankerzitat |",
        "| --- | --- | --- | --- |",
    ]
    for entry in categories:
        lines.append(
            f"| {entry['category']} | {'/'.join(entry['origins'])} | "
            f"{entry['count']} | {_anchor_cell(entry['anchor'])} |"
        )
    lines += [
        "",
        f"Summe: {sum(e['count'] for e in categories)} Kodierungen "
        f"in {len(categories)} Kategorien.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# codebook
# ---------------------------------------------------------------------------


def write_codebook(
    db_path: str,
    output_path: str,
    paper_id: str | None = None,
    verfahren: str = "",
    abstraktionsniveau: str = "",
    selektionskriterium: str = "",
) -> dict:
    """Schreibt den Kodierleitfaden und protokolliert das Vorgehen.

    Der Leitfaden wird ausschliesslich aus vorhandenen Kodierungen gerendert;
    fehlende Definitionen/Ankerbeispiele werden als fehlend markiert statt
    ausgefuellt. Das Vorgehen (Verfahrensreferenz, Abstraktionsniveau,
    Selektionskriterium) landet zusaetzlich im Decision-Log
    (``category="kodierung"``) -- ohne diesen Eintrag waere im Methodenkapitel
    nur das Ergebnis dokumentiert, nicht der Weg dorthin.

    Returns:
        ``{"output_path", "categories", "decision_id"}``.
    """
    if not verfahren.strip():
        raise ValueError(
            "verfahren ist Pflicht: ohne Verfahrensreferenz (z. B. "
            "'Qualitative Inhaltsanalyse nach Mayring') ist die Kategorienbildung "
            "nicht dokumentiert."
        )

    categories = collect_categories(db_path, paper_id)
    scope = paper_id or "alle Erhebungen"

    lines = [
        f"# Kodierleitfaden — {scope}",
        "",
        "> Generiert aus dem Vault (`transcript_import.py codebook`).",
        "> Kategorien, Ankerbeispiele und Kodierregeln stammen aus "
        "`vault.list_codings()` — fehlende Angaben sind als fehlend markiert, "
        "nicht ergänzt.",
        "",
        "## Verfahren",
        "",
        f"- **Verfahrensreferenz:** {verfahren}",
        f"- **Abstraktionsniveau:** {abstraktionsniveau or '— nicht festgelegt —'}",
        f"- **Selektionskriterium:** {selektionskriterium or '— nicht festgelegt —'}",
        "",
        "## Kategorien",
        "",
    ]

    if not categories:
        lines += ["> Noch keine Kodierungen im Vault.", ""]
    for entry in categories:
        lines += [
            f"### {entry['category']}",
            "",
            f"- **Herkunft:** {'/'.join(entry['origins'])}",
            f"- **Häufigkeit:** {entry['count']}",
            f"- **Ankerbeispiel:** {_anchor_cell(entry['anchor'])}",
            f"- **Kodierregel:** {entry['rule'] or NO_RULE}",
            "",
        ]

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")

    db = VaultDB(db_path)
    db.init_schema()
    decision_id = db.add_decision(
        category="kodierung",
        text=(
            f"Kategorienbildung nach {verfahren}. "
            f"Abstraktionsniveau: {abstraktionsniveau or 'nicht festgelegt'}. "
            f"Selektionskriterium: {selektionskriterium or 'nicht festgelegt'}."
        ),
        rationale=(
            f"Kodierleitfaden mit {len(categories)} Kategorien nach "
            f"{target} geschrieben (Scope: {scope})."
        ),
    )

    return {
        "output_path": str(target),
        "categories": len(categories),
        "decision_id": decision_id,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--db", required=True, help="Pfad zur Vault-DB")
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import", help="Transkriptdatei segmentieren und importieren")
    imp.add_argument("--paper-id", required=True)
    imp.add_argument("--file", required=True, help="Pfad zur Transkriptdatei (.txt/.md)")
    imp.add_argument("--title", default=None)

    ovw = sub.add_parser("overview", help="Kodier-Uebersicht als Markdown ausgeben")
    ovw.add_argument("--paper-id", default=None)

    cbk = sub.add_parser("codebook", help="Kodierleitfaden schreiben + Vorgehen protokollieren")
    cbk.add_argument("--paper-id", default=None)
    cbk.add_argument("--output", default="empirie/kodierleitfaden.md")
    cbk.add_argument("--verfahren", required=True)
    cbk.add_argument("--abstraktionsniveau", default="")
    cbk.add_argument("--selektionskriterium", default="")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "import":
        result = import_transcript(
            db_path=args.db,
            paper_id=args.paper_id,
            transcript_path=args.file,
            title=args.title,
        )
        print(json.dumps(result, ensure_ascii=False))
    elif args.command == "overview":
        print(render_overview(db_path=args.db, paper_id=args.paper_id))
    else:
        result = write_codebook(
            db_path=args.db,
            output_path=args.output,
            paper_id=args.paper_id,
            verfahren=args.verfahren,
            abstraktionsniveau=args.abstraktionsniveau,
            selektionskriterium=args.selektionskriterium,
        )
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
