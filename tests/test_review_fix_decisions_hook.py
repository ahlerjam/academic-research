"""Regressionstest fuer Finding 12 (Code-Review, Branch fix/code-review-max-findings).

Bug: hooks/post-tool-use-decisions.mjs::extractContent hashte bei Edit/MultiEdit
NUR das new_string-Fragment, nicht die resultierende Datei — bei Write dagegen
den kompletten Inhalt. Das verletzt den Idempotenz-Vertrag, den
academic_vault/decision_log.py::content_hash woertlich dokumentiert:
"dieselbe Datei mit demselben Inhalt einmal per Write und einmal per Edit
geschrieben ist eine Aenderung, keine zwei" — und umgekehrt: zwei GENUIN
verschiedene Datei-Zustaende, die zufaellig dasselbe new_string-Fragment
einfuegen (z.B. dieselbe Ueberschrift an zwei verschiedenen Stellen), hashten
identisch und wurden so faelschlich als "keine Aenderung" behandelt.

Der Hook liest bei PostToolUse den bereits geschriebenen Datei-Inhalt von der
Platte (das Tool hat zu diesem Zeitpunkt bereits geschrieben) und hasht DIESEN
— fuer Write, Edit und MultiEdit gleichermassen.
"""

import hashlib
import json
import os
import subprocess
from pathlib import Path

HOOK_PATH = Path(__file__).parent.parent / "hooks" / "post-tool-use-decisions.mjs"


def run_hook(payload: dict, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    """Startet den Hook als Subprocess mit JSON-Eingabe auf stdin."""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    return subprocess.run(
        ["node", str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def _log_lines(log_file: Path) -> list[str]:
    if not log_file.exists():
        return []
    return [line for line in log_file.read_text().strip().splitlines() if line.strip()]


def _hash_of(line: str) -> str:
    marker = "sha256="
    idx = line.rfind(marker)
    assert idx >= 0, f"kein sha256= in Log-Zeile: {line}"
    return line[idx + len(marker) :].strip()


# ---------------------------------------------------------------------------
# Kernbefund: gleicher new_string-Fragment-Text, aber unterschiedlicher
# resultierender Datei-Inhalt -> muessen unterschiedliche Hashes ergeben.
# ---------------------------------------------------------------------------


def test_edit_hash_reflects_resulting_file_not_fragment(tmp_path):
    """Zwei Edits mit IDENTISCHEM new_string, aber unterschiedlichem
    resultierenden Datei-Inhalt, muessen unterschiedliche sha256-Hashes im
    Log erzeugen (Finding 12: vorher hashte der Hook nur das Fragment, beide
    waeren identisch gewesen).
    """
    log_file = tmp_path / "decisions.log"
    md_file = tmp_path / "kapitel" / "03.md"
    md_file.parent.mkdir(parents=True)

    env_overrides = {
        "ACADEMIC_DECISIONS_LOG": str(log_file),
        "CLAUDE_PROJECT_DIR": str(tmp_path),
    }

    # Erste "Aenderung": Datei enthaelt die eingefuegte Ueberschrift an
    # Position 1. PostToolUse feuert NACHDEM das Edit-Tool bereits
    # geschrieben hat -> die Datei liegt schon im Ziel-Zustand vor.
    content_v1 = "# Kapitel 3\n\n## Fazit\n\nAlter Text.\n"
    md_file.write_text(content_v1, encoding="utf-8")
    payload_1 = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(md_file),
            "old_string": "irrelevant",
            "new_string": "## Fazit",
        },
    }
    result_1 = run_hook(payload_1, env_overrides=env_overrides)
    assert result_1.returncode == 0, result_1.stderr

    # Zweite, GENUIN andere Aenderung: dieselbe Ueberschrift "## Fazit" wird
    # an einer anderen Stelle mit anderem umgebenden Text eingefuegt -
    # new_string ist identisch zum ersten Edit, der resultierende Datei-
    # Inhalt aber komplett verschieden.
    content_v2 = "# Kapitel 3\n\nEinleitung neu.\n\n## Fazit\n\nKomplett anderer Text.\n"
    md_file.write_text(content_v2, encoding="utf-8")
    payload_2 = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(md_file),
            "old_string": "irrelevant2",
            "new_string": "## Fazit",  # identisches Fragment wie oben
        },
    }
    result_2 = run_hook(payload_2, env_overrides=env_overrides)
    assert result_2.returncode == 0, result_2.stderr

    lines = _log_lines(log_file)
    assert len(lines) == 2, f"Erwartet 2 Log-Zeilen, got {len(lines)}: {lines}"

    hash_1 = _hash_of(lines[0])
    hash_2 = _hash_of(lines[1])

    assert hash_1 != hash_2, (
        "Hashes sind identisch, obwohl der Datei-Inhalt unterschiedlich war "
        "(Finding 12: Hook hasht faelschlich nur das new_string-Fragment)."
    )

    # Und die Hashes muessen exakt dem SHA-256 des tatsaechlichen
    # Datei-Inhalts entsprechen (nicht irgendein Hash).
    assert hash_1 == hashlib.sha256(content_v1.encode("utf-8")).hexdigest()
    assert hash_2 == hashlib.sha256(content_v2.encode("utf-8")).hexdigest()


