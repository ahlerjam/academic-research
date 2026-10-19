---
id: 6
title: SQLite in WAL mode with FTS5 as the only database
status: accepted
tags: [architecture, storage, sqlite, search]
---

# ADR-0006: SQLite in WAL mode with FTS5 as the only database

Context: The tool runs local-first on a laptop and later on one small server for a few friends.
Install has to be easy on macOS, Windows and Linux, and retrieval for "chat with my literature"
should cost no tokens.

Decision: One SQLite file per project plus one instance file, WAL mode, files (PDFs, assets) on
disk addressed by sha256. Full-text retrieval uses FTS5 BM25 plus a trigram index; dense
embeddings are added only if recall@10 stays below 0.8 on the gold set. Every table change ships
as a numbered SQL migration in `packages/server/migrations/` in the same PR, with an upgrade test.
The driver (`node:sqlite` or `better-sqlite3`) and the durability setting are decided by spike T06
with a kill -9 crash test.

Rejected: Postgres with pgvector (a second service for every friend's install), a vector database.

Consequence: One server process per instance; horizontal scaling is a non-goal.
