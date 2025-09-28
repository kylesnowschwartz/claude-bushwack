"""CLI test suite."""

from __future__ import annotations

import json
import os
import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

import pytest
from click.testing import CliRunner

from claude_bushwack.cli import main
from claude_bushwack.conversation_metadata import ConversationMetadata
from claude_bushwack.core import ClaudeConversationManager, ConversationFile
from claude_bushwack.exceptions import (
  AmbiguousSessionIDError,
  ConversationNotFoundError,
)


@pytest.fixture
def runner() -> CliRunner:
  return CliRunner()


def _conversation(
  uuid: str,
  *,
  project_path: str = '/Users/kyle/Code/my-projects/claude-bushwack',
  parent_uuid: str | None = None,
  last_modified: datetime | None = None,
) -> ConversationFile:
  return ConversationFile(
    path=Path(f'/tmp/{uuid}.jsonl'),
    uuid=uuid,
    project_dir='-Users-kyle-Code-my-projects-claude-bushwack',
    project_path=project_path,
    last_modified=last_modified or datetime(2024, 1, 1, 0, 0, 0),
    parent_uuid=parent_uuid,
  )


class _RecordingManager:
  """Stub ClaudeConversationManager that records calls."""

  def __init__(self, conversations: Iterable[ConversationFile]) -> None:
    self._conversations = list(conversations)
    self.calls: list[tuple[str, tuple, dict]] = []

  def find_all_conversations(self, *args, **kwargs):
    self.calls.append(('find_all_conversations', args, kwargs))
    return list(self._conversations)

  def build_conversation_tree(self, conversations):
    self.calls.append(('build_conversation_tree', (conversations,), {}))
    roots = [conv for conv in conversations if conv.parent_uuid is None]
    children = {}
    for conv in conversations:
      if conv.parent_uuid:
        children.setdefault(conv.parent_uuid, []).append(conv)
    return roots, children

  def _get_current_project_dir(self) -> str:
    return '-Users-kyle-Code-my-projects-claude-bushwack'

  def _project_dir_to_path(self, value: str) -> Path:
    return Path('/Users/kyle/Code/my-projects/claude-bushwack')

  def branch_conversation(self, session_id: str):
    self.calls.append(('branch_conversation', (session_id,), {}))
    raise AssertionError('branch_conversation should be stubbed per-test')

  def get_conversation_ancestry(self, session_id: str):
    self.calls.append(('get_conversation_ancestry', (session_id,), {}))
    return []


def test_main_help(runner: CliRunner) -> None:
  result = runner.invoke(main, ['--help'])
  assert result.exit_code == 0
  assert 'Claude Bushwack' in result.output


