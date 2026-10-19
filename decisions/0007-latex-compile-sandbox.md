---
id: 7
title: latexmk with TeX Live in a no-network container compiles every PDF
status: accepted
tags: [export, latex, compile, security, install]
---

# ADR-0007: latexmk with TeX Live in a no-network container compiles every PDF

Context: Citation styles need biber/biblatex (biblatex-apa requires biber, csquotes and
biblatex >= 3.4, ctan.org/pkg/biblatex-apa). Class and style files are code, and `-no-shell-escape`
is not a sandbox: it does not stop file reads (TeX Live guide, restricted shell escape).

Decision: latexmk with real TeX Live and fixed flags `-synctex=1 -interaction=nonstopmode
-halt-on-error -no-shell-escape`. The tested default runs it in a throwaway container without
network, with only the project directory mounted, read-only root, dropped capabilities and
memory, CPU, pids and 60 s limits. Host TeX is allowed with an explicit warning. The image ships
TeX Live scheme-small plus biber and biblatex-apa; its size is measured in ticket T22.

Rejected: Tectonic (no built-in biber, tectonic issue #1267), SwiftLaTeX (AGPL, dormant),
texlive.js (unmaintained), busytex (no biber), Typst (not LaTeX).

Consequence: A friend needs Docker or a host TeX install; there is no zero-dependency installer.
