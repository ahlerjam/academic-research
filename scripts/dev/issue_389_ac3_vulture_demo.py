"""Temporaere Demo-Datei fuer Issue #389 AC3 Live-Verifikation.

Zweck: Dieser Test-PR (siehe docs/audit/2026-07-27-issue-389-ac3-vulture-live-verification.md)
prueft, dass der `dead-code`-Job in `pr-deep-review.yml` einen echten vulture-Fund
(nicht nur ruff F401) im Sticky-Comment meldet, sobald eine geaenderte Datei in
`deadCodePaths` (scripts/, academic_vault/) totem Code enthaelt.

Wichtig (empirisch verifiziert, vgl. Issue #389 "Out"-Scope: keine
--min-confidence-Aenderung): eine schlicht ungenutzte Top-Level-Funktion/-Klasse
hat bei vulture NUR 60% Default-Confidence und faellt damit unter die im
Workflow gesetzte Schwelle von --min-confidence 80 heraus. Nur zwei Kategorien
erreichen dort >=80%: unused imports (90%, aber deckungsgleich mit ruff F401)
sowie unreachable code / unused function-arguments (100%). Diese Datei nutzt
daher bewusst "unreachable code nach return" + ein ungenutztes Funktionsargument
als Demo-Faelle, NICHT eine schlicht ungenutzte Funktion.

Diese Datei wird NICHT gemergt — der Test-PR wird nach Erfassung des
Sticky-Comment-Nachweises geschlossen, ohne zu mergen.
"""


def demo_unreachable_after_return(value: int) -> int:
    """100% Confidence bei vulture: Code nach 'return' ist nie erreichbar."""
    return value * 2
    print("unreachable — never executes, vulture flags this at 100% confidence")


def demo_unused_argument(used: int, unused_marker_arg: int) -> int:
    """100% Confidence bei vulture: 'unused_marker_arg' wird im Body nie referenziert."""
    return used * 3


print(demo_unreachable_after_return(1))
print(demo_unused_argument(1, 2))
