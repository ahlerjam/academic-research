---
id: 16
title: The database enforces integrity, and export is blocked unless every hard guarantee holds
status: accepted
tags: [storage, sqlite, integrity, evidence, export, gates]
---

# ADR-0016: The database enforces integrity, and export is blocked unless every hard guarantee holds

Context: The operator requires that citations exist, that quality never silently degrades, and
that the SQLite data is robust. ADR-0006 chose SQLite in WAL mode with numbered migrations and a
kill -9 crash test in T06, but set no rules for the schema itself.

Decision: Every table is `STRICT` with foreign keys on and `CHECK` constraints for state columns.
`PRAGMA integrity_check` and `foreign_key_check` run at start and before every backup; backups use
SQLite's online backup API, never a copy of the live file. Every stored file carries sha256 and its
provenance (source, licence, time). Gates enforce these rules on migrations. Export is blocked
unless these hard guarantees hold: each cited source exists (DOI resolved at doi.org or Crossref,
or a valid ISBN found at DNB or K10plus, checked on a click), each direct quote is verbatim in the
anchored range, each anchor resolves and is not stale, each printed page is derived or set by the
user, and no quote, page, number or cite key comes from model text. Whether a paraphrase renders
its source correctly and whether a source is relevant are advisory checks only.

Rejected: warnings instead of a block (the guarantees are the product); trusting model judgement for
any guarantee (ADR-0009).

Consequence: An unchecked existence lookup is shown as "not verified" and blocks export until the
user runs the check. New gate rules for STRICT, foreign keys and CHECK on migrations follow the
ratchet. This refines ADR-0006.
