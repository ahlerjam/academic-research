---
id: 24
title: Sources without DOI or ISBN are captured with a stored copy and checked like papers
status: accepted
tags: [sourcing, evidence, export, grey-literature, law, integrity]
---

# ADR-0024: Sources without DOI or ISBN are captured with a stored copy and checked like papers

Context: ADR-0016 proves existence only through a DOI or an ISBN, so web pages, laws and print-only
sources (grey literature) had no path to a green trace check. The operator wants to capture them
either alone through a form or together with the assistant (answer of 2026-10-20). The federal
portal gesetze-im-internet.de offers every norm as XML for automated processing, with a daily
table of contents `gii-toc.xml` and the DTD `gii-norm.dtd` (its page "Hinweise", opened 2026-10-20).

Decision: A source without DOI or ISBN is captured with a stored copy, and the copy is its proof of
existence. A web page is fetched on the user's click; its extracted text, URL, retrieval time and
sha256 are stored. A German federal law is taken from the gesetze-im-internet.de XML with the norm,
its section and the date of the version. A print-only source gets an attached scan or photo of the
cited pages. Anchors and the quote check run against the copy exactly as against a PDF (ADR-0014).
Capture works through a form and through an MCP tool of the plugin; both produce the same record.
Only for a print-only source without an attached copy is a quote "not checked": the export then
asks once, lists every such quote, and the confirmation is written to the change log with time and
user. Every other hard guarantee of ADR-0016 stays a block.

Rejected: a link without a copy (pages change or vanish); blocking all sources without DOI or ISBN
(excludes law and grey literature); warnings without a confirmation.

Consequence: A new ticket N13 in milestone M2a builds capture; N9 adds the MCP tool; T21 adds the
"not checked" class with the logged confirmation. The NORTHSTAR non-goal on outbound connections
needs the operator's addition "and a web page the user captures". This refines ADR-0015 and
ADR-0016.
