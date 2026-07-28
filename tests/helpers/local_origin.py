"""Lokaler HTTP-Ursprung fuer hermetische End-to-End-Laeufe der Fetcher-Spiegel.

Warum das hier steht und nicht im Spiegel: ``generic_fetcher_nav.py`` bildet den
**Agenten** ab, und der ruft nie selbst HTTP auf (Verbots-Kapitel in
``agents/generic-fetcher.md``: „Keine direkten HTTP-Calls"). Der Agent bekommt
Seiten und Dateien ueber browser-use. Diese Klasse steht im Test genau an dieser
Stelle: sie ist der Transport, den der Spiegel injiziert bekommt.

Damit laeuft die Beschaffung nicht als Attrappe, sondern als echter Vorgang —
HTTP-GET auf einen realen Socket, echte Bytes, echte Datei auf der Platte —
ohne dass ein Test jemals das oeffentliche Netz beruehrt: ``get()`` weist jede
URL ausserhalb des eigenen Ursprungs hart zurueck.
"""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

#: Antwort-Timeout je Request. Der Server laeuft im selben Prozess auf Loopback.
TIMEOUT_SECONDS = 10


class LocalOrigin:
    """Serviert ein festes Routing ``pfad -> (content_type, bytes)`` auf 127.0.0.1.

    Nutzung als Kontextmanager::

        with LocalOrigin({"/a.pdf": ("application/pdf", pdf_bytes)}) as origin:
            navigator = GenericFetcherNavigator(
                profile={},
                pages=origin.page_transport(),
                assets=origin.asset_transport(),
            )

    Unbekannte Pfade beantwortet der Server mit einem echten 404.
    """

    def __init__(self, routes: Mapping[str, tuple[str, bytes]]) -> None:
        self.routes = dict(routes)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Lebenszyklus
    # ------------------------------------------------------------------

    def __enter__(self) -> LocalOrigin:
        routes = self.routes

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 — von BaseHTTPRequestHandler vorgegeben
                entry = routes.get(urlsplit(self.path).path)
                if entry is None:
                    body = b"<html><body><h1>404 Not Found</h1></body></html>"
                    self._respond(404, "text/html; charset=utf-8", body)
                    return
                content_type, body = entry
                self._respond(200, content_type, body)

            def _respond(self, code: int, content_type: str, body: bytes) -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                """Kein Request-Log auf stderr waehrend der Testlaeufe."""

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=TIMEOUT_SECONDS)
            self._thread = None

    # ------------------------------------------------------------------
    # Adressen
    # ------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("LocalOrigin ist nicht gestartet (als Kontextmanager benutzen).")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def get(self, url: str) -> tuple[str, bytes] | None:
        """Echter HTTP-GET gegen den eigenen Ursprung. ``None`` bei 4xx/5xx.

        Raises:
            ValueError: wenn die URL nicht auf diesen Ursprung zeigt. Der Test
                soll laut scheitern statt still ins oeffentliche Netz zu greifen.
        """
        if not url.startswith(self.base_url + "/"):
            raise ValueError(f"URL zeigt nicht auf den lokalen Ursprung {self.base_url}: {url}")
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
                return response.headers.get_content_type(), response.read()
        except urllib.error.URLError:
            # HTTPError ist eine URLError-Unterklasse — 404 landet ebenfalls hier.
            return None

    def page_transport(self) -> Callable[[str], str | None]:
        """Seiten-Transport fuer den Spiegel (im Agenten: browser-use „Seite laden").

        Liefert eine PDF-Antwort mit vorangestellter ``Content-Type``-Zeile aus,
        damit die Viewer-Heuristik dieselbe Beobachtung sieht wie im Browser.
        """

        def _load(url: str) -> str | None:
            payload = self.get(url)
            if payload is None:
                return None
            content_type, body = payload
            text = body.decode("utf-8", errors="replace")
            if "application/pdf" in content_type:
                return f"Content-Type: {content_type}\n\n{text}"
            return text

        return _load

    def asset_transport(self) -> Callable[[str], bytes | None]:
        """Datei-Transport fuer den Spiegel (im Agenten: browser-use „Download")."""

        def _download(url: str) -> bytes | None:
            payload = self.get(url)
            return None if payload is None else payload[1]

        return _download
