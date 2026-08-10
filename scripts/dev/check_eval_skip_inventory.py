"""Haelt die Skip-Menge eines Eval-Laufs gegen das dokumentierte Inventar (Issue #824).

Aufruf: ``python scripts/dev/check_eval_skip_inventory.py <junit.xml>``

Warum als eigener Schritt statt als pytest-Test? Der Guard muss die JUnit-XML
des **abgeschlossenen** Laufs sehen -- ein Test innerhalb desselben Laufs
kaeme dafuer zu frueh. Genutzt aus ``.github/workflows/eval-behavior.yml``,
damit ein neuer Dauer-Skip den geplanten Lauf rot faerbt, statt still gruen
durchzugehen (Muster Issue #470).

Exit-Codes: 0 = Skip-Menge entspricht dem Inventar, 1 = Abweichung,
2 = Aufruffehler.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.evals.skip_inventory import check_skip_inventory  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: check_eval_skip_inventory.py <junit.xml>", file=sys.stderr)
        return 2
    junit_path = Path(argv[1])
    if not junit_path.is_file():
        print(f"JUnit-XML nicht gefunden: {junit_path}", file=sys.stderr)
        return 2

    problems = check_skip_inventory(junit_path)
    if not problems:
        print("Skip-Inventar stimmt mit dem Lauf ueberein.")
        return 0
    print("Skip-Inventar weicht vom Lauf ab (Issue #824):", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
