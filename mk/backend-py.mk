# backend-py: Python component. Operator only.
PY_DIR := backend
UV := cd $(PY_DIR) && uv
# constraint: -c pins the operator's pytest.ini; -o addopts= and the empty variables drop options from any other source
PYTEST = out=$$(cd $(PY_DIR) && PYTEST_ADDOPTS= PYTEST_PLUGINS= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -c pytest.ini \
	-o addopts= -p no:cacheprovider -q $(1) 2>&1); rc=$$?; last=$$(printf '%s\n' "$$out" | grep . | tail -n 1); \
	if [ $$rc -ne 0 ] || ! printf '%s\n' "$$last" | grep -Eq '^=* *[0-9]+ passed(, [0-9]+ warnings?)? in [0-9.]+s'; then printf '%s\n' "$$out"; \
	echo "$(PY_DIR)/pytest.ini:1 [PY-TESTS-RAN] the run ended with '$$last'; every collected test must run and pass"; exit 1; fi
# constraint: ruff names unformatted files as 'Would reformat: f' or in a diff header '--> f:l:c', depending on the output mode
FORMAT_CHECK_PY = out=$$($(UV) run ruff format --check . 2>&1) || { files=$$(printf '%s\n' "$$out" \
	| sed -nE 's/^Would reformat: (.*)$$/\1/p; s/^ *--> ([^:]+):[0-9]+:[0-9]+$$/\1/p' | sort -u); \
	if [ -n "$$files" ]; then for f in $$files; do echo "$(PY_DIR)/$$f:1 [GATES-FORMAT] not formatted; run make fix"; done; \
	else printf '%s\n' "$$out"; fi; exit 1; }

setup-backend-py: ## Python: install from uv.lock (creates it on first run)
	@$(UV) sync $$(test -f uv.lock && echo --locked)

fix-backend-py: ## Python: format
	@$(UV) run ruff format --quiet .

lint-backend-py: ## Python: format check, ruff, import contracts, house rules
	@$(FORMAT_CHECK_PY)
	@$(UV) lock --check --quiet
	@out=$$($(UV) run ruff check --output-format concise . 2>&1) || { printf '%s\n' "$$out"; exit 1; }; \
	if printf '%s\n' "$$out" | grep -q 'has no effect because preview is not enabled'; then printf '%s\n' "$$out"; \
	echo "ruff.toml selects a preview rule without preview, so the rule never runs; the operator fixes ruff.toml"; exit 1; fi
	@out=$$($(UV) run lint-imports --config .importlinter 2>&1) || { printf '%s\n' "$$out" | sed -n '/^Broken contracts/,$$p' | grep . \
		|| printf '%s\n' "$$out"; exit 1; }
	@$(GATE) lint --component backend-py

typecheck-backend-py: ## Python: pyright strict
	@out=$$($(UV) run pyright 2>&1) || { printf '%s\n' "$$out"; exit 1; }

test-core-backend-py: ## Python: offline core tests
	@$(call PYTEST,tests/test_*_core.py)

test-backend-py: ## Python: behaviour tests
	@$(call PYTEST,tests)

check-backend-py: lint-backend-py typecheck-backend-py test-core-backend-py
