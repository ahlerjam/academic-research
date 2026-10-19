---
id: 20
title: Autonomous work runs as resumable jobs within the user's plan limits; accept-all needs a green check
status: accepted
tags: [agents, copilot, proposals, quota, autonomy]
---

# ADR-0020: Autonomous work runs as resumable jobs within the user's plan limits; accept-all needs a green check

Context: The operator allows agents up to full autonomy, including drafting the whole thesis, and
wants autocomplete while typing. Long jobs can exhaust the user's five-hour and seven-day plan
limits, which `$.session.usage` reports as percent used. ADR-0010 excluded proposals touching cite,
datum or tquote nodes from accept-all, which would block every autonomous chapter.

Decision: A research, outline, chapter or whole-thesis run is a job with numbered steps stored in
the project database; each step records its inputs, its proposals and its status, so a job resumes
after a restart, a crash or a limit. Before start the app shows an estimate from measured tokens
per step and the current plan usage; the job pauses when usage reaches a threshold (default 80 %,
set by the user) and resumes after the reset. Several jobs may run in parallel as subagents or
agent-team teammates under the claims of ADR-0017. Triggers by default: autocomplete after a
600 ms pause on, "check this" on a click on, review of each finished paragraph off, research only
on a command; each is a setting. Accept-all applies a job's proposals only when the validator and
the trace check pass for the resulting document; deletions spanning more than three blocks and any
`rawLatex` change still need a single review. This replaces ADR-0010's node exclusion.

Rejected: unbounded runs (plan limits stop them half done); accept-all without a check.

Consequence: Jobs need a table and a migration, a core decision for pause and resume, and a
behaviour test that pauses at the threshold and resumes. The whole-thesis pipeline (T45) is built
on jobs.
