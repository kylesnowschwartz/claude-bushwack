# Claude Bushwack

CLI/TUI tool for branching Claude Code conversations.

## Installation

Choose the workflow that matches how you like to manage Python CLIs. Each
method installs the `claude-bushwack` entry point defined in `pyproject.toml`.

### pip (virtual environment or system Python)

If you are working inside an existing virtual environment, install the package
directly:

```bash
pip install claude-bushwack  # once published to PyPI
```

If you prefer to build from source, clone this repository first and install from
the local checkout:

```bash
git clone git@github.com:kylesnowschwartz/claude-bushwack.git
cd claude-bushwack
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

### pipx (isolated global install)

[`pipx`](https://github.com/pypa/pipx) keeps CLI tools isolated while exposing
their binaries on your `$PATH`:

```bash
pipx install claude-bushwack
# or, after cloning the repository
pipx install .
```

### uv (Astral's fast package manager)

[`uv`](https://docs.astral.sh/uv/) can install the wheel from PyPI or straight
from source while managing its own environment:

```bash
uv tool install claude-bushwack
# or, after cloning the repository
uv tool install --from . claude-bushwack
```

### Poetry (developer setup)

For local development, continue using Poetry to create an editable install:

```bash
poetry install
```

#### Optional shell alias

If you would like a shorter command locally, add an alias in your shell profile:

```bash
echo "alias cb='claude-bushwack'" >> ~/.bashrc  # adapt for your shell
```

## Usage

### CLI Commands

### Short alias

## Development
