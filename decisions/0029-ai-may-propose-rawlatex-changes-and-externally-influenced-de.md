---
id: 29
title: AI may propose rawLatex changes, and externally influenced deletions always need a single review
status: accepted
tags: [proposals, accept-all, security, injection, rawlatex, jobs]
---

# ADR-0029: AI may propose rawLatex changes, and externally influenced deletions always need a single review

Context: ADR-0020 says that "any `rawLatex` change still needs a single review", while the plan of
2026-10-17 had the invariant "AI never edits rawLatex". ADR-0020 also lets accept-all apply a
deletion of up to three blocks, so an instruction hidden in a PDF or web page could cause a small
deletion without a review. The operator decided both points on 2026-10-20.

Decision: An AI proposal may change a `rawLatex` block. It is shown as code, is never applied by
accept-all and is applied only by a single accept that confirms the raw LaTeX. Every proposal that
was produced while untrusted external text was in the context (`influencedByExternalText: true`)
and that deletes content is likewise excluded from accept-all and needs a single review, whatever
its size. All other rules of ADR-0020 stay.

Rejected: a complete ban on AI proposals for `rawLatex` (blocks legitimate help with tables and
macros); accept-all for small externally influenced deletions (injection risk).

Consequence: T26a replaces the intake ban of its old AC4 with the single-review path; T33 tests
the exclusion with an injection fixture. This refines ADR-0020.
