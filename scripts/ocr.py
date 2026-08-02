#!/usr/bin/env python3
"""OCR-Wrapper fuer ocrmypdf.

Optionale Abhaengigkeit: ocrmypdf muss im PATH vorhanden sein.
Installation: brew install ocrmypdf  ODER  pip install ocrmypdf
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

log = logging.getLogger(__name__)

# Vorrang ueberall: Parameter > Env-Var > Default/Schaetzung.
# Muster analog zu resolve_max_parallel() in
# skills/parallel-screening/scripts/screening_ledger.py.
LANG_ENV = "ACADEMIC_RESEARCH_OCR_LANG"
TIMEOUT_ENV = "ACADEMIC_RESEARCH_OCR_TIMEOUT"

DEFAULT_LANG = "deu+eng"

# Zeitlimit-Schaetzung: Startwerte ohne empirische Grundlage aus diesem Repo
# (SKILL.md nennt "~30 s/Seite" als Faustregel fuer ocrmypdf lokal). Grosszuegig
# gewaehlt, damit langsamere Maschinen/Scans nicht faelschlich abbrechen.
SECONDS_PER_PAGE = 60.0
MIN_TIMEOUT_SECONDS = 300.0  # 5 Minuten Mindest-Zeitlimit, auch fuer kurze PDFs
FALLBACK_TIMEOUT_SECONDS = 3600.0  # 1 Stunde, falls Seitenzahl nicht lesbar ist

# ocrmypdf.exceptions.ExitCode.missing_dependency (siehe ocrmypdf-Doku:
# https://ocrmypdf.readthedocs.io/en/latest/apiref.html#ocrmypdf.exceptions.MissingDependencyError)
MISSING_DEPENDENCY_EXIT_CODE = 3


class OcrTimeoutError(RuntimeError):
    """ocrmypdf hat das konfigurierte Zeitlimit ueberschritten.

    Eigene Klasse (statt generischem RuntimeError), damit Aufrufer einen
    Zeitlimit-Abbruch programmatisch von einem inhaltlichen OCR-Fehlschlag
    unterscheiden koennen. Muster analog zu VaultLockedError in
    academic_vault/db.py.
    """


def _resolve_lang(lang: str | None) -> str:
    """Ermittelt die Tesseract-Sprachliste.

    Vorrang: Parameter ``lang`` > Env ``ACADEMIC_RESEARCH_OCR_LANG`` >
    Default ``"deu+eng"``.
    """
    if lang is not None:
        return lang
    env_lang = os.environ.get(LANG_ENV)
    if env_lang:
        return env_lang
    return DEFAULT_LANG


def _estimate_timeout_from_pages(input_pdf: str) -> float:
    """Schaetzt ein Zeitlimit aus der Seitenzahl von ``input_pdf``.

    Bei nicht lesbarer/oeffnbarer Datei (kaputtes oder verschluesseltes PDF)
    greift ``FALLBACK_TIMEOUT_SECONDS`` -- analog zum try/except-Muster von
    ``pdf.detect_needs_ocr``.
    """
    try:
        from pypdf import PdfReader

        total_pages = len(PdfReader(input_pdf).pages)
    except Exception:
        log.exception(
            "run_ocrmypdf: Seitenzahl von %s nicht ermittelbar, verwende Fallback-Zeitlimit",
            input_pdf,
        )
        return FALLBACK_TIMEOUT_SECONDS

    if total_pages <= 0:
        return FALLBACK_TIMEOUT_SECONDS

    return max(MIN_TIMEOUT_SECONDS, total_pages * SECONDS_PER_PAGE)


def _resolve_timeout(input_pdf: str, timeout: float | None) -> float:
    """Ermittelt das Zeitlimit in Sekunden fuer den ocrmypdf-Subprozess.

    Vorrang: Parameter ``timeout`` > Env ``ACADEMIC_RESEARCH_OCR_TIMEOUT`` >
    aus Seitenzahl hochgerechnet (``SECONDS_PER_PAGE``) > Fallback-Festwert.
    """
    if timeout is not None:
        return float(timeout)

    env_timeout = os.environ.get(TIMEOUT_ENV)
    if env_timeout:
        try:
            value = float(env_timeout)
        except ValueError:
            value = 0.0
        if value > 0:
            return value
        log.warning(
            "run_ocrmypdf: %s=%r ist kein gueltiges positives Zeitlimit, "
            "verwende stattdessen die Seitenzahl-Schaetzung",
            TIMEOUT_ENV,
            env_timeout,
        )

    return _estimate_timeout_from_pages(input_pdf)


# Exit-Code 3 (missing_dependency) deckt laut ocrmypdf-Doku nicht nur fehlende
# Tesseract-Sprachpakete ab, sondern auch Ghostscript, das tesseract-Binary
# selbst, unpaper, jbig2enc und pngquant. Nur wenn der stderr-Text auf ein
# Sprachdatei-Problem hindeutet, ist die sprachspezifische Meldung zutreffend
# -- sonst wuerde z. B. fehlendes Ghostscript faelschlich als Sprachproblem
# gemeldet (Review-Finding, PR #613).
_LANGUAGE_HINT_KEYWORDS = ("traineddata", "tessdata", "language")


def _is_language_related_stderr(lang: str, stderr: str) -> bool:
    """Prueft, ob ein missing_dependency-stderr tatsaechlich sprachbezogen ist."""
    stderr_lower = stderr.lower()
    if any(keyword in stderr_lower for keyword in _LANGUAGE_HINT_KEYWORDS):
        return True
    requested_codes = lang.split("+")
    return any(code and code.lower() in stderr_lower for code in requested_codes)


def _missing_language_message(lang: str, stderr: str) -> str:
    """Baut eine Fehlermeldung fuer ein fehlendes Tesseract-Sprachpaket.

    Die Sprachcode-Erkennung im stderr ist reine Zusatzinfo (das exakte
    stderr-Format kann je ocrmypdf-Version variieren) -- geworfen wird die
    Meldung bereits ueber den stabilen Exit-Code (``missing_dependency``),
    hier wird nur versucht, den betroffenen Sprachcode zu benennen. Aufrufer
    muss vorher mit ``_is_language_related_stderr`` pruefen, ob dieser Fall
    ueberhaupt zutrifft.
    """
    requested_codes = lang.split("+")
    matched = [code for code in requested_codes if code and code.lower() in stderr.lower()]
    codes_to_report = matched or requested_codes
    packages = ", ".join(f"tesseract-ocr-{code}" for code in codes_to_report)
    return (
        f"ocrmypdf meldet eine fehlende Tesseract-Sprachdatei fuer "
        f"'{lang}' (Exit {MISSING_DEPENDENCY_EXIT_CODE}): {stderr}\n"
        f"Installation: brew install tesseract-lang  (macOS, installiert alle "
        f"Sprachpakete)  ODER  apt-get install {packages}  (Debian/Ubuntu)."
    )


def run_ocrmypdf(
    input_pdf: str,
    output_pdf: str,
    lang: str | None = None,
    timeout: float | None = None,
) -> None:
    """Fuehrt ocrmypdf auf input_pdf aus und schreibt Ergebnis nach output_pdf.

    Prueft via shutil.which ob ocrmypdf im PATH vorhanden.

    Args:
        input_pdf: Pfad zum Eingangs-PDF (Scan ohne Text-Layer).
        output_pdf: Pfad fuer das OCR-behandelte Ausgabe-PDF.
        lang: Tesseract-Sprachliste fuer ``-l`` (z. B. ``"deu+eng"``).
            Vorrang: Parameter > Env ``ACADEMIC_RESEARCH_OCR_LANG`` > Default
            ``"deu+eng"``.
        timeout: Zeitlimit in Sekunden fuer den Subprozess. Vorrang: Parameter
            > Env ``ACADEMIC_RESEARCH_OCR_TIMEOUT`` > aus der Seitenzahl von
            ``input_pdf`` hochgerechnet > Fallback-Festwert (falls die
            Seitenzahl nicht lesbar ist).

    Raises:
        RuntimeError: Wenn ocrmypdf nicht im PATH ist oder der Prozess
            inhaltlich fehlschlaegt (z. B. fehlendes Sprachpaket -- die
            Meldung nennt dann Paketname und Installationsweg).
        OcrTimeoutError: Wenn der Subprozess das Zeitlimit ueberschreitet.
            Eigene Unterklasse von RuntimeError, damit dieser Fall
            programmatisch von einem inhaltlichen Fehlschlag unterscheidbar
            ist.
    """
    if shutil.which("ocrmypdf") is None:
        raise RuntimeError(
            "ocrmypdf nicht gefunden. "
            "Installation: brew install ocrmypdf  ODER  pip install ocrmypdf"
        )

    resolved_lang = _resolve_lang(lang)
    resolved_timeout = _resolve_timeout(input_pdf, timeout)

    cmd = ["ocrmypdf", "--skip-text", "-l", resolved_lang, input_pdf, output_pdf]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=resolved_timeout)
    except subprocess.TimeoutExpired as exc:
        raise OcrTimeoutError(
            f"ocrmypdf hat das Zeitlimit von {resolved_timeout:.0f}s "
            f"ueberschritten und wurde abgebrochen (input={input_pdf}). "
            "Das ist ein Zeitlimit-Abbruch, kein inhaltlicher OCR-Fehlschlag "
            "-- ggf. timeout erhoehen oder ACADEMIC_RESEARCH_OCR_TIMEOUT setzen."
        ) from exc

    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        if result.returncode == MISSING_DEPENDENCY_EXIT_CODE and _is_language_related_stderr(
            resolved_lang, stderr
        ):
            raise RuntimeError(_missing_language_message(resolved_lang, stderr))
        raise RuntimeError(f"ocrmypdf fehlgeschlagen (Exit {result.returncode}): {stderr}")
