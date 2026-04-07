SHELL := /bin/bash
COMPOSE := $(shell command -v docker-compose 2>/dev/null || echo "docker compose")

.PHONY: help dev prod down logs seed migrate migrate-up migrate-down migrate-down-all migrate-status migrate-create backend-shell frontend-shell test lint build install install-backend install-frontend

help:
	@echo "Available commands:"
	@echo "  make build            - Rebuild dev images (use after changing Dockerfiles or system deps)"
	@echo "  make install          - Install backend + frontend deps in running containers"
	@echo "  make install-backend  - pip install -r requirements.txt in running backend-dev"
	@echo "  make install-frontend - npm install in running frontend-dev"
	@echo "  make dev              - Start development profile (backend-dev, frontend-dev, db)"
	@echo "  make prod             - Start production profile (backend, frontend, db)"
	@echo "  make down             - Stop all containers"
	@echo "  make logs             - Tail logs for all services"
	@echo "  make seed             - Seed default admin user"
	@echo "  make migrate          - Run all pending migrations (alias for migrate-up)"
	@echo "  make migrate-up       - Run all pending migrations"
	@echo "  make migrate-down     - Roll back last migration"
	@echo "  make migrate-down-all - Roll back all migrations"
	@echo "  make migrate-status   - Show migration status"
	@echo "  make migrate-create name=<name> - Create a new migration file"
	@echo "  make backend-shell    - Open shell in backend-dev container"
	@echo "  make frontend-shell   - Open shell in frontend-dev container"
	@echo "  make test             - Run frontend e2e tests"
	@echo "  make lint             - Run lightweight backend/frontend checks"

dev:
	$(COMPOSE) --profile dev up -d

prod:
	$(COMPOSE) --profile prod up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

seed:
	$(COMPOSE) --profile dev exec backend-dev python seed_admin.py

migrate: migrate-up

migrate-up:
	$(COMPOSE) --profile dev exec backend-dev python migrate.py up

migrate-down:
	$(COMPOSE) --profile dev exec backend-dev python migrate.py down

migrate-down-all:
	$(COMPOSE) --profile dev exec backend-dev python migrate.py down --all

migrate-status:
	$(COMPOSE) --profile dev exec backend-dev python migrate.py status

migrate-create:
	$(COMPOSE) --profile dev exec backend-dev python migrate.py create "$(name)"

backend-shell:
	$(COMPOSE) --profile dev exec backend-dev /bin/sh

frontend-shell:
	$(COMPOSE) --profile dev exec frontend-dev /bin/sh

test:
	$(COMPOSE) --profile dev exec frontend-dev npm run test:e2e

lint:
	$(COMPOSE) --profile dev exec backend-dev python -m compileall .
	$(COMPOSE) --profile dev exec frontend-dev npm run build

build:
	$(COMPOSE) --profile dev build backend-dev frontend-dev

install: install-backend install-frontend

install-backend:
	$(COMPOSE) --profile dev exec backend-dev pip install -r requirements.txt

install-frontend:
	$(COMPOSE) --profile dev exec frontend-dev npm install
