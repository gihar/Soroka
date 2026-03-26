.PHONY: lint format test check install-dev

lint:
	ruff check . --fix
	ruff format --check .

format:
	ruff format .
	ruff check . --fix

test:
	pytest tests/ -v

test-cov:
	pytest tests/ -v --cov=src --cov-report=term-missing

check: lint test

install-dev:
	pip install -r requirements-dev.txt
