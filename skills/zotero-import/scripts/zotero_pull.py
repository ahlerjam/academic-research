"""zotero_pull.py — Zotero-Import-Logik fuer academic-research Plugin.

Liest Items und PDF-Attachments aus einer Zotero-Library, dedupliziert via
DOI/ISBN gegen den Vault. PDFs werden in temporaere Verzeichnisse heruntergeladen
und pdf_path im Vault gespeichert; Files-API-Upload ist optional (erfordert
ANTHROPIC_API_KEY) fuer den optionalen Citations-API-Zitatweg, siehe
skills/chapter-writer/references/citations-api.md. Ohne Key wird dieser
Upload uebersprungen und in ``ImportResult.files_api_skipped`` gezaehlt (#535)
— ein fehlender Key ist kein Importfehler. Lokale Zitierung via
vault.add_quote(extraction_method="local-verbatim") ist nur moeglich, wenn
pdf_path noch verfuegbar ist.

Aufruf:
    python skills/zotero-import/scripts/zotero_pull.py \\
        --config ~/.academic-research/config.yaml \\
        --db vault.db

Sicherheit:
    - zotero_api_key erscheint NIEMALS in Logs oder Outputs.
    - config.yaml muss Permissions 0600 haben.
    - Netz-Zugriff: ausschliesslich api.zotero.org (via pyzotero).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import yaml

logger = logging.getLogger(__name__)

# pyzotero: optionale Dep — fruehzeitiger Import fuer testbaren Mock-Punkt
try:
    from pyzotero import zotero  # noqa: F401
except ImportError:  # pragma: no cover
    zotero = None  # type: ignore[assignment]

# Vault-Funktionen direkt importieren (kein MCP-Roundtrip noetig)
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))
from academic_vault.files_api import is_configured as files_api_configured  # noqa: E402
from academic_vault.server import add_paper, add_quote, ensure_file  # noqa: E402

# ---------------------------------------------------------------------------
# Datenklassen
# ---------------------------------------------------------------------------


@dataclass
class ImportResult:
    """Ergebnis eines Zotero-Import-Laufs."""

    imported: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    file_ids: list[str] = field(default_factory=list)
    quotes_imported: int = 0
    # Annotationen mit Kommentar, aber ohne markierten Quellentext (Notiz-,
    # Bild-, Ink-Annotationen). Sie werden bewusst nicht als Quote importiert
    # (siehe _annotation_verbatim) — der Zaehler haelt das sichtbar, damit
    # fehlende PDF-Notizen nach dem Import nicht als stiller Datenverlust
    # dastehen.
    comments_skipped: int = 0
    # Volltexte, die aus Zoteros eigenem `fulltext_item()`-Endpunkt kamen statt
    # aus lokaler PDF-Extraktion (Issue #525) — spart Download+Re-Extraktion.
    fulltext_from_zotero: int = 0
    # Faelle, in denen Zotero-Volltext nicht verfuegbar war (nicht indiziert,
    # leer, oder sonstiger Fehler bei `fulltext_item()`) und sauber auf den
    # lokalen PDF-Parse-Pfad zurueckgefallen wurde (Issue #525 AC2 — dieser
    # Fallback muss geloggt und gezaehlt werden, nicht still bleiben).
    fulltext_fallback_local: int = 0
    # PDFs, fuer die der optionale Files-API-Upload uebersprungen wurde, weil
    # kein eigener ANTHROPIC_API_KEY gesetzt ist (#535). Der Zaehler haelt den
    # Skip sichtbar, ohne ihn als Importfehler zu zaehlen.
    files_api_skipped: int = 0


# ---------------------------------------------------------------------------
# Config-Laden mit 0600-Check
# ---------------------------------------------------------------------------


def load_config(config_path: str) -> dict:
    """Laedt config.yaml und prueft 0600-Permissions.

    Raises:
        PermissionError: wenn Datei nicht exakt 0600 Permissions hat.
        FileNotFoundError: wenn Datei nicht existiert.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config nicht gefunden: {config_path}")

    file_stat = path.stat()
    mode = stat.S_IMODE(file_stat.st_mode)
    if mode != 0o600:
        raise PermissionError(
            f"Config {config_path} hat unsichere Permissions {oct(mode)}. "
            f"Erforderlich: 0600. Bitte ausfuehren: chmod 0600 {config_path}"
        )

    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# DOI/ISBN Normalisierung
