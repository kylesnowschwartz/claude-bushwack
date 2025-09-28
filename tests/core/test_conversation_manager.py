"""Tests for :mod:`claude_bushwack.core`."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

from claude_bushwack.core import (
  AmbiguousSessionIDError,
  BranchingError,
  ClaudeConversationManager,
  ConversationMetadata,
  ConversationNotFoundError,
  InvalidUUIDError,
  extract_conversation_metadata,
)


def test_path_round_trip(manager: ClaudeConversationManager) -> None:
  """The path helpers should round-trip real project paths."""
  project_path = Path('/Users/kyle/Code/my-projects/claude-bushwack')
  encoded = manager._path_to_project_dir(project_path)
  assert encoded == '-Users-kyle-Code-my-projects-claude-bushwack'
  decoded = manager._project_dir_to_path(encoded)
  assert manager._path_to_project_dir(decoded) == encoded


def test_get_and_set_parent_uuid(
  manager: ClaudeConversationManager, conversation_factory
) -> None:
  """Parent UUID metadata is readable and writeable."""
  parent_uuid = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
  file_path = conversation_factory(
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', parent_uuid=parent_uuid, summary=None
  )

  assert manager._get_parent_uuid(file_path) == parent_uuid

  new_parent = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
  manager._set_parent_uuid_in_jsonl(file_path, new_parent)
  assert manager._get_parent_uuid(file_path) == new_parent


def test_find_all_conversations_current_project(
  populated_manager: ClaudeConversationManager, monkeypatch: pytest.MonkeyPatch
) -> None:
  """find_all_conversations respects the current project scope."""
  monkeypatch.setattr(
    'claude_bushwack.core.Path.cwd',
    lambda: Path('/Users/kyle/Code/my-projects/claude-bushwack'),
  )

  conversations = populated_manager.find_all_conversations(current_project_only=True)
  assert {conv.uuid for conv in conversations} == {
    '11111111-1111-1111-1111-111111111111',
    '22222222-2222-2222-2222-222222222222',
    '33333333-3333-3333-3333-333333333333',
  }
  assert conversations == sorted(
    conversations, key=lambda c: c.last_modified, reverse=True
  )


def test_find_all_conversations_filters(
  populated_manager: ClaudeConversationManager, monkeypatch: pytest.MonkeyPatch
) -> None:
  """Project filters and all-projects flags return expected results."""
  monkeypatch.setattr(
    'claude_bushwack.core.Path.cwd',
    lambda: Path('/Users/kyle/Code/my-projects/another'),
  )

  # No conversations for current project
  assert populated_manager.find_all_conversations(current_project_only=True) == []

  # Explicit filter should locate files
  filtered = populated_manager.find_all_conversations(
    project_filter='/Users/kyle/Code/my-projects/claude-bushwack'
  )
  assert {conv.uuid for conv in filtered} == {
    '11111111-1111-1111-1111-111111111111',
    '22222222-2222-2222-2222-222222222222',
    '33333333-3333-3333-3333-333333333333',
  }

  # all_projects collects the same data
  all_projects = populated_manager.find_all_conversations(all_projects=True)
  assert len(all_projects) == len(filtered)


def test_find_conversation_success(
  populated_manager: ClaudeConversationManager,
) -> None:
  """find_conversation resolves exact and partial UUIDs."""
  exact = populated_manager.find_conversation('11111111-1111-1111-1111-111111111111')
  assert exact.uuid == '11111111-1111-1111-1111-111111111111'

  partial = populated_manager.find_conversation('2222')
  assert partial.uuid.startswith('2222')


def test_find_conversation_errors(
  populated_manager: ClaudeConversationManager, conversation_factory
) -> None:
  """find_conversation raises on invalid, missing, or ambiguous IDs."""
  with pytest.raises(InvalidUUIDError):
    populated_manager.find_conversation('INVALID!')

  with pytest.raises(ConversationNotFoundError):
    populated_manager.find_conversation('44444444-4444-4444-4444-444444444444')

  # Create another conversation sharing the same prefix to trigger ambiguity.
  conversation_factory('22222222-aaaa-bbbb-cccc-444444444444', summary=None)
  with pytest.raises(AmbiguousSessionIDError):
    populated_manager.find_conversation('2222')


def test_branch_conversation_to_current_project(
  populated_manager: ClaudeConversationManager, monkeypatch: pytest.MonkeyPatch
) -> None:
  """branch_conversation creates a copy and injects a parent UUID."""
  monkeypatch.setattr(
    'claude_bushwack.core.Path.cwd',
    lambda: Path('/Users/kyle/Code/my-projects/claude-bushwack'),
  )

  source_uuid = '11111111-1111-1111-1111-111111111111'
  new_conversation = populated_manager.branch_conversation(source_uuid)
  assert new_conversation.parent_uuid == source_uuid
  assert new_conversation.path.exists()
  assert new_conversation.project_path == '/Users/kyle/Code/my-projects/claude-bushwack'
  # First line should now reference the parent
  assert populated_manager._get_parent_uuid(new_conversation.path) == source_uuid


def test_branch_conversation_custom_target(
  populated_manager: ClaudeConversationManager, tmp_path: Path
) -> None:
  """An explicit project path should be encoded and used."""
  target_path = tmp_path / 'custom-project'
  new_conversation = populated_manager.branch_conversation(
    '22222222-2222-2222-2222-222222222222', target_project_path=target_path
  )
  expected_dir = populated_manager._path_to_project_dir(target_path)
  assert new_conversation.project_dir == expected_dir
  assert (
    new_conversation.path.parent == populated_manager.claude_projects_dir / expected_dir
  )


def test_branch_conversation_rewrites_project_metadata(
  manager: ClaudeConversationManager,
  conversation_factory: Callable[..., Path],
  tmp_path: Path,
) -> None:
  """Metadata containing project paths should update for the new target."""
  source_uuid = 'aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb'
  old_project_dir = '-Users-kyle-Code-my-projects-claude-bushwack'
  old_project_path = '/Users/kyle/Code/my-projects/claude-bushwack'

  extra_line = SimpleNamespace(
    type='metadata',
    content={
      'projectDir': old_project_dir,
      'workspaceRoot': old_project_path,
      'gitBranch': 'feature/original',
      'metadata': {'projectDir': old_project_dir, 'workspaceRoot': old_project_path},
    },
  )

  conversation_factory(
    source_uuid,
    parent_uuid=None,
    summary='Source conversation',
    git_branch='feature/original',
    extra_lines=[extra_line],
  )

  target_project_path = tmp_path / 'second-project'
  (target_project_path / '.git' / 'refs' / 'heads').mkdir(parents=True)
  (target_project_path / '.git' / 'HEAD').write_text('ref: refs/heads/main')

  new_conversation = manager.branch_conversation(
    source_uuid, target_project_path=target_project_path
  )

  assert new_conversation.project_path == str(target_project_path)

  with new_conversation.path.open('r', encoding='utf-8') as handle:
    records = [json.loads(line) for line in handle if line.strip()]

  project_dir = manager._path_to_project_dir(target_project_path)
  for record in records:
    if 'gitBranch' in record:
      assert record['gitBranch'] == 'main'
    if 'projectDir' in record:
      assert record['projectDir'] == project_dir
    if 'workspaceRoot' in record:
      assert record['workspaceRoot'] == str(target_project_path)
    metadata = record.get('metadata')
    if isinstance(metadata, dict):
      if 'projectDir' in metadata:
        assert metadata['projectDir'] == project_dir
      if 'workspaceRoot' in metadata:
        assert metadata['workspaceRoot'] == str(target_project_path)


def test_branch_conversation_error_propagation(
  populated_manager: ClaudeConversationManager, monkeypatch: pytest.MonkeyPatch
) -> None:
  """Underlying errors are wrapped in BranchingError."""
  monkeypatch.setattr(
    populated_manager,
    'find_conversation',
    lambda session_id: (_ for _ in ()).throw(RuntimeError('boom')),
  )
  with pytest.raises(BranchingError):
    populated_manager.branch_conversation('1111')


def test_copy_move_conversation_creates_root(
  populated_manager: ClaudeConversationManager, tmp_path: Path
) -> None:
  """copy_move_conversation duplicates without retaining the parentUuid."""
  target_path = tmp_path / 'relocated-project'
  source_uuid = '22222222-2222-2222-2222-222222222222'

  new_conversation = populated_manager.copy_move_conversation(
    source_uuid, target_project_path=target_path
  )

  assert new_conversation.parent_uuid is None
  assert populated_manager._get_parent_uuid(new_conversation.path) is None
  assert new_conversation.project_path == str(target_path)

  original = populated_manager.find_conversation(source_uuid)
  assert original.path.exists(), 'Original conversation should remain in place'


def test_copy_move_conversation_rewrites_project_metadata(
  manager: ClaudeConversationManager,
  conversation_factory: Callable[..., Path],
  tmp_path: Path,
) -> None:
  """Metadata fields update to the new project and parentUuid is cleared."""
  source_uuid = 'bbbbbbbb-2222-3333-4444-cccccccccccc'
  old_project_dir = '-Users-kyle-Code-my-projects-claude-bushwack'
  old_project_path = '/Users/kyle/Code/my-projects/claude-bushwack'

  extra_line = SimpleNamespace(
    type='metadata',
    content={
      'projectDir': old_project_dir,
      'workspaceRoot': old_project_path,
      'gitBranch': 'feature/original',
      'metadata': {'projectDir': old_project_dir, 'workspaceRoot': old_project_path},
    },
  )

  conversation_factory(
    source_uuid,
    parent_uuid='aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb',
    summary='Source conversation',
    git_branch='feature/original',
    extra_lines=[extra_line],
  )

  target_project_path = tmp_path / 'copy-target'
  (target_project_path / '.git' / 'refs' / 'heads').mkdir(parents=True)
  (target_project_path / '.git' / 'HEAD').write_text('ref: refs/heads/main')

  new_conversation = manager.copy_move_conversation(
    source_uuid, target_project_path=target_project_path
  )

  with new_conversation.path.open('r', encoding='utf-8') as handle:
    records = [json.loads(line) for line in handle if line.strip()]

  project_dir = manager._path_to_project_dir(target_project_path)
  assert manager._get_parent_uuid(new_conversation.path) is None

  for record in records:
    if 'gitBranch' in record:
      assert record['gitBranch'] == 'main'
    if 'projectDir' in record:
      assert record['projectDir'] == project_dir
    if 'workspaceRoot' in record:
      assert record['workspaceRoot'] == str(target_project_path)
    metadata = record.get('metadata')
    if isinstance(metadata, dict):
      if 'projectDir' in metadata:
        assert metadata['projectDir'] == project_dir
      if 'workspaceRoot' in metadata:
        assert metadata['workspaceRoot'] == str(target_project_path)


def test_build_conversation_tree(populated_manager: ClaudeConversationManager) -> None:
  """build_conversation_tree groups root and children entries."""
  conversations = populated_manager.find_all_conversations(all_projects=True)
  roots, children = populated_manager.build_conversation_tree(conversations)
  root_ids = {conv.uuid for conv in roots}
  assert root_ids == {'11111111-1111-1111-1111-111111111111'}
  assert (
    children['11111111-1111-1111-1111-111111111111'][0].parent_uuid
    == '11111111-1111-1111-1111-111111111111'
  )


def test_get_conversation_ancestry(
  populated_manager: ClaudeConversationManager,
) -> None:
  """get_conversation_ancestry walks the parent chain until the root."""
  ancestry = populated_manager.get_conversation_ancestry(
    '22222222-2222-2222-2222-222222222222'
  )
  assert [item.uuid for item in ancestry] == [
    '11111111-1111-1111-1111-111111111111',
    '22222222-2222-2222-2222-222222222222',
  ]

  orphan = populated_manager.get_conversation_ancestry(
    '33333333-3333-3333-3333-333333333333'
  )
  assert [item.uuid for item in orphan] == ['33333333-3333-3333-3333-333333333333']


def test_get_conversation_ancestry_handles_cycles(
  populated_manager: ClaudeConversationManager, conversation_factory
) -> None:
  """Cycles should not result in an infinite loop."""
  cyclic_uuid = '44444444-4444-4444-4444-444444444444'
  conversation_factory(cyclic_uuid, parent_uuid=cyclic_uuid, summary=None)
  ancestry = populated_manager.get_conversation_ancestry(cyclic_uuid)
  assert [item.uuid for item in ancestry] == [cyclic_uuid]


def test_extract_conversation_metadata_basic(
  manager: ClaudeConversationManager, conversation_factory
) -> None:
  """extract_conversation_metadata parses basic conversation data."""
  test_uuid = 'aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb'
  conversation_factory(
    test_uuid,
    parent_uuid=None,
    summary='Test conversation summary',
    git_branch='main',
    extra_lines=[],
  )

  conversation = manager.find_conversation(test_uuid)
  metadata = extract_conversation_metadata(conversation)

  assert isinstance(metadata, ConversationMetadata)
  assert metadata.summary == 'Test conversation summary'
  assert metadata.git_branch == 'main'
  assert metadata.message_count > 0  # Should have at least one message
  assert metadata.created_at is not None
  assert metadata.preview.strip()  # Should have some preview text


def test_extract_conversation_metadata_empty_file(
  manager: ClaudeConversationManager, tmp_path: Path
) -> None:
  """extract_conversation_metadata handles empty or invalid files gracefully."""
  from datetime import datetime

  from claude_bushwack.core import ConversationFile

  # Create an empty file
  empty_file = tmp_path / 'empty.jsonl'
  empty_file.touch()

  conversation = ConversationFile(
    path=empty_file,
    uuid='empty-file',
    project_dir='test',
    project_path=str(tmp_path),
    last_modified=datetime.now(),
    parent_uuid=None,
  )

  metadata = extract_conversation_metadata(conversation)

  assert metadata.summary == ''
  assert metadata.preview == ''
  assert metadata.created_at is None
  assert metadata.message_count == 0
  assert metadata.git_branch is None


def test_extract_conversation_metadata_missing_file(tmp_path: Path) -> None:
  """extract_conversation_metadata handles missing files gracefully."""
  from datetime import datetime

  from claude_bushwack.core import ConversationFile

  # Reference a non-existent file
  missing_file = tmp_path / 'missing.jsonl'

  conversation = ConversationFile(
    path=missing_file,
    uuid='missing-file',
    project_dir='test',
    project_path=str(tmp_path),
    last_modified=datetime.now(),
    parent_uuid=None,
  )

  metadata = extract_conversation_metadata(conversation)

  # Should return empty metadata when file doesn't exist
  assert metadata.summary == ''
  assert metadata.preview == ''
  assert metadata.created_at is None
  assert metadata.message_count == 0
  assert metadata.git_branch is None


def test_extract_conversation_metadata_complex_content(
  manager: ClaudeConversationManager, conversation_factory, tmp_path: Path
) -> None:
  """extract_conversation_metadata handles complex message structures."""
  from datetime import datetime

  test_uuid = 'cccccccc-1111-2222-3333-000000000000'

  # Import ConversationLine from conftest
  import sys
  from pathlib import Path

  # Add tests directory to path to import conftest
  tests_dir = Path(__file__).parent.parent
  sys.path.append(str(tests_dir))
  from conftest import ConversationLine

  # Create complex message structures using ConversationLine
  complex_message = ConversationLine(
    type='user',
    content={
      'timestamp': '2024-01-15T10:30:00Z',
      'role': 'user',
      'message': {
        'role': 'user',
        'content': [
          {
            'type': 'text',
            'text': 'This is a complex message with structured content.',
          },
          {'type': 'text', 'text': ' It has multiple parts.'},
        ],
      },
      'gitBranch': 'feature/test-branch',
    },
  )

  session_hook_message = ConversationLine(
    type='user',
    content={
      'timestamp': '2024-01-15T10:31:00Z',
      'role': 'user',
      'message': {
        'role': 'user',
        'content': '<session-start-hook>This should be ignored</session-start-hook>',
      },
    },
  )

  regular_message = ConversationLine(
    type='assistant',
    content={
      'timestamp': '2024-01-15T10:32:00Z',
      'role': 'assistant',
      'message': {'role': 'assistant', 'content': 'Assistant response'},
    },
  )

  conversation_factory(
    test_uuid,
    parent_uuid=None,
    summary='Complex content test',
    preview_text='This is a complex message with structured content. It has multiple parts.',
    created_at=datetime(2024, 1, 15, 10, 30, 0).replace(
      tzinfo=datetime.now().astimezone().tzinfo
    ),
    git_branch='feature/test-branch',
    extra_lines=[complex_message, session_hook_message, regular_message],
  )

  conversation = manager.find_conversation(test_uuid)
  metadata = extract_conversation_metadata(conversation)

  assert metadata.summary == 'Complex content test'
  assert metadata.git_branch == 'feature/test-branch'
  assert metadata.message_count >= 3  # Should count the messages we added
  assert (
    'This is a complex message with structured content. It has multiple parts.'
    in metadata.preview
  )
  # Session hooks should be ignored in preview
  assert 'session-start-hook' not in metadata.preview
  assert metadata.created_at == datetime(2024, 1, 15, 10, 30, 0).replace(
    tzinfo=datetime.now().astimezone().tzinfo
  )
