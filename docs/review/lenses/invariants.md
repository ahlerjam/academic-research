# Review lens: invariants

Add-only. Read together with the product invariants in AGENTS.md and the anti-goals A1-A10 of the plan, section 2.

- A quote, page, number or cite key reaches the document only from code; model text and PDF text are proposals until a deterministic check accepted them (A1).
- A broken trace blocks the export; only a print-only quote without a stored copy may pass, marked not checked, after a logged confirmation.
- Wording says "trace check", never "verified", where only "string present at page N" is proven (A3).
- No fuzzy accept of a quote, no guessed page, no silent re-extraction (A4).
- Every untrusted string that reaches LaTeX passes `escapeLatex` in core.
- Untrusted text is rendered as text, never as markdown or HTML, and never injected as an HTML string.
- A key or token never reaches a log line, an error message, the client bundle, Yjs, an export or a backup (A6).
- No authorship colour and no AI marker reaches `.tex`, `.pdf`, docx or PDF metadata (A2); the disclosure annex exists only on the user's request.
- The app makes no model call of its own, sends no telemetry and opens a network connection only on a user click.
- A crash or accept-all can be restored (A5).
- Nothing outside G1-G7; an idea becomes an `idea:operator` issue (A7).
