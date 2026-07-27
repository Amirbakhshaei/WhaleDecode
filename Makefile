.PHONY: install up down logs run-bot run-worker migrate seed lint typecheck test

install:
	poetry install

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

run-bot:
	poetry run whaledecode bot

run-worker:
	poetry run whaledecode worker

migrate:
	alembic upgrade head

seed:
	poetry run whaledecode seed

lint:
	ruff check src/ tests/

typecheck:
	mypy src/

test:
	pytest

test-unit:
	pytest tests/unit

test-graphs:
	pytest tests/graphs

pre-commit: lint typecheck test
