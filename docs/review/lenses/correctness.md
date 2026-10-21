# Review lens: correctness

Add-only. A reviewer reads this file and the diff. A line is added when a confirmed finding class recurs three times; it is never changed or removed (GATES-RATCHET).

- Every scenario of the unit plan, the negative one included, is covered by a named test that fails when the behaviour is removed.
- A decision is a `decide*` function in core that returns a `{ kind: ... }` union; the caller switches on `kind` exhaustively.
- A flow loads, decides, applies; it holds no comparison or branch of its own.
- A foreign system is reached only through a port with an in-memory `.fake.ts` twin; no test uses the network.
- A new table ships its numbered migration in the same change.
- An outcome of a unit of work is logged as one JSON line with `status` and `duration_ms`; the response carries `X-Request-Id`.
- No abstraction for the second case, no helper with one caller, no error path for an impossible error.
- Every external fact in code or docs (version, licence, API behaviour) names an opened source or says "Nicht verifiziert".
- The diff stays within the unit's `paths` and within about 400 lines without tests.
