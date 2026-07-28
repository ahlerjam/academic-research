"""Doku-Regressionstest fuer auth-helper.md Credential-Handling (Chunk C, #83).

Regression #193 — im Zuge von Issue #377 aus der frueheren Testdatei fuer das
zugehoerige (inzwischen als tote Parallellogik entfernte) Auth-Helper-Modul
hierher verschoben. Dieser Test prueft unabhaengig davon nur den
Markdown-Prompt-Text in ``agents/auth-helper.md``.

Sicherheits-Labels: security, v6, browser-use
"""

from pathlib import Path

import pytest


class TestAuthHelperPromptNoCredentialLeak:
    """Regression #193 — auth-helper.md darf Credentials NICHT im browser-use-Prompt
    uebergeben (sonst landen sie im LLM-Reasoning-Stream → Leak via Trace-Logs,
    Hook-Captures, Error-Messages).

    Akzeptanzkriterium: Credentials werden ueber ENV-Variablen (z.B. BROWSER_USE_USER /
    BROWSER_USE_PASS) und deterministische Eingabe (browser-use input <idx> "$VAR")
    behandelt — der Prompt-Text enthaelt keine Credential-Platzhalter mehr.
    """

    @pytest.fixture
    def doc_path(self) -> Path:
        return Path(__file__).parent.parent / "agents" / "auth-helper.md"

    @pytest.fixture
    def doc_text(self, doc_path) -> str:
        assert doc_path.exists(), f"auth-helper.md fehlt: {doc_path}"
        return doc_path.read_text(encoding="utf-8")

    # Muster, die einen Credential-Wert in den LLM-Prompt schreiben wuerden.
    # Beispiele aus dem alten Template:
    #   "Fuelle Passwort-Feld mit dem Wert aus dem Profil-Feld <credentials_keys[1]>"
    #   "Benutzername: <Wert aus credentials_keys[0] im Profil>"
    LEAK_PATTERNS = [
        "credentials_keys[0]",
        "credentials_keys[1]",
        "Wert aus dem Profil-Feld",
        "Wert aus credentials_keys",
    ]

    def test_no_credential_placeholder_in_prompt(self, doc_text):
        """Kein Credential-Platzhalter im Prompt-Text (sonst LLM-Stream-Leak)."""
        found = [p for p in self.LEAK_PATTERNS if p in doc_text]
        assert not found, (
            "auth-helper.md uebergibt Credentials im browser-use-Prompt — "
            f"verbotene Muster gefunden: {found}. "
            "Credentials muessen via ENV-Var + 'browser-use input' eingegeben werden, "
            "nicht als Prompt-Platzhalter."
        )

    def test_uses_env_variables_for_credentials(self, doc_text):
        """Credentials werden ueber ENV-Variablen referenziert."""
        assert "BROWSER_USE_USER" in doc_text and "BROWSER_USE_PASS" in doc_text, (
            "auth-helper.md muss Credentials ueber ENV-Variablen "
            "(BROWSER_USE_USER / BROWSER_USE_PASS) ansprechen statt im Prompt."
        )

    def test_uses_deterministic_input_for_credentials(self, doc_text):
        """Credential-Eingabe erfolgt deterministisch via 'browser-use input'."""
        assert "browser-use input" in doc_text, (
            "auth-helper.md muss 'browser-use input <idx> \"$VAR\"' nutzen, "
            "damit der Credential-Wert nicht in den LLM-Prompt gelangt."
        )

    def test_env_vars_not_echoed(self, doc_text):
        """Die Credential-ENV-Variablen duerfen nicht via echo/print ausgegeben werden."""
        import re

        # echo/print, das eine Credential-ENV-Var ausgibt → Leak in stdout/Logs
        leak_echo = re.findall(
            r"(?:echo|print[^\n]*)\$?\{?BROWSER_USE_(?:USER|PASS)",
            doc_text,
        )
        assert not leak_echo, f"Credential-ENV-Var wird ausgegeben (Leak): {leak_echo}"

    def test_security_policy_still_documented(self, doc_text):
        """Die Sicherheits-Policy (Credentials nie in Outputs) bleibt dokumentiert."""
        assert "NIEMALS" in doc_text, "Sicherheits-Policy-Abschnitt fehlt"
