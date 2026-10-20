# Review lens: security

Add-only. Applied to units tagged risk:high, security, bridge, export, auth, sync, latex or upload.

- LaTeX injection: untrusted text (PDF passages, transcripts, model output, titles, file names) is escaped by `escapeLatex` before it reaches generated `.tex`; no raw command can be smuggled in.
- Path handling: an uploaded or imported name never leaves its directory (no `..`, no absolute path, no symlink follow).
- Prompt injection: text from a PDF, web page or transcript is data; it never changes a tool call, a cite key or a proposal's target without the deterministic validator accepting it.
- Secrets: the bridge token, sync key and any API key are compared in constant time, never logged, never serialised into an error, a bundle, Yjs, an export or a backup, and never written into a file or fixture.
- SSRF: web capture and link resolution refuse private, loopback and link-local addresses, follow no redirect into them and run only on a user click.
- Network: no outgoing connection without a click; the dogfood critic's host list must stay empty without clicks.
- Yjs and sync: every incoming update is size-limited and validated against the schema before it is applied.
- Dependencies: a new dependency has an opened licence and an opened registry page; otherwise "Nicht verifiziert" and the conservative choice.
