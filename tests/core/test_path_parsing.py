"""Tests for path parsing, encoding/decoding, and metadata extraction."""

import builtins
import json
from pathlib import Path


from claude_bushwack.core import ClaudeConversationManager


class TestPathEncodingAndRoundTrips:
  """Test path encoding and round-trip conversions."""

  def test_plain_paths_round_trip(self):
    """Plain paths without hyphens should round-trip correctly."""
    manager = ClaudeConversationManager()

    safe_paths = [
      '/Users/kyle/Code/simple',
      '/Users/kyle/Code/project/subdir',
      '/Users/kyle/Code/deeply/nested/structure/works',
      '/tmp/test',
    ]

    for original_path in safe_paths:
      original = Path(original_path)
      encoded = manager._path_to_project_dir(original)
      reconstructed = manager._project_dir_to_path(encoded)

      assert str(reconstructed) == str(
        original
      ), f'Safe path failed round-trip: {original} -> {reconstructed}'

  def test_hidden_paths_round_trip(self):
    """Hidden directories should use double-dash encoding and round-trip correctly."""
    manager = ClaudeConversationManager()

    hidden_paths = [
      '/Users/kyle/.config',
      '/Users/kyle/.ssh/keys',
      '/Users/kyle/.local/share/app',
    ]

    for original_path in hidden_paths:
      original = Path(original_path)
      encoded = manager._path_to_project_dir(original)
      reconstructed = manager._project_dir_to_path(encoded)

      assert '--' in encoded, f'Hidden directory should use double-dash: {encoded}'
      assert str(reconstructed) == str(
        original
      ), f'Hidden directory failed round-trip: {original} -> {reconstructed}'

  def test_hyphenated_paths_round_trip(self):
    """Hyphenated project paths should round-trip via cache."""
    manager = ClaudeConversationManager()

    realistic_patterns = [
      '/Users/kyle/Code/my-awesome-project',
      '/Users/kyle/Code/react-native-app',
      '/Users/kyle/Code/company-name/project-name',
      '/Users/kyle/Code/main-project/feature-branch.worktree',
    ]

    for original_path in realistic_patterns:
      original = Path(original_path)
      encoded = manager._path_to_project_dir(original)
      reconstructed = manager._project_dir_to_path(encoded)

      assert str(reconstructed) == str(
        original
      ), f'Hyphenated path failed round-trip: {original} -> {reconstructed}'

  def test_directory_token_encoding(self):
    """Test the specific encoding patterns used by Claude."""
    manager = ClaudeConversationManager()

    encoding_tests = [
      ('/Users/kyle', '-Users-kyle'),
      ('/tmp/test', '-tmp-test'),
      ('/Users/kyle/.config', '-Users-kyle--config'),
      ('/Users/kyle/.config/some-app', '-Users-kyle--config-some-app'),
      ('/Users/kyle/Code/project.worktree', '-Users-kyle-Code-project.worktree'),
    ]

    for original_path, expected_encoding in encoding_tests:
      original = Path(original_path)
      encoded = manager._path_to_project_dir(original)

      assert (
        encoded == expected_encoding
      ), (
        f'Encoding mismatch: {original_path} -> {encoded}, expected {expected_encoding}'
      )


