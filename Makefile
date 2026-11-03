.PHONY: help setup install-hooks lint format typecheck audit test up down logs clean

help:
	@echo "Incident Investigation Agent - Developer Commands"
	@echo "  make setup          Install dependencies and git pre-commit hooks"
	@echo "  make install-hooks  Install pre-commit hooks (Ruff, Gitleaks, Mypy)"
	@echo "  make lint           Check code quality with Ruff"
	@echo "  make format         Auto-format code with Ruff"
	@echo "  make typecheck      Run Mypy static type analysis"
	@echo "  make audit          Run pip-audit vulnerability scanner"
	@echo "  make test           Run test suite in Docker"
	@echo "  make up             Start all services with Docker Compose"
	@echo "  make down           Stop all Docker Compose services"
	@echo "  make logs           View application container logs"

setup: install-hooks

install-hooks:
	pre-commit install --install-hooks -t pre-commit -t commit-msg

lint:
	docker compose run --rm test ruff check app tests

format:
	docker compose run --rm test ruff format app tests

typecheck:
	docker compose run --rm test mypy --config-file=pyproject.toml app

audit:
	docker compose run --rm test pip-audit -r requirements.txt

test:
	docker compose run --rm test

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f app

chaos-deadlock:
	python3 -m simulation.run_chaos --scenario deadlock

chaos-bad-deploy:
	python3 -m simulation.run_chaos --scenario bad-deployment

chaos-clear:
	python3 -m simulation.run_chaos --scenario clear

chaos-health:
	python3 -m simulation.run_chaos --scenario health

ui:
	docker compose up -d ui

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