def test_list_command_default_scope(
  monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
  convo = _conversation('11111111-1111-1111-1111-111111111111')
  manager = _RecordingManager([convo])
  monkeypatch.setattr('claude_bushwack.cli.ClaudeConversationManager', lambda: manager)
  monkeypatch.setattr(
    'claude_bushwack.cli.extract_conversation_metadata',
    lambda conv: ConversationMetadata(
      summary='Root summary',
      preview='Root preview',
      created_at=datetime(2024, 1, 1, 12, 0, 0),
      message_count=4,
      git_branch='feature/root',
    ),
  )
  result = runner.invoke(main, ['list'])
  assert result.exit_code == 0
  assert 'Found 1 conversation(s) for current project' in result.output
  assert convo.uuid[:8] in result.output
  assert 'Root      │' in result.output
  assert '│ summary   │' in result.output
  assert 'feature' in result.output
  assert manager.calls[0][0] == 'find_all_conversations'


def test_list_command_tree(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
  root = _conversation('11111111-1111-1111-1111-111111111111')
  child = _conversation('22222222-2222-2222-2222-222222222222', parent_uuid=root.uuid)
  manager = _RecordingManager([root, child])
  monkeypatch.setattr('claude_bushwack.cli.ClaudeConversationManager', lambda: manager)
  metadata_by_uuid = {
    root.uuid: ConversationMetadata(
      summary='Root conversation summary',
      preview='',
      created_at=datetime(2024, 1, 2, 10, 0, 0),
      message_count=3,
      git_branch='main',
    ),
    child.uuid: ConversationMetadata(
      summary='',
      preview='Child preview text',
      created_at=datetime(2024, 1, 2, 11, 0, 0),
      message_count=2,
      git_branch='feature/child',
    ),
  }
  calls: list[str] = []

  def _fake_extract(conversation):
    calls.append(conversation.uuid)
    return metadata_by_uuid[conversation.uuid]

  monkeypatch.setattr(
    'claude_bushwack.cli.extract_conversation_metadata', _fake_extract
  )
  result = runner.invoke(main, ['list', '--tree'])
  assert result.exit_code == 0
  assert '🌳 Conversation Tree' in result.output
  assert root.uuid[:8] in result.output
  assert child.uuid[:8] in result.output
  assert 'Root conversation summary' in result.output
  assert 'Child preview' in result.output
  assert set(calls) == {root.uuid, child.uuid}


def test_branch_command_success(
  monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
  new = _conversation(
    '33333333-3333-3333-3333-333333333333',
    parent_uuid='22222222-2222-2222-2222-222222222222',
  )

  class _BranchingManager(_RecordingManager):
    def branch_conversation(self, session_id: str, target_project_path=None):
      assert session_id == '22222222-2222-2222-2222-222222222222'
      assert target_project_path is None
      return new

  manager = _BranchingManager([new])
  monkeypatch.setattr('claude_bushwack.cli.ClaudeConversationManager', lambda: manager)
  result = runner.invoke(main, ['branch', '22222222-2222-2222-2222-222222222222'])
  assert result.exit_code == 0
  assert 'Successfully branched conversation!' in result.output
  assert new.uuid in result.output


def test_branch_command_with_target_rewrites_metadata(
  monkeypatch: pytest.MonkeyPatch,
  runner: CliRunner,
  manager: ClaudeConversationManager,
  conversation_factory: Callable[..., Path],
  tmp_path: Path,
) -> None:
  source_uuid = '55555555-5555-5555-5555-555555555555'
  encoded_current = manager._path_to_project_dir(
    Path('/Users/kyle/Code/my-projects/claude-bushwack')
  )

  extra_line = types.SimpleNamespace(
    type='metadata',
    content={
      'projectDir': encoded_current,
      'workspaceRoot': '/Users/kyle/Code/my-projects/claude-bushwack',
      'gitBranch': 'feature/source',
      'metadata': {
        'projectDir': encoded_current,
        'workspaceRoot': '/Users/kyle/Code/my-projects/claude-bushwack',
      },
    },
  )

  conversation_factory(
    source_uuid,
    summary='CLI source',
    git_branch='feature/source',
    extra_lines=[extra_line],
  )

  target_project_path = tmp_path / 'cli-target'
  (target_project_path / '.git' / 'refs' / 'heads').mkdir(parents=True)
  (target_project_path / '.git' / 'HEAD').write_text('ref: refs/heads/target-branch')

  monkeypatch.setattr('claude_bushwack.cli.ClaudeConversationManager', lambda: manager)

  result = runner.invoke(
    main, ['branch', source_uuid, '--project', str(target_project_path)]
  )

  assert result.exit_code == 0
  assert 'Successfully branched conversation!' in result.output

  encoded_target = manager._path_to_project_dir(target_project_path)
  target_dir = manager.claude_projects_dir / encoded_target
  files = list(target_dir.glob('*.jsonl'))
  assert files, 'Branch command should create a conversation file'

  with files[0].open('r', encoding='utf-8') as handle:
    records = [json.loads(line) for line in handle if line.strip()]

  assert any(
    record.get('parentUuid') == source_uuid
    for record in records
    if 'parentUuid' in record
  )
  for record in records:
    if 'gitBranch' in record:
      assert record['gitBranch'] == 'target-branch'
    if 'workspaceRoot' in record:
      assert record['workspaceRoot'] == str(target_project_path)
    if 'projectDir' in record:
      assert record['projectDir'] == encoded_target
    metadata = record.get('metadata')
    if isinstance(metadata, dict):
      if 'projectDir' in metadata:
        assert metadata['projectDir'] == encoded_target
      if 'workspaceRoot' in metadata:
        assert metadata['workspaceRoot'] == str(target_project_path)


def test_branch_command_errors(
  monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
  class _ErrorManager(_RecordingManager):
    def branch_conversation(self, session_id: str, target_project_path=None):
      raise ConversationNotFoundError(session_id)

  manager = _ErrorManager([])
  monkeypatch.setattr('claude_bushwack.cli.ClaudeConversationManager', lambda: manager)
  result = runner.invoke(main, ['branch', '99999999-9999-9999-9999-999999999999'])
  assert result.exit_code != 0
  assert 'No conversation found with ID' in result.output

  class _AmbiguousManager(_RecordingManager):
    def branch_conversation(self, session_id: str, target_project_path=None):
      raise AmbiguousSessionIDError(session_id, [])

  manager = _AmbiguousManager([])
  monkeypatch.setattr('claude_bushwack.cli.ClaudeConversationManager', lambda: manager)
  result = runner.invoke(main, ['branch', '1111'])
  assert result.exit_code != 0
  assert 'Ambiguous session ID' in result.output


def test_tree_command(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
  root = _conversation('11111111-1111-1111-1111-111111111111')
  child = _conversation('22222222-2222-2222-2222-222222222222', parent_uuid=root.uuid)

  class _TreeManager(_RecordingManager):
    def get_conversation_ancestry(self, session_id: str):
      assert session_id == child.uuid
      return [root, child]

  manager = _TreeManager([root, child])
  monkeypatch.setattr('claude_bushwack.cli.ClaudeConversationManager', lambda: manager)
  result = runner.invoke(main, ['tree', child.uuid])
  assert result.exit_code == 0
  assert 'Conversation Ancestry Chain' in result.output
  assert '🌱' in result.output
  assert '📍' in result.output


def test_tui_command_success(
  monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
  class FakeApp:
    def run(self):
      self.ran = True

  fake_module = types.ModuleType('claude_bushwack.tui')
  fake_module.BushwackApp = FakeApp
  import claude_bushwack as package

  monkeypatch.setitem(sys.modules, 'claude_bushwack.tui', fake_module)
  monkeypatch.setattr(package, 'tui', fake_module, raising=False)
  result = runner.invoke(main, ['tui'])
  assert result.exit_code == 0


def test_tui_command_executes_external_command(
  monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
  class FakeExternalCommand:
    def __init__(self, executable: str, args: list[str]):
      self.executable = executable
      self.args = args

  class FakeApp:
    def run(self):
      return FakeExternalCommand('/usr/local/bin/claude', ['claude', '--resume', 'abc'])

  fake_module = types.ModuleType('claude_bushwack.tui')
  fake_module.BushwackApp = FakeApp
  fake_module.ExternalCommand = FakeExternalCommand

  captured = {}

  def fake_execv(executable, args):
    captured['executable'] = executable
    captured['args'] = args

  import claude_bushwack as package

  monkeypatch.setitem(sys.modules, 'claude_bushwack.tui', fake_module)
  monkeypatch.setattr(package, 'tui', fake_module, raising=False)
  monkeypatch.setattr(os, 'execv', fake_execv)

  result = runner.invoke(main, ['tui'])
  assert result.exit_code == 0
  assert captured['executable'] == '/usr/local/bin/claude'
  assert captured['args'] == ['claude', '--resume', 'abc']
  assert 'Loading conversation...' in result.output


def test_tui_command_missing_textual(
  monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
  import claude_bushwack as package

  fake_module = types.ModuleType('claude_bushwack.tui')

  def _getattr(name: str):
    raise ImportError('No module named textual')

  fake_module.__getattr__ = _getattr  # type: ignore[attr-defined]

  monkeypatch.setitem(sys.modules, 'claude_bushwack.tui', fake_module)
  monkeypatch.setattr(package, 'tui', fake_module, raising=False)
  result = runner.invoke(main, ['tui'])
  assert result.exit_code != 0
  assert 'Textual is not installed' in result.output
