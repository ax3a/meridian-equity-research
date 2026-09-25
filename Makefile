# Meridian developer entry points (Linux/macOS/WSL).
#
# Windows/PowerShell users: every target here has a line-for-line equivalent in scripts/*.ps1
# (e.g. `make setup` <-> `scripts\setup.ps1`) — see that directory for the Windows-native path.
#
# Targets are kept thin on purpose: each one just runs the same handful of commands a developer
# would type by hand, so there is nothing "magic" hidden behind `make`.

.DEFAULT_GOAL := help
.PHONY: help setup dev test test-backend test-frontend lint lint-backend lint-frontend \
        format format-backend format-frontend docker-up docker-up-deps docker-down migrate eval

BACKEND_DIR := backend
FRONTEND_DIR := frontend
VENV_BIN := $(BACKEND_DIR)/.venv/bin
PYTHON := $(VENV_BIN)/python

help:
	@echo "Meridian developer commands:"
	@echo "  make setup        - create backend venv + install deps, npm install, copy .env"
	@echo "  make dev          - run backend (uvicorn --reload) and frontend (next dev) together"
	@echo "  make test         - run backend pytest and frontend vitest"
	@echo "  make lint         - ruff check (backend) + eslint/tsc (frontend)"
	@echo "  make format       - ruff format (backend) + eslint --fix (frontend)"
	@echo "  make migrate      - alembic upgrade head against DATABASE_URL"
	@echo "  make docker-up    - docker compose --profile full up -d --build (full stack)"
	@echo "  make docker-up-deps - docker compose up -d db redis (datastores only, for local dev)"
	@echo "  make docker-down  - docker compose --profile full down"
	@echo "  make eval         - run the evaluation harness (backend/evals)"

setup:
	test -f .env || cp .env.example .env
	@ver="$$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)"; \
	if [ "$$ver" != "3.12" ]; then \
		echo "python3 on PATH reports '$$ver', not 3.12 (backend requires >=3.12) - aborting."; \
		echo "Install Python 3.12 (or point python3 at it) and re-run 'make setup'."; \
		exit 1; \
	fi
	python3 -m venv $(BACKEND_DIR)/.venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e "$(BACKEND_DIR)[dev,embeddings,otel]"
	cd $(FRONTEND_DIR) && npm install
	test -f $(FRONTEND_DIR)/.env.local || cp $(FRONTEND_DIR)/.env.local.example $(FRONTEND_DIR)/.env.local

dev:
	@echo "Starting backend (http://localhost:8000) and frontend (http://localhost:3000)..."
	@trap 'kill 0' EXIT; \
	( cd $(BACKEND_DIR) && .venv/bin/python -m uvicorn meridian.api.app:create_app --factory --reload \
	  --host 0.0.0.0 --port 8000 ) & \
	( cd $(FRONTEND_DIR) && npm run dev ) & \
	wait

test: test-backend test-frontend

test-backend:
	cd $(BACKEND_DIR) && .venv/bin/python -m pytest -q

test-frontend:
	cd $(FRONTEND_DIR) && npm run test

lint: lint-backend lint-frontend

lint-backend:
	cd $(BACKEND_DIR) && .venv/bin/python -m ruff check src tests
	cd $(BACKEND_DIR) && .venv/bin/python -m ruff format --check src tests

lint-frontend:
	cd $(FRONTEND_DIR) && npm run lint
	cd $(FRONTEND_DIR) && npm run typecheck

format: format-backend format-frontend

format-backend:
	cd $(BACKEND_DIR) && .venv/bin/python -m ruff format src tests
	cd $(BACKEND_DIR) && .venv/bin/python -m ruff check --fix src tests

format-frontend:
	cd $(FRONTEND_DIR) && npx eslint . --fix

migrate:
	cd $(BACKEND_DIR) && .venv/bin/python -m alembic upgrade head

docker-up:
	docker compose --profile full up -d --build

docker-up-deps:
	docker compose up -d db redis

docker-down:
	docker compose --profile full down

eval:
	@if [ -d evals ]; then \
		cd $(BACKEND_DIR) && .venv/bin/python -m evals.run; \
	else \
		echo "evals/ does not exist yet (Task 14) - nothing to run."; \
	fi
