---
id: 14
title: A citation anchor is a text range in the source, for a quote or a paraphrase
status: accepted
tags: [evidence, quotes, citations, core, editor]
---

# ADR-0014: A citation anchor is a text range in the source, for a quote or a paraphrase

Context: The review of 2026-10-19 found that a typed quote is never bound to its anchor
(`CiteItem.anchorId?` points at a sentence id), that matching on single sentences fails on
"z. B.", "et al." and page breaks, and that paraphrases, the normal case in business theses and
APA, have no anchor at all. The schema has no data yet, so changing it now costs no migration.

Decision: An anchor is `{ sourceId, from: { page, offset }, to: { page, offset }, kind: "quote" |
"locus", textHash, extractor: { name, version } }`, set by selecting a passage. Matching runs on the
normalised page text with page N and N+1 joined and running heads marked as spans; an offset map
leads back to page and offset; sentence ids stay the retrieval unit. A `quote` anchor renders its
visible text from the range (inline node `squote`); APA-permitted changes (ellipsis, square
brackets, first letter, end punctuation) are typed spans, each an exact substring in source
order. A `locus` anchor shows the passage without claiming wording. A typed page locator is
compared with the anchor's page (`locator-mismatch`). A changed `textHash` or extractor version
makes the anchor `stale`, which blocks export. Unanchored citations are listed with a coverage
line; only a broken trace blocks.

Rejected: anchors only for direct quotes (paraphrases stay unchecked); fuzzy matching (ADR-0009).

Consequence: T08, T15, T16, T17a, T17b, T18 and T21 get new acceptance criteria. This refines
ADR-0005 (document nodes) and ADR-0009 (deterministic evidence) without replacing them.
