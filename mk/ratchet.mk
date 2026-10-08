# Ratchet: agents may add gates, never weaken them. Operator only.
check-repo: ratchet-guard

ratchet-guard: ## New rules only; changed or deleted rules are red
	@$(GATE) guard
