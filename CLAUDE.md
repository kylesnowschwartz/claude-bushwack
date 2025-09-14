# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Claude Bushwack is a CLI/TUI tool for branching Claude Code conversations. The core concept is to allow users to create branches from existing Claude conversations by copying JSONL conversation files stored in `$HOME/.claude/projects/` and generating new UUIDs for the copies.

## Architecture

The application follows a dual-interface pattern:

- **CLI Interface** (`src/claude_bushwack/cli.py`): Click-based command-line interface with Rich formatting
- **TUI Interface** (`src/claude_bushwack/tui.py`): Textual-based terminal user interface

Both interfaces share common functionality but serve different use cases - CLI for scripting/automation, TUI for interactive browsing and management.

The entry points are:
- `claude-bushwack` (full command)
- `cb` (short alias)

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

## Project Status

This is currently a scaffold with placeholder implementations. The TODOS/ directory contains markdown files outlining the remaining PRD sections to complete before full implementation.
- Remember to consult @/Users/kyle/Code/Cloned-Sources/textual/CLAUDE.md for information on the textual framework
- Clean Separation of concerns:

  - core.py: Pure business logic, no UI dependencies, raises exceptions
  - cli.py: Handles Rich formatting, catches exceptions, provides user-friendly messages
  - tui.py: Handles Textual widgets, catches exceptions, provides visual feedback
  - exceptions.py: Shared exception definitions with structured data