# ---------------------------------------------------------------------------


def _normalize_doi(doi: str) -> str | None:
    """Normalisiert DOI: lowercase, strip https://doi.org/ Prefix."""
    if not doi or not doi.strip():
        return None
    doi = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
    return doi or None


def _normalize_isbn(isbn: str) -> str | None:
    """Normalisiert ISBN: entfernt Leerzeichen und Bindestriche, lowercase."""
    if not isbn or not isbn.strip():
        return None
    return isbn.strip().replace("-", "").replace(" ", "").lower() or None


# ---------------------------------------------------------------------------
# Vault-Dedup-Pruefung
# ---------------------------------------------------------------------------


def _paper_exists_in_vault(db_path: str, doi: str | None, isbn: str | None) -> bool:
    """Prueft ob ein Paper mit diesem DOI oder ISBN bereits im Vault ist."""
    if not doi and not isbn:
        return False  # Kein Identifier → immer importieren

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if doi:
            row = conn.execute(
                "SELECT paper_id FROM papers WHERE lower(doi) = ?", (doi,)
            ).fetchone()
            if row:
                return True
        if isbn:
            # ISBN-Vergleich: beide normalisiert (Bindestriche entfernt)
            rows = conn.execute("SELECT isbn FROM papers WHERE isbn IS NOT NULL").fetchall()
            for r in rows:
                if _normalize_isbn(r["isbn"]) == isbn:
                    return True
    finally:
        conn.close()
    return False


# ---------------------------------------------------------------------------
# Zotero-Item zu CSL-JSON konvertieren
# ---------------------------------------------------------------------------

_ITEM_TYPE_MAP = {
    "journalArticle": "article-journal",
    "book": "book",
    "bookSection": "chapter",
    "conferencePaper": "paper-conference",
    "thesis": "thesis",
    "report": "report",
    "webpage": "webpage",
    "magazineArticle": "article-magazine",
    "newspaperArticle": "article-newspaper",
}


def _zotero_item_to_csl(item_data: dict) -> dict:
    """Konvertiert Zotero-Item-Data in ein CSL-JSON-kompatibles dict."""
    item_type = _ITEM_TYPE_MAP.get(item_data.get("itemType", ""), "article-journal")

    authors = []
    for creator in item_data.get("creators", []):
        if creator.get("creatorType") in ("author", "editor"):
            authors.append(
                {
                    "family": creator.get("lastName", ""),
                    "given": creator.get("firstName", ""),
                }
            )

    csl = {
        "type": item_type,
        "title": item_data.get("title", ""),
        "author": authors,
        "issued": {
            "date-parts": [[item_data.get("date", "")[:4] if item_data.get("date") else ""]]
        },
        "abstract": item_data.get("abstractNote", ""),
        "publisher": item_data.get("publisher", ""),
        "container-title": item_data.get("publicationTitle", ""),
        "volume": item_data.get("volume", ""),
        "issue": item_data.get("issue", ""),
        "page": item_data.get("pages", ""),
        "DOI": item_data.get("DOI", ""),
        "ISBN": item_data.get("ISBN", ""),
    }
    # Leere Strings entfernen (sauberes JSON)
    return {k: v for k, v in csl.items() if v != "" and v != [] and v != {}}


# ---------------------------------------------------------------------------
# Annotation-Helpers (Issue #395)
# ---------------------------------------------------------------------------


