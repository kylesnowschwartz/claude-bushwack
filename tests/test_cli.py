"""CLI test suite."""

from __future__ import annotations

import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pytest
from click.testing import CliRunner

from claude_bushwack.cli import main
from claude_bushwack.core import ConversationFile
from claude_bushwack.exceptions import AmbiguousSessionIDError, ConversationNotFoundError


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


def test_list_command_default_scope(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
  convo = _conversation('11111111-1111-1111-1111-111111111111')
  manager = _RecordingManager([convo])
  monkeypatch.setattr('claude_bushwack.cli.ClaudeConversationManager', lambda: manager)
  result = runner.invoke(main, ['list'])
  assert result.exit_code == 0
  assert 'Found 1 conversation(s) for current project' in result.output
  assert convo.uuid in result.output
  assert manager.calls[0][0] == 'find_all_conversations'


def test_list_command_tree(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
  root = _conversation('11111111-1111-1111-1111-111111111111')
  child = _conversation('22222222-2222-2222-2222-222222222222', parent_uuid=root.uuid)
  manager = _RecordingManager([root, child])
  monkeypatch.setattr('claude_bushwack.cli.ClaudeConversationManager', lambda: manager)
  result = runner.invoke(main, ['list', '--tree'])
  assert result.exit_code == 0
  assert '🌳 Conversation Tree' in result.output
  assert root.uuid[:8] in result.output
  assert child.uuid[:8] in result.output


def test_branch_command_success(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
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


def test_branch_command_errors(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
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


def test_tui_command_success(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
  class FakeApp:
    def run(self):
      self.ran = True

  fake_module = types.SimpleNamespace(BushwackApp=FakeApp)
  monkeypatch.setitem(sys.modules, 'claude_bushwack.tui', fake_module)
  result = runner.invoke(main, ['tui'])
  assert result.exit_code == 0


def test_tui_command_missing_textual(monkeypatch: pytest.MonkeyPatch, runner: CliRunner) -> None:
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
