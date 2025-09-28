# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Claude Bushwack is a CLI/TUI tool for branching Claude Code conversations. The core concept is to allow users to create branches from existing Claude conversations by copying JSONL conversation files stored in `$HOME/.claude/projects/` and generating new UUIDs for the copies.

## Architecture

The application follows a dual-interface pattern:

- **CLI Interface** (`src/claude_bushwack/cli.py`): Click-based command-line interface with Rich formatting
- **TUI Interface** (`src/claude_bushwack/tui.py`): Textual-based terminal user interface

Both interfaces share common functionality but serve different use cases - CLI for scripting/automation, TUI for interactive browsing and management.

The entry point is:
- `claude-bushwack`

## Development Commands

```bash
# Setup
make install          # Install dependencies via Poetry
make dev             # Install with dev dependencies

# Testing and Quality
make test            # Run pytest test suite
pytest tests/test_cli.py::test_branch_command  # Run single test
make lint            # Check code quality (ruff + black)
make format          # Auto-format code
make clean           # Remove Python cache files

# Running
make tui             # Launch TUI interface
make run             # Run CLI (shows help)
poetry run claude-bushwack branch <session-id>  # Direct CLI usage
```

## Key Implementation Details

**Claude Conversation Storage**: Conversations are stored as JSONL files in `$HOME/.claude/projects/-Users-username-path-to-project-dir/uuid-12345-xyz.jsonl`

**Branching Strategy**: Copy existing conversation files and generate new UUIDs while maintaining project directory structure and ensuring uniqueness.

**TUI Layout**: Uses Textual's container system with sidebar (conversation list) and main content area (actions/details).

**Development Stack**:
- Poetry for dependency management
- Textual ^0.47.0 for TUI
- Click ^8.0.0 for CLI
- Rich ^13.0.0 for formatted output
- Black + Ruff for code quality

- Remember to consult @/Users/kyle/Code/Cloned-Sources/textual/CLAUDE.md for information on the textual framework
- Clean Separation of concerns:

  - core.py: Pure business logic, no UI dependencies, raises exceptions
  - cli.py: Handles Rich formatting, catches exceptions, provides user-friendly messages
  - tui.py: Handles Textual widgets, catches exceptions, provides visual feedback
  - exceptions.py: Shared exception definitions with structured data
  - etc.

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

