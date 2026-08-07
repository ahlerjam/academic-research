"""Lokaler HuggingFace-Hub-Ursprung fuer den Abbruch-/Resume-Beleg (#718, AC4).

Warum ein eigener Ursprung statt eines Mocks von ``snapshot_download``:
AC4 ("ein abgebrochener Download wird beim naechsten Setup-Lauf fortgesetzt
statt neu begonnen") ist eine Aussage ueber den Cache-Zustand auf der Platte
nach einem echten Abbruch. Ein gemocktes ``snapshot_download`` legt keinen
Cache an und kann die Aussage grundsaetzlich nicht belegen. Diese Klasse
serviert deshalb auf 127.0.0.1 genau die drei Endpunkte, die
``huggingface_hub.snapshot_download`` braucht, sodass der Produktionspfad
(``scripts/model_prefetch.py`` -> ``snapshot_download`` -> Blob-Cache +
Snapshot-Symlinks) unveraendert und mit echten Bytes laeuft -- ohne dass ein
Test je das oeffentliche Netz oder ein GB-grosses Modell anfasst. Muster
uebernommen von ``tests/helpers/local_origin.py``.

Bediente Endpunkte (huggingface_hub 1.25.1):

* ``GET /api/models/{repo_id}/revision/{rev}``  -> Repo-Metadaten (``sha``)
* ``GET /api/models/{repo_id}/tree/{rev}``      -> Dateiliste (Vollstaendigkeits-Check)
* ``HEAD|GET /{repo_id}/resolve/{rev}/{datei}`` -> ETag/Groesse bzw. Bytes

Der Abbruch selbst wird ueber ``stall_file`` erzeugt: diese eine Datei wird
erst ausgeliefert, wenn alle uebrigen Dateien desselben Repos vollstaendig
durch sind, und dann nur noch tropfenweise. Der Test kann den herunterladenden
Prozess so exakt in dem Moment hart beenden, in dem ein Repo teils fertig, teils
noch in Uebertragung ist.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

#: Wartezeit, bis die uebrigen Dateien eines Repos durch sind, bevor die
#: Stall-Datei zu tropfen beginnt.
SIBLING_TIMEOUT_SECONDS = 30.0

#: Groesse und Takt der Tropfen-Auslieferung. Zusammen ergeben 64 Bytes alle
#: 20 ms ein Zeitfenster von mehreren Sekunden, in dem der Test zuverlaessig
#: hart beenden kann.
STALL_CHUNK_BYTES = 64
STALL_DELAY_SECONDS = 0.02


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Ein hart beendeter Client ist hier der Testfall, kein Serverfehler.

    Ohne diese Ueberschreibung schreibt ``ThreadingHTTPServer`` bei jedem
    abgerissenen Socket einen Traceback nach stderr -- im Abbruchtest also
    genau dann, wenn alles nach Plan laeuft.
    """

    daemon_threads = True

    def handle_error(self, request: object, client_address: object) -> None:
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Request:
    """Ein beim Ursprung eingegangener Aufruf.

    ``method`` ist ``"API"`` fuer die beiden Metadaten-Endpunkte und sonst das
    HTTP-Verb. ``range_header`` haelt den ``Range``-Header fest -- daran haengt
    die Aussage, ob ``huggingface_hub`` eine halb geladene Datei fortsetzt
    (Range gesetzt) oder von vorn beginnt (kein Range).
    """

    method: str
    repo_id: str
    filename: str
    range_header: str | None = None


def _fake_sha(repo_id: str) -> str:
    """Deterministischer 40-stelliger Commit-Hash je Repo (Format wie auf dem Hub)."""
    return hashlib.sha1(repo_id.encode()).hexdigest()


