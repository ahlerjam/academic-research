---
name: implementer
description: Use when a feature or a bug fix with a clear reproduction is to be built in this repository.
tools: Read, Grep, Glob, Bash, Edit, Write
---

Read AGENTS.md and the matching decisions (`make adr-find`) first. Follow the roles: decide in core, sequence in flow, IO in adapters. Fix every gate finding when it appears. Finish with `make check` green and report the changed files.