class TestMetadataExtraction:
  """Test JSONL metadata parsing functionality."""

  def test_extracts_from_cwd_field(self, tmp_path):
    """Should extract project path from 'cwd' field in JSONL metadata."""
    manager = ClaudeConversationManager()

    jsonl_file = tmp_path / 'test.jsonl'
    metadata = {
      'cwd': '/Users/kyle/Code/my-projects/claude-bushwack',
      'sessionId': 'test-session',
      'type': 'user',
    }

    jsonl_file.write_text(json.dumps(metadata) + '\n')

    result = manager._get_project_path_from_jsonl(jsonl_file)
    assert result == '/Users/kyle/Code/my-projects/claude-bushwack'

  def test_extracts_from_alternative_fields(self, tmp_path):
    """Should extract project path from alternative fields like projectPath, workspaceRoot."""
    manager = ClaudeConversationManager()

    test_cases = [
      ('projectPath', '/Users/kyle/Code/some-other-project'),
      ('workspaceRoot', '/Users/kyle/Code/workspace-project'),
      ('workingDirectory', '/Users/kyle/Code/working-dir'),
    ]

    for field_name, expected_path in test_cases:
      jsonl_file = tmp_path / f'test_{field_name}.jsonl'
      metadata = {
        field_name: expected_path,
        'sessionId': 'test-session',
        'type': 'user',
      }

      jsonl_file.write_text(json.dumps(metadata) + '\n')

      result = manager._get_project_path_from_jsonl(jsonl_file)
      assert result == expected_path, f'Failed to extract from {field_name}'

  def test_prioritizes_cwd_over_other_fields(self, tmp_path):
    """Should prefer 'cwd' over other fields when multiple are present."""
    manager = ClaudeConversationManager()

    jsonl_file = tmp_path / 'test.jsonl'
    metadata = {
      'cwd': '/Users/kyle/Code/primary-project',
      'projectPath': '/Users/kyle/Code/secondary-project',
      'workspaceRoot': '/Users/kyle/Code/tertiary-project',
      'sessionId': 'test-session',
      'type': 'user',
    }

    jsonl_file.write_text(json.dumps(metadata) + '\n')

    result = manager._get_project_path_from_jsonl(jsonl_file)
    assert result == '/Users/kyle/Code/primary-project'

  def test_skips_summary_lines_before_metadata(self, tmp_path):
    """Should skip summary lines and find metadata in later lines."""
    manager = ClaudeConversationManager()

    jsonl_file = tmp_path / 'test.jsonl'

    with open(jsonl_file, 'w') as f:
      f.write(json.dumps({'type': 'summary', 'summary': 'Test conversation'}) + '\n')
      f.write(json.dumps({'type': 'summary', 'summary': 'Another summary'}) + '\n')
      f.write(
        json.dumps(
          {
            'cwd': '/Users/kyle/Code/my-projects/claude-bushwack',
            'sessionId': 'test-session',
            'type': 'user',
          }
        )
        + '\n'
      )

    result = manager._get_project_path_from_jsonl(jsonl_file)
    assert result == '/Users/kyle/Code/my-projects/claude-bushwack'

  def test_returns_none_when_no_project_fields(self, tmp_path):
    """Should return None when no recognized project path fields are found."""
    manager = ClaudeConversationManager()

    jsonl_file = tmp_path / 'test.jsonl'
    metadata = {
      'sessionId': 'test-session',
      'type': 'user',
      'message': {'role': 'user', 'content': 'test'},
    }

    jsonl_file.write_text(json.dumps(metadata) + '\n')

    result = manager._get_project_path_from_jsonl(jsonl_file)
    assert result is None

  def test_returns_none_when_project_field_empty(self, tmp_path):
    """Should return None when project path field is empty string or null."""
    manager = ClaudeConversationManager()

    jsonl_file = tmp_path / 'test.jsonl'

    # Test empty string
    metadata = {'cwd': '', 'sessionId': 'test-session', 'type': 'user'}
    jsonl_file.write_text(json.dumps(metadata) + '\n')
    result = manager._get_project_path_from_jsonl(jsonl_file)
    assert result is None

    # Test null value
    metadata['cwd'] = None
    jsonl_file.write_text(json.dumps(metadata) + '\n')
    result = manager._get_project_path_from_jsonl(jsonl_file)
    assert result is None


