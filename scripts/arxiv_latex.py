#!/usr/bin/env python3
"""arXiv-LaTeX-Quellcode-Zugriff fuer Formeltreue bei MINT-Themen (#399).

PDF-Textextraktion zerstoert bei MINT-nahen Papers haeufig Formeln (Unicode-
Mapping, Ligaturen, Layout-Heuristiken). Der arXiv-e-print-Endpoint liefert
fuer die meisten Submissions den LaTeX-Rohquellcode, in dem Formeln exakt und
maschinenlesbar als `$...$`/`\\begin{equation}`-Text vorliegen.

Diese Datei ist bewusst eigenstaendig und aendert NICHTS an der bestehenden
PDF-Resolve/Extract-Pipeline in scripts/pdf.py bzw. scripts/search.py -- sie
stellt nur eine Alternative bereit, wenn ein Paper eine arXiv-ID hat.

Muster-Vorbild (laut Issue #399): takashiishida/arxiv-latex-mcp (MIT-Lizenz)
bzw. dessen Kernbaustein `arxiv-to-prompt` -- insbesondere die Heuristik,
die Haupt-.tex-Datei ueber das Vorkommen von `\\documentclass` zu finden.
Diese Datei ist eine eigenstaendige Neuimplementierung dieser Idee, kein
Codeuebernahme.

Wichtig -- Scope-Grenze (Issue #399, "Out"): KEIN Formel-Parsing, KEINE
`\\input`/`\\include`-Aufloesung, nur Rohtext-Zugriff auf die Haupt-.tex-Datei.

Sicherheitsmodell (Tar-Slip): Der e-print-Endpoint liefert im Mehrdatei-Fall
ein gzip-tar-Archiv, dessen Inhalt letztlich von arXiv-Autor:innen hochgeladen
wurde -- also strukturell untrusted Input. Diese Implementierung schreibt
NIE auf Platte (kein `extractall`/`extract`), sondern liest Tar-Mitglieder
ausschliesslich im Speicher (`tar.extractfile(member).read()`). Zusaetzlich
begrenzen `ARXIV_LATEX_MAX_MEMBERS`/`ARXIV_LATEX_MAX_MEMBER_SIZE` Anzahl bzw.
Groesse der betrachteten Mitglieder gegen Decompression-Bomb-Szenarien
(Vorbild: `OAI_MAX_PAGES`/`OAI_MAX_RECORDS` in scripts/search.py, Issue #236).

Usage:
  python arxiv_latex.py --arxiv-id 2301.12345
"""

from __future__ import annotations

import argparse
import gzip
import io
import logging
import sys
import tarfile

import httpx

TIMEOUT = 30.0
GZIP_MAGIC = b"\x1f\x8b"
PDF_MAGIC = b"%PDF"
PS_MAGIC = b"%!PS"

# DOI-Praefix, den scripts/search.py::search_arxiv() fuer arXiv-Treffer setzt
# (`doi = f"10.48550/arxiv.{arxiv_id}"`) -- Grundlage fuer arxiv_id_from_doi().
ARXIV_DOI_PREFIX = "10.48550/arxiv."

# Caps gegen Decompression-Bomb/Speicherverbrauch beim In-Memory-Tar-Handling
# (Vorbild: OAI_MAX_PAGES/OAI_MAX_RECORDS aus scripts/search.py, Issue #236).
ARXIV_LATEX_MAX_MEMBERS = 500
ARXIV_LATEX_MAX_MEMBER_SIZE = 10_000_000  # 10 MB pro einzelner .tex-Datei

log = logging.getLogger(__name__)


def arxiv_id_from_doi(doi: str | None) -> str | None:
    """Extrahiert die arXiv-ID aus einer DOI im Muster `10.48550/arxiv.<id>`.

    scripts/search.py::search_arxiv() setzt fuer arXiv-Treffer genau dieses
    DOI-Muster (`doi = f"10.48550/arxiv.{arxiv_id}"`). Dieser Baustein macht
    das Feature aus scripts/pdf.py heraus nutzbar (#399, Scope "In": Nutzung
    als Alternative zur PDF-Extraktion, wenn ein Paper eine arXiv-ID hat) --
    ohne die bestehende Pipeline fuer Nicht-arXiv-Quellen zu beruehren, da
    diese Funktion fuer alle anderen DOIs (bzw. `None`) `None` liefert.

    Args:
        doi: DOI-String, roh oder bereits normalisiert; `None` erlaubt.

    Returns:
        Die arXiv-ID (z.B. "2301.12345") oder `None`, wenn `doi` nicht dem
        arXiv-DOI-Muster entspricht.
    """
    if not doi:
        return None
    value = doi.strip().lower()
    if not value.startswith(ARXIV_DOI_PREFIX):
        return None
    return value[len(ARXIV_DOI_PREFIX) :] or None


