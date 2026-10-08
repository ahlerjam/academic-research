---
id: 2
title: Rules bind to roles, not to languages
status: accepted
tags: [architecture, roles, gates]
---

# ADR-0002: Rules bind to roles, not to languages

Context: Strict FP rules (no classes, no DI) fit a Python backend but fight Angular, which
requires components, directives and injectable services as classes. Workarounds against the
framework are exactly the Goodhart cases the gates exist to prevent.

Decision: A rule binds to a role, a role to a path in `gates/roles.json`. The core is strictly
pure in every language: no class except data models, no IO, no framework, no exception, a
rejection is a value. `flow`, `api`/`ui` and `adapter` may use the framework idiom, but as a
checkable list (decorator yes, inheritance no, `inject()` instead of constructor parameters).
Python keeps file-name roles, TypeScript and Kotlin use role directories (`core/`, `flow/`,
`ui/`). A feature never imports another feature.

Rejected: one constitution per language, because it maintains the same idea several times and
lets the copies drift.

Consequence: Role directories go against the Angular style guide's advice against folders by
code type; that is accepted on purpose. A source file without a role is a finding (GATES-ROLES).

