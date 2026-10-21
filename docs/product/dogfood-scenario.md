# Dogfood scenario

Followed by the critic agent as a first-time user in a headless browser, on the running app (`PORT=<n> WEB_PORT=<m> make dev`). Material: `fixtures/dogfood/` only (synthetic or CC BY / CC0 with the licence page recorded in `fixtures/dogfood/LICENSES.json`), never the operator's PDFs or data. Steps for features that do not exist yet are recorded as "not yet reachable", not failed. Run once in German and once in English.

1. Open the app. Record the time to an editable document and the outgoing hosts (expected: none).
2. Create a project, write a chapter of at least 400 words from the fixture text, with two headings.
3. Import a BibTeX or RIS file from the fixtures; import two PDFs from the fixtures.
4. Insert five citations with `Ctrl+K`-style keyboard flow; anchor each to a passage; make two of them verbatim quotes.
5. Hover a citation: the card shows the passage and its printed page. Record the hover latency.
6. Break one trace on purpose (alter the quoted text). Expect: the check turns red, the export is blocked with a reason.
7. Repair the trace. Export the PDF. Check by code that every quote and page appears in the PDF text as anchored, and that the PDF metadata and the `.tex` contain no authorship or AI marker.
8. Put one source without a PDF on the wishlist; open its library link. Expect: no network call before the click.
9. Make a backup, damage the project, restore it. Expect: identical content.
10. Collect console errors, failed requests and every host from `browser_network_requests`. A host contacted without a click is severity S1.

Scoring: steps passed, seconds per step, error counts, and a rubric of 1-5 for trust and provenance, flow, error messages, German and English. The numbers of `docs/product/quality-bar.json` are compared with the measurements. The question "would I open this tomorrow" is never scored by an agent.
