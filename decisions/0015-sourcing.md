---
id: 15
title: Sourcing runs on a click; open access is fetched, everything else goes to a wishlist with library links
status: accepted
tags: [sourcing, search, wishlist, library, openurl, relevance]
---

# ADR-0015: Sourcing runs on a click; open access is fetched, everything else goes to a wishlist with library links

Context: The operator wants the tool to find and obtain sources, filter them for relevance, and
for closed literature produce a wishlist with links that open the item in any library. NORTHSTAR
(PR #63) allows outbound connections only on the user's click, only to Zotero, open metadata and
open-access services and the model; no background search, no download behind a library login.
The research of 2026-10-19 (workflow wf_82b92c7e-f95) checked the services and URL schemes.

Decision: A search adapter per service (OpenAlex, Crossref, DNB SRU, K10plus SRU, EconBiz), each a
port with a `.fake.ts`, throttled from the response headers, raw answers stored with sha256. Core
normalises DOI and ISBN-13 (invalid ones are dropped, never repaired), merges only on DOI, valid
ISBN or a service id (a title fingerprint alone is only a candidate), and decides open access from a
licence allowlist. A download checks content type, `%PDF-`, size and sha256 and records provenance;
a refusal becomes a wishlist entry. The wishlist and its links are built by core without a network
call: doi.org (optionally through an EZproxy or OpenAthens prefix), OpenURL 1.0 to the user's link
resolver, JOP and ZDB with the library's ISIL, a catalogue template, WorldCat, interlibrary loan;
export as HTML without scripts, CSV, RIS, CSL-JSON and BibTeX. A library profile per user lives in
the instance file; TIB Hannover (ISIL DE-89) is the example profile. A relevance filter scores each
candidate from deterministic signals (topic match, co-citation with the user's sources, type, year,
language) plus an optional advisory model reason; the user decides, and every include or exclude
is written to a screening log from which PRISMA counts are derived.

Rejected: Google Scholar, SSRN and BASE as adapters (terms or blocking; click links only); scraping
behind a login; a vector database (ADR-0006 stays).

Consequence: The wishlist ships in v0.1; search and download in stage 2a. The TIB resolver address
is Nicht verifiziert and is checked with the profile's test link.
