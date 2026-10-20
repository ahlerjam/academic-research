---
id: 30
title: A removed member's shared sources and data stay shared and are marked owner-removed
status: accepted
tags: [collaboration, sharing, roles, sources, personal-data]
---

# ADR-0030: A removed member's shared sources and data stay shared and are marked owner-removed

Context: ADR-0018 makes interview data, transcripts and survey files private to the member who
imported them and shares PDFs at three levels, but does not say what happens when that member
leaves or is removed. The tickets T38 and Y2 had proposed different rules for PDFs and for own
data. The operator decided one rule on 2026-10-20.

Decision: When a member is removed, everything that member had shared (PDFs at their sharing level,
cited passages, transcripts, survey files and datasets) stays shared with the project at the same
level and is marked `owner-removed`. Anchors and trace checks keep working. Nothing becomes newly
visible: an item that was not shared stays private and leaves the project with the member. The
project owner may delete an `owner-removed` item, and a deletion the removed member asks for is
carried out by the owner through the normal deletion path, which reaches the sync server and every
local cache.

Rejected: withdrawing PDFs but keeping own data (two rules); withdrawing everything (breaks
anchors and trace checks of the remaining authors).

Consequence: T38 and Y2 implement the same rule and test it. The copyright notice for fully shared
books (ADR-0018) stays visible on `owner-removed` items. This refines ADR-0018.
