---
id: 18
title: Local-first app on 127.0.0.1; shared projects live on a sync server with roles and private data
status: accepted
tags: [hosting, sync, security, auth, roles, privacy, collaboration]
supersedes: [11]
---

# ADR-0018: Local-first app on 127.0.0.1; shared projects live on a sync server with roles and private data

Context: ADR-0011 made stage 1 local on 127.0.0.1 and put a hosted profile for friends into
stage 3, online only. On 2026-10-19 the operator moved collaboration into v0.1 and decided that
every co-author keeps their own local app and their own Claude Code (ADR-0013).

Decision: The app always runs locally on 127.0.0.1 with the protections of ADR-0011: foreign
Host and Origin rejected on HTTP and WebSocket upgrade, browser opened with a one-time code in the
URL fragment exchanged for an HttpOnly, SameSite=Strict cookie, a custom header on mutating
requests. A shared project lives on a sync server, which is the same server program in the
`hosted` profile behind a TLS reverse proxy, run on a small server or on one member's machine. The
local app opens it as a remote project: it keeps a local Yjs copy and a local SQLite cache, works
offline and syncs when connected; the member's Claude Code talks only to the local app, which
forwards tool calls to the sync server with the member's token. Access is by single-use hashed
invite links that expire after 7 days, argon2id passwords, rate limits and lockout. Roles: owner,
editor, commenter. Interview data, transcripts and survey files stay private to the member who
imported them until that member shares them; only that member deletes them. PDFs are shared at one
of three levels: none (default), cited passages only, or the full PDF with a copyright notice for
books. A member's agents see exactly what that member may see.

Rejected: every member on one hosted web instance (members would lose their own Claude Code
link); peer-to-peer sync (no stable authority for roles and deletion); passkeys and mail login in
v1 (see ADR-0011).

Consequence: The deletion path must reach the sync server and every local cache. Tool calls from
an editor's agents are checked against roles on the server, not in the local app.
