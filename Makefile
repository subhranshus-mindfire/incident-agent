.PHONY: help setup install-hooks lint format test up down logs clean

help:
	@echo "Available commands:"
	@echo "  make setup          Install dependencies and git pre-commit hooks"
	@echo "  make install-hooks  Install pre-commit hooks"
	@echo "  make lint           Check code quality with Ruff"
	@echo "  make format         Auto-format code with Ruff"
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

test:
	docker compose run --rm test

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f app

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
