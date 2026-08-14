#!/usr/bin/env python3
"""Aequivalenzpruefung der #890-Fassung von `deduplicate()` gegen die
Vor-#890-Fassung auf der REALEN Treffermenge vom 12.08.2026 (Issue #890 AC3).

Warum dieses Skript existiert
-----------------------------
AC3 von #890 verlangt woertlich: „Auf der Treffermenge vom 12.08.2026 findet
die neue Fassung dieselben Zusammenfuehrungen wie die alte." Die Rohdatei
dieser Menge liegt dort, wo `commands/search.md` sie schreibt: im
Sitzungsverzeichnis des Laufs,
`~/.academic-research/sessions/2026-08-12T10-25-52Z/`. `all_raw.json` dieses
Laufs enthaelt exakt die 1957 Treffer, die im Issue als zweite Messung
(„1957 Titel liefen ueber 5 Minuten ohne Ergebnis") stehen; `prefiltered.json`
die 1603 der ersten Messung.

Dieses Skript

1. zieht aus dieser Rohdatei eine eingecheckte Fixture (`extract`) — nur die
   Felder, die `deduplicate()` liest, ohne Abstracts/Autoren,
2. laesst die HISTORISCHE Fassung `d141b09:scripts/dedup.py` (der Stand direkt
   vor #890, gemergt als PR #758) darauf laufen und friert deren Ergebnis als
   Golden-Datei ein (`golden`),
3. vergleicht das Ergebnis der AKTUELLEN Fassung mit dieser Golden-Datei
   (`compare`) — wahlweise gegen die eingefrorene Datei (schnell) oder gegen
   einen frischen Lauf der historischen Fassung (`--live`, Minuten).

Die Referenz wird bewusst per `git show` aus der Historie geladen und nicht im
Test nachgebaut: Nur so ist „die alte Fassung" tatsaechlich die alte Fassung
und keine Re-Implementierung, die von ihr abweichen kann.

Aufrufe
-------
    uv run python scripts/dev/verify_dedup_890_hitset.py extract \\
        --source ~/.academic-research/sessions/2026-08-12T10-25-52Z/all_raw.json

    uv run python scripts/dev/verify_dedup_890_hitset.py golden      # Minuten

    uv run python scripts/dev/verify_dedup_890_hitset.py compare     # Sekunden
    uv run python scripts/dev/verify_dedup_890_hitset.py compare --live

    # gegen die unreduzierten Rohdatensaetze desselben Laufs:
    uv run python scripts/dev/verify_dedup_890_hitset.py compare --live \\
        --papers ~/.academic-research/sessions/2026-08-12T10-25-52Z/all_raw.json
"""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "dedup_890"
HITSET_PATH = FIXTURE_DIR / "hitset_2026-08-12.json.gz"
GOLDEN_PATH = FIXTURE_DIR / "golden_pre_890_output.json.gz"

# Stand von scripts/dedup.py direkt VOR #890: der #707-Merge aus PR #758.
PRE_890_REV = "d141b09"

# Felder, die `deduplicate()`/`merge_group()` tatsaechlich lesen. Abstracts und
# Autorennamen bleiben draussen (Umfang und Fremdtext), `run`/`query_block`
# sind Laufmetadaten ohne Wirkung auf die Gruppierung.
FIXTURE_FIELDS = ("title", "doi", "url", "year", "source_module", "citations")


def load_json_gz(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    assert isinstance(data, list)
    return data


def save_json_gz(payload: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0: die Datei ist ein eingecheckter Fixture-Stand, kein Zeitstempel-
    # Artefakt — sonst aendert jede Neuerzeugung den Blob ohne Inhaltsaenderung.
    with path.open("wb") as handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0) as raw:
            raw.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1).encode())


