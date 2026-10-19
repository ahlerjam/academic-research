---
id: 9
title: Evidence checks are deterministic code; the model only proposes
status: accepted
tags: [evidence, quotes, citations, core, csl]
---

# ADR-0009: Evidence checks are deterministic code; the model only proposes

Context: The product promises that a quote, a printed page, a statistic or a cite key never
reaches the thesis unchecked. A model judgement cannot carry that promise.

Decision: `packages/core` holds the checks. Normalisation is NFC plus an explicit fold table
(ligatures, quote and dash forms, NBSP, whitespace, flagged dehyphenation), not NFKC, because
NFKC removes formatting distinctions such as superscripts (unicode.org/reports/tr15).
`decideQuote` accepts only substrings and reports near misses. The printed page comes from
`/PageLabels` or a user-set offset, never a guess. Cite nodes are style independent; the
rendering path for all CSL styles (CSL processor vs biblatex) is decided by spike T05, with
biblatex-apa as fallback. A proposal validator rejects numerals, quoted strings and cite keys
that no datum, checked quote or retrieved passage backs. The trace check gates export and says
what it does not cover (whether a passage supports a claim).

Rejected: fuzzy acceptance of quotes; model-verified citations as the trust anchor.

Consequence: The UI says "trace check", never "verified".
