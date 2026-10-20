# TypeScript workspace (every packages/<name> with a tsconfig.json). Operator only.
TS_PROJECTS := tsconfig.json $(patsubst %/tsconfig.json,%,$(sort $(wildcard packages/*/tsconfig.json)))
# constraint: --config pins ESLint and Prettier to the root config; without it both load a config next to each file as code
ESLINT = $(BIN)/eslint --config eslint.config.mjs
PRETTIER = $(BIN)/prettier --config .prettierrc.json
# constraint: vitest prints 'skipped' or 'todo' in its summary when a test did not run; every collected test must run
VITEST = out=$$($(BIN)/vitest run --reporter=default $(1) 2>&1); rc=$$?; \
	if [ $$rc -ne 0 ] || printf '%s\n' "$$out" | grep -Eq 'Tests .*(skipped|todo)'; then printf '%s\n' "$$out" | tail -n 40; \
	echo "vitest.config.ts:1 [TS-TESTS-RAN] every collected test must run and pass"; exit 1; fi

setup-ts: ## TypeScript: install from pnpm-lock.yaml
	@pnpm install --frozen-lockfile --reporter=silent

fix-ts: ## TypeScript: format and autofix
	@$(PRETTIER) --write --log-level warn .
	@$(ESLINT) --fix --max-warnings 0 . || true

lint-ts: ## TypeScript: format check, ESLint, house rules
	@$(PRETTIER) --check --log-level warn . || { echo "[GATES-FORMAT] not formatted; run make fix"; exit 1; }
	@$(ESLINT) --max-warnings 0 .
	@for c in $(COMPONENTS); do $(GATE) lint --component $$c || exit 1; done

typecheck-ts: ## TypeScript: tsc strict for every project
	@for p in $(TS_PROJECTS); do $(BIN)/tsc -p $$p --pretty false || exit 1; done

test-ts: ## TypeScript: every Vitest test, none skipped
	@$(call VITEST,)

# The stop gate runs make -s check-<component> for every component a change touches.
check-%:
	@test -f packages/$*/tsconfig.json || { echo "Makefile:1 [GATES-INFRA] check-$*: there is no component packages/$*"; exit 1; }
	@$(PRETTIER) --check --log-level warn packages/$* || { echo "[GATES-FORMAT] not formatted; run make fix"; exit 1; }
	@$(ESLINT) --max-warnings 0 packages/$*
	@$(GATE) lint --component $*
	@$(BIN)/tsc -p packages/$* --pretty false
	@$(call VITEST,packages/$*/)

test-e2e: ## Browser end-to-end tests (Playwright, added with the first UI ticket)
	@if [ -d packages/web/e2e ]; then $(BIN)/playwright test -c packages/web/playwright.config.ts; else echo "test-e2e: no e2e tests yet"; fi

test-acceptance: ## Slice acceptance specs in packages/web/e2e/scenario (heavy, not in the stop gate)
	@if [ -d packages/web/e2e/scenario ]; then $(BIN)/playwright test -c packages/web/playwright.config.ts packages/web/e2e/scenario/; else echo "test-acceptance: no scenario specs yet"; fi

# constraint: proof-verify takes PASS only from the runner's JSON report proof-out/stage-<s>.report.json (gates/proofs/README.md)
proof: ## Run the proof specs of one stage; writes proof-out/stage-<s>.report.json and proof-out/<id>.json: make proof STAGE=<1|2a|2b|3|4|5>
	@case "$(STAGE)" in 1|2a|2b|3|4|5) ;; *) echo "proof: STAGE must be one of 1 2a 2b 3 4 5"; exit 1;; esac
	@specs=$$(ls packages/web/e2e/proof/stage-$(STAGE)*.spec.ts 2>/dev/null); \
		test -n "$$specs" || { echo "packages/web/e2e/proof:1 [GATES-INFRA] proof: no spec for stage $(STAGE)"; exit 1; }; \
		rm -rf proof-out && mkdir proof-out && PROOF_OUT="$(CURDIR)/proof-out" \
		PLAYWRIGHT_JSON_OUTPUT_FILE="$(CURDIR)/proof-out/stage-$(STAGE).report.json" \
		$(BIN)/playwright test -c packages/web/playwright.config.ts --reporter=json $$specs