def _parse_page_label(label: str | None) -> int | None:
    """Parst Zoteros `annotationPageLabel` zu `int`, falls exakt numerisch.

    Zotero erlaubt beliebige Strings als Seitenlabel (roemische Ziffern wie
    "iv", Bereiche wie "12-13", leere Strings). Solche Faelle werden bewusst
    NICHT geraten/approximiert, sondern liefern `None` — `printed_page` ist
    eine INTEGER-Spalte und darf nicht raten.
    """
    if label is None:
        return None
    stripped = label.strip()
    # isdecimal() statt isdigit(): isdigit() laesst Unicode-Ziffern wie
    # Hochstellungszeichen ("²") durch, fuer die int() dennoch einen
    # ValueError wirft (isdecimal() lehnt sie korrekt ab).
    if not stripped or not stripped.isdecimal():
        return None
    return int(stripped)


def _annotation_verbatim(child_data: dict) -> str | None:
    """Extrahiert den markierten QUELLENTEXT aus einem Annotation-Kind.

    Ausschliesslich `annotationText` — der von Zotero aus dem PDF
    uebernommene Ausschnitt (Highlight/Underline). Gibt `None`, wenn das Feld
    leer ist; solche Annotationen werden nicht als Quote importiert.

    KEIN Fallback auf `annotationComment`: Der Kommentar ist der eigene Text
    der forschenden Person, kein Beleg aus der Quelle. `quotes.verbatim`
    traegt aber genau eine Zusage — *dieser Wortlaut steht so in der Quelle* —
    und `hooks/verbatim-guard.mjs` gibt ein Zitat im Kapitel allein deshalb
    frei, weil `search_quote_text()` es in `quotes.verbatim` findet (LIKE-Suche
    ohne weiteren Diskriminator; `extraction_method` wird nicht gelesen). Ein
    Fallback wuerde die eigene Notiz also zum vermeintlich belegten Zitat
    machen und den Guard genau die Fehlzuschreibung durchwinken lassen, die er
    verhindern soll. Zotero selbst trennt beides strikt: In Note-Templates
    wird `{{:highlight}}` (= `annotationText`) in Anfuehrungszeichen bzw.
    `<blockquote>` gerendert, `{{:comment}}` dagegen ausserhalb des Zitats.
    """
    return (child_data.get("annotationText") or "").strip() or None


def _existing_quote_keys(db_path: str, paper_id: str) -> set[tuple[str, int | None]]:
    """Liest die bereits vorhandenen Quote-Schluessel eines Papers.

    Schluessel ist `(verbatim, printed_page)` — die fachliche Identitaet einer
    importierten Markierung. Zwei Markierungen mit demselben Wortlaut auf
    verschiedenen Seiten bleiben dadurch zwei getrennte Quotes, ein zweiter
    Import derselben Markierung wird jedoch erkannt.

    Notwendig, weil `add_quote()` jede Quote mit frischer `uuid4()` einfuegt
    und selbst nicht dedupliziert: Items ohne DOI/ISBN durchlaufen bei jedem
    Lauf den vollen Importpfad (`_paper_exists_in_vault` kann sie nicht
    erkennen), waehrend `paper_id` ueber den stabilen Zotero-Key konstant
    bleibt — ohne diesen Filter wuechse pro Lauf eine weitere Kopie jeder
    Markierung an dasselbe Paper.
    """
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT verbatim, printed_page FROM quotes WHERE paper_id = ?", (paper_id,)
        ).fetchall()
    finally:
        conn.close()
    return {(verbatim, printed_page) for verbatim, printed_page in rows}


# ---------------------------------------------------------------------------
# Attachment-Download (gemockt in Tests)
# ---------------------------------------------------------------------------


