# Anyq - common tasks. Replaces the macOS-only start.sh.
#
# On Windows run these through Git Bash, or call the underlying command
# directly (each recipe is a single portable line).

PYTHON ?= .venv/Scripts/python.exe
COMPOSE ?= docker compose

.DEFAULT_GOAL := help
.PHONY: help up down restart logs ps build test test-all lint fmt clean venv seed seed-check seed-preview

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up:  ## Start the whole stack (build if needed)
	$(COMPOSE) up --build -d
	@echo "Frontend: http://localhost:$${FRONTEND_PORT:-3000}"

down:  ## Stop the stack (volumes are kept)
	$(COMPOSE) down --remove-orphans

restart:  ## Restart every service
	$(COMPOSE) restart

ps:  ## Show service status
	$(COMPOSE) ps

logs:  ## Tail logs of all services (make logs S=agent for one)
	$(COMPOSE) logs -f $(S)

build:  ## Rebuild images without starting
	$(COMPOSE) build

test:  ## Run the tests that need no docker (backend + agent + curated content)
	$(PYTHON) -m pytest tests/backend tests/agent tests/curated

test-all:  ## Run everything, including the e2e/ui suites (needs `make up`)
	ANYQ_STACK_UP=1 $(PYTHON) -m pytest

lint:  ## Lint python and the frontend
	$(PYTHON) -m ruff check backend agent exporter scripts tests
	cd frontend && npm run lint

fmt:  ## Auto-format python
	$(PYTHON) -m ruff format backend agent exporter scripts tests
	$(PYTHON) -m ruff check --fix backend agent exporter scripts tests

venv:  ## Create the local venv used by the test tasks
	python -m venv .venv
	$(PYTHON) -m pip install -U pip
	$(PYTHON) -m pip install -r backend/requirements.txt -r requirements-dev.txt

seed-check:  ## Validate the curated content tree (no docker, no rendering)
	$(PYTHON) scripts/seed_library.py --check

seed-preview:  ## Render every curated language for review, publish nothing
	$(PYTHON) scripts/seed_library.py --preview

seed:  ## Render and publish the approved curated languages
	$(PYTHON) scripts/seed_library.py

clean:  ## Remove local build artefacts and caches
	rm -rf frontend/dist .pytest_cache .ruff_cache .artifacts/*
	find . -name __pycache__ -type d -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
