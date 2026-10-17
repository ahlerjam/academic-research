---
id: 11
title: Local-first on 127.0.0.1; a hosted profile for trusted friends comes later
status: accepted
tags: [hosting, security, auth, install]
---

# ADR-0011: Local-first on 127.0.0.1; a hosted profile for trusted friends comes later

Context: The first user is the operator writing a thesis; friends join later on one server.
A local web server is reachable by any web page through DNS rebinding and cross-site WebSocket
requests unless it checks Host and Origin.

Decision: Stage 1 runs only on 127.0.0.1, rejects foreign Host and Origin on HTTP and WebSocket
upgrade, opens the browser with a one-time code in the URL fragment exchanged for an HttpOnly,
SameSite=Strict cookie and needs a custom header on mutating requests. Stage 3 adds a hosted
profile: TLS reverse proxy, admin bootstrap, single-use hashed invite links that expire after 7
days, argon2id passwords, rate limits and lockout, and roles owner, editor, commenter.

Rejected: passkeys in v1 (need a stable HTTPS origin and a custom invite flow); mail-based login
(needs a mail server); a desktop wrapper in v1.

Consequence: Hosted mode is online-only in v1; offline merge for hosted clients is later.