def _download_attachment(
    zot_client, item_key: str, attachment_key: str, dest_dir: str
) -> str | None:
    """Laedt ein PDF-Attachment herunter. Gibt lokalen Pfad zurueck oder None bei Fehler.

    Diese Funktion wird in Tests via patch('zotero_pull._download_attachment') ersetzt.
    """
    try:
        dest_path = os.path.join(dest_dir, f"{attachment_key}.pdf")
        zot_client.dump(attachment_key, path=dest_path)
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
            return dest_path
    except Exception:
        pass
    return None


def _fetch_zotero_fulltext(zot_client, attachment_key: str) -> str | None:
    """Holt den von Zotero bereits extrahierten/indizierten PDF-Volltext (Issue #525).

    Nutzt pyzotero's ``fulltext_item()`` (Endpunkt
    ``/items/{key}/fulltext``, liefert ``{"content": ..., "indexedPages"/
    "totalPages"|"indexedChars"/"totalChars"}``). Der Aufruf ist unabhaengig
    vom PDF-Download: `fulltext_item()` liefert auch dann Text, wenn
    `_download_attachment()` fehlschlaegt oder gar nicht erst versucht wird.

    Gibt ``None`` zurueck, wenn Zotero den Text (noch) nicht indiziert hat
    (404 `ResourceNotFoundError`), der Content leer/kein String ist (auch ein
    unkonfigurierter Mock-Rueckgabewert in Tests faellt darunter — bewusst
    strikt typgeprueft statt truthy-Check), oder bei jedem anderen Fehler
    (Netzwerk, Rate-Limit, lokaler Endpunkt ohne Sync). Diese Funktion wird
    in Tests via patch('zotero_pull._fetch_zotero_fulltext') bzw. am
    Mock-Client ersetzt und darf run_import() niemals durch eine Exception
    unterbrechen — genau wie _download_attachment().
    """
    try:
        response = zot_client.fulltext_item(attachment_key)
        content = response.get("content") if isinstance(response, dict) else None
        if not isinstance(content, str):
            return None
        return content.strip() or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Haupt-Import-Funktion
# ---------------------------------------------------------------------------


