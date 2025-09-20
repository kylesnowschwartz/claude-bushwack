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
  ConversationNotFoundError,
  InvalidUUIDError,
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
