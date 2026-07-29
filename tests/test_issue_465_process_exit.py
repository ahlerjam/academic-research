"""Regressionstest fuer Fix-Runde PR #487 (Issue #465), AC1 auf Prozessebene.

Der urspruengliche Fix (PR #487, Commit 1615b52) begrenzt run_search()/main()
korrekt ueber `time_budget` -- beide kehren innerhalb des Budgets zurueck. Der
produktiv genutzte Aufrufpfad ist aber nicht main() als Python-Funktion,
sondern `python scripts/search.py ...` als eigener Prozess (siehe
commands/search.md, Schritt 3, Bash-Aufruf). AC1 verlangt: "Der Gesamtlauf ist
ueber einen konfigurierbaren Wert begrenzt und haelt ihn ein" -- gemeint ist
der Lauf, den der Aufrufer (Bash-Tool/Shell) tatsaechlich abwartet, also die
Prozesslaufzeit, nicht nur die Rueckkehrzeit von main().

Root cause (siehe tests/fixtures/search/_subprocess_time_budget_driver.py):
concurrent.futures.thread registriert einen globalen atexit-Hook
(threading._register_atexit), der beim Interpreter-Exit ALLE je gestarteten
ThreadPoolExecutor-Worker-Threads joint -- unabhaengig davon, ob
executor.shutdown(wait=False, cancel_futures=True) bereits aufgerufen wurde.
cancel_futures=True storniert nur noch nicht gestartete Futures; ein Worker-
Thread, der bereits in einem blockierenden httpx-Request steckt (hier:
crossref mit kuenstlicher Verzoegerung), laeuft bis zu dessen Ende weiter und
haelt damit den Prozessexit auf -- selbst wenn run_search() das Budget laengst
eingehalten und main() bereits zurueckgekehrt ist.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

DRIVER = Path(__file__).parent / "fixtures" / "search" / "_subprocess_time_budget_driver.py"
FIXTURES = Path(__file__).parent / "fixtures" / "search"
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"

TIME_BUDGET_S = 1.0
SLOW_DELAY_S = 2.0
# Aktuell (vor dem Fix) braucht der Gesamtprozess ca. 2.5-3.3s (SLOW_DELAY_S +
# internes time.sleep(0.5) je Quelle + Python-Start-Overhead), obwohl main()
# nach ca. 1.0-1.1s zurueckkehrt. Der Toleranzwert liegt bewusst deutlich
# unter diesem beobachteten Ist-Wert, aber mit Luft ueber dem Budget fuer
# Prozessstart-Overhead auf langsamer CI-Hardware.
MAX_ALLOWED_PROCESS_S = TIME_BUDGET_S + 1.0


def test_subprocess_terminates_within_time_budget(tmp_path):
    """Der Gesamtprozess (nicht nur main()/run_search()) muss innerhalb des
    konfigurierten Zeitbudgets tatsaechlich terminieren (AC1, Prozessebene).

    Reproduziert den produktiven Aufrufpfad aus commands/search.md: `python
    scripts/search.py --time-budget 1.0 ...` mit einer kuenstlich um 2s
    verzoegerten Quelle (crossref). Vor dem Fix haengt der Prozess am
    concurrent.futures.thread-atexit-Hook fest, bis der langsame Worker-
    Thread seinen blockierenden Request beendet hat -- weit ueber dem Budget.
    """
    output_path = tmp_path / "results.json"

    start = time.monotonic()
    proc = subprocess.run(
        [
            sys.executable,
            str(DRIVER),
            str(SCRIPTS_DIR),
            str(FIXTURES),
            str(output_path),
            str(SLOW_DELAY_S),
            str(TIME_BUDGET_S),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    elapsed = time.monotonic() - start

    assert proc.returncode == 0, (
        f"Treiber-Prozess exitcode={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    assert elapsed < MAX_ALLOWED_PROCESS_S, (
        f"Gesamtprozess brauchte {elapsed:.2f}s bis zum tatsaechlichen Exit "
        f"(Budget={TIME_BUDGET_S}s, erlaubte Obergrenze={MAX_ALLOWED_PROCESS_S}s) -- "
        "main()/run_search() halten das Budget zwar ein, der Prozess wartet aber "
        "beim Interpreter-Exit auf den noch laufenden langsamen Worker-Thread "
        "(concurrent.futures.thread-atexit-Hook)."
    )

    # Die schnellen Quellen (openalex/arxiv) muessen trotz Skip von crossref
    # vollstaendig im Ergebnis stehen (AC3) -- das war schon vor diesem Fix
    # korrekt und darf durch die Aenderung nicht regressieren.
    status_path = tmp_path / "results_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["skipped_modules"] == ["crossref"]
    assert status["failed_modules"] == []
    assert status["papers_per_module"]["openalex"] > 0
    assert status["papers_per_module"]["arxiv"] > 0
