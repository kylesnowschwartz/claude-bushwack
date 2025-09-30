"""Tests for TUI ProjectDirectoryTree.decode_path() method integration."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from claude_bushwack.core import ClaudeConversationManager
from claude_bushwack.tui import ProjectDirectoryTree


class TestTuiDecodePathIntegration:
  """Test the TUI's decode_path method integration with manager."""

  @pytest.fixture
  def temp_projects_dir(self):
    """Provide an isolated projects directory cleaned up after each test."""
    with TemporaryDirectory() as tmp:
      yield Path(tmp)

  @pytest.fixture
  def mock_manager(self, temp_projects_dir):
    """Create a manager with a temporary claude projects directory."""
    return ClaudeConversationManager(claude_projects_dir=temp_projects_dir)

  @pytest.fixture
  def project_tree(self, mock_manager):
    """Create a ProjectDirectoryTree with real manager."""
    tree = ProjectDirectoryTree.__new__(ProjectDirectoryTree)
    tree._manager = mock_manager
    tree._filter_text = ''
    tree._current_project_token = None
    return tree

  def test_returns_none_for_projects_root(self, temp_projects_dir, project_tree):
    """Should return None when given the claude projects root directory."""
    project_tree._manager.claude_projects_dir = temp_projects_dir

    result = project_tree.decode_path(temp_projects_dir)

    assert result is None

  def test_falls_back_to_directory_reconstruction(
    self, temp_projects_dir, project_tree
  ):
    """Should fall back to directory reconstruction when no JSONL files found."""
    # Create a project directory without conversation files
    project_dir = temp_projects_dir / '-Users-kyle-Code-simple-project'
    project_dir.mkdir(parents=True)

    project_tree._manager.claude_projects_dir = temp_projects_dir

    result = project_tree.decode_path(project_dir)

    # Should get a result from the fallback mechanism
    assert result is not None
    assert isinstance(result, Path)

  def test_returns_none_when_iterdir_fails(
    self, temp_projects_dir, project_tree, monkeypatch
  ):
    """Should gracefully fall back to lossy decoding when directory is inaccessible."""
    project_tree._manager.claude_projects_dir = temp_projects_dir
    project_dir = temp_projects_dir / '-Users-kyle-Code-test-project'
    project_dir.mkdir(parents=True)

    original_iterdir = Path.iterdir

    def fake_iterdir(self):
      if self == project_dir:
        raise PermissionError('Permission denied for test')
      return original_iterdir(self)

    monkeypatch.setattr(Path, 'iterdir', fake_iterdir)

    try:
      result = project_tree.decode_path(project_dir)
    finally:
      monkeypatch.undo()

    # With refactored helper, PermissionError is handled gracefully
    # and falls back to lossy decoding instead of returning None
    assert result is not None
    assert isinstance(result, Path)
    assert str(result) == '/Users/kyle/Code/test/project'

  def test_uses_manager_metadata_extraction(self, temp_projects_dir, project_tree):
    """Should use manager's metadata extraction for accurate path resolution."""
    project_dir = temp_projects_dir / '-Users-kyle-Code-hyphen-project'
    project_dir.mkdir(parents=True)

    # Create a JSONL file with metadata
    conversation_file = project_dir / 'test.jsonl'
    metadata = {
      'cwd': '/Users/kyle/Code/hyphen-project',
      'sessionId': 'test-session',
      'type': 'user',
    }
    conversation_file.write_text(json.dumps(metadata))

    project_tree._manager.claude_projects_dir = temp_projects_dir

    result = project_tree.decode_path(project_dir)

    # Should get the path from metadata via manager
    assert result == Path('/Users/kyle/Code/hyphen-project')
