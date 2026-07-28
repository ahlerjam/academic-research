"""Testbarer Python-Spiegel der Navigationslogik aus ``agents/generic-fetcher.md``.

Gleiches Muster wie ``tests/helpers/book_fetcher_router.py``: der Agent selbst ist
ein reiner Prompt (kein Python unter ``agents/``, Issue #173). Damit die
Entscheidungsregeln trotzdem pruefbar sind, bildet dieses Modul sie 1:1 nach und
faehrt gegen gespeicherte DOM-Fixtures statt gegen einen echten Browser.

**Grenze des Spiegels:** Er trifft Entscheidungen, er laedt nichts herunter.
``_download()`` leitet nur den Zielpfad ab; ein echter Download passiert
ausschliesslich im Agenten via ``browser-use``. Alles, was hier gruen ist, belegt
die Navigations- und Abbruchlogik — nicht die Netz-Beschaffung (vgl.
``docs/evals/STRATEGY.md``, Status ``structural``).

Gegen Drift zwischen Prompt und Spiegel sichert
``tests/test_generic_fetcher.py::TestPromptMirrorCoupling`` in beide Richtungen ab.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlsplit

AGENT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "agents",
    "generic-fetcher.md",
)

# ---------------------------------------------------------------------------
# Vokabular (muss woertlich im Agent-Prompt stehen — Kopplungstest)
# ---------------------------------------------------------------------------

#: Die fuenf Seitenzustaende. Je Zustand genau eine erlaubte Folgeaktion.
PAGE_STATES = (
    "open_access",
    "licensed",
    "paywalled",
    "login_required",
    "unavailable",
)

#: Werte fuer ``tries[].decision`` plus der Abbruchgrund ``step_budget_exhausted``.
DECISIONS = (
    "pdf_link_detected",
    "embedded_pdf_detected",
    "downloaded",
    "licensed_route",
    "paywall_no_license",
    "login_wall_no_license",
    "page_unavailable",
    "safety_boundary",
    "captcha_detected",
    "redirect_followed",
    "step_budget_exhausted",
)

STEP_BUDGET_EXHAUSTED = "step_budget_exhausted"

POSITIVE_PDF_TEXTS = (
    "Download PDF",
    "PDF herunterladen",
    "Get PDF",
    "Volltext (PDF)",
    "Full Text",
    "View PDF",
)

NEGATIVE_PDF_TEXTS = ("Vorschau", "Preview", "Sample Chapter")

PAYWALL_SIGNALS = ("Get Access", "Purchase", "Buy", "Subscribe")

LOGIN_SIGNALS = (
    "Sign in to view",
    "Anmelden für Volltext",
    "Institutional Login",
    "Shibboleth",
)

CAPTCHA_SIGNALS = ("I'm not a robot", "Please verify", "reCAPTCHA")

UNAVAILABLE_SIGNALS = ("404 Not Found", "Page not found", "Seite nicht gefunden")


@dataclass(frozen=True)
class ViewerPattern:
    """Ein Viewer-/Embed-Muster fuer JavaScript-eingebettete PDFs.

    ``prompt_marker`` ist der Literal-Text, der im Agent-Prompt stehen MUSS —
    darueber haengt der Kopplungstest.
    """

    name: str
    prompt_marker: str


VIEWER_PATTERNS = (
    ViewerPattern("pdfjs_file_param", "viewer.html?file="),
    ViewerPattern("embed_application_pdf", '<embed type="application/pdf">'),
    ViewerPattern("object_application_pdf", '<object type="application/pdf">'),
    ViewerPattern("pdfjs_viewer_container", "#viewerContainer"),
    ViewerPattern("response_content_type", "Content-Type: application/pdf"),
)

_ANCHOR_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.I | re.S)
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
_SRC_RE = re.compile(r"""src\s*=\s*["']([^"']+)["']""", re.I)
_DATA_RE = re.compile(r"""data\s*=\s*["']([^"']+)["']""", re.I)
_META_REFRESH_RE = re.compile(
    r"""<meta[^>]+http-equiv\s*=\s*["']refresh["'][^>]*content\s*=\s*["'][^"']*?url\s*=\s*([^"';\s]+)""",
    re.I,
)
_VIEWER_FILE_RE = re.compile(r"""viewer[^"']*?[?&]file=([^"'&]+)""", re.I)
_EMBED_TAG_RE = re.compile(r"<embed\b[^>]*>", re.I)
_OBJECT_TAG_RE = re.compile(r"<object\b[^>]*>", re.I)
_VIEWER_CONTAINER_RE = re.compile(r"""id\s*=\s*["']viewerContainer["']""", re.I)
_PDF_DATA_ATTR_RE = re.compile(r"""data-pdf-url\s*=\s*["']([^"']+)["']""", re.I)
_TAGS_RE = re.compile(r"<[^>]+>")


