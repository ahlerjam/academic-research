---
id: 4
title: TypeScript end to end in one pnpm workspace with role-bound gates
status: accepted
tags: [architecture, stack, typescript, gates, roles]
---

# ADR-0004: TypeScript end to end in one pnpm workspace with role-bound gates

Context: The product is a structured editor (ProseMirror, Yjs, PDF.js are JavaScript) with a
deterministic evidence core that both the browser (hover, preview) and the server (export, trace
check) must run identically. The earlier scaffold was Python-only. One maintainer works with AI
coding agents, so one language, one lockfile and one test runner keep the surface small.

Decision: One pnpm workspace with three packages: `packages/core` (pure decisions, no IO),
`packages/server` (Node 24, Hono HTTP, adapters) and `packages/web` (Vite UI). Node runs the
TypeScript sources directly (type stripping, `erasableSyntaxOnly`), so the server needs no build
step. TypeScript 6.0.x, because typescript-eslint 8.71 declares `typescript >=4.8.4 <6.1.0`
(npm peerDependencies, read 2026-10-17); TypeScript 7 follows when type-aware linting supports it.
ESLint strict-type-checked, Prettier, Vitest; ast-grep house rules (`TS-*`) bind per role through
`gates/roles.json`. Python appears only as an isolated worker if a later spike requires it.

Rejected: Python core plus TypeScript UI (two implementations of the document model and the
quote check); extending Overleaf CE (AGPL, no extension API verified, lacks comments, history and
sandboxed compile in CE).

Consequence: The agent-repo Python rules are dropped; the cross-cutting gates stay. A dependency
must be public for 7 days before install (`minimumReleaseAge` in `pnpm-workspace.yaml`).
