---
id: 23
title: Every user-facing message has a code with German and English text; German is the default
status: accepted
tags: [ui, i18n, core, messages]
---

# ADR-0023: Every user-facing message has a code with German and English text; German is the default

Context: The first users write in German, the project is public, and the review found that core
returns English prose in its results, which would have to be translated later at every call site.

Decision: From T17a on, every finding, rejection and notice that a user can see is a code in core
with parameters, for example `{ kind: "locator-mismatch", page: 12, locator: "S. 14" }`. A core text
table maps each code to a German and an English sentence; the UI and exports pick the language
from the user's setting, German by default. Logs keep the code. No i18n library is added.

Rejected: English prose in core results (translation later at every caller); a runtime i18n
framework (more than two languages are not planned).

Consequence: A gate or test checks that every code has both texts.
