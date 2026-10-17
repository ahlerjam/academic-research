# academic-research

A local-first writing tool for scientific theses where nothing is without a trace: citations show
the verbatim PDF passage with its printed page, numbers come from your own data, interview quotes
point at the transcript line, and a copilot proposes, never silently changes. Export goes through
LaTeX to PDF with your university's template and any common citation style.

Status: stage 1 in progress. Goal and stages: [NORTHSTAR.md](NORTHSTAR.md); plan:
[docs/plan/2026-10-17-academic-research-plan.md](docs/plan/2026-10-17-academic-research-plan.md);
decisions: [decisions/](decisions/index.md).

## Prerequisites

- Node.js (version in `.node-version`) with `corepack enable` for pnpm.
- `python3` (3.9 or newer) and `ast-grep` for the repository gates
  (`brew install ast-grep` or `npm i -g @ast-grep/cli`).
- Later stages: Docker for the LaTeX compile container.

## Develop

```sh
make setup     # install from pnpm-lock.yaml
make dev       # server on http://127.0.0.1:4317 and the web UI via Vite
make check     # lint, typecheck, tests: what CI and the stop gate run
make help      # every verb
```

Agents read [AGENTS.md](AGENTS.md). Every rule lives in `gates/catalog.json`, is reported in the
turn by the hooks in `.claude/settings.json` and runs again in CI. `make gates-selftest` proves
that every gate turns red on a real violation.

Operator only: `make sync` after changing `gates/catalog.json`, `gates/roles.json` or
`gates/controls.json`, then `make controls-baseline`.

## Licence

AGPL-3.0-only, see [LICENSE](LICENSE).
