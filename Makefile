.PHONY: install test lint format clean run tui dev

install:
	poetry install

test:
	poetry run pytest

lint:
	poetry run ruff check src/ tests/
	poetry run ruff format --check src/ tests/

format:
	poetry run ruff format src/ tests/
	poetry run ruff check --fix src/ tests/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -name "*.pyc" -delete

run:
	poetry run claude-bushwack

tui:
	poetry run claude-bushwack tui

dev:
	poetry install --with dev
