"""AC3-Regression (#718): die Lazy-Download-Meldung darf den MCP-stdio-Kanal nicht zerstoeren.

``academic_vault/server.py`` startet per ``mcp.run()`` -- Default-Transport ist
``stdio`` (``FastMCP.run(transport="stdio")``), und dort IST ``sys.stdout`` der
JSON-RPC-Kanal: ``mcp.server.stdio.stdio_server`` legt einen
``TextIOWrapper(sys.stdout.buffer)`` darueber und schreibt jede Antwort als eine
Zeile JSON hinein. Jede Nicht-JSON-Zeile auf stdout ist damit ein
Protokollfehler, kein kosmetisches Problem -- und alle drei Lazy-Load-Pfade
(Embedding, Reranker, NLI) laufen IN-PROCESS in genau diesem Prozess.

Der Test startet den echten Serverprozess, laesst einen echten MCP-Tool-Aufruf
(``vault.component_status`` -> ``health.get_component_status`` ->
``embedding_model.get_embedder``) den Lazy-Load ausloesen und prueft beide
Kanaele: stdout traegt ausschliesslich JSON, die Meldung selbst steht auf
stderr. Beide Haelften sind noetig -- ein blosses Loeschen der Meldung wuerde
die erste Haelfte auch erfuellen, AC3 aber verfehlen.

Kein Netzzugriff: ``sentence_transformers`` wird per PYTHONPATH durch ein
Stub-Modul ersetzt, das beim Laden abbricht. Die Groessen-Meldung faellt davor,
danach greift der dokumentierte Degradationspfad (``get_embedder() -> None``).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("mcp.server.fastmcp")

from mcp.types import LATEST_PROTOCOL_VERSION  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

# Stub statt echtem Backend: der Import in ``_load_backend_model`` gelingt (er
# steht VOR der Meldung), die Instanziierung danach nicht -- genau das Fenster,
# in dem die Meldung faellt.
_STUB_SENTENCE_TRANSFORMERS = (
    "class SentenceTransformer:\n"
    "    def __init__(self, *args, **kwargs):\n"
    '        raise RuntimeError("Test-Stub: kein echtes Modell, kein Netzzugriff")\n'
)

_TOOL_CALL_ID = 2


def _drain(stream, sink: list[str]) -> None:
    for line in stream:
        sink.append(line)


def _server_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """Env eines realen Serverstarts, aber vollstaendig von HOME/Netz isoliert."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    project_dir = tmp_path / "mein-forschungsprojekt"
    project_dir.mkdir()

    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    (stub_dir / "sentence_transformers.py").write_text(
        _STUB_SENTENCE_TRANSFORMERS, encoding="utf-8"
    )

    # Leeres Cache-Verzeichnis => is_cached() ist False => die Meldung faellt.
    model_cache = tmp_path / "leerer-model-cache"
    model_cache.mkdir()

    env = dict(os.environ)
    env["HOME"] = str(fake_home)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env["PYTHONPATH"] = os.pathsep.join([str(stub_dir), str(REPO_ROOT)])
    env["SQLITE_VEC_PATH"] = ""
    env["VAULT_EMBEDDING_CACHE"] = str(model_cache)
    # Doppelt gesichert gegen Netzzugriff: is_cached() nutzt bereits
    # local_files_only=True, HF_HUB_OFFLINE macht es prozessweit verbindlich.
    env["HF_HUB_OFFLINE"] = "1"
    # Ohne das ist stdout gegen eine Pipe blockgepuffert; die Verschmutzung
    # traefe dann irgendwann und ggf. mitten in einer JSON-Zeile ein. Mit
    # Zeilenpufferung wird der Defekt zu genau einer zusaetzlichen Zeile --
    # reproduzierbar pruefbar statt zufaellig zerhackt.
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("VAULT_DB_PATH", None)
    return env, project_dir


def _call_component_status(tmp_path: Path, timeout: float = 180.0) -> tuple[list[str], str]:
    """Fuehrt initialize + tools/call gegen den echten Serverprozess aus.

    Rueckgabe: (stdout-Zeilen, stderr-Text). Bewusst rohes JSON-RPC statt
    ``mcp.client.stdio``: der Client verwirft eine unparsebare Zeile still
    (``read_stream_writer.send(exc)``, im ``_receive_loop`` nur weitergereicht)
    -- er wuerde den Protokollbruch also gar nicht sichtbar machen.
    """
    env, project_dir = _server_env(tmp_path)

    proc = subprocess.Popen(
        [sys.executable, "-m", "academic_vault.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(project_dir),
        text=True,
        encoding="utf-8",
        bufsize=1,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    threads = [
        threading.Thread(target=_drain, args=(proc.stdout, stdout_lines), daemon=True),
        threading.Thread(target=_drain, args=(proc.stderr, stderr_lines), daemon=True),
    ]
    for thread in threads:
        thread.start()

    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "issue718-stdio-test", "version": "1.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": _TOOL_CALL_ID,
            "method": "tools/call",
            "params": {"name": "vault.component_status", "arguments": {}},
        },
    ]

    try:
        assert proc.stdin is not None
        for request in requests:
            proc.stdin.write(json.dumps(request) + "\n")
            proc.stdin.flush()

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _has_response(stdout_lines, _TOOL_CALL_ID):
                break
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        else:  # pragma: no cover -- nur bei haengendem Server
            pytest.fail(
                "Keine Antwort auf vault.component_status innerhalb von "
                f"{timeout:.0f}s. stdout={stdout_lines!r} stderr={''.join(stderr_lines)!r}"
            )
    finally:
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except OSError:  # pragma: no cover
            pass
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()
            proc.wait(timeout=30)
        for thread in threads:
            thread.join(timeout=30)

    return stdout_lines, "".join(stderr_lines)


def _has_response(lines: list[str], request_id: int) -> bool:
    for line in list(lines):
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("id") == request_id:
            return True
    return False


@pytest.fixture(scope="module")
def channels(tmp_path_factory) -> tuple[list[str], str]:
    """Ein Serverstart fuer beide Assertions -- der Prozessstart ist der teure Teil."""
    return _call_component_status(tmp_path_factory.mktemp("issue718-stdio"))


class TestLazyDownloadNoticeKeepsStdioProtocolIntact:
    """AC3: Meldung vor dem Lazy-Download -- ohne den JSON-RPC-Kanal zu brechen."""

    def test_server_stdout_carries_only_json_rpc_lines(self, channels):
        stdout_lines, stderr = channels
        offenders = []
        for line in stdout_lines:
            if not line.strip():
                continue
            try:
                json.loads(line)
            except ValueError:
                offenders.append(line.rstrip("\n"))
        assert not offenders, (
            "Nicht-JSON-Zeilen auf stdout des MCP-Servers -- der JSON-RPC-Kanal ist "
            f"zerstoert: {offenders!r}\nstderr:\n{stderr}"
        )

    def test_lazy_download_notice_reaches_stderr(self, channels):
        stdout_lines, stderr = channels
        assert "Embedding-Modell" in stderr, (
            "Die Groessen-Meldung vor dem Lazy-Download fehlt auf stderr -- AC3 verlangt "
            f"sie, nur eben nicht auf stdout.\nstderr:\n{stderr}"
        )
        assert "GB" in stderr, f"Meldung auf stderr ohne Groessenangabe:\n{stderr}"
        assert not any("Embedding-Modell" in line for line in stdout_lines), (
            "Die Meldung steht (auch) auf stdout -- genau der Protokollbruch, den "
            "AC3 verhindern soll."
        )