def load_reference_module(rev: str) -> Any:
    """Lade `scripts/dedup.py` aus der Git-Historie als eigenstaendiges Modul."""
    completed = subprocess.run(
        ["git", "show", f"{rev}:scripts/dedup.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    module = ModuleType(f"dedup_pre_890_{rev}")
    module.__dict__["__file__"] = f"<git:{rev}:scripts/dedup.py>"
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    exec(compile(completed.stdout, f"<git:{rev}:scripts/dedup.py>", "exec"), module.__dict__)
    return module


def load_current_module() -> Any:
    """Die aktuelle `scripts/dedup.py` — bewusst erst hier importiert, damit
    `sys.path` vorher steht (das Skript laeuft ausserhalb von pytest)."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import dedup

    return dedup


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    """Kanonisiere einen `deduplicate()`-Ausgabedatensatz fuer den Vergleich
    gegen die eingefrorene Vor-#890-Golden-Datei (`d141b09`).

    Dies ist die EINE Kanonisierungsfunktion fuer diesen Vergleich —
    `tests/test_dedup.py` importiert sie direkt (`from
    scripts.dev.verify_dedup_890_hitset import canonical`), statt eine eigene
    Kopie zu pflegen. Zwei Abweichungen zwischen der historischen und der
    aktuellen Fassung sind bekannt und müssen hier ausgeglichen werden, sonst
    ist der Vergleich falsch-rot, ohne dass sich am Dedup-*Verhalten* etwas
    geaendert haette:

    1. `source_modules`-Reihenfolge: `merge_group()` baut dieses Feld als
       `list({...})` aus einem Set von Strings (`scripts/dedup.py`). Die
       Iterationsreihenfolge eines String-Sets haengt am `PYTHONHASHSEED` und
       unterscheidet sich damit zwischen zwei Prozessen — nachgestellt:
       `PYTHONHASHSEED=7 python3 -c 'print(list({"dblp","arxiv"}))'` liefert
       `['dblp', 'arxiv']`, mit `PYTHONHASHSEED=12` `['arxiv', 'dblp']`. Das
       ist eine Prozess-Eigenschaft, die #890 nicht eingefuehrt hat: die
       Vor-#890-Fassung `d141b09` enthaelt dieselbe Zeile. Auf der realen
       Treffermenge betraf es 47 der 1390 Gruppen, ausschliesslich im Feld
       `source_modules` und in keiner einzigen Gruppenzugehoerigkeit — die
       Gruppierung selbst ist von Set-Reihenfolgen unabhaengig
       (`_get_cluster_ids()` nutzt Sets nur fuer Schnittmengen-Tests).

    2. `found_via_known_item`: Die Golden-Datei ist bei `d141b09` eingefroren
       — VOR #890 UND VOR #886. #886 (Known-Item-Suche, seither in main und
       ueber den Merge auch in diesem Branch) fuegt dieses Feld seither an
       JEDEM Ausgabedatensatz von `deduplicate()` an (auf dieser Fixture
       immer `false`, da sie keine Known-Item-Treffer enthaelt) —
       `scripts/dedup.py::merge_group()`. Das ist eine Schema-Erweiterung
       durch eine voellig unabhaengige, orthogonal gemergte Aenderung, keine
       Folge der #890-Blocking-Logik. Beleg: nach Ausschluss dieses einen
       Feldes sind `actual` und `expected` auf der realen 1957-Titel-Menge
       bytegleich (1390 von 1390 Gruppen) — die Gruppierung selbst ist also
       unveraendert.

    Ohne beide Ausschluesse waere der Vergleich strukturell IMMER rot: Feld 1
    zufallsabhaengig, Feld 2 deterministisch (jeder aktuelle Datensatz traegt
    es, kein Golden-Datensatz).
    """
    normalized = {k: v for k, v in record.items() if k != "found_via_known_item"}
    if "source_modules" in normalized:
        normalized["source_modules"] = sorted(normalized["source_modules"])
    return normalized


def canonical(payload: list[dict[str, Any]]) -> list[str]:
    """Reihenfolgeunabhaengige, vergleichbare Darstellung einer Ergebnisliste."""
    return sorted(
        json.dumps(normalize_record(record), sort_keys=True, default=str) for record in payload
    )


def cmd_extract(args: argparse.Namespace) -> int:
    source = Path(args.source).expanduser()
    with source.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    reduced = [{field: record.get(field) for field in FIXTURE_FIELDS} for record in raw]
    save_json_gz(reduced, HITSET_PATH)
    print(f"{len(reduced)} Treffer aus {source} -> {HITSET_PATH}")
    return 0


def cmd_golden(args: argparse.Namespace) -> int:
    papers = load_json_gz(HITSET_PATH)
    reference = load_reference_module(args.ref_rev)
    start = time.monotonic()
    result = reference.deduplicate(papers, args.threshold)
    elapsed = time.monotonic() - start
    # Kanonisiert eingefroren (siehe `normalize_record`), damit ein zweiter
    # Lauf dieselbe Datei erzeugt statt eines neuen Blobs mit gleicher Aussage.
    save_json_gz([normalize_record(record) for record in result], GOLDEN_PATH)
    print(
        f"Referenz {args.ref_rev}: {len(papers)} -> {len(result)} Papers "
        f"in {elapsed:.1f}s -> {GOLDEN_PATH}"
    )
    return 0


def load_papers(path_argument: str | None) -> list[dict[str, Any]]:
    """Eingabemenge laden: ohne `--papers` die eingecheckte Fixture, mit
    `--papers` eine beliebige (auch unreduzierte) Trefferdatei — damit sich
    die Aequivalenz auch gegen die vollstaendigen Rohdatensaetze des Laufs
    pruefen laesst, nicht nur gegen die feldreduzierte Fixture."""
    if path_argument is None:
        return load_json_gz(HITSET_PATH)
    path = Path(path_argument).expanduser()
    if path.suffix == ".gz":
        return load_json_gz(path)
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    assert isinstance(payload, list)
    return payload


def cmd_compare(args: argparse.Namespace) -> int:
    if args.papers is not None and not args.live:
        # Die Golden-Datei gehoert zur Fixture. Gegen eine andere Eingabe
        # verglichen wuerde sie garantiert abweichen — und zwar ohne dass das
        # etwas ueber die Aequivalenz aussagt.
        print("--papers braucht --live (die eingefrorene Golden-Datei gilt nur fuer die Fixture)")
        return 2
    papers = load_papers(args.papers)

    if args.live:
        reference = load_reference_module(args.ref_rev)
        start = time.monotonic()
        expected = reference.deduplicate(papers, args.threshold)
        ref_elapsed = time.monotonic() - start
        print(f"Vor-#890 ({args.ref_rev}, live): {len(expected)} Papers in {ref_elapsed:.1f}s")
        if args.papers is None and GOLDEN_PATH.exists():
            # Gleiche Eingabe wie die Golden-Datei: dann ist der Live-Lauf auch
            # der Beleg, dass die eingefrorene Datei nicht veraltet ist.
            if canonical(load_json_gz(GOLDEN_PATH)) != canonical(expected):
                print("ABWEICHUNG: eingefrorene Golden-Datei != frischer Lauf der alten Fassung")
                return 1
            print("Golden-Datei deckt sich mit dem frischen Lauf der alten Fassung.")
    else:
        expected = load_json_gz(GOLDEN_PATH)
        print(f"Vor-#890 ({args.ref_rev}, eingefroren): {len(expected)} Papers")

    current = load_current_module()
    start = time.monotonic()
    actual = current.deduplicate(papers, args.threshold)
    elapsed = time.monotonic() - start
    print(f"Aktuell (#890-Blocking):        {len(actual)} Papers in {elapsed:.1f}s")

    expected_canonical = canonical(expected)
    actual_canonical = canonical(actual)
    if expected_canonical == actual_canonical:
        print(f"IDENTISCH: {len(papers)} Treffer, {len(actual)} Gruppen, kein Unterschied.")
        return 0

    only_expected = set(expected_canonical) - set(actual_canonical)
    only_actual = set(actual_canonical) - set(expected_canonical)
    print(f"ABWEICHUNG: {len(only_expected)} nur alt, {len(only_actual)} nur neu")
    for record in sorted(only_expected)[:5]:
        print(f"  nur alt: {record[:300]}")
    for record in sorted(only_actual)[:5]:
        print(f"  nur neu: {record[:300]}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument("--ref-rev", default=PRE_890_REV)
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser("extract", help="Fixture aus der realen Rohdatei ziehen")
    extract.add_argument("--source", required=True)
    extract.set_defaults(func=cmd_extract)

    golden = sub.add_parser("golden", help="Ergebnis der Vor-#890-Fassung einfrieren")
    golden.set_defaults(func=cmd_golden)

    compare = sub.add_parser("compare", help="Aktuelle Fassung gegen die alte vergleichen")
    compare.add_argument("--live", action="store_true", help="Referenz frisch rechnen (Minuten)")
    compare.add_argument(
        "--papers",
        default=None,
        help="Andere Eingabemenge als die Fixture (nur mit --live sinnvoll)",
    )
    compare.set_defaults(func=cmd_compare)

    args = parser.parse_args()
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
