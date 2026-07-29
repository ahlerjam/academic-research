"""Subprocess-Treiber fuer den Prozess-Exit-Regressionstest zu #465 (Fix-Runde PR #487).

Wird NICHT von pytest direkt gesammelt (kein `test_`-Praefix), sondern von
tests/test_issue_465_process_exit.py per `subprocess.run([sys.executable,
DIESE_DATEI, ...])` gestartet. Bildet exakt den produktiv genutzten Aufrufpfad
nach, den commands/search.md ueber Bash aufruft (`python scripts/search.py
... --time-budget ...`): das `httpx`-Modul wird VOR dem Ausfuehren von
search.py global gepatcht (Client durch ein MockTransport ersetzt, kein
echter Netzwerkzugriff), dann wird search.py per `runpy.run_path(...,
run_name="__main__")` als eigenstaendiges Skript ausgefuehrt -- das feuert
tatsaechlich dessen `if __name__ == "__main__":`-Guard (inkl. `sys.exit(...)`
bzw. `os._exit(...)`), NICHT nur `search.main()` als importierte Funktion.
Ein direkter `search.main()`-Aufruf wuerde diesen Guard uebergehen und damit
den Fix aus #487 gar nicht erst durchlaufen -- genau dieser Unterschied
wurde in der ersten Fassung dieses Treibers uebersehen (Fix-Runde PR #487,
Debugging-Notiz: der erste Testlauf blieb trotz os._exit()-Fix bei 2.63s
haengen, weil hier faelschlich `search.main()` statt des `__main__`-Guards
aufgerufen wurde).

Damit misst der aufrufende Test die tatsaechliche Prozesslaufzeit (Python-
Interpreter-Start bis Exit), nicht nur die Rueckkehrzeit von main()/run_search()
-- genau das Symptom aus der Fix-Runden-Meldung: main() kehrt innerhalb des
Budgets zurueck, der Gesamtprozess terminiert aber erst, wenn der zuvor
gestartete langsame Worker-Thread fertig ist (concurrent.futures.thread
joint beim Interpreter-Exit ALLE je gestarteten Executor-Threads, unabhaengig
von executor.shutdown(wait=False, cancel_futures=True)).

Argumente: <scripts_dir> <fixtures_dir> <output_path> <slow_delay_s> <time_budget_s>
"""

from __future__ import annotations

import runpy
import sys
import time
from pathlib import Path


def main() -> None:
    scripts_dir, fixtures_dir, output_path, slow_delay_s, time_budget_s = sys.argv[1:6]

    sys.path.insert(0, scripts_dir)

    import httpx

    def _fixture_response(name: str, content_type: str = "application/json") -> httpx.Response:
        body = (Path(fixtures_dir) / name).read_bytes()
        return httpx.Response(200, content=body, headers={"content-type": content_type})

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.crossref.org" in url:
            time.sleep(float(slow_delay_s))
            return _fixture_response("crossref_response.json")
        if "api.openalex.org" in url:
            return _fixture_response("openalex_response.json")
        if "export.arxiv.org" in url:
            return _fixture_response("arxiv_response.xml", "text/xml")
        return httpx.Response(404, text="unknown host in test driver")

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def patched_client(*args: object, **kwargs: object) -> httpx.Client:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)  # type: ignore[arg-type]

    # Patcht das *echte* httpx-Modul (nicht erst nach einem `import search`),
    # damit runpy.run_path() unten search.py voellig unveraendert -- inkl.
    # seines eigenen `import httpx` -- als "__main__" ausfuehren kann und
    # dabei denselben, bereits gepatchten httpx.Client-Namen sieht.
    httpx.Client = patched_client  # type: ignore[assignment]

    sys.argv = [
        "search.py",
        "--query",
        "climate change",
        "--modules",
        "crossref,openalex,arxiv",
        "--limit",
        "3",
        "--time-budget",
        time_budget_s,
        "--output",
        output_path,
    ]

    # runpy.run_path(..., run_name="__main__") fuehrt search.py exakt so aus,
    # wie `python scripts/search.py ...` es taete -- inkl. seines
    # `if __name__ == "__main__":`-Guards (sys.exit()/os._exit()). Ein
    # direkter Aufruf von `search.main()` (fruehere Fassung dieses Treibers)
    # wuerde diesen Guard NICHT durchlaufen und damit den in #487 dort
    # platzierten Fix umgehen.
    script_path = str(Path(scripts_dir) / "search.py")
    runpy.run_path(script_path, run_name="__main__")


if __name__ == "__main__":
    main()
