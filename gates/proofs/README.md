# Proof contract

Operator file. One `stage-<s>.json` per NORTHSTAR stage (`1`, `2a`, `2b`, `3`, `4`, `5`). A milestone is
done only when `python3 -I gates/gate.py proof-verify --stage <s>` is green on main after
`make proof STAGE=<s>` (workflow `proof.yml`), and the judge panel has ruled on every `OPEN (operator)` item
(`docs/autonomy/charter.md` section 3). The contract grows only through the operator.

## Contract file

- `outcome`, `proof`: verbatim quotes of the stage row in `NORTHSTAR.md`.
- `contracts[]`: `id` (`S<STAGE>-<NAME>`, e.g. `S2A-DATUM-STALE`), `northstar` (a verbatim quote of
  `NORTHSTAR.md`; line breaks do not matter), `evidence` and `source` (issue and acceptance criteria).
- `evidence: "e2e"` needs `artefact` (one of the kinds below) and `negative` (the mandatory negative case:
  a deliberately wrong input or fault and the rejection that must follow). `threshold`
  (`{"metric", "min"}`) makes a measured number part of the contract.
- `evidence: "operator"` (the name predates operator decision 6 of 2026-10-20) needs `operator`: what happens
  outside the runner and who records it. proof-verify prints it as OPEN and never counts it as passed; the
  judge panel (`ar-judge`, and `ar-release` before a release) rules on it and records the verdict in the
  ticket and in `docs/release/<version>.md`.

## What a proof spec delivers

Specs live in `packages/web/e2e/proof/` and run through `make proof STAGE=<s>`, which collects only the files
`packages/web/e2e/proof/stage-<s>*.spec.ts`; name a spec `stage-<s>-<topic>.spec.ts` (for example
`stage-1-quote-exact.spec.ts`). The contract id goes into the test title, never only into the file name.

1. **Runner report.** `make proof` writes the Playwright JSON report to `proof-out/stage-<s>.report.json`.
   PASS comes only from this report, never from a file a spec writes.
2. **Titles.** For every e2e id there is at least one test whose title (with its `describe` titles; the file
   name does not count) contains the id, and at least one more whose title contains the id and the word
   `negative`, e.g. `S1-QUOTE-EXACT negative: one changed character blocks the export`. Write the id followed
   by a space, never by a hyphen: `S1-QUOTE-EXACT-NEGATIVE` reads as an unknown id and is red. Every test
   carrying an id must pass on its first run: skipped, flaky, `test.fail` and failed tests are red. An id with
   the stage prefix that is not in the contract is red.
3. **Evidence record.** The spec writes `$PROOF_OUT/<ID>.json`:

   ```json
   {
     "id": "S1-QUOTE-EXACT",
     "artefacts": ["S1-QUOTE-EXACT/trace.json"],
     "negative": {"case": "<the contract's negative, verbatim>", "input": "<the wrong input>", "reason": "<the rejection observed, e.g. its code>"},
     "measurement": {"metric": "recall@10", "value": 0.83}
   }
   ```

   `measurement` only where the contract has a `threshold`; the value must reach `min`.
4. **Artefacts.** Every listed artefact is a non-empty regular file inside `proof-out/<ID>/` (no symlink, no
   `..`), produced by the app during the run. At least one has the contract's kind:

   | kind | suffix | content |
   | --- | --- | --- |
   | `pdf` | `.pdf` | starts with `%PDF-` |
   | `zip` | `.zip` | starts with `PK\x03\x04` |
   | `docx` | `.docx` | starts with `PK\x03\x04` |
   | `png` | `.png` | PNG signature |
   | `json` | `.json` | parses as JSON |
   | `tex` | `.tex` | non-empty UTF-8 |
   | `text` | `.txt` `.log` `.md` `.html` `.csv` `.ris` `.bib` | non-empty UTF-8 |

proof-verify checks presence and form. Whether a spec really exercises its NORTHSTAR sentence and whether its
negative case is a real rejection is audited by `ar-judge` before the first green proof run.