def run_import(
    config_path: str,
    db_path: str,
) -> ImportResult:
    """Fuehrt den Zotero-Import durch.

    Args:
        config_path: Pfad zur config.yaml (muss 0600 haben).
        db_path: Pfad zur Vault-SQLite-Datenbank.

    Returns:
        ImportResult mit Zaehlung von importierten, uebersprungenen Elementen und Fehlern.

    Raises:
        PermissionError: wenn config_path nicht 0600 hat.
        ImportError: wenn pyzotero nicht installiert ist.
    """
    # 1. Config laden (prueft 0600)
    cfg = load_config(config_path)

    api_key = cfg.get("zotero_api_key", "")
    library_id = str(cfg.get("zotero_library_id", ""))
    library_type = cfg.get("zotero_library_type", "user")

    if not api_key:
        raise ValueError("zotero_api_key fehlt in config.yaml")
    if not library_id:
        raise ValueError("zotero_library_id fehlt in config.yaml")

    # 2. pyzotero-Client erstellen
    if zotero is None:
        raise ImportError(
            "pyzotero ist nicht installiert. Bitte ausfuehren: pip install 'pyzotero>=1.5'"
        )

    zot = zotero.Zotero(library_id, library_type, api_key)

    # 3. Alle Items laden
    all_items = zot.everything(zot.items())

    result = ImportResult()

    # Vault-Schema initialisieren falls DB neu
    from academic_vault.db import VaultDB

    VaultDB(db_path).init_schema()

    with tempfile.TemporaryDirectory() as tmp_dir:
        for item in all_items:
            item_data = item.get("data", {})
            item_key = item_data.get("key", str(uuid4()))
            item_type = item_data.get("itemType", "")

            # Attachments, Notes etc. ueberspringen
            if item_type in ("attachment", "note", "annotation"):
                continue

            doi_raw = item_data.get("DOI", "") or ""
            isbn_raw = item_data.get("ISBN", "") or ""
            doi = _normalize_doi(doi_raw)
            isbn = _normalize_isbn(isbn_raw)

            # Dedup-Check
            if _paper_exists_in_vault(db_path, doi, isbn):
                result.skipped += 1
                continue

            # CSL-JSON erzeugen
            csl = _zotero_item_to_csl(item_data)
            csl_str = json.dumps(csl, ensure_ascii=False)
            paper_id = f"zotero-{item_key}"

            try:
                add_paper(
                    db_path=db_path,
                    paper_id=paper_id,
                    csl_json=csl_str,
                    doi=doi,
                    isbn=isbn,
                    pdf_path=None,
                )

                # PDF-Attachments verarbeiten
                children = zot.children(item_key)
                for child in children:
                    child_data = child.get("data", {})
                    if (
                        child_data.get("itemType") == "attachment"
                        and child_data.get("contentType") == "application/pdf"
                    ):
                        att_key = child_data.get("key", "")

                        # Zotero-Volltext bevorzugen (Issue #525): separater,
                        # vom PDF-Download unabhaengiger API-Call. Wird VOR
                        # dem `add_paper(..., pdf_path=...)`-Aufruf unten
                        # geschrieben, damit `_maybe_extract_fulltext()`
                        # (server.py) `get_fulltext(paper_id) is not None`
                        # sieht und die lokale PDF-Extraktion ueberspringt.
                        zotero_text = _fetch_zotero_fulltext(zot, att_key)
                        if zotero_text:
                            VaultDB(db_path).set_fulltext(paper_id, zotero_text, extractor="zotero")
                            result.fulltext_from_zotero += 1
                        else:
                            # Kein Fehler (Issue #525 AC2): nicht indiziert, leer
                            # oder anderer Fehler bei fulltext_item() -- sauberer
                            # Fallback auf den lokalen PDF-Parse-Pfad weiter unten.
                            # Muss sichtbar bleiben statt still zu verschwinden.
                            result.fulltext_fallback_local += 1
                            logger.info(
                                "Zotero-Volltext fuer Attachment %s nicht verfuegbar "
                                "(nicht indiziert/leer/Fehler) -- Fallback auf lokalen "
                                "PDF-Parse.",
                                att_key,
                            )

                        local_path = _download_attachment(zot, item_key, att_key, tmp_dir)
                        if local_path:
                            # pdf_path im Vault setzen
                            add_paper(
                                db_path=db_path,
                                paper_id=paper_id,
                                csl_json=csl_str,
                                doi=doi,
                                isbn=isbn,
                                pdf_path=local_path,
                            )
                            # Optionaler Files-API-Upload + Cache (eigener
                            # ANTHROPIC_API_KEY noetig, siehe citations-api.md).
                            # Ohne Key wird der Pfad explizit uebersprungen und
                            # gezaehlt (#535) — kein Eintrag in result.errors,
                            # denn ein fehlender Key ist kein Importfehler. Das
                            # except faengt nur noch echte Upload-Fehler MIT Key.
                            if not files_api_configured():
                                result.files_api_skipped += 1
                                logger.info(
                                    "Optionaler Files-API-Upload fuer %s uebersprungen: "
                                    "kein ANTHROPIC_API_KEY gesetzt.",
                                    paper_id,
                                )
                            else:
                                try:
                                    file_id = ensure_file(
                                        db_path=db_path,
                                        paper_id=paper_id,
                                        api_key="",  # ANTHROPIC_API_KEY aus Env
                                    )
                                    if file_id:
                                        result.file_ids.append(file_id)
                                except Exception as e:
                                    result.errors.append(
                                        f"ensure_file fuer {paper_id} fehlgeschlagen: {e}"
                                    )

                        # Annotationen (Highlights/Notizen) dieses Attachments
                        # importieren — unabhaengig vom Download-Erfolg des PDFs.
                        try:
                            annotation_children = zot.children(att_key)
                        except Exception as e:
                            result.errors.append(
                                f"Annotationen fuer {att_key} konnten nicht geladen werden: {e}"
                            )
                            annotation_children = []

                        # Bereits vorhandene Quotes dieses Papers einmal lesen;
                        # jede neu eingefuegte Markierung wandert in dasselbe Set,
                        # damit auch Dubletten innerhalb eines Laufs greifen.
                        seen_quotes = _existing_quote_keys(db_path, paper_id)

                        for annotation_child in annotation_children:
                            ann_data = annotation_child.get("data", {})
                            if ann_data.get("itemType") != "annotation":
                                continue
                            verbatim = _annotation_verbatim(ann_data)
                            if not verbatim:
                                # Nur-Kommentar-Annotation: nicht als Quote
                                # importieren (Nutzertext, kein Beleg), aber
                                # mitzaehlen statt still zu verwerfen.
                                if (ann_data.get("annotationComment") or "").strip():
                                    result.comments_skipped += 1
                                continue
                            printed_page = _parse_page_label(ann_data.get("annotationPageLabel"))
                            if (verbatim, printed_page) in seen_quotes:
                                continue
                            try:
                                add_quote(
                                    db_path=db_path,
                                    paper_id=paper_id,
                                    verbatim=verbatim,
                                    extraction_method="manual",
                                    printed_page=printed_page,
                                )
                                seen_quotes.add((verbatim, printed_page))
                                result.quotes_imported += 1
                            except Exception as e:
                                result.errors.append(
                                    f"Quote-Import fuer Annotation in {paper_id} "
                                    f"fehlgeschlagen: {e}"
                                )

                        if local_path:
                            break  # Nur erstes erfolgreich geladenes PDF-Attachment

                result.imported += 1

            except Exception as e:
                result.errors.append(f"Import-Fehler fuer {item_key}: {e}")

    return result


