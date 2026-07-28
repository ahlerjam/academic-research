"""Rendert den Quickstart-Cast zu einem statischen Terminal-SVG (Issue #451).

Warum ein eigener Renderer: die README zeigt eine Demonstration des realen
Durchlaufs aus ``docs/quickstart-protocol.md``. Damit dieses Bild nicht von Hand
gemalt und damit unpruefbar wird, ist ``docs/assets/quickstart.cast`` die
einzige Quelle — dieses Skript erzeugt daraus deterministisch
``docs/assets/quickstart.svg``. Ein Test rendert neu und vergleicht byteweise;
driftet das Bild vom Mitschnitt ab, wird die Suite rot.

Bewusst statisch statt animiert: GitHub reicht eingebettete SVG durch einen
Sanitizer, dessen Umgang mit SMIL-Animationen nicht zugesichert ist. Ein
Standbild rendert ueberall; der Cast bleibt als abspielbare Quelle im Repo
(``asciinema play docs/assets/quickstart.cast``).

Aufruf:

    uv run python scripts/dev/render_quickstart_svg.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CAST_PATH = REPO_ROOT / "docs" / "assets" / "quickstart.cast"
SVG_PATH = REPO_ROOT / "docs" / "assets" / "quickstart.svg"

ANSI_RE = re.compile(r"\x1b\[([0-9;]*)m")

#: Terminalpalette (GitHub-Dark-nah, in Light- und Dark-Mode gleich lesbar).
BACKGROUND = "#0d1117"
BORDER = "#30363d"
TITLEBAR = "#161b22"
DEFAULT_FG = "#c9d1d9"

SGR_COLORS = {
    "31": "#ff7b72",  # rot   — Guard blockt
    "32": "#3fb950",  # gruen — Erfolg
    "33": "#d29922",  # gelb  — Degradation/Warnung
    "36": "#39c5cf",  # cyan  — Hinweis
    "90": "#8b949e",  # grau  — Ausgabedetail
    "97": "#f0f6fc",  # weiss — getippter Befehl
}

FONT_SIZE = 14
LINE_HEIGHT = 20
CHAR_WIDTH = 8.4
PAD_X = 18
TITLEBAR_HEIGHT = 32
PAD_TOP = 14
PAD_BOTTOM = 16

FONT_FAMILY = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'DejaVu Sans Mono', monospace"


class CastError(ValueError):
    """Der Cast ist kein gueltiger asciicast v2."""


def parse_cast(cast_text: str) -> tuple[dict, str]:
    """Zerlegt einen asciicast v2 in Header und zusammenhaengenden Ausgabetext."""
    lines = [ln for ln in cast_text.splitlines() if ln.strip()]
    if not lines:
        raise CastError("Cast ist leer.")
    header = json.loads(lines[0])
    if header.get("version") != 2:
        raise CastError(f"asciicast-Version {header.get('version')!r}, erwartet 2.")
    chunks = []
    for raw in lines[1:]:
        event = json.loads(raw)
        if len(event) != 3:
            raise CastError(f"Ereignis mit {len(event)} Feldern statt 3: {raw!r}")
        if event[1] == "o":
            chunks.append(event[2])
    return header, "".join(chunks)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _runs(line: str, start_color: str) -> tuple[list[tuple[str, str]], str]:
    """Zerlegt eine Zeile in (Text, Farbe)-Laeufe und liefert die Endfarbe zurueck."""
    runs: list[tuple[str, str]] = []
    color = start_color
    pos = 0
    for match in ANSI_RE.finditer(line):
        if match.start() > pos:
            runs.append((line[pos : match.start()], color))
        for code in (match.group(1) or "0").split(";"):
            if code in ("", "0"):
                color = DEFAULT_FG
            elif code in SGR_COLORS:
                color = SGR_COLORS[code]
        pos = match.end()
    if pos < len(line):
        runs.append((line[pos:], color))
    return runs, color


def render_svg(cast_text: str) -> str:
    """Erzeugt das statische Terminal-SVG zu einem Cast (deterministisch)."""
    header, output = parse_cast(cast_text)
    lines = output.replace("\r\n", "\n").replace("\r", "").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        raise CastError("Cast enthaelt keine Ausgabe.")

    cols = int(header.get("width", 80))
    width = round(cols * CHAR_WIDTH + 2 * PAD_X)
    height = TITLEBAR_HEIGHT + PAD_TOP + len(lines) * LINE_HEIGHT + PAD_BOTTOM
    title = str(header.get("title", "Terminal"))

    out: list[str] = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{_escape(title)}">'
    )
    out.append(f"  <title>{_escape(title)}</title>")
    out.append(
        f'  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="10" '
        f'fill="{BACKGROUND}" stroke="{BORDER}"/>'
    )
    out.append(
        f'  <path d="M0.5 10.5a10 10 0 0 1 10-10h{width - 21}a10 10 0 0 1 10 10'
        f'v{TITLEBAR_HEIGHT - 10}h-{width - 1}z" fill="{TITLEBAR}" stroke="{BORDER}"/>'
    )
    for index, dot in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        out.append(f'  <circle cx="{20 + index * 18}" cy="16" r="6" fill="{dot}"/>')
    out.append(
        f'  <text x="{width / 2:.0f}" y="21" fill="#8b949e" font-size="12" '
        f'font-family="{FONT_FAMILY}" text-anchor="middle">{_escape(title)}</text>'
    )
    out.append(f'  <g font-family="{FONT_FAMILY}" font-size="{FONT_SIZE}" xml:space="preserve">')

    color = DEFAULT_FG
    for row, line in enumerate(lines):
        baseline = TITLEBAR_HEIGHT + PAD_TOP + row * LINE_HEIGHT + FONT_SIZE
        runs, color = _runs(line, color)
        if not any(text for text, _ in runs):
            continue
        spans = "".join(
            f'<tspan fill="{run_color}">{_escape(text)}</tspan>' for text, run_color in runs if text
        )
        out.append(f'    <text x="{PAD_X}" y="{baseline}">{spans}</text>')

    out.append("  </g>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cast", type=Path, default=CAST_PATH, help="Quelle (asciicast v2)")
    parser.add_argument("--out", type=Path, default=SVG_PATH, help="Zieldatei (SVG)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="nur pruefen, ob die Zieldatei dem gerenderten Cast entspricht",
    )
    args = parser.parse_args(argv)

    svg = render_svg(args.cast.read_text(encoding="utf-8"))
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        if current != svg:
            print(f"{args.out} weicht vom gerenderten Cast ab.", file=sys.stderr)
            return 1
        print(f"{args.out} ist aktuell.")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(svg, encoding="utf-8")
    print(f"{args.out} geschrieben ({len(svg.splitlines())} Zeilen).")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI-Einstieg
    raise SystemExit(main())
