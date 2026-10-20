# Releases

How a version of academic-research is released without the operator. The kernel files that enforce it are
`.github/workflows/release.yml`, `.claude/workflows/ar-release.js`, `ops/conductor/gh_ops.py` and the
`release-artifacts` verb in the `Makefile`; this page only describes them.

## Order

1. `state.py` (in `ops/conductor/`) reports every milestone proof green on `main`.
2. The lead runs the saved workflow `ar-release` with `{"version": "<version>", "issue": <release unit>}`.
   It runs a critic pass on `main`, collects the proof runs, the changelog section and the open S1/S2
   findings, lets a Fable judge panel decide, and writes `docs/release/<version>.md` (format below) plus the
   `CHANGELOG.md` section if it is missing. The lead opens the pull request for both with
   `gh_ops.py open-pr` and `enable-auto-merge`; it merges like any unit, after green `gate` and `protect`.
3. The lead runs `gh_ops.py dispatch-release --version <version> --dry-run true`. `release.yml` verifies and builds.
4. When the dry run of the same commit is green and `state.py` reports `release_ready: true`, the lead runs
   `gh_ops.py dispatch-release --version <version> --dry-run false`. Only then does the job `publish` tag `v<version>` and
   create the GitHub release with the archives.

No session runs `gh workflow run release.yml` or pushes a tag directly; the bash rules `BASH-RELEASE-REAL`
and `BASH-TAG-PUSH` refuse it.

## What release.yml checks (job verify)

- dispatched on `refs/heads/main`; `version` is `MAJOR.MINOR.PATCH` and higher than the last `v*` tag;
- `CHANGELOG.md` has a heading `## <version>` or `## [<version>]` (a leading `v` is allowed);
- `docs/release/<version>.md` exists and has exactly one line starting with `verdict:`, and it is
  `verdict: release`;
- for each stage 1, 2a, 2b, 3, 4, 5 the newest completed `proof.yml` run on `main` (run name
  `proof stage <s>`) concluded `success` and its commit is on the history of the release commit;
- with `dry_run=false`: a successful run `release <version> dry_run=true` of the same commit;
- `make check gates-selftest`, then `make proof STAGE=<s>` and `gate.py proof-verify --stage <s>` for
  every stage.

## Verdict file `docs/release/<version>.md`

Written by `ar-release` from the panel's structured result, never by hand:

```markdown
# Release <version>

verdict: release
commit: <sha of main the panel judged>
panel: <model of each judge>

## Rubric
- <line>: pass|fail - <evidence: run URL, exit code, file:line>

## Judge-panel items
- T23 chapter review: pass|fail - <evidence>
- T32 suggestions: pass|fail - <evidence>
- T45 design approval: pass|fail - <evidence>
- Declaration and annex wording: pass|fail - <evidence>
- ADRs set to accepted: <list>

## Open S1/S2 findings
- none | <issue links>

## Human items (not blocking)
- Request to Anthropic: drafted in <issue>, sent only by the operator.
```

A verdict other than `release` is written as `verdict: hold` with the reasons; `release.yml` then stays red.

## Archives

`make release-artifacts` checks that `package.json` has the script `release:artifacts`, empties
`release-out/`, runs the script with `RELEASE_OUT` (absolute path of `release-out/`) and
`SOURCE_DATE_EPOCH` (commit time of `HEAD`), and writes `release-out/SHA256SUMS` over every `.tar.gz` and
`.zip` in it. The script is product code (agent lane). The archives must be byte-reproducible: the job
`build` builds twice and the job `publish` rebuilds on its own runner, and both compare the checksums.
Fixed file times from `SOURCE_DATE_EPOCH`, sorted entries and fixed owner ids are the usual means.

Workflow artifacts (`actions/upload-artifact`) are not used, because no pinned commit of that action exists
in the repository yet; the build job writes the checksums into its job summary instead.
