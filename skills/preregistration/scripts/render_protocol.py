#!/usr/bin/env python3
"""Deterministischer Rechenkern des preregistration-Skills (Issue #607).

Vier Bausteine:

``klassifiziere_vorhaben``
    Ordnet einem Vorhaben (Methodik-Typ aus dem Dialog) eine Vorlage zu und
    liefert eine Begruendung. Kein Freitext-Raten -- ein unbekannter Typ ist
    ein Fehler, keine Best-Guess-Zuordnung (AC1, AC4-Prinzip auch hier).

``rendere_protokoll``
    Rendert ``./preregistration.md`` aus einem Vorhaben-Dict. Reine Funktion
    des Inputs: kein Zeitstempel, keine Zufallsquelle -- zwei Laeufe mit
    demselben Input liefern byte-identischen Text (AC4). Pflichtfelder ohne
    Wert werden mit einem festen Platzhalter ausgewiesen, nie stillschweigend
    ausgelassen oder mit Plausiblem gefuellt (AC4). Jedes Protokoll traegt den
    Abschnitt "## Abweichungen vom Protokoll" (AC5) und einen Beleg-Block mit
    Vorlagenquelle + Fundstelle (AC6).

``lade_pflichtfelder`` / ``lade_osf_felder``
    Lesen die Feldnamen aus ``references/prospero-fields.md`` bzw.
    ``references/osf-templates.md`` -- die Feldliste lebt in genau einer
    Quelle, das Skript haelt sie nicht doppelt vor.

``aktualisiere_academic_context``
    Schreibt Suchstrategie und Ein-/Ausschlusskriterien strukturiert in einen
    bereits gelesenen ``academic_context.md``-Text, ohne den Rest der Datei
    anzutasten (AC3) -- Ablage dort, weil ``parallel-screening`` und der
    ``query-generator``-Agent diese Datei bereits kennen.

Bewusst NICHT in diesem Skript: ob ein Vorhaben ueberhaupt
praeregistrierungspflichtig ist, und das Einreichen bei OSF/PROSPERO selbst
(beides Out-of-Scope laut Issue #607).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PLATZHALTER = "[OFFEN]"

SKILL_DIR = Path(__file__).resolve().parent.parent
PROSPERO_FIELDS_MD = SKILL_DIR / "references" / "prospero-fields.md"
OSF_TEMPLATES_MD = SKILL_DIR / "references" / "osf-templates.md"

# Ueberschriften, wie sie woertlich in osf-templates.md stehen -- Bindeglied
# zwischen Template-Kuerzel und dem geparsten Abschnitt.
OSF_UEBERSCHRIFTEN = {
    "general": 'general — „OSF Preregistration"',
    "secondary-data": 'secondary-data — „Secondary Data Preregistration"',
    "qualitative": 'qualitative — „Qualitative Preregistration"',
}

TEMPLATE_QUELLEN: dict[str, dict[str, str]] = {
    "prospero": {
        "name": "PROSPERO-Registrierungsformular",
        "url": "https://www.crd.york.ac.uk/prospero/",
        "fundstelle": "Booth et al. 2012, Systematic Reviews 1:2, PMC3348673, abgerufen 2026-08-04",
    },
    "general": {
        "name": "OSF Preregistration",
        "url": "https://osf.io/",
        "fundstelle": "OSF Registration Schema 697b72f611a8e98484c6139b, "
        "Version 4, abgerufen 2026-08-04",
    },
    "secondary-data": {
        "name": "OSF Secondary Data Preregistration",
        "url": "https://osf.io/",
        "fundstelle": "OSF Registration Schema 64775783798e08000a70407e, "
        "Version 3, abgerufen 2026-08-04",
    },
    "qualitative": {
        "name": "OSF Qualitative Preregistration",
        "url": "https://osf.io/",
        "fundstelle": "OSF Registration Schema 5fa0ac510a7f38001c8ae854, "
        "Version 1, abgerufen 2026-08-04",
    },
}

# ---------------------------------------------------------------------------
# Vorhaben-Klassifikation (AC1)
# ---------------------------------------------------------------------------

_TYP_ALIASE: dict[str, tuple[str, str]] = {
    "systematic-review": (
        "prospero",
        "Systematischer Review: PROSPERO ist faktische Voraussetzung fuer die "
        "Publikation in einschlaegigen Zeitschriften und verlangt ein eigenes, "
        "erzwungenes Pflichtfeld-Set -- das allgemeine OSF-Template deckt das "
        "nicht ab.",
    ),
    "qualitativ": (
        "qualitative",
        "Qualitatives Design: ein starrer quantitativer Analyseplan (Hypothesen, "
        "Teststatistik, Stichprobenumfang-Rationale) passt nicht auf offene "
        "Fallauswahl und interpretative Auswertung -- das OSF-Qualitative-Template "
        "fragt stattdessen Design, Fallauswahlstrategie und "
        "Glaubwuerdigkeitsstrategien ab.",
    ),
    "sekundaerdaten": (
        "secondary-data",
        "Analyse an bereits vorhandenen Daten: das Sekundaerdaten-Template fragt "
        "zusaetzlich Zugriffsweg, Herkunft und Vorwissen ueber den Datensatz ab -- "
        "Angaben, die das allgemeine Template nicht kennt.",
    ),
    "quantitativ": (
        "general",
        "Quantitatives Hypothesentest-Design ohne speziellere Passform: das "
        "allgemeine OSF-Preregistration-Template deckt Hypothesen, Design, "
        "Stichprobe und Analyseplan ab.",
    ),
}
_TYP_ALIASE["mixed-methods"] = _TYP_ALIASE["qualitativ"]
_TYP_ALIASE["secondary-data"] = _TYP_ALIASE["sekundaerdaten"]
_TYP_ALIASE["qualitative"] = _TYP_ALIASE["qualitativ"]
_TYP_ALIASE["quantitative"] = _TYP_ALIASE["quantitativ"]


def klassifiziere_vorhaben(methodik_typ: str) -> tuple[str, str]:
    """Ordnet dem Vorhaben eine Vorlage zu und begruendet die Wahl.

    ``methodik_typ`` kommt aus dem Dialog mit dem User (bzw. aus
    ``./academic_context.md`` / ``methodology-advisor``) -- keine Heuristik auf
    Freitext. Ein unbekannter Typ ist ein Fehler, keine Best-Guess-Zuordnung.
    """
    schluessel = methodik_typ.strip().lower()
    if schluessel not in _TYP_ALIASE:
        bekannte = ", ".join(
            sorted({"systematic-review", "qualitativ", "sekundaerdaten", "quantitativ"})
        )
        raise ValueError(f"Unbekannter methodik_typ '{methodik_typ}'. Erwartet: {bekannte}.")
    return _TYP_ALIASE[schluessel]


# ---------------------------------------------------------------------------
# Referenz-Parsing
# ---------------------------------------------------------------------------


def lade_pflichtfelder(pfad: Path = PROSPERO_FIELDS_MD) -> list[str]:
    """Liest die PROSPERO-Pflichtfelder aus der Referenzdatei -- keine zweite,
    hartkodierte Liste im Code."""
    text = pfad.read_text(encoding="utf-8")
    treffer = re.search(r"^## Pflichtfelder\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not treffer:
        raise ValueError(f"{pfad}: keine '## Pflichtfelder'-Section gefunden.")
    return [zeile[2:].strip() for zeile in treffer.group(1).splitlines() if zeile.startswith("- ")]


def lade_osf_felder(template: str, pfad: Path = OSF_TEMPLATES_MD) -> dict[str, list[str]]:
    """Feldnamen je Sektion einer OSF-Vorlage, gruppiert nach '### '-Ueberschrift."""
    if template not in OSF_UEBERSCHRIFTEN:
        raise ValueError(
            f"Unbekanntes OSF-Template '{template}'. Erwartet: {', '.join(OSF_UEBERSCHRIFTEN)}."
        )
    text = pfad.read_text(encoding="utf-8")
    ueberschrift = re.escape(OSF_UEBERSCHRIFTEN[template])
    treffer = re.search(rf"^## {ueberschrift}\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not treffer:
        raise ValueError(f"{pfad}: Template '{template}' nicht gefunden.")
    sektionen: dict[str, list[str]] = {}
    aktuelle: str | None = None
    for zeile in treffer.group(1).splitlines():
        if zeile.startswith("### "):
            aktuelle = zeile[4:].strip()
            sektionen[aktuelle] = []
        elif zeile.startswith("- ") and aktuelle is not None:
            sektionen[aktuelle].append(zeile[2:].strip())
    return sektionen


def _alle_bekannten_felder(template: str) -> set[str]:
    """Sammelt alle bekannten Feldnamen fuer ein Template (Pflicht + Optional)."""
    if template == "prospero":
        result = set(lade_pflichtfelder())
        # Auch optionale Felder parsen
        ref_text = PROSPERO_FIELDS_MD.read_text(encoding="utf-8")
        optional_treffer = re.search(
            r"^## Optionale Felder.*?\n(.*?)(?=^## |\Z)", ref_text, re.M | re.S
        )
        if optional_treffer:
            for zeile in optional_treffer.group(1).splitlines():
                if zeile.startswith("- "):
                    result.add(zeile[2:].strip())
        return result
    else:
        result: set[str] = set()
        for namen in lade_osf_felder(template).values():
            result.update(namen)
        return result


# ---------------------------------------------------------------------------
# Protokoll rendern (AC2, AC4, AC5, AC6)
# ---------------------------------------------------------------------------


def _feld_block(name: str, wert: str | None) -> list[str]:
    if wert is not None and not isinstance(wert, str):
        raise TypeError(
            f"Feldwert für '{name}' muss ein String oder None sein, nicht {type(wert).__name__}"
        )
    return [f"### {name}", "", (wert.strip() if wert and wert.strip() else PLATZHALTER), ""]


def rendere_protokoll(plan: dict[str, Any]) -> str:
    """Baut das Praeregistrierungsprotokoll als Markdown-Text.

    Reine Funktion von ``plan`` -- kein Zeitstempel, keine Zufallsquelle, damit
    derselbe Input immer denselben Text liefert (AC4: byte-identischer Re-Run).
    """
    template = plan.get("template")
    if template not in TEMPLATE_QUELLEN:
        raise ValueError(
            f"Unbekanntes Template '{template}'. Erwartet: {', '.join(TEMPLATE_QUELLEN)}."
        )
    quelle = TEMPLATE_QUELLEN[template]
    felder: dict[str, str] = plan.get("felder") or {}

    zeilen: list[str] = ["# Präregistrierungsprotokoll", "", f"Vorlage: {quelle['name']}", ""]
    if plan.get("titel"):
        zeilen += [f"Arbeitstitel: {plan['titel']}", ""]
    if plan.get("begruendung"):
        zeilen += [f"Begründung der Vorlagenwahl: {plan['begruendung']}", ""]

    # Rendere Felder je nach Template, erhalte aber die Reihenfolge aus der Referenz
    if template == "prospero":
        zeilen += ["## Pflichtfelder (PROSPERO)", ""]
        # Reihenfolge aus der Referenzdatei erhalten (nicht aus Set iterieren!)
        pflichtfelder_liste = lade_pflichtfelder()
        for name in pflichtfelder_liste:
            zeilen += _feld_block(name, felder.get(name))
    else:
        for sektion, namen in lade_osf_felder(template).items():
            zeilen += [f"## {sektion}", ""]
            for name in namen:
                zeilen += _feld_block(name, felder.get(name))

    # Validiere, dass keine unbekannten Feldschlüssel vorhanden sind
    bekannte = _alle_bekannten_felder(template)
    unbekannte = set(felder.keys()) - bekannte
    if unbekannte:
        raise ValueError(
            f"Plan enthält unbekannte Feldschlüssel, die im Template '{template}' nicht "
            f"existieren: {', '.join(sorted(unbekannte))}. Diese würden ohne Fehler "
            f"verworfen; bitte überprüfen Sie die Feldnamen gegen die Referenzdatei."
        )

    zeilen += [
        "## Abweichungen vom Protokoll",
        "",
        "Weicht die spätere Durchführung von diesem Protokoll ab (geänderte "
        "Kriterien, zusätzliche Analysen, andere Stichprobe als geplant), gehört "
        "die Begründung mit Datum und Bezug auf das betroffene Feld hierhin. "
        "Dieser Abschnitt bleibt bis zur ersten Abweichung mit dem Platzhalter "
        "stehen -- er wird nicht gelöscht.",
        "",
        PLATZHALTER,
        "",
        "## Quelle",
        "",
        f"- Vorlage: {quelle['name']}",
        f"- URL: {quelle['url']}",
        f"- Fundstelle: {quelle['fundstelle']}",
        "",
    ]
    return "\n".join(zeilen)


# ---------------------------------------------------------------------------
# academic_context.md — Suchstrategie / Ein-/Ausschlusskriterien (AC3)
# ---------------------------------------------------------------------------


def _liste_oder_platzhalter(eintraege: list[str] | None) -> list[str]:
    if not eintraege:
        return [PLATZHALTER]
    if not isinstance(eintraege, list):
        raise TypeError(
            f"Kriterien/Liste muss vom Typ list sein, nicht {type(eintraege).__name__}. "
            f"Wert: {repr(eintraege)}"
        )
    # Zusätzliche Validierung: jeder Eintrag muss ein String sein
    for idx, eintrag in enumerate(eintraege):
        if not isinstance(eintrag, str):
            raise TypeError(
                f"Listeneintrag [{idx}] muss ein String sein, nicht {type(eintrag).__name__}: "
                f"{repr(eintrag)}"
            )
    return [f"- {e}" for e in eintraege]


def _section_block(ueberschrift: str, zeilen: list[str]) -> str:
    return "\n".join([f"### {ueberschrift}", "", *zeilen, ""])


_HEADING_SPLIT = re.compile(r"(?m)^(?=#{2,3} )")


def _upsert_section(text: str, ueberschrift: str, block: str) -> str:
    """Ersetzt eine '### <ueberschrift>'-Section, falls vorhanden, sonst haengt
    sie ans Dateiende an. Alle anderen Sections bleiben inhaltlich unveraendert.

    Arbeitet auf ganzen "Chunks" (eine Ueberschrift + ihr Inhalt bis zur
    naechsten Ueberschrift), nicht auf einem einzelnen Regex-Ersetzungslauf --
    das haelt die Funktion einen Fixpunkt: ein zweiter Aufruf mit denselben
    Werten liefert exakt denselben Text (sonst waechst bei jedem Lauf die
    Anzahl Leerzeilen am Section-Ende um eine, weil Trenner und Inhalt nicht
    sauber getrennt sind).
    """
    zielzeile = f"### {ueberschrift}"
    chunks = _HEADING_SPLIT.split(text)
    neuer_chunk = block.rstrip("\n") + "\n"
    ersetzt = False
    ergebnis: list[str] = []
    for chunk in chunks:
        erste_zeile = chunk.splitlines()[0].strip() if chunk else ""
        if erste_zeile == zielzeile:
            ergebnis.append(neuer_chunk)
            ersetzt = True
        elif chunk:
            ergebnis.append(chunk.rstrip("\n") + "\n")
    if not ersetzt:
        ergebnis.append(neuer_chunk)
    return "\n".join(ergebnis)


def aktualisiere_academic_context(
    text: str,
    *,
    suchstrategie: str | None,
    einschlusskriterien: list[str] | None,
    ausschlusskriterien: list[str] | None,
) -> str:
    """Schreibt Suchstrategie + Ein-/Ausschlusskriterien in einen bereits
    gelesenen ``academic_context.md``-Text (AC3). Das Lesen-vor-Schreiben ist
    Sache des Aufrufers (Regel aus academic-context/SKILL.md); diese Funktion
    ist eine reine Texttransformation und damit ohne Vault-/Dateizugriff
    testbar.
    """
    strategie_zeile = (
        suchstrategie.strip() if suchstrategie and suchstrategie.strip() else PLATZHALTER
    )
    text = _upsert_section(
        text, "Suchstrategie", _section_block("Suchstrategie", [strategie_zeile])
    )
    kriterien_zeilen = [
        "**Einschluss**",
        *_liste_oder_platzhalter(einschlusskriterien),
        "",
        "**Ausschluss**",
        *_liste_oder_platzhalter(ausschlusskriterien),
    ]
    text = _upsert_section(
        text,
        "Ein-/Ausschlusskriterien",
        _section_block("Ein-/Ausschlusskriterien", kriterien_zeilen),
    )
    return text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_classify(args: argparse.Namespace) -> int:
    template, begruendung = klassifiziere_vorhaben(args.methodik_typ)
    print(
        json.dumps({"template": template, "begruendung": begruendung}, ensure_ascii=False, indent=2)
    )
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    protokoll = rendere_protokoll(plan)
    Path(args.out).write_text(protokoll, encoding="utf-8")
    print(f"Protokoll geschrieben: {args.out}")
    return 0


def _cmd_update_context(args: argparse.Namespace) -> int:
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    context_pfad = Path(args.context)
    if not context_pfad.exists():
        print(
            f"{context_pfad} existiert nicht. Erst academic-context-Skill laufen "
            f"lassen, dann diesen Schritt wiederholen.",
            file=sys.stderr,
        )
        return 1
    text = context_pfad.read_text(encoding="utf-8")
    aktualisiert = aktualisiere_academic_context(
        text,
        suchstrategie=plan.get("suchstrategie"),
        einschlusskriterien=plan.get("einschlusskriterien"),
        ausschlusskriterien=plan.get("ausschlusskriterien"),
    )
    context_pfad.write_text(aktualisiert, encoding="utf-8")
    print(f"Aktualisiert: {context_pfad}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="render_protocol.py",
        description="Deterministischer Rechenkern des preregistration-Skills.",
    )
    unter = parser.add_subparsers(dest="kommando", required=True)

    p_classify = unter.add_parser("classify", help="Vorlage anhand des Methodik-Typs bestimmen")
    p_classify.add_argument("--methodik-typ", required=True, dest="methodik_typ")
    p_classify.set_defaults(func=_cmd_classify)

    p_render = unter.add_parser("render", help="Präregistrierungsprotokoll rendern")
    p_render.add_argument("--plan", required=True)
    p_render.add_argument("--out", required=True)
    p_render.set_defaults(func=_cmd_render)

    p_context = unter.add_parser(
        "update-context", help="Suchstrategie/Kriterien in academic_context.md schreiben"
    )
    p_context.add_argument("--plan", required=True)
    p_context.add_argument("--context", default="./academic_context.md")
    p_context.set_defaults(func=_cmd_update_context)

    args = parser.parse_args(list(argv) if argv is not None else None)
    result: int = args.func(args)
    return result


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
