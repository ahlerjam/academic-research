"""Live-Sondierung: bindet sich der academic-vault-MCP-Server an eine CLI-Eval-Sitzung? (#824)

Aufruf::

    uv run python scripts/eval/probe_vault_mcp_binding_824.py \
        --out docs/evals/2026-08-10-vault-mcp-evals-824-live-results.json

Beantwortet Akzeptanzkriterium 1 durch einen **tatsaechlichen Lauf**, nicht
durch Annahme. Der Beweis haengt nicht am Antworttext, sondern am
**Zustand der Wegwerf-Datenbank nach dem Lauf**: der Agent kann einen Quote
mit ``extraction_method="local-verbatim"`` nur dort hinterlassen, wenn er
das MCP-Werkzeug ``vault.add_quote`` wirklich erreicht hat -- und die
serverseitige fail-closed-Verbatim-Pruefung gegen das lokale PDF bestanden
hat. Ein halluzinierter Antworttext kann das nicht faelschen.

Sondiert werden zugleich die beiden offenen Flag-Fragen aus dem Plan:

* Reicht ``--allowedTools mcp__academic-vault__*,Read`` im ``--print``-Modus,
  oder braucht der Schreibpfad zusaetzlich ``--permission-mode
  bypassPermissions`` (wie in ``measure_context_enrichment_710.py``)?
* Genuegt die Test-MCP-Config mit ``sys.executable -m academic_vault.server``
  und ``PYTHONPATH``/``VAULT_DB_PATH`` im ``env``-Block?

Der Lauf braucht kein API-Budget (OAuth-Sitzung der CLI) und keinen
Netzzugriff ausser dem Modellaufruf selbst.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.evals.eval_runner import SESSION_PROFILES, load_agent_content  # noqa: E402
from tests.evals.vault_fixture import build_vault_session  # noqa: E402

CLI_TIMEOUT_SECONDS = 300

#: Der qe-01-Prompt aus evals/quote-extractor/evals.json -- der teuerste Fall
#: (get_paper -> Read des PDFs -> add_quote mit Verbatim-Pruefung).
QE_01_INPUT = (
    '{"paper": {"paper_id": "devops2022", "title": "DevOps Governance Frameworks", '
    '"doi": "10.1109/MS.2022.1234567"}, "research_query": "DevOps Governance", '
    '"max_quotes": 2, "max_words_per_quote": 25}'
)


def run_variant(
    *,
    label: str,
    permission_mode: str | None,
    model: str,
) -> dict[str, Any]:
    """Eine Sondierungs-Sitzung gegen eine frische Wegwerf-Vault."""
    from academic_vault.db import VaultDB

    with tempfile.TemporaryDirectory(prefix="vault-probe-824-") as tmp:
        session = build_vault_session(Path(tmp) / "vault-session")
        command = [
            "claude",
            "--print",
            "--model",
            model,
            "--output-format",
            "json",
            "--system-prompt",
            load_agent_content("quote-extractor"),
            "--allowedTools",
            SESSION_PROFILES["vault"]["allowed_tools"],
            "--setting-sources",
            "",
            "--mcp-config",
            str(session.mcp_config_path),
            "--strict-mcp-config",
        ]
        if permission_mode:
            command += ["--permission-mode", permission_mode]
        command.append(f"Input: {QE_01_INPUT}")

        started = time.perf_counter()
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=CLI_TIMEOUT_SECONDS,
            cwd=str(session.root),
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)

        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError:
            envelope = {"_raw_stdout": proc.stdout[:2000]}

        db = VaultDB(str(session.db_path))
        quotes = db.find_quotes("devops2022", k=50)
        written = [q for q in quotes if not str(q["quote_id"]).startswith("seed-")]

        return {
            "label": label,
            "permission_mode": permission_mode,
            "model": model,
            "returncode": proc.returncode,
            "stderr_tail": proc.stderr[-800:],
            "duration_ms": elapsed_ms,
            "allowed_tools": SESSION_PROFILES["vault"]["allowed_tools"],
            "cwd_was_tmp": True,
            "db_quotes_total": len(quotes),
            "db_quotes_written_by_agent": [
                {
                    "quote_id": q["quote_id"],
                    "verbatim": q["verbatim"],
                    "extraction_method": q["extraction_method"],
                    "pdf_page": q["pdf_page"],
                }
                for q in written
            ],
            "binding_proven": bool(written),
            "envelope": envelope,
        }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Zieldatei fuer die Rohdaten")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument(
        "--with-bypass",
        action="store_true",
        help="Zusaetzliche Variante mit --permission-mode bypassPermissions",
    )
    args = parser.parse_args(argv[1:])

    variants: list[dict[str, Any]] = [
        run_variant(label="profil-flags-only", permission_mode=None, model=args.model)
    ]
    if args.with_bypass:
        variants.append(
            run_variant(
                label="profil-flags+bypassPermissions",
                permission_mode="bypassPermissions",
                model=args.model,
            )
        )

    payload = {
        "issue": 824,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "variants": variants,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for variant in variants:
        print(
            f"{variant['label']}: returncode={variant['returncode']} "
            f"binding_proven={variant['binding_proven']} "
            f"quotes_written={len(variant['db_quotes_written_by_agent'])}",
            file=sys.stderr,
        )
    return 0 if any(v["binding_proven"] for v in variants) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