def test_multiedit_hash_reflects_resulting_file(tmp_path):
    """MultiEdit: Hash muss der resultierenden Datei entsprechen, nicht der
    Verkettung der new_string-Fragmente.
    """
    log_file = tmp_path / "decisions.log"
    md_file = tmp_path / "kap2.md"

    env_overrides = {
        "ACADEMIC_DECISIONS_LOG": str(log_file),
        "CLAUDE_PROJECT_DIR": str(tmp_path),
    }

    final_content = "# Kapitel 2\nErster Block\nZweiter Block\n"
    md_file.write_text(final_content, encoding="utf-8")

    payload = {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": str(md_file),
            "edits": [
                {"old_string": "a", "new_string": "Erster Block"},
                {"old_string": "b", "new_string": "Zweiter Block"},
            ],
        },
    }
    result = run_hook(payload, env_overrides=env_overrides)
    assert result.returncode == 0, result.stderr

    lines = _log_lines(log_file)
    assert len(lines) == 1
    hash_val = _hash_of(lines[0])

    fragment_hash = hashlib.sha256(
        "\n".join(["Erster Block", "Zweiter Block"]).encode("utf-8")
    ).hexdigest()
    file_hash = hashlib.sha256(final_content.encode("utf-8")).hexdigest()

    assert hash_val != fragment_hash, "Hook hasht noch das Fragment statt der Datei"
    assert hash_val == file_hash


def test_write_and_edit_same_final_content_hash_identically(tmp_path):
    """Kontrollprobe fuer denselben Vertrag in die andere Richtung: Write und
    Edit, die BEIDE denselben resultierenden Datei-Inhalt erzeugen, muessen
    denselben Hash liefern (echte Idempotenz, kein falsches Positiv).
    """
    log_file = tmp_path / "decisions.log"
    md_file = tmp_path / "gleich.md"

    env_overrides = {
        "ACADEMIC_DECISIONS_LOG": str(log_file),
        "CLAUDE_PROJECT_DIR": str(tmp_path),
    }

    shared_content = "# Titel\nInhalt identisch.\n"

    # Write: Datei entsteht mit shared_content.
    md_file.write_text(shared_content, encoding="utf-8")
    result_write = run_hook(
        {
            "tool_name": "Write",
            "tool_input": {"file_path": str(md_file), "content": shared_content},
        },
        env_overrides=env_overrides,
    )
    assert result_write.returncode == 0, result_write.stderr

    # Edit: Datei liegt (simuliert) weiterhin mit demselben Endzustand vor,
    # nur das new_string-Fragment im Payload weicht vom kompletten Inhalt ab.
    result_edit = run_hook(
        {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(md_file),
                "old_string": "Platzhalter",
                "new_string": "Inhalt identisch.",
            },
        },
        env_overrides=env_overrides,
    )
    assert result_edit.returncode == 0, result_edit.stderr

    lines = _log_lines(log_file)
    assert len(lines) == 2
    assert (
        _hash_of(lines[0])
        == _hash_of(lines[1])
        == hashlib.sha256(shared_content.encode("utf-8")).hexdigest()
    )


# ---------------------------------------------------------------------------
# Edge-Case: Datei nach dem Tool-Aufruf nicht lesbar -> Fehler wird NICHT
# stillschweigend verschluckt (stderr-Diagnose), Hook bleibt aber fail-open.
# ---------------------------------------------------------------------------


def test_missing_file_after_edit_logs_diagnostic_and_falls_back(tmp_path):
    """Existiert die Datei beim Hook-Aufruf nicht (Race/geloescht), darf der
    Hook weder crashen noch schweigend eine falsche Zeile schreiben — er
    meldet den Lesefehler auf stderr und faellt auf den Fragment-Hash zurueck.
    """
    log_file = tmp_path / "decisions.log"
    md_file = tmp_path / "kapitel" / "verschwunden.md"
    md_file.parent.mkdir(parents=True)
    # Datei bewusst NICHT anlegen.

    env_overrides = {
        "ACADEMIC_DECISIONS_LOG": str(log_file),
        "CLAUDE_PROJECT_DIR": str(tmp_path),
    }

    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(md_file),
            "old_string": "alt",
            "new_string": "neu",
        },
    }
    result = run_hook(payload, env_overrides=env_overrides)

    assert result.returncode == 0, "Hook muss trotz Lesefehler fail-open bleiben"
    assert "nicht von Platte lesbar" in result.stderr, (
        f"Lesefehler wird nicht diagnostiziert, stderr={result.stderr!r}"
    )

    lines = _log_lines(log_file)
    assert len(lines) == 1, "Fallback muss trotzdem eine Log-Zeile schreiben"
    assert _hash_of(lines[0]) == hashlib.sha256(b"neu").hexdigest()
