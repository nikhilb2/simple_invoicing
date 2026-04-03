SHELL := /bin/bash

.PHONY: help dev prod down logs seed migrate migrate-up migrate-down migrate-down-all migrate-status migrate-create backend-shell frontend-shell test lint

help:
	@echo "Available commands:"
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
	docker-compose --profile dev up -d

prod:
	docker-compose --profile prod up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

seed:
	docker-compose --profile dev exec backend-dev python seed_admin.py

migrate: migrate-up

migrate-up:
	docker-compose --profile dev exec backend-dev python migrate.py up

migrate-down:
	docker-compose --profile dev exec backend-dev python migrate.py down

migrate-down-all:
	docker-compose --profile dev exec backend-dev python migrate.py down --all

migrate-status:
	docker-compose --profile dev exec backend-dev python migrate.py status

migrate-create:
	docker-compose --profile dev exec backend-dev python migrate.py create "$(name)"

backend-shell:
	docker-compose --profile dev exec backend-dev /bin/sh

frontend-shell:
	docker-compose --profile dev exec frontend-dev /bin/sh

test:
	docker-compose --profile dev exec frontend-dev npm run test:e2e

lint:
	docker-compose --profile dev exec backend-dev python -m compileall .
	docker-compose --profile dev exec frontend-dev npm run build
