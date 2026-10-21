# Releases

How a version of academic-research is released without the operator. The kernel files that enforce it are
`.github/workflows/release.yml`, `.claude/workflows/ar-release.js`, `ops/conductor/gh_ops.py` and the
`release-artifacts` verb in the `Makefile`; this page only describes them.

## Order

1. `state.py` (in `ops/conductor/`) reports every milestone proof green on `main` and no unit is ready,
   running or in a pull request; its next step is `release-prep`.
2. The lead starts the worktree `claude/release-<version>` from the current `origin/main` and runs the saved
   workflow `ar-release` in it with
   `{"version": "<version>", "issue": <release issue>, "port": 4401, "webPort": 5501, "notes": "", "worktree": "<path>"}`.
   It runs a critic pass on `main`, collects the proof runs, the changelog section and the open S1/S2
   findings, lets a Fable judge panel decide, and writes `docs/release/<version>.md` (format below) plus the
   `CHANGELOG.md` section if it is missing. The lead checks the hash of `.ar/release-check.log`, opens the
   pull request for both with `gh_ops.py open-pr --holder <id>` and `gh_ops.py enable-auto-merge --holder <id>`,
   and files the returned `actions` (the critic's findings, and a plan card with the reasons on `verdict: hold`)
   with `gh_ops.py apply-actions --holder <id>`; it merges like any unit, after green `gate` and `protect`.
   The release pull request changes only the verdict file and `CHANGELOG.md`.
3. The lead runs `gh_ops.py dispatch-release --holder <id> --version <version> --dry-run true`. `release.yml`
   verifies and builds. A red dry run is never dispatched again for the same commit; `state.py` names it as
   `dry_run_red` and the lead files a plan card for slice S9.
4. When the dry run of the same commit is green and `state.py` reports `release_ready: true`, the lead runs
   `gh_ops.py dispatch-release --holder <id> --version <version> --dry-run false`. Only then does the job
   `publish` tag `v<version>` and create the GitHub release with the archives. `state.py` offers no release
   step while a release run is in progress.

No session runs `gh workflow run release.yml` or pushes a tag directly; the bash rules `BASH-RELEASE-DIRECT`
and `BASH-TAG-PUSH` refuse it (`gh_ops.py` runs `gh` itself and is not a typed command). Every `gh_ops.py`
verb above needs the lead's own valid lease (`--holder <id>`).

## What release.yml checks (job verify)

- dispatched on `refs/heads/main`; `version` is `MAJOR.MINOR.PATCH` and higher than the last `v*` tag;
- `CHANGELOG.md` has a heading `## <version>` or `## [<version>]` (a leading `v` is allowed);
- `docs/release/<version>.md` exists and has exactly one line starting with `verdict:`, and it is
  `verdict: release`;
- the verdict file has exactly one line `commit: <40-hex sha>`; that commit exists and is on the history of the
  release commit, and since it only `docs/release/<version>.md` and `CHANGELOG.md` changed
  (`git diff --name-only <judged> <release commit>`);
- the last change of the verdict file on the first-parent history of the release commit is a merge commit with
  two parents and the subject `Merge pull request #<n> from <owner>/claude/release-<version>` (the repository
  keeps the default merge commit message), and its first parent is the judged commit: the panel judged the
  `main` the release pull request was merged onto, so no code on the release branch escapes the verdict;
- for each stage 1, 2a, 2b, 3, 4, 5 the newest completed `proof.yml` run on `main` (run name
  `proof stage <s>`) concluded `success` and its commit is on the history of the release commit;
- with `dry_run=false`: a successful run `release <version> dry_run=true` of the same commit;
- `make check gates-selftest`, then `make proof STAGE=<s>` and `gate.py proof-verify --stage <s>` for
  every stage.

`state.py` reads the same runs the same way (newest completed run per run name), so `release_ready` and the
job verify agree. Its check `verdict_bound` is stricter than the job verify: the single `commit:` line names a
parent of the merge commit of the newest merged pull request from `claude/release-<version>` of the same
repository, that parent is not the pull request's head, the merge commit is the head of `main`, and
`pulls/<n>/files` lists only the verdict file and `CHANGELOG.md`. Without it
`gh_ops.py dispatch-release --holder <id> --dry-run false` is refused. A `CHANGELOG.md` fix after the release merge passes the job verify but sends
`state.py` back to `release-prep`.

## Verdict file `docs/release/<version>.md`

Written by `ar-release` from the panel's structured result, never by hand:

```markdown
# Release <version>

verdict: release
commit: <sha of main the panel judged>
panel: readiness (fable), trust (fable), taste (fable)

## Proof runs
- stage <s>: success <run URL>

## Rubric
- [<lens>] <line>: pass|fail - <evidence: run URL, exit code, file:line>

## Reasons
- [<lens>] <reason>

## ADRs set to accepted
- none | <paths>

## Open S1/S2 findings
- none | <issue links>

## Critic run
- findings: none | <severity and title>
- hosts without a click: none | <hosts>
- failed steps: none | <steps>

## Human items (not blocking)
- Request to Anthropic: drafted by an agent; only the operator sends it.
```

The taste lens rules on the judge-panel items of `docs/autonomy/charter.md` section 3 (T23 chapter review,
T32 suggestions, T45 design approval, declaration and annex wording, ADR acceptance) in its rubric lines.
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
