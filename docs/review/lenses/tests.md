# Review lens: tests

Add-only. The reviewer of this lens sees every test change made after the test commit of the unit.

- A test asserts behaviour a user or a caller can observe; an `expect` on a constant, a mock of the unit's own core or an assertion that cannot fail is a blocker.
- Each plan scenario has a test; the negative scenario is a real rejection caused by a deliberately wrong input.
- The new tests failed on the base commit for an assertion or a missing module, not for a syntax error (the red-on-base evidence is present).
- After the test commit no test lost an assertion, was skipped, focused, marked todo or deleted; a weakened test is a blocker.
- Unit tests exist only for `decide*` functions with a real decision; server features have one behaviour test; UI behaviour has a Playwright spec.
- Fixtures are synthetic or CC-licensed with the licence recorded; no real PDF, no vendor-prefixed token (use `FAKE_<name>`).
- A proof spec under `packages/web/e2e/proof/` carries its contract id in the title, contains at least one `expect`, and writes an artefact derived from the running app.
- A test does not depend on the clock, randomness, the network or the order of other tests.
