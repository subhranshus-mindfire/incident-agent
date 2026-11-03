.PHONY: help setup install-hooks lint format typecheck audit test up down logs chaos-deadlock chaos-bad-deploy chaos-cpu-burn chaos-traffic chaos-rollback chaos-clear chaos-health ui clean

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
	@echo "  make chaos-deadlock     Inject a DB deadlock fault into payment-api"
	@echo "  make chaos-bad-deploy   Inject a bad-deployment regression (DEP-101)"
	@echo "  make chaos-cpu-burn     Inject CPU saturation"
	@echo "  make chaos-traffic      Send requests so faults show in metrics (COUNT=50)"
	@echo "  make chaos-rollback     Call the rollback endpoint (fix a bad deployment)"
	@echo "  make chaos-health       Show payment-api health and active faults"
	@echo "  make chaos-clear        Clear all injected faults"

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

# Chaos simulation runs inside the app container, which reaches payment-api by its service name.
CHAOS = docker compose exec app python -m simulation.run_chaos --url http://payment-api:8080

chaos-deadlock:
	$(CHAOS) --scenario deadlock

chaos-bad-deploy:
	$(CHAOS) --scenario bad-deployment

chaos-cpu-burn:
	$(CHAOS) --scenario cpu-burn

chaos-traffic:
	$(CHAOS) --scenario traffic --traffic-count $(or $(COUNT),50)

chaos-rollback:
	$(CHAOS) --scenario rollback

chaos-clear:
	$(CHAOS) --scenario clear

chaos-health:
	$(CHAOS) --scenario health

ui:
	docker compose up -d ui

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
