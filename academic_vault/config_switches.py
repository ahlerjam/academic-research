"""Generischer Vorrang-Resolver fuer Boolean-Schalter (Issue #719).

Vor #719 hatte jede der drei lokalen Modell-Komponenten (Embedding, lokaler
Reranker, NLI-Zitatscan) ihre eigene Auswertung von Argument/Env/Config/Default
-- ``nli_prefilter.py::resolve_nli_prefilter_enabled`` war das einzige Modul
mit einem sauberen, getesteten Vorrang. Dieses Modul verallgemeinert genau
dieses Muster, damit alle drei denselben, an einer Stelle getesteten Code
durchlaufen:

    Argument > Umgebungsvariable(n) > ``config/parallel_agents.json`` > Default

``resolve_bool_switch`` nimmt bewusst eine LISTE von Env-Variablen entgegen
(statt nur einer): so laesst sich ein bestehender Schalter (z. B.
``VAULT_AUTO_EMBED``) als Alias fortfuehren, ohne dass Aufrufer zwei getrennte
Resolver-Aufrufe verdrahten muessen. Innerhalb der Liste gewinnt der zuerst
uebergebene Name; ein nicht erkannter Wert (weder truthy noch falsy) wird
uebersprungen, nicht als Fehler behandelt -- die naechste Env-Variable bzw.
danach die Config-Datei entscheidet dann.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "parallel_agents.json"

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def resolve_bool_switch(
    explicit: bool | None,
    env_vars: str | Sequence[str],
    config_key: str,
    default: bool,
    config_path: str | Path | None = None,
) -> bool:
    """Loest einen Boolean-Schalter nach dem Vorrang Argument > Env > Config > Default.

    Args:
        explicit: Explizit uebergebener Wert (z. B. Funktionsargument). ``None``
            bedeutet "nicht gesetzt" -- ``False`` ist ein gueltiger expliziter
            Wert und gewinnt gegenueber allem anderen.
        env_vars: Eine Env-Variable oder eine PRIORITAETSGEORDNETE Liste
            mehrerer Namen (kanonischer Name zuerst, Alt-Namen/Aliase danach).
            Jede wird gegen :data:`_TRUTHY`/:data:`_FALSY` geprueft
            (case-insensitiv, getrimmt); ein nicht erkannter Wert wird
            uebersprungen statt den Vorrang zu beenden.
        config_key: Schluessel in der Config-Datei (Top-Level, Wert muss ein
            JSON-Bool sein -- alles andere (fehlender Schluessel, falscher Typ,
            kaputtes JSON, fehlende Datei) faellt auf ``default`` zurueck.
        default: Ergebnis, wenn weder Argument noch Env noch Config greifen.
        config_path: Pfad zur Config-Datei. Default:
            ``config/parallel_agents.json`` im Repo-Root.

    Returns:
        Der aufgeloeste Boolean-Wert.
    """
    if explicit is not None:
        return bool(explicit)

    names = (env_vars,) if isinstance(env_vars, str) else tuple(env_vars)
    for name in names:
        raw = os.environ.get(name)
        if raw is None:
            continue
        stripped = raw.strip().lower()
        if stripped in _TRUTHY:
            return True
        if stripped in _FALSY:
            return False
        # Nicht erkannter Wert: diese Variable wird ignoriert, die naechste
        # (bzw. danach Config/Default) entscheidet -- kein stiller Fehler.

    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data[config_key]
    except (OSError, ValueError, KeyError, TypeError):
        value = None
    if isinstance(value, bool):
        return value

    return default
