# Repository Guidelines

## Project Structure & Module Organization
Application code lives in `src/claude_bushwack/`: `cli.py` exposes the CLI surface, `core.py` holds conversation management, `tui.py` renders the Textual interface, and `exceptions.py` centralizes errors. Tests mirror this layout beneath `tests/`, with integration-style checks in `tests/tui/`. Deterministic fixtures and sample JSONL transcripts sit in `tests/assets/`; add new fixtures there so the suite stays self-contained.

## Build, Test, and Development Commands
Run `poetry install` (or `make install`) to set up dependencies. Execute the CLI with `poetry run claude-bushwack`; append `tui` to launch the interface. `make test` drives the full pytest suite via Poetry, while `make lint` runs Ruff lint/format checks. Use `make format` to auto-apply Ruff fixes, and `make dev` for a full dev bootstrap.

## Coding Style & Naming Conventions
Python modules use 2-space indentation and an 88-character width, enforced by Ruff. Prefer single quotes for strings and avoid trailing commas when formatting through `poetry run ruff format`. Follow standard naming: modules and packages in `snake_case`, classes in `PascalCase`, functions, variables, and fixtures in `snake_case`. Keep CLI verbs first (`branch create`) and surface-friendly.

## Testing Guidelines
Write pytest tests that mirror the source tree (`tests/tui/test_bushwack_app.py`, etc.). Name files `test_<module>.py` and functions `test_<behavior>`. Use the provided fixtures in `tests/conftest.py`, including `conversation_factory` and the deterministic `sample_conversation` asset. Before commiting or completing a task, run `make test`; add regression coverage when introducing new TUI states or CLI flows.

## Commit & Pull Request Guidelines
Use Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`) with imperative summaries under 72 characters. Group related changes into focused commits. PRs should summarize the change, link relevant issues, and include evidence of testing (command output or screenshots for TUI updates). Call out any CLI command additions or interface adjustments so downstream automation can keep pace.

## Security & Configuration Tips
Target Python 3.9+ (tested on 3.12). Do not commit tokens or live conversation transcripts; sanitize samples before storing them under `tests/assets/`. Regenerate `poetry.lock` only when deliberately updating dependencies, and review new Rich/Textual extensions for compatibility.
