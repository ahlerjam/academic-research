"""Testbarer Python-Spiegel der drei freien Archiv-Fetcher aus Issue #450.

Gleiches Muster wie ``tests/helpers/generic_fetcher_nav.py``: die Agenten unter
``agents/`` sind reine Prompts (kein Python, Issue #173). Damit AC1 aus #450
(„Jeder der drei Agents beschafft einen bekannten gemeinfreien Testtitel als
PDF") ueberhaupt eine pruefbare Aussage sein kann, bildet dieses Modul die
Beschaffungswege 1:1 nach und **fuehrt sie aus**: es holt die Datei ueber den
injizierten Transport, legt sie im Download-Verzeichnis ab, verschiebt sie auf
den Zielpfad und **liest sie von der Platte zurueck** — existiert, groesser als
``MIN_PDF_BYTES``, beginnt mit ``%PDF-``. Erst danach gibt es ``success``.

Warum der Umweg ueber ein Download-Verzeichnis statt „Datei direkt schreiben":
das ist der reale Mechanismus. ``browser-use`` (0.12.6) hat **kein**
``download``-Unterkommando. Dateien landen automatisch im Download-Verzeichnis
der Session (``accept_downloads=True``, ``auto_download_pdfs=True``,
``downloads_path`` = ``<tmp>/browser-use-downloads-<id>``); der Agent muss sie
von dort auf ``output_path`` verschieben und pruefen. Der Spiegel modelliert
genau diese Reihenfolge, damit der Prompt keinen Schritt beschreiben kann, den
das Werkzeug nicht hat.

**Grenze des Spiegels:** Der Transport ist injiziert. Im Agenten liefert ihn
``browser-use``, im hermetischen Test ein echter HTTP-Ursprung auf 127.0.0.1
(``tests/helpers/local_origin.py``). Das oeffentliche Netz der drei Archive
deckt ``tests/test_free_archive_live_fetch.py`` ab (opt-in ueber
``RUN_LIVE_ARCHIVE_FETCH=1``); der belegte Stand steht in
``evals/free-archive-fetchers/live-verification.json``.

Gegen Drift zwischen Prompt und Spiegel sichert
``tests/test_free_archive_fetchers.py::TestPromptMirrorCoupling`` ab.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable
from html import unescape
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Die drei Archive dieses Issues. Reihenfolge = Reihenfolge in ``AGENT_NAMES``.
ARCHIVES = ("hathitrust", "internetarchive", "mdz")

AGENT_FILES = {
    "hathitrust": os.path.join(REPO_ROOT, "agents", "hathitrust-fetcher.md"),
    "internetarchive": os.path.join(REPO_ROOT, "agents", "internetarchive-fetcher.md"),
    "mdz": os.path.join(REPO_ROOT, "agents", "mdz-fetcher.md"),
}

AGENT_NAME = {
    "hathitrust": "hathitrust-fetcher",
    "internetarchive": "internetarchive-fetcher",
    "mdz": "mdz-fetcher",
}

#: Kopf jeder PDF-Datei — erster Pruefstein der Download-Verifikation.
PDF_MAGIC = b"%PDF-"

#: Zweiter Pruefstein. Die Agenten fordern „Groesse > 10 KB"; darunter ist es
#: eine Fehlerseite oder ein Vorschau-Schnipsel, kein Digitalisat.
MIN_PDF_BYTES = 10 * 1024

#: Festes Praefix jedes ``reason``-Feldes, das eine Zugriffsstufe meldet (AC2).
ACCESS_LEVEL_PREFIX = "Zugriffsstufe:"

# ---------------------------------------------------------------------------
# Zugriffsstufen je Archiv (muessen woertlich im jeweiligen Prompt stehen)
# ---------------------------------------------------------------------------

ACCESS_LEVELS = {
    "hathitrust": ("Vollansicht", "Suche-im-Buch", "nur Metadaten"),
    "internetarchive": ("Vollansicht", "Borrow-only (Controlled Digital Lending)", "nur Metadaten"),
    "mdz": ("Vollansicht", "nur Metadaten"),
}

#: HathiTrust-Sonderfall: Zugriffsstufe Vollansicht, aber die Download-Route
#: antwortet mit einem Rate-Limit (HTTP 429). Live belegt am 2026-07-29, siehe
#: ``live-verification.json``. Bewusst NICHT als „Sperre" formuliert: 429 ist ein
#: voruebergehender Zustand, den HathiTrust selbst mit „IMAGE TEMPORARILY
#: UNAVAILABLE" und „Please try again." beschriftet.
HATHITRUST_RATE_LIMIT_REASON = (
    f"{ACCESS_LEVEL_PREFIX} Vollansicht, Download vom Rate-Limit abgewiesen (HTTP 429)"
)

#: Wie oft der Agent es erneut versuchen soll, bevor er aufgibt. Ein einziger
#: Versuch fuehrt bei einem Rate-Limit garantiert nie zu einer Datei — genau
#: dieser Fehler stand vor der Fix-Runde zu PR #498 im Spiegel.
HATHITRUST_DOWNLOAD_ATTEMPTS = 3

# ---------------------------------------------------------------------------
# DOM-Marker (live erhoben am 2026-07-29)
# ---------------------------------------------------------------------------

CAPTCHA_SIGNALS = (
    "Bestätigen Sie, dass Sie ein Mensch sind",
    "Verify you are human",
    "Sicherheitsüberprüfung wird durchgeführt",
    "Checking your browser",
    "reCAPTCHA",
)

HATHITRUST_FULL_VIEW_SIGNALS = ("Full view", "Public Domain.")
HATHITRUST_LIMITED_SIGNALS = ("Limited (search only)", "Limited (search-only)")
#: Antwortmarker der Download-Route, wenn das Rate-Limit greift. Die ersten
#: beiden sind HathiTrusts eigene Beschriftung des 429 (live gesehen im Viewer),
#: die letzten beiden die Cloudflare-Fehlerseite, die denselben Zustand traegt.
HATHITRUST_RATE_LIMIT_SIGNALS = (
    "Error code: 429",
    "IMAGE TEMPORARILY UNAVAILABLE",
    "Page Blocked",
    "your attempt to access HathiTrust has been blocked",
)

INTERNETARCHIVE_BORROW_SIGNALS = ("Borrow for 14 days", "available for lending only")

MDZ_PDF_MENU_TEXT = "PDF/DaFo"
MDZ_RIGHTS_RADIO = "xdfz"
MDZ_RIGHTS_ACCEPT_VALUE = "2"
MDZ_DOWNLOAD_READY_TEXT = "PDF-Datei öffnen oder herunterladen"

_ANCHOR_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.I | re.S)
_TAGS_RE = re.compile(r"<[^>]+>")
_DD_RE = re.compile(r"<dt>\s*{}\s*</dt>\s*<dd>(.*?)</dd>", re.I | re.S)
_FORM_RE = re.compile(r"<form\b([^>]*)>(.*?)</form>", re.I | re.S)
_INPUT_RE = re.compile(r"<input\b([^>]*?)/?>", re.I | re.S)

#: Attribute so lesen, wie Server sie wirklich schreiben: doppelt, einfach oder
#: gar nicht gequotet, mit oder ohne Leerzeichen ums Gleichheitszeichen. Die
#: MDZ-Zwischenseite liefert alle drei Varianten in einem einzigen Formular
#: (``name='xdfz'``, ``id="klammer"``, ``size=3 ... value = 1``) — eine auf
#: doppelte Anfuehrungszeichen festgelegte Regex faellt dort still auf die Nase.
_ATTR_RE = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")

#: Das blosse Attribut ``disabled`` (ohne Wert). Ein Browser schickt solche
#: Felder nicht mit — MDZ nutzt das fuer ``dafoumleitung``. Bewusst nicht als
#: Teilstring-Suche: ``this.disabled=true`` steht im onclick-Handler daneben.
_DISABLED_RE = re.compile(r"(?:^|\s)disabled(?=[\s/>]|$)", re.I)


def _attrs(tag_inner: str) -> dict[str, str]:
    return {
        match.group(1).casefold(): unescape(
            match.group(2) or match.group(3) or match.group(4) or ""
        )
        for match in _ATTR_RE.finditer(tag_inner)
    }


def _text(html: str) -> str:
    """Sichtbarer Text: Tags raus, Entities aufgeloest, Leerraum normalisiert.

    Das Aufloesen der Entities ist nicht kosmetisch — der MDZ-Link heisst im
    Markup ``PDF-Datei &ouml;ffnen oder herunterladen``; ohne ``unescape`` wuerde
    kein Vergleich mit dem sichtbaren Text je greifen.
    """
    return re.sub(r"\s+", " ", unescape(_TAGS_RE.sub(" ", html))).strip()


def _has(html: str, signals: tuple[str, ...]) -> str | None:
    lowered = html.casefold()
    for signal in signals:
        if signal.casefold() in lowered:
            return signal
    return None


def _anchors(html: str, base_url: str) -> list[tuple[str, str]]:
    """``[(sichtbarer Text, absolute URL)]`` in Dokumentreihenfolge."""
    out: list[tuple[str, str]] = []
    for raw_attrs, inner in _ANCHOR_RE.findall(html):
        href = _attrs(raw_attrs).get("href")
        if href:
            out.append((_text(inner), urljoin(base_url, href)))
    return out


def _definition(html: str, term: str) -> str:
    match = _DD_RE.pattern.format(re.escape(term))
    found = re.search(match, html, re.I | re.S)
    return _text(found.group(1)) if found else ""


class ArchiveDownloadError(RuntimeError):
    """Der Transport hat gar nichts geliefert — es gibt nichts zu pruefen."""


class ArchiveFetcherNavigator:
    """Spiegelt den Beschaffungsweg eines der drei Archiv-Fetcher.

    Args:
        archive: Einer der Werte aus :data:`ARCHIVES`.
        pages: URL -> HTML (im Agenten: ``browser-use open`` + ``browser-use state``).
            ``None`` = Seite nicht ladbar.
        downloads: URL -> Bytes. Im Agenten legt Chromium die Datei bei einem Klick
            selbst im Session-Download-Verzeichnis ab; hier liefert der Transport
            die Bytes, die der Spiegel genau dorthin schreibt.
        downloads_dir: Das Session-Download-Verzeichnis (im Agenten
            ``<tmp>/browser-use-downloads-<id>``).
    """

    def __init__(
        self,
        archive: str,
        pages: Callable[[str], str | None],
        downloads: Callable[[str], bytes | None],
        downloads_dir: str,
    ) -> None:
        if archive not in ARCHIVES:
            raise ValueError(f"Unbekanntes Archiv {archive!r}; erlaubt: {ARCHIVES}")
        self.archive = archive
        self._pages = pages
        self._downloads = downloads
        self.downloads_dir = downloads_dir

    # ------------------------------------------------------------------
    # Einstieg
    # ------------------------------------------------------------------

    def fetch(self, entry_url: str, output_path: str) -> dict:
        """Faehrt den Beschaffungsweg und gibt das Output-Schema des Agenten zurueck."""
        html = self._pages(entry_url)
        if html is None or not html.strip():
            return self._result("no_match", reason=f"Seite {entry_url} nicht ladbar oder leer")

        captcha = _has(html, CAPTCHA_SIGNALS)
        if captcha:
            return self._result("captcha", reason=f"CAPTCHA/Bot-Check erkannt ({captcha!r})")

        handler = {
            "hathitrust": self._fetch_hathitrust,
            "internetarchive": self._fetch_internetarchive,
            "mdz": self._fetch_mdz,
        }[self.archive]
        return handler(entry_url, html, output_path)

    # ------------------------------------------------------------------
    # HathiTrust
    # ------------------------------------------------------------------

    def _fetch_hathitrust(self, url: str, html: str, output_path: str) -> dict:
        if _has(html, HATHITRUST_LIMITED_SIGNALS):
            return self._result(
                "metadata_only",
                url=url,
                reason=f"{ACCESS_LEVEL_PREFIX} Suche-im-Buch",
            )
        if not _has(html, HATHITRUST_FULL_VIEW_SIGNALS):
            return self._result(
                "metadata_only",
                url=url,
                reason=f"{ACCESS_LEVEL_PREFIX} nur Metadaten",
            )

        target = self._hathitrust_volume_url(html, url)
        if target is None:
            return self._result(
                "pickup_required",
                url=url,
                reason="Vollansicht gemeldet, aber kein Gesamtband-Download-Link im Formular",
            )

        # Der Abruf der signierten URL kann statt der Datei die 429-Seite liefern.
        # Ein Rate-Limit gibt nach kurzer Wartezeit wieder frei, deshalb wird hier
        # erneut angeklopft statt sofort aufzugeben. Erst wenn alle Versuche
        # dasselbe Signal liefern, ist es ein Befund.
        for _attempt in range(HATHITRUST_DOWNLOAD_ATTEMPTS):
            probe = self._pages(target)
            if not (probe and _has(probe, HATHITRUST_RATE_LIMIT_SIGNALS)):
                return self._download(target, output_path, url, self._hathitrust_edition(html))
        return self._result("pickup_required", url=url, reason=HATHITRUST_RATE_LIMIT_REASON)

    @staticmethod
    def _hathitrust_volume_url(html: str, base_url: str) -> str | None:
        for text, href in _anchors(html, base_url):
            if "imgsrv/download" in href and text.casefold() == "download":
                return href
        return None

    @staticmethod
    def _hathitrust_edition(html: str) -> str:
        # Bewusst gegen das rohe Markup: im getaggten Text endet die Angabe am
        # naechsten Tag, im enttaggten Text liefe ``[^<]+`` bis zum Dateiende.
        found = re.search(r"Published:\s*([^<]+)", html, re.I)
        return _text(found.group(1)) if found else ""

    # ------------------------------------------------------------------
    # Internet Archive / Open Library
    # ------------------------------------------------------------------

    def _fetch_internetarchive(self, url: str, html: str, output_path: str) -> dict:
        pdf_url = self._internetarchive_pdf_url(html, url)
        if pdf_url is None:
            if _has(html, INTERNETARCHIVE_BORROW_SIGNALS):
                return self._result(
                    "metadata_only",
                    url=url,
                    reason=(f"{ACCESS_LEVEL_PREFIX} Borrow-only (Controlled Digital Lending)"),
                )
            return self._result(
                "metadata_only", url=url, reason=f"{ACCESS_LEVEL_PREFIX} nur Metadaten"
            )
        return self._download(pdf_url, output_path, url, self._internetarchive_edition(html))

    @staticmethod
    def _internetarchive_pdf_url(html: str, base_url: str) -> str | None:
        """Der Farb-PDF-Link. ``_bw.pdf`` ist die Graustufen-Zweitausgabe."""
        candidates = [
            href
            for text, href in _anchors(html, base_url)
            if urlsplit(href).path.casefold().endswith(".pdf") and "PDF download" in text
        ]
        for href in candidates:
            if not urlsplit(href).path.casefold().endswith("_bw.pdf"):
                return href
        return candidates[0] if candidates else None

    @staticmethod
    def _internetarchive_edition(html: str) -> str:
        publisher = _definition(html, "Publisher")
        date = _definition(html, "Publication date")
        return ", ".join(part for part in (publisher, date) if part)

    # ------------------------------------------------------------------
    # MDZ
    # ------------------------------------------------------------------

    def _fetch_mdz(self, url: str, html: str, output_path: str) -> dict:
        edition = _definition(html, "Entstehung")
        menu_url = next(
            (href for text, href in _anchors(html, url) if text == MDZ_PDF_MENU_TEXT), None
        )
        if menu_url is None:
            return self._result(
                "metadata_only", url=url, reason=f"{ACCESS_LEVEL_PREFIX} nur Metadaten"
            )

        form_html = self._pages(menu_url)
        if form_html is None or not form_html.strip():
            return self._result(
                "pickup_required", url=url, reason=f"Zwischenseite {menu_url} nicht ladbar"
            )

        ready_url = self._mdz_accept_rights(form_html, menu_url)
        if ready_url is None:
            return self._result(
                "pickup_required",
                url=url,
                reason=(
                    f"Rechtehinweis-Formular ohne Radiobutton {MDZ_RIGHTS_RADIO!r} — "
                    f"Ablauf hat sich geaendert"
                ),
            )

        ready_html = self._pages(ready_url)
        pdf_url = (
            None
            if ready_html is None
            else next(
                (
                    href
                    for text, href in _anchors(ready_html, ready_url)
                    if text.startswith(MDZ_DOWNLOAD_READY_TEXT)
                ),
                None,
            )
        )
        if pdf_url is None:
            return self._result(
                "pickup_required",
                url=url,
                reason=(
                    f"Nach Bestaetigung des Rechtehinweises kein Link "
                    f"{MDZ_DOWNLOAD_READY_TEXT!r} — Abbruch statt Rateversuch"
                ),
            )
        return self._download(pdf_url, output_path, url, edition)

    @staticmethod
    def _mdz_accept_rights(form_html: str, form_url: str) -> str | None:
        """Setzt den Rechtehinweis auf „Ja" und baut die Ziel-URL des ersten WEITER.

        Die Vorbelegung ist ``xdfz=1`` („Nein"); ohne die Umstellung auf
        ``xdfz=2`` liefert MDZ nur wieder die Zwischenseite. Live belegt am
        2026-07-29 (siehe ``evals/free-archive-fetchers/live-verification.json``).

        Abgeschickt wird, was ein Browser abschicken wuerde: alle ``hidden``- und
        ``text``-Felder ausser den ``disabled``-en (``dafoumleitung``), keine
        nicht angehakte Checkbox (``dafoocr``), dazu der gewaehlte Radiowert und
        der Name des gedrueckten Buttons.
        """
        form = next(
            (
                match
                for match in _FORM_RE.finditer(form_html)
                if any(
                    _attrs(raw).get("name") == MDZ_RIGHTS_RADIO
                    for raw in _INPUT_RE.findall(match.group(2))
                )
            ),
            None,
        )
        if form is None:
            return None
        action = _attrs(form.group(1)).get("action")
        if not action:
            return None

        fields: dict[str, str] = {}
        for raw_attrs in _INPUT_RE.findall(form.group(2)):
            attrs = _attrs(raw_attrs)
            name = attrs.get("name")
            if not name or _DISABLED_RE.search(raw_attrs):
                continue
            if attrs.get("type", "text").casefold() in ("hidden", "text"):
                fields[name] = attrs.get("value", "")

        fields[MDZ_RIGHTS_RADIO] = MDZ_RIGHTS_ACCEPT_VALUE
        fields["submitbutton"] = "WEITER"
        target = urljoin(form_url, action)
        parts = urlsplit(target)
        query = dict(parse_qsl(parts.query))
        query.update(fields)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))

    # ------------------------------------------------------------------
    # Beschaffung + Verifikation
    # ------------------------------------------------------------------

    def _download(self, pdf_url: str, output_path: str, source_url: str, edition: str) -> dict:
        """Klick -> Datei im Download-Verzeichnis -> verschieben -> von Platte pruefen."""
        try:
            landed = self._land_in_downloads_dir(pdf_url)
        except ArchiveDownloadError as exc:
            return self._result("pickup_required", url=source_url, reason=str(exc))

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        shutil.move(landed, output_path)

        size = self._verify_artifact(output_path)
        if size is None:
            os.remove(output_path)
            return self._result(
                "pickup_required",
                url=source_url,
                reason=(
                    f"Datei unter {output_path} bestand die Pruefung nicht "
                    f"(existiert / > {MIN_PDF_BYTES} Bytes / beginnt mit {PDF_MAGIC.decode()})"
                ),
            )

        return self._result(
            "success",
            pdf_path=output_path,
            url=source_url,
            edition=edition,
            reason=f"PDF verifiziert unter {output_path} ({size} Bytes, beginnt mit %PDF-)",
        )

    def _land_in_downloads_dir(self, pdf_url: str) -> str:
        """Modelliert das automatische Ablegen durch Chromium (``accept_downloads``)."""
        payload = self._downloads(pdf_url)
        if payload is None:
            raise ArchiveDownloadError(f"Download von {pdf_url} lieferte keine Daten")
        os.makedirs(self.downloads_dir, exist_ok=True)
        landed = os.path.join(self.downloads_dir, self._derive_name(pdf_url))
        with open(landed, "wb") as fh:
            fh.write(payload)
        return landed

    @staticmethod
    def _derive_name(pdf_url: str) -> str:
        name = os.path.basename(urlsplit(pdf_url).path) or "download"
        return name if name.casefold().endswith(".pdf") else f"{name}.pdf"

    @staticmethod
    def _verify_artifact(path: str) -> int | None:
        """Evidenzschritt: die geschriebene Datei zurueckgelesen, nicht behauptet."""
        if not os.path.isfile(path):
            return None
        size = os.path.getsize(path)
        if size <= MIN_PDF_BYTES:
            return None
        with open(path, "rb") as fh:
            head = fh.read(len(PDF_MAGIC))
        return size if head == PDF_MAGIC else None

    def _result(self, status: str, **extra) -> dict:
        result = {"status": status, "source_subagent": AGENT_NAME[self.archive]}
        result.update({k: v for k, v in extra.items() if v is not None})
        return result
