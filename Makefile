.DEFAULT_GOAL := help

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' Makefile | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

dev: ## Create .venv and sync deps
	uv sync

migrate: ## Apply platform migrations (010+) to the database
	uv run python -m api.migrate

api: ## Run the API with reload
	uv run uvicorn api.main:app --reload --port 8000

web: ## Run the web dev server
	cd web && npm run dev

install-web: ## Install web dependencies
	cd web && npm install

test: ## Run tests
	uv run pytest -q

lint: ## Lint python
	uv run ruff check .

.PHONY: help dev migrate api web install-web test lint
