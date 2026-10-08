# Local stack. Operator only.
up: ## Start the stack and wait until it is healthy (the host port is assigned per worktree)
	@test -f .env.db-password || { echo "create .env.db-password (git-ignored) first"; exit 1; }
	@docker compose up -d --wait

down: ## Stop the stack and drop its volumes
	@docker compose down -v

db-check db-schema: ## Schema drift check and dump (need postgres)
	@echo "$@: no database component configured"