def load_max_steps() -> int:
    """Liest ``maxSteps`` aus dem Frontmatter des Agent-Prompts (Single Source of Truth)."""
    import yaml

    with open(AGENT_FILE, encoding="utf-8") as fh:
        content = fh.read()
    match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if not match:
        raise ValueError(f"Kein Frontmatter in {AGENT_FILE}")
    fm = yaml.safe_load(match.group(1)) or {}
    max_steps = fm.get("maxSteps")
    if not isinstance(max_steps, int) or max_steps <= 0:
        raise ValueError(
            f"agents/generic-fetcher.md: maxSteps fehlt oder ist ungueltig: {max_steps!r}"
        )
    return max_steps


def _strip_tags(html: str) -> str:
    return _TAGS_RE.sub(" ", html)


def _first_signal(text: str, signals: tuple[str, ...]) -> str | None:
    lowered = text.casefold()
    for signal in signals:
        if signal.casefold() in lowered:
            return signal
    return None


class GenericFetcherNavigator:
    """Spiegelt den Entscheidungsbaum des generic-fetcher-Agenten.

    Args:
        profile: Geparste ``active.yaml`` (``licensed_sites``, ``proxy_pattern``,
            ``auth_url``). Leeres Dict = kein Uni-Profil.
        pages: URL -> HTML. Entweder ein Mapping oder eine Callable; fehlende
            Seiten liefern ``None`` (= Seite nicht ladbar).
        max_steps: Schritt-Budget; Default ist ``maxSteps`` aus dem Agent-Frontmatter.
        download_dir: Zielverzeichnis fuer den abgeleiteten ``file_path``.
    """

    def __init__(
        self,
        profile: Mapping,
        pages: Mapping[str, str] | Callable[[str], str | None],
        max_steps: int | None = None,
        download_dir: str = "/tmp",
    ) -> None:
        self.profile = dict(profile or {})
        self.licensed_sites = tuple(self.profile.get("licensed_sites") or ())
        self.proxy_pattern = self.profile.get("proxy_pattern") or ""
        self.auth_url = self.profile.get("auth_url") or ""
        self._pages = pages
        self.max_steps = load_max_steps() if max_steps is None else max_steps
        self.download_dir = download_dir

    # ------------------------------------------------------------------
    # Seitenzugriff (im Agenten: browser-use)
    # ------------------------------------------------------------------

    def _fetch(self, url: str) -> str | None:
        if callable(self._pages):
            return self._pages(url)
        return self._pages.get(url)

    # ------------------------------------------------------------------
    # Erkennungs-Heuristiken
    # ------------------------------------------------------------------

    def detect_captcha(self, html: str) -> str | None:
        return _first_signal(html, CAPTCHA_SIGNALS)

    def detect_redirect(self, html: str, base_url: str) -> str | None:
        match = _META_REFRESH_RE.search(html)
        return urljoin(base_url, match.group(1)) if match else None

    def detect_pdf_link(self, html: str, base_url: str) -> str | None:
        """Direkter PDF-Link: href auf ``.pdf`` oder Anchor-Text mit Positiv-Indikator."""
        for attrs, inner in _ANCHOR_RE.findall(html):
            href_match = _HREF_RE.search(attrs)
            if not href_match:
                continue
            href = href_match.group(1)
            text = _strip_tags(inner)
            if _first_signal(text, NEGATIVE_PDF_TEXTS):
                continue
            href_is_pdf = urlsplit(href).path.casefold().endswith(".pdf")
            if href_is_pdf or _first_signal(text, POSITIVE_PDF_TEXTS):
                return urljoin(base_url, href)
        return None

    def detect_embedded_pdf(self, html: str, base_url: str) -> tuple[str, str] | None:
        """Erkennt JavaScript-eingebettete PDFs. Gibt ``(pdf_url, pattern_name)`` zurueck."""
        if html.lstrip().casefold().startswith("content-type: application/pdf"):
            return base_url, "response_content_type"

        match = _VIEWER_FILE_RE.search(html)
        if match:
            return urljoin(base_url, unquote(match.group(1))), "pdfjs_file_param"

        for tag in _EMBED_TAG_RE.findall(html):
            src = _SRC_RE.search(tag)
            if src and (
                "application/pdf" in tag.casefold()
                or urlsplit(src.group(1)).path.casefold().endswith(".pdf")
            ):
                return urljoin(base_url, src.group(1)), "embed_application_pdf"

        for tag in _OBJECT_TAG_RE.findall(html):
            data = _DATA_RE.search(tag)
            if data and (
                "application/pdf" in tag.casefold()
                or urlsplit(data.group(1)).path.casefold().endswith(".pdf")
            ):
                return urljoin(base_url, data.group(1)), "object_application_pdf"

        if _VIEWER_CONTAINER_RE.search(html):
            attr = _PDF_DATA_ATTR_RE.search(html)
            if attr:
                return urljoin(base_url, unquote(attr.group(1))), "pdfjs_viewer_container"
        return None

    # ------------------------------------------------------------------
    # Uni-Profil
    # ------------------------------------------------------------------

    def is_licensed(self, url: str) -> bool:
        host = urlsplit(url).hostname or ""
        return any(
            host.casefold() == site.casefold() or host.casefold().endswith("." + site.casefold())
            for site in self.licensed_sites
        )

    def profile_route(self, url: str) -> str:
        """Der im Profil hinterlegte Zugangsweg — Proxy-Umschreibung, sonst ``auth_url``."""
        if self.proxy_pattern:
            parts = urlsplit(url)
            path = parts.path or "/"
            if parts.query:
                path = f"{path}?{parts.query}"
            return self.proxy_pattern.format(host=parts.hostname or "", path=path)
        return self.auth_url

    # ------------------------------------------------------------------
    # Zustandsklassifikation
    # ------------------------------------------------------------------

    def classify_state(self, html: str | None, url: str) -> str | None:
        """Einer der fuenf Zustaende — oder ``None``, wenn nichts eindeutig ist."""
        if html is None or not html.strip():
            return "unavailable"
        if _first_signal(html, UNAVAILABLE_SIGNALS):
            return "unavailable"

        gated = _first_signal(html, PAYWALL_SIGNALS) or _first_signal(html, LOGIN_SIGNALS)
        if gated and self.is_licensed(url) and self.profile_route(url):
            return "licensed"
        if self.detect_pdf_link(html, url) or self.detect_embedded_pdf(html, url):
            return "open_access"
        if _first_signal(html, PAYWALL_SIGNALS):
            return "paywalled"
        if _first_signal(html, LOGIN_SIGNALS):
            return "login_required"
        return None

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def navigate(
        self,
        url: str,
        title: str | None = None,
        session_context: str | None = None,
    ) -> dict:
        """Fuehrt den Entscheidungsbaum aus und gibt das Output-Schema zurueck."""
        tries: list[dict] = []
        current = url
        action = "load_page"

        while True:
            if len(tries) >= self.max_steps:
                return self._result("pickup_required", tries, reason=STEP_BUDGET_EXHAUSTED)

            html = self._fetch(current)
            step = len(tries) + 1

            if html is None or not html.strip():
                self._log(
                    tries, step, action, current, "Seite lieferte keinen Inhalt", "page_unavailable"
                )
                return self._result(
                    "no_match", tries, reason=f"Seite {current} nicht ladbar oder leer"
                )

            captcha = self.detect_captcha(html)
            if captcha:
                self._log(
                    tries, step, action, current, f"Captcha-Signal {captcha!r}", "captcha_detected"
                )
                return self._result("captcha", tries, reason=f"Captcha erkannt ({captcha!r})")

            redirect = self.detect_redirect(html, current)
            if redirect:
                self._log(
                    tries,
                    step,
                    action,
                    current,
                    f"Weiterleitung auf {redirect}",
                    "redirect_followed",
                )
                current, action = redirect, "load_page"
                continue

            state = self.classify_state(html, current)

            if state == "unavailable":
                self._log(
                    tries,
                    step,
                    action,
                    current,
                    "Seite meldet 'nicht verfuegbar'",
                    "page_unavailable",
                )
                return self._result("no_match", tries, reason=f"Kein Volltext unter {current}")

            if state == "open_access":
                pdf_url, decision = self._pdf_target(html, current)
                self._log(tries, step, action, current, f"PDF-Quelle {pdf_url}", decision)
                if len(tries) >= self.max_steps:
                    return self._result("pickup_required", tries, reason=STEP_BUDGET_EXHAUSTED)
                file_path = self._download(pdf_url)
                self._log(
                    tries,
                    len(tries) + 1,
                    "download_pdf",
                    pdf_url,
                    f"PDF gespeichert unter {file_path}",
                    "downloaded",
                )
                return self._result(
                    "success",
                    tries,
                    file_path=file_path,
                    pdf_url=pdf_url,
                    reason=f"Volltext ueber {decision} beschafft",
                )

            if state == "licensed":
                route = self.profile_route(current)
                self._log(
                    tries,
                    step,
                    action,
                    current,
                    f"Zugangs-Gate auf lizenzierter Domain, Profil-Route {route}",
                    "licensed_route",
                )
                if not session_context:
                    return self._result(
                        "auth_required",
                        tries,
                        url=route,
                        reason="Lizenzierte Domain im Uni-Profil — Zugang ueber den hinterlegten Weg statt anonymer Kopien",
                    )
                current, action = route, "open_profile_route"
                continue

            if state == "paywalled":
                signal = _first_signal(html, PAYWALL_SIGNALS)
                self._log(
                    tries, step, action, current, f"Paywall-Signal {signal!r}", "paywall_no_license"
                )
                return self._result(
                    "pickup_required",
                    tries,
                    reason=(
                        f"Paywall-Signal '{signal}' erkannt und keine passende Lizenz im "
                        f"Uni-Profil — Abbruch ohne Umgehungsversuch"
                    ),
                )

            if state == "login_required":
                signal = _first_signal(html, LOGIN_SIGNALS)
                self._log(
                    tries, step, action, current, f"Login-Wall {signal!r}", "login_wall_no_license"
                )
                return self._result(
                    "pickup_required",
                    tries,
                    reason=(
                        f"Login-Wall '{signal}' erkannt und keine passende Lizenz im "
                        f"Uni-Profil — Abbruch ohne Umgehungsversuch"
                    ),
                )

            self._log(
                tries,
                step,
                action,
                current,
                "Weder eindeutiger PDF-Hinweis noch eindeutiges Zugangs-Signal",
                "safety_boundary",
            )
            return self._result(
                "pickup_required",
                tries,
                reason="Kein Zustand eindeutig feststellbar — Safety-Boundary",
            )

    # ------------------------------------------------------------------
    # Interna
    # ------------------------------------------------------------------

    def _pdf_target(self, html: str, url: str) -> tuple[str, str]:
        direct = self.detect_pdf_link(html, url)
        if direct:
            return direct, "pdf_link_detected"
        embedded = self.detect_embedded_pdf(html, url)
        assert embedded is not None  # classify_state hat open_access nur dann gesetzt
        return embedded[0], "embedded_pdf_detected"

    def _download(self, pdf_url: str) -> str:
        """Leitet den Zielpfad ab — der Spiegel laedt selbst nichts herunter."""
        name = os.path.basename(urlsplit(pdf_url).path) or "download"
        if not name.casefold().endswith(".pdf"):
            name = f"{name}.pdf"
        return os.path.join(self.download_dir, name)

    @staticmethod
    def _log(
        tries: list[dict], step: int, action: str, url: str, observation: str, decision: str
    ) -> None:
        tries.append(
            {
                "step": step,
                "action": action,
                "url": url,
                "observation": observation,
                "decision": decision,
            }
        )

    @staticmethod
    def _result(status: str, tries: list[dict], **extra) -> dict:
        result = {"status": status, "source": "generic-fetcher", "tries": tries}
        result.update({k: v for k, v in extra.items() if v is not None})
        return result
