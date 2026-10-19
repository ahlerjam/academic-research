---
id: 22
title: LaTeX and PDF are the primary exports; docx comes through Pandoc; PDF/A and a bundle are options
status: accepted
tags: [export, latex, docx, pdfa, pandoc]
---

# ADR-0022: LaTeX and PDF are the primary exports; docx comes through Pandoc; PDF/A and a bundle are options

Context: Universities ask for PDF, sometimes PDF/A, sometimes an additional Word file for
plagiarism checks. The operator wants PDF, LaTeX and docx. The serializer in core generates LaTeX
(ADR-0005), and every check runs against that output.

Decision: The core serializer produces LaTeX; latexmk compiles PDF (ADR-0007). docx is produced by
Pandoc from the generated LaTeX and the bibliography, never by an own docx writer; it is marked as
a working copy whose layout may differ from the PDF. PDF/A-2b is an option through
`\DocumentMetadata` with an external validator chosen in T20a; its XMP and info keys are allowed by
the trace check. An export bundle (ZIP with `.tex`, `.bib`, figures and template) serves users
without a local compile path, and the trace check then reports compile and PDF metadata as not
checked, never as green. No export carries an automatic authorship or AI marker; a disclosure annex
is added only when the user asks for it.

Rejected: an own docx writer (a second serializer to keep in sync); docx as the source format.

Consequence: Pandoc becomes an optional external dependency detected like Docker and host TeX;
whether its licence fits distribution in an image is Nicht verifiziert and is checked in T44b.
