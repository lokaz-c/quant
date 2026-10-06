# Quant Portfolio Simulator
# Local targets use $(PYTHON); create a virtualenv first (see README).

PYTHON ?= python3
# Throwaway PostgreSQL for `make test-pg` and `make sql-check`
PG_TEST_CONTAINER ?= quant-test-postgres
PG_TEST_PORT ?= 55432
PG_TEST_URL = postgresql://quant:quant@127.0.0.1:$(PG_TEST_PORT)/postgres
# pg_isready over TCP: during first-start initdb the image runs a temporary
# server on the Unix socket only, so a socket check can pass too early
PG_START = docker run -d --rm --name $(PG_TEST_CONTAINER) -e POSTGRES_USER=quant -e POSTGRES_PASSWORD=quant \
	-p 127.0.0.1:$(PG_TEST_PORT):5432 postgres:15-alpine >/dev/null && \
	until docker exec $(PG_TEST_CONTAINER) pg_isready -h 127.0.0.1 -U quant -q; do sleep 1; done
PG_STOP = docker stop $(PG_TEST_CONTAINER) >/dev/null

.PHONY: help run down logs install install-live dev frontend frontend-dev test-frontend migrate test test-pg sql-check data results bench clean db-shell

help:
	@echo "make run           Start PostgreSQL + the app in Docker (http://localhost:8000)"
	@echo "make down          Stop the Docker stack and delete its database volume"
	@echo "make logs          Follow the app container's logs"
	@echo "make install       pip install -r requirements.txt"
	@echo "make install-live  pip install -r requirements-live.txt (adds alpaca-py)"
	@echo "make dev           Build the frontend, run the app locally on SQLite (http://localhost:8000)"
	@echo "make frontend      npm ci (when the lockfile changes) and build frontend/dist (needs Node 24)"
	@echo "make frontend-dev  Vite dev server with hot reload (http://localhost:5173); run make dev too"
	@echo "make test-frontend Type-check and test the frontend (vitest)"
	@echo "make migrate       alembic upgrade head on DATABASE_URL (default sqlite:///quant.db)"
	@echo "make test          Run the test suite (PostgreSQL tests skip)"
	@echo "make test-pg       Run the test suite with a throwaway PostgreSQL 15 container"
	@echo "make sql-check     Compare the SQL window-function metrics with Python on the benchmark runs"
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

dev: frontend
	$(PYTHON) init_db.py
	$(PYTHON) -m app.main

frontend/node_modules: frontend/package-lock.json
	cd frontend && npm ci
	touch frontend/node_modules

frontend: frontend/node_modules
	cd frontend && npm run build

frontend-dev: frontend/node_modules
	cd frontend && npm run dev

test-frontend: frontend/node_modules
	cd frontend && npm run typecheck && npm test

migrate:
	$(PYTHON) -m alembic upgrade head

test:
	$(PYTHON) -m pytest

test-pg:
	@$(PG_START)
	QUANT_TEST_POSTGRES_URL=$(PG_TEST_URL) QUANT_REQUIRE_POSTGRES=1 $(PYTHON) -m pytest; \
		status=$$?; $(PG_STOP); exit $$status

sql-check:
	@$(PG_START)
	DATABASE_URL=$(PG_TEST_URL) $(PYTHON) -m scripts.sql_check; status=$$?; $(PG_STOP); exit $$status

data:
	$(PYTHON) -m backtest_engine.data_loader

results:
	$(PYTHON) -m scripts.results

bench:
	$(PYTHON) -m scripts.bench

db-shell:
	docker compose exec db psql -U quant_user -d quant_db

clean:
	rm -rf .pytest_cache htmlcov .coverage quant.db frontend/dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
