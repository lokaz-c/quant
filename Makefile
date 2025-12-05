# Makefile for Quant Portfolio Simulator

.PHONY: help build up down restart logs test clean generate-data run-example

help:
	@echo "Quant Portfolio Simulator - Available Commands"
	@echo "================================================"
	@echo "make build          - Build Docker images"
	@echo "make up             - Start all services"
	@echo "make down           - Stop all services"
	@echo "make restart        - Restart all services"
	@echo "make logs           - View application logs"
	@echo "make test           - Run test suite"
	@echo "make generate-data  - Generate sample market data"
	@echo "make run-example    - Run example backtest"
	@echo "make clean          - Clean up containers and volumes"
	@echo "make shell          - Open shell in web container"
	@echo "make db-shell       - Open PostgreSQL shell"

build:
	docker-compose build

up:
	docker-compose up -d
	@echo "Services started. Access at http://localhost:5000"

down:
	docker-compose down

restart:
	docker-compose restart

logs:
	docker-compose logs -f web

test:
	docker-compose exec web pytest -v

test-coverage:
	docker-compose exec web pytest --cov=backtest_engine --cov=app --cov-report=html

generate-data:
	docker-compose exec web python backtest_engine/data_loader.py

run-example:
	docker-compose exec web python run_example.py

clean:
	docker-compose down -v
	rm -rf __pycache__ */__pycache__ */*/__pycache__
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage

shell:
	docker-compose exec web /bin/bash

db-shell:
	docker-compose exec db psql -U quant_user -d quant_db

setup: build up generate-data
	@echo "Setup complete! Application is ready at http://localhost:5000"
