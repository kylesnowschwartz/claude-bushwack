"""Tests for the Textual TUI."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest

from claude_bushwack.core import ConversationFile
from claude_bushwack.exceptions import ConversationNotFoundError
from claude_bushwack.tui import BushwackApp


@pytest.fixture
def bushwack_app(monkeypatch: pytest.MonkeyPatch, populated_manager, project_cwd):
  monkeypatch.setattr(
    'claude_bushwack.tui.ClaudeConversationManager', lambda: populated_manager
  )
  return BushwackApp()


def run_app(app: BushwackApp, interaction) -> None:
  async def _runner() -> None:
    async with app.run_test() as pilot:
      await interaction(pilot)

  asyncio.run(_runner())


def capture_status(app: BushwackApp, monkeypatch: pytest.MonkeyPatch) -> List[str]:
  original = app.show_status
  messages: List[str] = []

  def recorder(message: str, duration: float = 3.0) -> None:
    messages.append(message)
    original(message, duration)

  monkeypatch.setattr(app, 'show_status', recorder)
  return messages


def test_load_conversations_populates_tree(
  bushwack_app: BushwackApp, monkeypatch: pytest.MonkeyPatch
):
  messages = capture_status(bushwack_app, monkeypatch)

  async def _interaction(pilot) -> None:
    tree = bushwack_app.query_one('#conversation_tree')
    await pilot.pause()
    assert tree.root.children, 'Expected conversations to populate the tree'

  run_app(bushwack_app, _interaction)
  assert messages[-1].startswith('Scope: current project')


def test_toggle_scope_updates_status(
  bushwack_app: BushwackApp, monkeypatch: pytest.MonkeyPatch
):
  messages = capture_status(bushwack_app, monkeypatch)

  async def _interaction(pilot) -> None:
    bushwack_app.action_toggle_scope()
    await pilot.pause()
    assert bushwack_app.show_all_projects is True

  run_app(bushwack_app, _interaction)
  assert any('Scope: all projects' in message for message in messages)


def test_branch_conversation_success(
  monkeypatch: pytest.MonkeyPatch,
  bushwack_app: BushwackApp,
  conversation_factory,
  populated_manager,
  project_cwd: Path,
):
  new_uuid = '44444444-4444-4444-4444-444444444444'

  def fake_branch(uuid: str) -> ConversationFile:
    assert uuid == '11111111-1111-1111-1111-111111111111'
    path = conversation_factory(new_uuid, parent_uuid=uuid, summary=None)
    return ConversationFile(
      path=path,
      uuid=new_uuid,
      project_dir=populated_manager._path_to_project_dir(project_cwd),
      project_path=str(project_cwd),
      last_modified=datetime.now(tz=timezone.utc),
      parent_uuid=uuid,
    )

  bushwack_app.conversation_manager.branch_conversation = fake_branch
  messages = capture_status(bushwack_app, monkeypatch)

  async def _interaction(pilot) -> None:
    tree = bushwack_app.query_one('#conversation_tree')
    await pilot.pause()
    node = tree.root.children[0]
    tree.select_node(node)
    bushwack_app._set_selected_from_node(node)
    bushwack_app.action_branch_conversation()
    await pilot.pause()

  run_app(bushwack_app, _interaction)
  assert any('Branched' in message for message in messages)


def test_branch_conversation_error(
  monkeypatch: pytest.MonkeyPatch, bushwack_app: BushwackApp
):
  bushwack_app.conversation_manager.branch_conversation = lambda uuid: (
    _ for _ in ()
  ).throw(ConversationNotFoundError(uuid))
  messages = capture_status(bushwack_app, monkeypatch)

  async def _interaction(pilot) -> None:
    tree = bushwack_app.query_one('#conversation_tree')
    await pilot.pause()
    node = tree.root.children[0]
    tree.select_node(node)
    bushwack_app._set_selected_from_node(node)
    bushwack_app.action_branch_conversation()
    await pilot.pause()

  run_app(bushwack_app, _interaction)
  assert any('Branch failed' in message for message in messages)


def test_open_conversation_missing_cli(
  monkeypatch: pytest.MonkeyPatch, bushwack_app: BushwackApp
):
  monkeypatch.setattr('claude_bushwack.tui.shutil.which', lambda name: None)
  messages = capture_status(bushwack_app, monkeypatch)

  async def _interaction(pilot) -> None:
    tree = bushwack_app.query_one('#conversation_tree')
    await pilot.pause()
    node = tree.root.children[0]
    tree.select_node(node)
    bushwack_app._set_selected_from_node(node)
    bushwack_app.action_open_conversation()
    await pilot.pause()

  run_app(bushwack_app, _interaction)
  assert any('claude CLI not found on PATH' in message for message in messages)


def test_refresh_tree_updates_status(
  bushwack_app: BushwackApp, monkeypatch: pytest.MonkeyPatch
):
  messages = capture_status(bushwack_app, monkeypatch)

  async def _interaction(pilot) -> None:
    await pilot.pause()
    bushwack_app.action_refresh_tree()
    await pilot.pause()

  run_app(bushwack_app, _interaction)
  assert any('Refreshing conversations' in message for message in messages)


def test_formatting_helpers(bushwack_app: BushwackApp):
  timestamp = datetime(2024, 1, 1, 12, 34, tzinfo=timezone.utc)
  expected_timestamp = timestamp.astimezone().strftime('%m-%d %H:%M')
  assert bushwack_app._format_timestamp(timestamp) == expected_timestamp
  naive_timestamp = datetime(2024, 1, 1, 12, 34)
  assert bushwack_app._format_timestamp(naive_timestamp) == '01-01 12:34'
  assert (
    bushwack_app._format_branch('feature/super-long-branch')
    == 'feature/super-long-branch'
  )
  long_branch = 'feature/super-long-branch-name-exceeds-limit'
  assert bushwack_app._format_branch(long_branch) == 'feature/super-long-branch-nam...'
  assert bushwack_app._format_preview('preview text') == 'preview text'
  assert bushwack_app._format_summary('summary goes here') == 'summary goes here'
  assert bushwack_app._format_snippet('', '[placeholder]') == '[placeholder]'


def test_coerce_text_variants(bushwack_app: BushwackApp):
  message = {
    'content': [{'type': 'text', 'text': 'hello'}, {'type': 'text', 'text': 'world'}]
  }
  assert bushwack_app._coerce_text(message) == 'hello world'
  message = {'text': [{'text': 'foo'}, 'bar']}
  assert bushwack_app._coerce_text(message) == 'foo bar'
  message = {'body': 'fallback'}
  assert bushwack_app._coerce_text(message) == 'fallback'


def test_extract_display_data_from_sample(
  bushwack_app: BushwackApp, sample_conversation: Path
):
  conversation = ConversationFile(
    path=sample_conversation,
    uuid=sample_conversation.stem,
    project_dir='-Users-kyle-Code-my-projects-claude-bushwack',
    project_path='/Users/kyle/Code/my-projects/claude-bushwack',
    last_modified=datetime.now(tz=timezone.utc),
  )
  data = bushwack_app._extract_display_data(conversation)
  assert data.message_count > 0
  assert isinstance(data.preview, str)


def test_expand_and_collapse_branch(
  bushwack_app: BushwackApp, monkeypatch: pytest.MonkeyPatch
):
  async def _interaction(pilot) -> None:
    tree = bushwack_app.query_one('#conversation_tree')
    await pilot.pause()
    node = tree.root.children[0]
    bushwack_app._collapse_branch(node)
    assert not node.is_expanded
    bushwack_app._expand_branch(node)
    assert node.is_expanded

  run_app(bushwack_app, _interaction)
