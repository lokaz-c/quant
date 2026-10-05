# Quant Portfolio Simulator
# Local targets use $(PYTHON); create a virtualenv first (see README).

PYTHON ?= python3

.PHONY: help run down logs install install-live dev test data results bench clean db-shell

help:
	@echo "make run           Start PostgreSQL + the app in Docker (http://localhost:8000)"
	@echo "make down          Stop the Docker stack and delete its database volume"
	@echo "make logs          Follow the app container's logs"
	@echo "make install       pip install -r requirements.txt"
	@echo "make install-live  pip install -r requirements-live.txt (adds alpaca-py)"
	@echo "make dev           Run the app locally on SQLite (http://localhost:8000)"
	@echo "make test          Run the test suite"
	@echo "make data          Regenerate data/sample_data.csv (synthetic, seed 42)"
	@echo "make results       Run the benchmark backtests and write docs/results.md"
	@echo "make bench         Time backtests and write docs/benchmark.md"
	@echo "make db-shell      psql into the Docker database"
	@echo "make clean         Remove caches and the local SQLite database"

run:
	docker compose up --build

down:
	docker compose down -v

logs:
	docker compose logs -f web

install:
	$(PYTHON) -m pip install -r requirements.txt

install-live:
	$(PYTHON) -m pip install -r requirements-live.txt

dev:
	$(PYTHON) init_db.py
	$(PYTHON) -m app.main

test:
	$(PYTHON) -m pytest

data:
	$(PYTHON) -m backtest_engine.data_loader

results:
	$(PYTHON) -m scripts.results

bench:
	$(PYTHON) -m scripts.bench

db-shell:
	docker compose exec db psql -U quant_user -d quant_db

clean:
	rm -rf .pytest_cache htmlcov .coverage quant.db
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
