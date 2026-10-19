# Hooks and CI call only these verbs. Operator only.
SHELL := /bin/bash
GATE := python3 -I -B gates/gate.py
BIN := node_modules/.bin
COMPONENTS := core server web
.DEFAULT_GOAL := help
.PHONY: help setup setup-gates doctor fix lint typecheck test test-core test-e2e check check-repo dev \
	decisions adr-find adr-new sync gates-selftest gates-bench controls-baseline controls-anchor suppress-baseline

-include mk/*.mk

help: ## List every verb
	@grep -hE '^[a-z0-9][a-z0-9 -]*:.*## ' $(MAKEFILE_LIST) | sed -E 's/:[^#]*## /\t/' | sort

setup: setup-gates setup-ts ## Install every toolchain from its lockfile
	@$(GATE) mark-setup
	@echo "RESULT: PASS setup"

setup-gates: ## Check the tools the gates need (never installs silently)
	@command -v python3 >/dev/null || { echo "python3 missing"; exit 1; }
	@command -v ast-grep >/dev/null || { echo "ast-grep missing: see README.md, section Prerequisites"; exit 1; }
	@command -v node >/dev/null || { echo "node missing: install the version in .node-version"; exit 1; }
	@command -v pnpm >/dev/null || { echo "pnpm missing: corepack enable"; exit 1; }

doctor: ## Check hooks, manifest, tools and AGENTS.md
	@$(GATE) doctor

fix: fix-ts ## Apply every formatter and autofix

lint: lint-ts check-repo ## Format check, linters, house rules, repo rules, drift

typecheck: typecheck-ts ## Strict type checks

test-core: test-ts ## Offline unit and behaviour tests (no network, no TeX)

test: test-ts ## Every offline test

check: ## What the stop gate and CI run: lint, typecheck, tests
	@$(MAKE) -s lint typecheck test-core && echo "RESULT: PASS check"

check-repo: ## Repo rules, drift checks and the sync check
	@$(GATE) check-repo >/dev/null || $(GATE) check-repo
	@$(GATE) drift >/dev/null || $(GATE) drift

dev: ## Start server and web dev servers on 127.0.0.1
	@trap 'kill 0' EXIT; node --watch packages/server/src/main.ts & $(BIN)/vite packages/web

decisions: ## Regenerate decisions/index.md
	@$(GATE) adr index

adr-find: ## Find decisions: make adr-find TAG=<tag> Q=<text>
	@$(GATE) adr find --tag "$(TAG)" --query "$(Q)"

adr-new: ## Create the next ADR (ask the operator first): make adr-new TITLE="..."
	@$(GATE) adr new --title "$(TITLE)"

sync: ## Operator: regenerate settings.json, rules, CODEOWNERS and rule notes from gates/
	@$(GATE) sync

gates-selftest: ## Prove that every gate turns red on its fixture
	@$(GATE) selftest

gates-bench: ## Time the in-turn checks
	@$(GATE) bench

controls-baseline: ## Operator: write gates/controls.sha256 after changing a control file
	@$(GATE) baseline

controls-anchor: ## Operator, without a remote: point refs/gates/baseline at the committed baseline
	@$(GATE) anchor

suppress-baseline: ## Operator: accept the current inline suppressions: make suppress-baseline REASON=<issue-url>
	@$(GATE) suppress-baseline --reason "$(REASON)"
