"""Tests for CLI interface."""

from click.testing import CliRunner

from claude_bushwack.cli import main


def test_main_help():
  """Test main command help."""
  runner = CliRunner()
  result = runner.invoke(main, ['--help'])
  assert result.exit_code == 0
  assert 'Claude Bushwack' in result.output


def test_branch_command():
  """Test branch command with invalid session ID."""
  runner = CliRunner()
  result = runner.invoke(main, ['branch', 'invalid-session-id'])
  # Should fail with invalid UUID format error
  assert result.exit_code != 0
  assert 'Invalid UUID format' in result.output


def test_list_command():
  """Test list command."""
  runner = CliRunner()
  result = runner.invoke(main, ['list'])
  assert result.exit_code == 0
  # Should either find conversations or show "No conversations found"
  assert (
    'Found' in result.output and 'conversation(s)' in result.output
  ) or 'No conversations found' in result.output
