# academic-research

This repository was set up with the `agent-repo` skill. Agents read `AGENTS.md`; this file is for people.

- `make help` lists every verb. `make setup` installs the toolchains from the lockfiles.
- Every architecture rule lives in `gates/catalog.json`, is reported in the turn by the hooks in
  `.claude/settings.json` and runs again in CI with the same make targets.
- `make gates-selftest` proves that every gate turns red on a real violation.
- Operator only: `make controls-baseline` after changing a control file, `make sync` after changing
  `gates/catalog.json`, `gates/roles.json` or `gates/controls.json`.

## Prerequisites

`make setup` checks these and never installs them silently:

- `git`, `make` and `python3` (3.9 or newer) for the gates.
- `ast-grep` (the binary `ast-grep`; on Linux `sg` is usually another program): `brew install ast-grep`,
  `npm i @ast-grep/cli -g`, `cargo install ast-grep --locked` or `pip install ast-grep-cli`.
- `uv` for Python; the Python version comes from `.python-version`.
- `docker` with Compose for `make up`, `make db-check` and `make test`.