class TestErrorHandling:
  """Test error handling in path parsing and metadata extraction."""

  def test_handles_malformed_json_lines(self, tmp_path):
    """Should handle malformed JSON lines gracefully and continue searching."""
    manager = ClaudeConversationManager()

    jsonl_file = tmp_path / 'test.jsonl'

    with open(jsonl_file, 'w') as f:
      f.write('{"malformed": json}\n')  # Invalid JSON
      f.write('not json at all\n')  # Not JSON
      f.write(
        json.dumps(
          {
            'cwd': '/Users/kyle/Code/my-projects/claude-bushwack',
            'sessionId': 'test-session',
            'type': 'user',
          }
        )
        + '\n'
      )

    result = manager._get_project_path_from_jsonl(jsonl_file)
    assert result == '/Users/kyle/Code/my-projects/claude-bushwack'

  def test_returns_none_for_missing_file(self, tmp_path):
    """Should return None when file doesn't exist."""
    manager = ClaudeConversationManager()

    non_existent_file = tmp_path / 'does_not_exist.jsonl'

    result = manager._get_project_path_from_jsonl(non_existent_file)
    assert result is None

  def test_returns_none_on_permission_error(self, tmp_path, monkeypatch):
    """Should return None when file cannot be read due to permissions."""
    manager = ClaudeConversationManager()

    jsonl_file = tmp_path / 'test.jsonl'
    jsonl_file.write_text('{"cwd": "/test/path"}\n')

    original_open = builtins.open

    def fake_open(path, mode='r', *args, **kwargs):
      if Path(path) == jsonl_file and 'r' in mode:
        raise PermissionError('Permission denied for test')
      return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr('builtins.open', fake_open)

    result = manager._get_project_path_from_jsonl(jsonl_file)
    assert result is None


class TestScanLimitsAndOptimization:
  """Test scan limits and optimization features."""

  def test_respects_scan_line_limit(self, tmp_path):
    """Should stop searching after the configured scan line limit."""
    manager = ClaudeConversationManager()
    manager._METADATA_SCAN_LINE_LIMIT = 5

    jsonl_file = tmp_path / 'test.jsonl'

    with open(jsonl_file, 'w') as f:
      for i in range(5):
        f.write(json.dumps({'line': i, 'type': 'filler'}) + '\n')
      f.write(
        json.dumps(
          {
            'cwd': '/Users/kyle/Code/should-not-be-found',
            'sessionId': 'test-session',
            'type': 'user',
          }
        )
        + '\n'
      )

    result = manager._get_project_path_from_jsonl(jsonl_file)
    assert result is None

  def test_metadata_lookup_when_cache_miss(self, tmp_path):
    """Decode should consult metadata when the in-memory cache is empty."""
    manager = ClaudeConversationManager(claude_projects_dir=tmp_path)

    original_path = Path('/Users/kyle/Code/hyphen-heavy-project/sub-dir')
    encoded = manager._path_to_project_dir(original_path)

    # Simulate a fresh manager instance without cached mappings
    manager._project_dir_cache.pop(encoded)

    project_dir = tmp_path / encoded
    project_dir.mkdir(parents=True)

    conversation_file = project_dir / 'metadata.jsonl'
    conversation_file.write_text(
      json.dumps({'cwd': str(original_path), 'type': 'user'}) + '\n'
    )

    reconstructed = manager._project_dir_to_path(encoded)

    assert reconstructed == original_path


class TestRealWorldPatterns:
  """Test with real-world Claude directory patterns."""

  def test_handles_real_world_project_tokens(self, tmp_path):
    """Real Claude directory token patterns should decode via metadata."""
    manager = ClaudeConversationManager(claude_projects_dir=tmp_path)

    real_patterns = [
      ('-Users-kyle-Code-dotfiles-claude', '/Users/kyle/Code/dotfiles/claude'),
      ('-Users-kyle--config-nvim', '/Users/kyle/.config/nvim'),
      ('-tmp-test-branch', '/tmp/test/branch'),
    ]

    for encoded_dir, expected_original_path in real_patterns:
      project_dir = tmp_path / encoded_dir
      project_dir.mkdir(parents=True, exist_ok=True)

      conversation_file = project_dir / 'test.jsonl'
      metadata = {
        'cwd': expected_original_path,
        'sessionId': 'test-session',
        'type': 'user',
      }
      with open(conversation_file, 'w') as f:
        f.write(json.dumps(metadata) + '\n')

      # Test that metadata lookup works
      result = manager._get_project_path_from_jsonl(conversation_file)
      assert result == expected_original_path

      # Test that directory reconstruction uses metadata
      reconstructed = manager._project_dir_to_path(encoded_dir)
      assert str(reconstructed) == expected_original_path