class FakeHfHub:
    """Serviert ``{repo_id: {dateiname: bytes}}`` als HF-Hub auf 127.0.0.1.

    Nutzung als Kontextmanager::

        with FakeHfHub({"org/mini": {"config.json": b"{}"}}) as hub:
            os.environ["HF_ENDPOINT"] = hub.endpoint
    """

    def __init__(
        self,
        repos: Mapping[str, Mapping[str, bytes]],
        *,
        stall_file: tuple[str, str] | None = None,
    ) -> None:
        self.repos = {repo: dict(files) for repo, files in repos.items()}
        self.stall_file = stall_file
        self.requests: list[Request] = []
        self._served: set[tuple[str, str]] = set()
        self._lock = threading.Lock()
        #: Gesetzt, sobald von der Stall-Datei die ersten Bytes auf der Leitung
        #: sind -- ab hier liegt beim Client eine halbe Datei auf der Platte.
        self.stall_started = threading.Event()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Lebenszyklus
    # ------------------------------------------------------------------

    def __enter__(self) -> FakeHfHub:
        self._server = _QuietThreadingHTTPServer(("127.0.0.1", 0), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def endpoint(self) -> str:
        assert self._server is not None, "FakeHfHub laeuft nicht (Kontextmanager benutzen)."
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    # ------------------------------------------------------------------
    # Auswertung
    # ------------------------------------------------------------------

    def reset_log(self) -> None:
        with self._lock:
            self.requests.clear()

    def downloaded_files(self, repo_id: str) -> set[str]:
        """Dateien dieses Repos, deren BYTES per GET tatsaechlich uebertragen wurden.

        Metadaten-Aufrufe (``HEAD``, ``/revision/``, ``/tree/``) zaehlen bewusst
        nicht mit: sie kosten keinen Download, und ``huggingface_hub`` fragt sie
        auch fuer bereits gecachte Dateien ab.
        """
        with self._lock:
            return {r.filename for r in self.requests if r.repo_id == repo_id and r.method == "GET"}

    def file_requests(self, repo_id: str, filename: str) -> list[Request]:
        with self._lock:
            return [r for r in self.requests if r.repo_id == repo_id and r.filename == filename]

    def touched_repos(self) -> set[str]:
        with self._lock:
            return {r.repo_id for r in self.requests}

    # ------------------------------------------------------------------
    # Interna
    # ------------------------------------------------------------------

    def _wait_for_siblings(self, repo_id: str, filename: str) -> None:
        """Blockiert, bis alle uebrigen Dateien dieses Repos ausgeliefert sind."""
        others = {name for name in self.repos[repo_id] if name != filename}
        deadline = time.monotonic() + SIBLING_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            with self._lock:
                if others <= {name for repo, name in self._served if repo == repo_id}:
                    return
            time.sleep(0.01)

    def _resolve(self, path: str) -> tuple[str, str] | None:
        """``/{repo}/resolve/{rev}/{datei}`` -> ``(repo_id, dateiname)``."""
        repo_part, sep, rest = path.lstrip("/").partition("/resolve/")
        if not sep or repo_part not in self.repos:
            return None
        _, _, filename = rest.partition("/")
        if filename not in self.repos[repo_part]:
            return None
        return repo_part, filename

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        hub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            # -- Antwort-Bausteine ------------------------------------
            def _json(self, payload: object) -> None:
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _not_found(self) -> None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _file_headers(self, repo_id: str, body: bytes) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("ETag", f'"{hashlib.sha256(body).hexdigest()}"')
                self.send_header("X-Repo-Commit", _fake_sha(repo_id))
                self.end_headers()

            # -- Routen -----------------------------------------------
            def do_HEAD(self) -> None:  # noqa: N802 — von BaseHTTPRequestHandler vorgegeben
                target = hub._resolve(urlsplit(self.path).path)
                if target is None:
                    self._not_found()
                    return
                repo_id, filename = target
                hub._log("HEAD", repo_id, filename, self.headers.get("Range"))
                self._file_headers(repo_id, hub.repos[repo_id][filename])

            def do_GET(self) -> None:  # noqa: N802 — von BaseHTTPRequestHandler vorgegeben
                path = urlsplit(self.path).path
                if path.startswith("/api/models/"):
                    self._serve_api(path)
                    return
                target = hub._resolve(path)
                if target is None:
                    self._not_found()
                    return
                self._serve_file(*target)

            def _serve_api(self, path: str) -> None:
                rest = path[len("/api/models/") :]
                for marker in ("/revision/", "/tree/"):
                    repo_id, sep, _ = rest.partition(marker)
                    if sep and repo_id in hub.repos:
                        hub._log("API", repo_id, marker.strip("/"))
                        files = hub.repos[repo_id]
                        if marker == "/revision/":
                            self._json(
                                {
                                    "id": repo_id,
                                    "modelId": repo_id,
                                    "sha": _fake_sha(repo_id),
                                    "siblings": [{"rfilename": n} for n in files],
                                }
                            )
                        else:
                            self._json(
                                [
                                    {
                                        "type": "file",
                                        "path": name,
                                        "size": len(body),
                                        "oid": hashlib.sha256(body).hexdigest()[:40],
                                    }
                                    for name, body in files.items()
                                ]
                            )
                        return
                self._not_found()

            def _serve_file(self, repo_id: str, filename: str) -> None:
                hub._log("GET", repo_id, filename, self.headers.get("Range"))
                body = hub.repos[repo_id][filename]
                if hub.stall_file == (repo_id, filename):
                    hub._wait_for_siblings(repo_id, filename)
                    self._file_headers(repo_id, body)
                    self._trickle(body)
                    return
                self._file_headers(repo_id, body)
                self.wfile.write(body)
                hub._mark_served(repo_id, filename)

            def _trickle(self, body: bytes) -> None:
                """Liefert die Datei so langsam aus, dass der Test dazwischenhauen kann."""
                for offset in range(0, len(body), STALL_CHUNK_BYTES):
                    try:
                        self.wfile.write(body[offset : offset + STALL_CHUNK_BYTES])
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return  # Client wurde beendet -- genau das ist der Testfall
                    hub.stall_started.set()
                    time.sleep(STALL_DELAY_SECONDS)

            def log_message(self, *args: object) -> None:
                """Kein Request-Log auf stderr waehrend der Testlaeufe."""

        return Handler

    def _log(
        self, method: str, repo_id: str, filename: str, range_header: str | None = None
    ) -> None:
        with self._lock:
            self.requests.append(
                Request(
                    method=method,
                    repo_id=repo_id,
                    filename=filename,
                    range_header=range_header,
                )
            )

    def _mark_served(self, repo_id: str, filename: str) -> None:
        with self._lock:
            self._served.add((repo_id, filename))
