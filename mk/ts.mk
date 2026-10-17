# TypeScript workspace (packages/core, packages/server, packages/web). Operator only.
TS_PROJECTS := tsconfig.json packages/core packages/server packages/web
# constraint: vitest prints 'skipped' or 'todo' in its summary when a test did not run; every collected test must run
VITEST = out=$$($(BIN)/vitest run --reporter=default $(1) 2>&1); rc=$$?; \
	if [ $$rc -ne 0 ] || printf '%s\n' "$$out" | grep -Eq 'Tests .*(skipped|todo)'; then printf '%s\n' "$$out" | tail -n 40; \
	echo "vitest.config.ts:1 [TS-TESTS-RAN] every collected test must run and pass"; exit 1; fi

setup-ts: ## TypeScript: install from pnpm-lock.yaml
	@pnpm install --frozen-lockfile --reporter=silent

fix-ts: ## TypeScript: format and autofix
	@$(BIN)/prettier --write --log-level warn .
	@$(BIN)/eslint --fix --max-warnings 0 . || true

lint-ts: ## TypeScript: format check, ESLint, house rules
	@$(BIN)/prettier --check --log-level warn . || { echo "[GATES-FORMAT] not formatted; run make fix"; exit 1; }
	@$(BIN)/eslint --max-warnings 0 .
	@for c in $(COMPONENTS); do $(GATE) lint --component $$c || exit 1; done

typecheck-ts: ## TypeScript: tsc strict for every project
	@for p in $(TS_PROJECTS); do $(BIN)/tsc -p $$p --pretty false || exit 1; done

test-ts: ## TypeScript: every Vitest test, none skipped
	@$(call VITEST,)

test-e2e: ## Browser end-to-end tests (Playwright, added with the first UI ticket)
	@test -d packages/web/e2e || { echo "test-e2e: no e2e tests yet"; exit 0; }
	@$(BIN)/playwright test -c packages/web/playwright.config.ts
