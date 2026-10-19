---
id: 5
title: A structured document with typed inline nodes; LaTeX is generated output
status: accepted
tags: [architecture, editor, latex, export, prosemirror, yjs]
---

# ADR-0005: A structured document with typed inline nodes; LaTeX is generated output

Context: The wedge is "nothing in the thesis without a trace": a citation shows its verbatim PDF
passage, a number points at an analysis, an interview quote at a transcript line. A free-text
`.tex` buffer cannot validate any of that, and LaTeX error messages stop non-LaTeX friends.

Decision: The document is a ProseMirror document (MIT) held in Yjs 13.6.x through y-prosemirror
1.x. Blocks have stable `blockId`s; inline atoms `cite` (cluster with mode and items), `datum`,
`tquote`, `xref`, `math` carry ids, never copied text. A pure serializer in `packages/core`
generates LaTeX with a source map kept outside the `.tex`; every untrusted string passes
`escapeLatex`. A read-only LaTeX source view and editable `rawLatex` blocks serve power users;
the AI may never create or edit `rawLatex`.

Rejected: a raw LaTeX editor (no validation possible); Tiptap Pro, BlockNote xl, Lexical and
Milkdown (licence or binding gaps, see the plan's research); Yjs 14 (only release candidates).

Consequence: `.tex` import is best effort (unknown constructs become `rawLatex`). Export output
must be byte-identical for any mix of authors.
