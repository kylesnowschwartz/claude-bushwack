# Repository Guidelines

## Project Structure & Module Organization
Source code lives under `src/claude_bushwack/`. The CLI entrypoint is `cli.py`, the branching logic is in `core.py`, UI widgets reside in `tui.py`, and shared errors are defined in `exceptions.py`. Tests mirror the package layout in `tests/`, with `test_cli.py` covering the command surface. Ancillary tooling (Makefile, Poetry config) sits at the repository root; keep new assets in `assets/` if introduced.

## Build, Test, and Development Commands
Install dependencies with `poetry install` or `make install`. Use `poetry run claude-bushwack` (or the short alias `poetry run cb`) to execute the CLI; append `tui` to launch the Textual interface. `make test` runs the full pytest suite via Poetry. `make lint` performs Ruff lint and format checks, while `make format` auto-formats and fixes lint violations. For a fresh dev setup, `make dev` installs main and dev dependencies.

## Coding Style & Naming Conventions
All Python files target 2-space indentation and 88-character lines, enforced by Ruff (`pyproject.toml`). Prefer single quotes for strings and avoid trailing commas when formatting with `poetry run ruff format`. Follow standard Python naming: modules and packages in `snake_case`, classes in `PascalCase`, functions and variables in `snake_case`. Keep CLI command names concise and verbs first (e.g., `branch create`).

## Testing Guidelines
Write tests with pytest and place them beneath `tests/`, mirroring the package path. Name files `test_<module>.py` and functions `test_<behavior>`. When adding CLI scenarios, use fixtures to simulate command invocations and branch trees. Run `make test` locally before opening a pull request; add regression tests that cover new branching states or TUI behaviors.

## Commit & Pull Request Guidelines
Prefer Conventional Commit prefixes (`feat:`, `fix:`, `docs:`). Start summaries with an imperative verb and keep them under 72 characters. For pull requests, include: overview of the change, testing evidence (`make test` output or screenshots for TUI updates), and links to related issues. Flag any CLI interface changes in the description so downstream scripts can be updated.

## Environment & Security Notes
The project assumes Python 3.9+. Avoid committing API tokens or conversation transcripts; use `.env` files ignored by git. Review dependencies when adding new Textual or Rich extensions, and run `poetry lock` only when intentionally updating the lockfile.