# ---------------------------------------------------------------------------
# CLI-Einstiegspunkt
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI fuer manuellen Aufruf."""
    default_config = os.path.expanduser("~/.academic-research/config.yaml")
    default_db = os.environ.get("VAULT_DB_PATH", "vault.db")

    parser = argparse.ArgumentParser(
        description="Zotero-Import: Holt Items aus Zotero und importiert sie in den Vault."
    )
    parser.add_argument("--config", default=default_config, help="Pfad zur config.yaml (0600)")
    parser.add_argument("--db", default=default_db, help="Pfad zur Vault-SQLite-DB")
    args = parser.parse_args()

    result = run_import(config_path=args.config, db_path=args.db)
    print(f"Importiert: {result.imported}")
    print(f"Uebersprungen (Duplikat): {result.skipped}")
    print(f"Fehler: {len(result.errors)}")
    if result.errors:
        for err in result.errors:
            print(f"  - {err}", file=sys.stderr)
    if result.file_ids:
        print(f"Optionale Files-API file_ids gecacht: {len(result.file_ids)}")
    if result.files_api_skipped:
        print(
            f"Optionaler Files-API-Upload uebersprungen (kein eigener "
            f"ANTHROPIC_API_KEY): {result.files_api_skipped}"
        )
    if result.fulltext_from_zotero:
        print(
            f"Volltext von Zotero uebernommen (ohne lokalen PDF-Parse): "
            f"{result.fulltext_from_zotero}"
        )
    if result.fulltext_fallback_local:
        print(
            f"Zotero-Volltext nicht verfuegbar, Fallback auf lokalen PDF-Parse: "
            f"{result.fulltext_fallback_local}"
        )
    if result.quotes_imported:
        print(f"Annotationen als Quotes importiert: {result.quotes_imported}")
    if result.comments_skipped:
        print(
            f"Nur-Kommentar-Annotationen uebersprungen: {result.comments_skipped} "
            f"(eigener Text, kein Beleg aus der Quelle — nicht als Zitat importiert)"
        )


if __name__ == "__main__":
    main()
