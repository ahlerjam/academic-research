"""Sanitizer for log bundles + fuzzer findings."""

from __future__ import annotations

import re

# Snapshot of patterns formerly in tools/log_watcher/claude_analyze.py
# (deleted 2026-05-17 in Claude-Code-Strategie cleanup).
_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]+"),
    re.compile(r"(?i)(?:api[_-]?key|token|password|secret)\s*[=:]\s*[^\s\"\']+"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
]

# Issue #469 AC1: embedded prompt-injection attempts in untrusted diff/log text
# (e.g. a PR description or code comment trying to redirect the reviewer
# model) get neutralized with their OWN marker, kept separate from
# `[REDACTED]` so downstream consumers can tell "secret removed" apart from
# "instruction attempt removed". Deliberately narrow — matches the canonical
# jailbreak/prompt-injection phrasings the project's own AGENTS.md red line
# calls out, not a general "looks bossy" heuristic, to keep false positives
# on legitimate code/prose low.
_INSTRUCTION_PATTERNS = [
    re.compile(r"(?i)ignore\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above)\s+instructions?"),
    re.compile(
        r"(?i)disregard\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above)(?:\s+instructions?)?"
    ),
    re.compile(r"(?i)new\s+instructions?\s+for\s+(?:the\s+)?(?:assistant|model|ai|claude)\b"),
]


def sanitize_text(text: str) -> str:
    """Redact secrets and neutralize embedded-instruction attempts in ``text``.

    Secrets (API keys, tokens, private-key blocks) are replaced with the
    ``[REDACTED]`` token. Separately, phrasing that attempts to redirect a
    downstream LLM reviewer (prompt injection embedded in untrusted diff/log
    content) is replaced with the ``[INSTRUCTION NEUTRALIZED]`` token so the
    two categories stay distinguishable in the sanitized output.
    """
    for pat in _SECRET_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    for pat in _INSTRUCTION_PATTERNS:
        text = pat.sub("[INSTRUCTION NEUTRALIZED]", text)
    return text
