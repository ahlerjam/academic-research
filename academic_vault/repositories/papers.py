"""Papers-Aggregat: CRUD der ``papers``-Tabelle plus die
Klammer-Zitat-Verifikation (Issue #378), die auf demselben
Papers-Bestand arbeitet.

Reiner Move aus der frueheren ``academic_vault/db.py`` (Issue #841) --
die Methodenkoerper sind unveraendert.
"""

import json
import time
from pathlib import Path

from ..vault_schema import (
    _OPTIONAL_PAPER_COLUMNS,
    _OPTIONAL_PAPER_DEFAULTS,
    _UNSET,
    SCIHUB_PROVENANCE_SIDECAR_SUFFIX,
    VALID_PAPER_TYPES,
    VALID_SOURCE_KINDS,
    _Unset,
)
from ..vault_text import csl_families, csl_year, normalize_family_name
from ._base import ConnectionHost


class PapersRepo(ConnectionHost):
    """Papers-CRUD und die Klammer-Zitat-Verifikation (Issue #378)."""

    # ------------------------------------------------------------------
    # Papers CRUD
    # ------------------------------------------------------------------

    def add_paper(
        self,
        paper_id: str,
        csl_json: str,
        doi: str | None | _Unset = _UNSET,
        isbn: str | None | _Unset = _UNSET,
        pdf_path: str | None | _Unset = _UNSET,
        page_offset: int | _Unset = _UNSET,
        editor: str | None | _Unset = _UNSET,
        chapter: str | None | _Unset = _UNSET,
        page_first: int | None | _Unset = _UNSET,
        page_last: int | None | _Unset = _UNSET,
        container_title: str | None | _Unset = _UNSET,
        parent_paper_id: str | None | _Unset = _UNSET,
        provenance: str | None | _Unset = _UNSET,
        source_kind: str | _Unset = _UNSET,
    ) -> None:
        """Upsert eines Papers in die papers-Tabelle.

        type wird aus csl_json extrahiert. Erlaubte Werte: article-journal, book, chapter.

        provenance: Herkunfts-Tag (z.B. "scihub", "oa") fuer Audit-Zwecke (#195).

        source_kind: ``"literature"`` (Default) oder ``"primary"`` fuer eigenes
        Erhebungsmaterial (Issue #473). Beantwortet eine andere Frage als
        ``provenance`` ("woher bezogen") -- naemlich, ob der Eintrag ueberhaupt
        Literatur ist. Wird der Parameter beim Upsert weggelassen, bleibt der
        Bestandswert erhalten; ein Transkript wird also nicht durch ein
        spaeteres Metadaten-Update zur Literaturquelle.

        Malformed JSON wird NICHT mehr stillschweigend zu 'article-journal'
        defaulted (Issue #213, Security Round-2 M3), sondern als ValueError
        gemeldet. Fehlt das Feld 'type' komplett, gilt weiterhin der
        DB-Default 'article-journal'.

        Alle optionalen Parameter defaulten auf das Sentinel ``_UNSET``
        statt auf ``None``/``0`` (Issue #455): Ein zweiter Upsert-Aufruf fuer
        dieselbe ``paper_id``, der ein optionales Feld nicht mit uebergibt,
        laesst dessen Bestandswert unangetastet -- vorher wurde jedes nicht
        uebergebene Feld stillschweigend auf seinen Default zurueckgesetzt.
        Ein bewusst geleertes Feld (explizit ``None``/``0`` uebergeben) wird
        weiterhin geleert, weil dieser Wert von ``_UNSET`` unterscheidbar ist.
        """
        try:
            csl = json.loads(csl_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"csl_json ist kein valides JSON: {exc}") from exc
        if not isinstance(csl, dict):
            raise ValueError("csl_json muss ein JSON-Objekt sein.")
        paper_type = csl.get("type", "article-journal")

        if paper_type not in VALID_PAPER_TYPES:
            raise ValueError(
                f"Ungueltiger type '{paper_type}' -- erlaubt: {sorted(VALID_PAPER_TYPES)}"
            )

        if not isinstance(source_kind, _Unset) and source_kind not in VALID_SOURCE_KINDS:
            raise ValueError(
                f"Ungueltiger source_kind '{source_kind}' -- erlaubt: {sorted(VALID_SOURCE_KINDS)}"
            )

        # Sci-Hub-Provenance-Durchsetzung (Issue #627): Wird in diesem Aufruf
        # ein pdf_path uebergeben und liegt daneben der Sidecar-Marker des
        # scihub-fetcher-Agenten, wird provenance hart auf "scihub" gesetzt --
        # auch wenn der Aufrufer provenance weglaesst (_UNSET) oder einen
        # abweichenden Wert uebergibt. Ohne uebergebenen pdf_path (Sentinel
        # oder None) gibt es nichts zu pruefen; der Bestandswert bleibt dann
        # ohnehin unangetastet. Der Marker wird nach erfolgreicher
        # Persistierung in der DB konsumiert (gelöscht), damit er keinen
        # Einfluss auf einen späteren Überschreibvorgang derselben PDF hat
        # (Issue #627 Audit P1).
        sidecar_path_to_consume: Path | None = None
        if not isinstance(pdf_path, _Unset) and pdf_path is not None:
            sidecar_path = Path(str(pdf_path) + SCIHUB_PROVENANCE_SIDECAR_SUFFIX)
            if sidecar_path.is_file():
                provenance = "scihub"
                sidecar_path_to_consume = sidecar_path

        supplied: dict[str, object] = {
            "doi": doi,
            "isbn": isbn,
            "pdf_path": pdf_path,
            "page_offset": page_offset,
            "editor": editor,
            "chapter": chapter,
            "page_first": page_first,
            "page_last": page_last,
            "container_title": container_title,
            "parent_paper_id": parent_paper_id,
            "provenance": provenance,
            "source_kind": source_kind,
        }
        # Werte fuer den INSERT-Zweig (Neuanlage): bei nicht uebergebenen
        # (Sentinel-)Feldern der bisherige Default -- fuer eine echte
        # Neuanlage aendert sich dadurch nichts am Ergebnis.
        insert_values = {
            col: (_OPTIONAL_PAPER_DEFAULTS[col] if val is _UNSET else val)
            for col, val in supplied.items()
        }
        # Nur tatsaechlich uebergebene Spalten landen im UPDATE SET -- das
        # ist der Kern des Fixes: nicht uebergebene optionale Felder
        # behalten beim Upsert ihren Bestandswert.
        provided_columns = [col for col, val in supplied.items() if val is not _UNSET]

        now = int(time.time())
        set_clauses = ["type = excluded.type", "csl_json = excluded.csl_json"]
        set_clauses += [f"{col} = excluded.{col}" for col in provided_columns]
        set_clauses.append("updated_at = excluded.updated_at")

        columns = [
            "paper_id",
            "type",
            "csl_json",
            *_OPTIONAL_PAPER_COLUMNS,
            "added_at",
            "updated_at",
        ]
        placeholders = ", ".join("?" for _ in columns)
        values = (
            paper_id,
            paper_type,
            csl_json,
            *(insert_values[col] for col in _OPTIONAL_PAPER_COLUMNS),
            now,
            now,
        )

        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                f"""
                INSERT INTO papers ({", ".join(columns)})
                VALUES ({placeholders})
                ON CONFLICT(paper_id) DO UPDATE SET
                  {", ".join(set_clauses)}
                """,
                values,
            )

        # Marker nach Persistierung konsumieren (Issue #627 Audit P1):
        # Verhindert, dass ein Marker einen späteren Überschreibvorgang
        # derselben PDF beeinflusst.
        if sidecar_path_to_consume is not None:
            sidecar_path_to_consume.unlink(missing_ok=True)

    def get_paper(self, paper_id: str) -> dict | None:
        """Gibt Paper-Record als dict zurueck oder None."""
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM papers WHERE paper_id = ?", (paper_id,)).fetchone()
        if row is None:
            return None
        return dict(row)

    def set_page_offset(self, paper_id: str, offset: int) -> None:
        """Setzt page_offset fuer ein Paper.

        Raises:
            ValueError: ``paper_id`` verweist auf kein bestehendes Paper.
            VaultLockedError: Vault ist gesperrt (Material-Passport-Lock,
                Issue #380/#407) -- ein gesperrter Passport darf keine
                Seitenzitate mehr verschieben.
        """
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            cursor = conn.execute(
                "UPDATE papers SET page_offset = ?, updated_at = ? WHERE paper_id = ?",
                (offset, int(time.time()), paper_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"vault.set_page_offset: Paper '{paper_id}' nicht gefunden")

    def get_page_offset(self, paper_id: str) -> int:
        """Gibt page_offset fuer ein Paper zurueck. Fallback: 0."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT page_offset FROM papers WHERE paper_id = ?", (paper_id,)
            ).fetchone()
        if row is None:
            return 0
        return int(row["page_offset"] or 0)

    def list_papers_by_provenance(self, provenance: str) -> list[dict]:
        """Gibt alle Papers mit dem angegebenen provenance-Tag zurueck (Audit, #195).

        Beispiel: ``list_papers_by_provenance("scihub")`` liefert alle aus dem
        SciHub-Tier bezogenen Papers fuer ein Provenance-Audit.
        """
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM papers WHERE provenance = ? ORDER BY added_at",
                (provenance,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_literature_papers(self) -> list[dict]:
        """Gibt alle Papers mit ``source_kind='literature'`` zurueck (#604).

        Grundlage fuer ``server.check_retractions()``: unabhaengig vom
        Importweg (zotero-import, reading-list-import, anchor-paper-survey,
        github-repo-research, fetch, ...) liefert diese Abfrage jedes
        Literatur-Paper -- eigenes Erhebungsmaterial (``source_kind='primary'``,
        Transkripte etc.) ist bewusst ausgeschlossen, ein Retraction-Check
        ergibt dafuer keinen Sinn.
        """
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM papers WHERE source_kind = 'literature' ORDER BY added_at",
            ).fetchall()
        return [dict(r) for r in rows]

    def update_retraction_checked_at(self, paper_id: str, checked_at: int) -> None:
        """Setzt ``retraction_checked_at`` fuer ein Paper (#604).

        Wird nur nach einer erfolgreichen Crossref-Pruefung aufgerufen
        (``server.check_retractions()``) -- ein Crossref-Ausfall darf den
        Zeitstempel nicht vorruecken, sonst wuerde der naechste Lauf faelschlich
        annehmen, das Paper sei bereits aktuell geprueft.

        Raises:
            ValueError: ``paper_id`` verweist auf kein bestehendes Paper.
            VaultLockedError: Vault ist gesperrt (Material-Passport-Lock).
        """
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            cursor = conn.execute(
                "UPDATE papers SET retraction_checked_at = ? WHERE paper_id = ?",
                (checked_at, paper_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(
                    f"vault.update_retraction_checked_at: Paper '{paper_id}' nicht gefunden"
                )

    # ------------------------------------------------------------------
    # Klammer-Zitat-Verifikation (Issue #378)
    # ------------------------------------------------------------------

    def _papers_snapshot(self) -> list[dict]:
        """Liest die komplette ``papers``-Tabelle einmal und parst ``csl_json``.

        Extrahiert aus :meth:`find_papers_by_author_year` (Issue #501), damit
        Aufrufer mit mehreren Belegen (:func:`academic_vault.server.verify_citations`)
        sich einen Scan + Parse-Durchlauf ueber die komplette Tabelle teilen
        koennen, statt ihn je Beleg zu wiederholen. Zeilen mit kaputtem oder
        nicht-dict ``csl_json`` werden stillschweigend uebersprungen (wie bisher
        in :meth:`find_papers_by_author_year`). Ergebnis enthaelt zusaetzlich
        das bereits geparste ``csl``-Feld.
        """
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT paper_id, csl_json, page_first, page_last FROM papers"
            ).fetchall()
        snapshot: list[dict] = []
        for row in rows:
            record = dict(row)
            try:
                csl = json.loads(record["csl_json"])
            except (TypeError, ValueError):
                continue
            if not isinstance(csl, dict):
                continue
            record["csl"] = csl
            snapshot.append(record)
        return snapshot

    def _match_papers_in_snapshot(
        self, snapshot: list[dict], family: str, year: int | None
    ) -> list[dict]:
        """Matcht ``family``/``year`` gegen einen bereits gelesenen :meth:`_papers_snapshot`.

        Reine In-Memory-Filterung (kein DB-Zugriff) -- Kern von
        :meth:`find_papers_by_author_year`, extrahiert (Issue #501), damit
        :func:`academic_vault.server.verify_citations` denselben Snapshot fuer
        mehrere Belege wiederverwenden kann, statt ihn je Beleg neu einzulesen.
        Der Namensvergleich laeuft ueber :func:`normalize_family_name`
        (Umlaut-Faltung + Diakritika-Strip), damit ``Müller``/``Mueller``/
        ``Muller`` denselben Eintrag treffen.
        """
        wanted = normalize_family_name(family)
        if not wanted or year is None:
            return []
        matches: list[dict] = []
        for record in snapshot:
            csl = record["csl"]
            if csl_year(csl) != int(year):
                continue
            if any(normalize_family_name(f) & wanted for f in csl_families(csl)):
                matches.append(
                    {
                        "paper_id": record["paper_id"],
                        "csl_json": record["csl_json"],
                        "page_first": record["page_first"],
                        "page_last": record["page_last"],
                    }
                )
        return matches

    def find_papers_by_author_year(self, family: str, year: int) -> list[dict]:
        """Findet Papers, deren CSL-Autorenliste ``family`` enthaelt und deren
        Erscheinungsjahr exakt ``year`` ist.

        Es gibt bewusst keine SQL-seitige Vorfilterung: ``csl_json`` ist ein
        Textblob, dessen Autorenfelder sich nicht zuverlaessig per LIKE
        eingrenzen lassen, ohne genau diese Schreibvarianten zu verlieren.
        Fuer Aufrufer mit mehreren Belegen (Batch) siehe
        :meth:`_papers_snapshot` + :meth:`_match_papers_in_snapshot`.
        """
        return self._match_papers_in_snapshot(self._papers_snapshot(), family, year)

    def known_page_markers(self, paper_id: str) -> tuple[list[int], int | None, int | None]:
        """Bekannte Seitendaten eines Papers: Stichproben-Set und ggf. voller Bereich.

        Rueckgabe ``(samples, page_first, page_last)`` — ``samples`` ist die
        sortierte, deduplizierte Menge aller ``quotes.printed_page``-Werte;
        ``page_first``/``page_last`` sind ``None``, wenn kein vollstaendiger
        Seitenumfang hinterlegt ist (oder das Paper unbekannt ist).
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT page_first, page_last FROM papers WHERE paper_id = ?",
                (paper_id,),
            ).fetchone()
            samples = sorted(
                {
                    r["printed_page"]
                    for r in conn.execute(
                        "SELECT printed_page FROM quotes "
                        "WHERE paper_id = ? AND printed_page IS NOT NULL",
                        (paper_id,),
                    ).fetchall()
                }
            )
        if row is None:
            return samples, None, None
        return samples, row["page_first"], row["page_last"]

    def page_coverage(self, paper_id: str, page: int, page_end: int | None = None) -> str:
        """Prueft, ob ``[page, page_end]`` von den im Vault bekannten Seitendaten
        gedeckt ist. Ohne ``page_end`` (oder mit ``page_end == page``) wird eine
        Einzelseite geprueft.

        Die beiden Quellen sind bewusst NICHT gleichwertig (Issue #724 kehrt die
        urspruengliche Regel aus #378 fuer den Faellen ohne vollstaendigen
        Seitenumfang um):

        * ``papers.page_first``/``page_last`` beschreiben den vollstaendigen
          Seitenumfang und koennen eine Seite deshalb auch widerlegen.
        * ``quotes.printed_page`` ist eine punktuelle Stichprobe der bereits
          extrahierten Stellen. Liegt ZUSAETZLICH ein vollstaendiger
          Seitenumfang vor, bestaetigt eine Stichprobe weiterhin auch dann,
          wenn sie (fehlerhaft) ausserhalb dieses Umfangs liegt. Ist dagegen
          KEIN vollstaendiger Seitenumfang bekannt, ist die Stichproben-Menge
          die einzige verfuegbare Evidenz und wird selbst zum widerlegenden
          Signal: liegt der Beleg nicht in dieser Menge, gilt er als
          ``"outside"`` statt als unentscheidbar ``"unknown"``. Das senkt die
          Trennschaerfe bei Buechern mit vielen, aber nur teilweise erfassten
          Zitaten (Buecher/Kapitel mit mehreren Stichproben auf verschiedenen
          Seiten) — akzeptierter Trade-off aus Issue #724, weil die
          Seitenzahl sonst fuer den Regelfall des PDF-Ingests (kein CSL-
          Seitenumfang) komplett ungeprueft bliebe.

        Ein Seitenbereich (``page_end`` gesetzt) gilt als ``"covered"``, wenn
        IRGENDEINE bekannte Einzelseite oder der vollstaendige Seitenumfang mit
        dem Bereich ueberlappt.

        Rueckgabe:
          ``"covered"``  — Bereich ueberlappt ``[page_first, page_last]`` oder
                            enthaelt eine bekannte ``quotes.printed_page``.
          ``"outside"``  — vollstaendiger Seitenumfang bekannt und der Bereich
                            liegt vollstaendig ausserhalb, ODER kein
                            vollstaendiger Seitenumfang bekannt, aber
                            mindestens eine Stichprobe vorhanden und keine
                            davon im Bereich.
          ``"unknown"``  — ueberhaupt keine Seitendaten zum Paper hinterlegt
                            (dokumentierter Soft-Pass; sonst waeren
                            Massen-False-Positives die Folge).
        """
        samples, first, last = self.known_page_markers(paper_id)
        lo, hi = page, page if page_end is None else page_end
        if hi < lo:
            lo, hi = hi, lo
        # Stichprobe zuerst: eine belegte Quote-Seite bestaetigt auch dann,
        # wenn sie ausserhalb eines (ggf. fehlerhaften) Seitenumfangs liegt.
        if any(lo <= p <= hi for p in samples):
            return "covered"
        if first is not None and last is not None:
            return "covered" if hi >= first and lo <= last else "outside"
        if samples:
            return "outside"
        return "unknown"

    def set_ocr_done(self, paper_id: str, value: int = 1) -> None:
        """Setzt ocr_done-Flag fuer ein Paper.

        Raises:
            ValueError: ``paper_id`` verweist auf kein bestehendes Paper.
            VaultLockedError: Vault ist gesperrt (Material-Passport-Lock).
        """
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            cursor = conn.execute(
                "UPDATE papers SET ocr_done = ?, updated_at = ? WHERE paper_id = ?",
                (value, int(time.time()), paper_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"vault.set_ocr_done: Paper '{paper_id}' nicht gefunden")

    def update_pdf_path(self, paper_id: str, new_path: str) -> None:
        """Aktualisiert pdf_path fuer ein Paper.

        Raises:
            ValueError: ``paper_id`` verweist auf kein bestehendes Paper.
            VaultLockedError: Vault ist gesperrt (Material-Passport-Lock).
        """
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            cursor = conn.execute(
                "UPDATE papers SET pdf_path = ?, updated_at = ? WHERE paper_id = ?",
                (new_path, int(time.time()), paper_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"vault.update_pdf_path: Paper '{paper_id}' nicht gefunden")
