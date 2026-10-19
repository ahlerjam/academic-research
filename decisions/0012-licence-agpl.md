---
id: 12
title: The project is licensed under AGPL-3.0
status: accepted
tags: [licence, open-source]
---

# ADR-0012: The project is licensed under AGPL-3.0

Context: The tool is open source for students and friends and may later run as a hosted
instance. A permissive licence lets anyone offer a closed hosted fork.

Decision: AGPL-3.0-only for the whole repository (builder's call, consistent with the earlier
architecture note). Dependencies stay licence-compatible; PyMuPDF (AGPL,
pymupdf.readthedocs.io/en/latest/about.html) is not used; the dependency licence report is ticket T44.

Rejected: MIT or Apache-2.0 (allow closed hosted forks).

Consequence: Anyone who offers a modified version over a network must publish its source.