def _decode_tex(data: bytes) -> str:
    """Dekodiert TeX-Bytes defensiv (nicht garantiert UTF-8, aeltere Papers
    z.T. Latin-1/ASCII) -- nie eine UnicodeDecodeError nach aussen werfen."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _pick_main_tex(tex_files: dict[str, bytes]) -> bytes | None:
    """Waehlt die Haupt-.tex-Datei aus mehreren Kandidaten.

    Heuristik (angelehnt an takashiishida/arxiv-latex-mcp): erste Datei mit
    `\\documentclass`, sonst Fallback auf die groesste Datei. Bewusst kein
    `\\input`/`\\include`-Flattening (Scope-Grenze aus dem Issue).
    """
    if not tex_files:
        return None
    for content in tex_files.values():
        if b"\\documentclass" in content:
            return content
    return max(tex_files.values(), key=len)


def _extract_tex_from_targz(decompressed: bytes) -> bytes | None:
    """Liest alle .tex-Mitglieder eines (bereits entpackten) tar-Archivs rein
    im Speicher aus und liefert den Inhalt der Haupt-.tex-Datei.

    Schreibt nie auf Platte (kein extractall/extract) -- siehe Modul-Docstring
    zum Tar-Slip-Risiko. Begrenzt Anzahl und Groesse betrachteter Mitglieder.
    """
    tex_files: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(decompressed), mode="r:*") as tar:
            for idx, member in enumerate(tar.getmembers()):
                if idx >= ARXIV_LATEX_MAX_MEMBERS:
                    log.warning(
                        "Tar-Archiv hat mehr als %d Mitglieder -- breche Scan ab",
                        ARXIV_LATEX_MAX_MEMBERS,
                    )
                    break
                if not member.isfile() or not member.name.endswith(".tex"):
                    continue
                if member.size > ARXIV_LATEX_MAX_MEMBER_SIZE:
                    log.warning(
                        "Ueberspringe %s: %d Bytes > Limit %d",
                        member.name,
                        member.size,
                        ARXIV_LATEX_MAX_MEMBER_SIZE,
                    )
                    continue
                extracted = tar.extractfile(member)
                if extracted is None:
                    continue
                tex_files[member.name] = extracted.read()
    except tarfile.TarError:
        return None

    main = _pick_main_tex(tex_files)
    return main


def fetch_arxiv_latex_source(arxiv_id: str) -> str | None:
    """Laedt den e-print-Endpoint fuer eine arXiv-ID und liefert den Inhalt
    der Haupt-.tex-Datei als Text zurueck.

    Der `/e-print/<id>`-Endpoint liefert je nach Quelle unterschiedliche
    Formate: gzip-tar (Mehrdatei-LaTeX-Quelle), gzip-Einzeldatei (Einzeldatei-
    LaTeX-Quelle) oder rohe PDF-Bytes (PDF-only-Submission, kein LaTeX
    verfuegbar). Format-Erkennung laeuft ueber Magic-Bytes, nicht ueber die
    Annahme "immer Tarball".

    Args:
        arxiv_id: arXiv-ID ohne Versions-Suffix, z.B. "2301.12345".

    Returns:
        Inhalt der Haupt-.tex-Datei als str, oder None wenn keine LaTeX-Quelle
        verfuegbar ist (PDF-only, HTTP-Fehler, kaputtes/leeres Archiv, kein
        .tex gefunden). Wirft nie eine Exception nach aussen.
    """
    url = f"https://arxiv.org/e-print/{arxiv_id}"
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            content = resp.content
    except httpx.HTTPError:
        log.info("arXiv e-print-Abruf fehlgeschlagen fuer %s", arxiv_id)
        return None

    if not content:
        return None

    if content.startswith(GZIP_MAGIC):
        try:
            decompressed = gzip.decompress(content)
        except OSError:
            return None
        if tarfile.is_tarfile(io.BytesIO(decompressed)):
            main_tex = _extract_tex_from_targz(decompressed)
            if main_tex is None:
                return None
            return _decode_tex(main_tex)
        # Einzeldatei-gzip (kein Tar): die entpackten Bytes SIND die Quelle --
        # aber nur, wenn sie erkennbar LaTeX sind. arXiv liefert PDF-only-
        # bzw. PostScript-only-Einzeldatei-Submissions ebenfalls gzip-gepackt
        # aus (Content-Encoding: x-gzip). Die vorherige Bedingung
        # (`\\documentclass not in decompressed and not decompressed.strip()`)
        # war effektiv nur "leere Daten -> None", da eine leere Datei nie
        # `\\documentclass` enthaelt -- jeder nicht-leere Nicht-LaTeX-Inhalt
        # (PDF, PostScript, Klartext) fiel unbemerkt auf _decode_tex() durch,
        # das ueber den latin-1-Fallback (siehe oben) jeden Binaerinhalt
        # klaglos in einen str verwandelt (critic-Review PR #435).
        if not decompressed.strip():
            return None
        if decompressed.startswith(PDF_MAGIC) or decompressed.startswith(PS_MAGIC):
            log.info(
                "arXiv %s: Einzeldatei-gzip ist PDF/PostScript, keine LaTeX-Quelle",
                arxiv_id,
            )
            return None
        if b"\\documentclass" not in decompressed and b"\\begin{document}" not in decompressed:
            log.info(
                "arXiv %s: Einzeldatei-gzip enthaelt kein erkennbares LaTeX",
                arxiv_id,
            )
            return None
        return _decode_tex(decompressed)

    if content.startswith(PDF_MAGIC):
        log.info("arXiv %s ist PDF-only, keine LaTeX-Quelle verfuegbar", arxiv_id)
        return None

    # Unbekanntes Format -- kein Absturz, aber auch kein verwertbarer Text.
    log.info("arXiv %s: unbekanntes e-print-Format, kein LaTeX extrahiert", arxiv_id)
    return None


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arxiv-id", required=True, help="arXiv-ID, z.B. 2301.12345")
    args = parser.parse_args()

    source = fetch_arxiv_latex_source(args.arxiv_id)
    if source is None:
        print(f"Keine LaTeX-Quelle verfuegbar fuer {args.arxiv_id}", file=sys.stderr)
        return 1
    print(source)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
