"""Tests for the Textual TUI."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import pytest

from claude_bushwack.core import ConversationFile
from claude_bushwack.exceptions import ConversationNotFoundError
from claude_bushwack.tui import BushwackApp, DirectoryPickerScreen, ExternalCommand


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
  source_uuid = '11111111-1111-1111-1111-111111111111'
  expected_target = Path(populated_manager.find_conversation(source_uuid).project_path)

  def fake_branch(
    uuid: str, target_project_path: Optional[Path] = None
  ) -> ConversationFile:
    assert uuid == source_uuid
    assert target_project_path == expected_target
    path = conversation_factory(new_uuid, parent_uuid=uuid, summary=None)
    return ConversationFile(
      path=path,
      uuid=new_uuid,
      project_dir=populated_manager._path_to_project_dir(expected_target),
      project_path=str(expected_target),
      last_modified=datetime.now(tz=timezone.utc),
      parent_uuid=uuid,
    )

  bushwack_app.conversation_manager.branch_conversation = fake_branch
  messages = capture_status(bushwack_app, monkeypatch)
  branch_calls: list[tuple[str, Optional[Path]]] = []

  def spy_branch(uuid: str, target_project_path: Optional[Path] = None):
    branch_calls.append((uuid, target_project_path))
    return fake_branch(uuid, target_project_path)

  bushwack_app.conversation_manager.branch_conversation = spy_branch

  async def _interaction(pilot) -> None:
    tree = bushwack_app.query_one('#conversation_tree')
    await pilot.pause()
    node = tree.root.children[0]
    tree.select_node(node)
    bushwack_app._set_selected_from_node(node)
    bushwack_app.action_branch_conversation()
    await pilot.pause()

  run_app(bushwack_app, _interaction)
  expected_call = (source_uuid, expected_target)
  assert branch_calls == [expected_call]
  assert any('Branched' in message for message in messages)


def test_branch_conversation_skips_picker(
  monkeypatch: pytest.MonkeyPatch,
  bushwack_app: BushwackApp,
  conversation_factory,
  populated_manager,
  project_cwd: Path,
) -> None:
  new_uuid = '55555555-5555-5555-5555-555555555555'

  def fake_branch(uuid: str, target_project_path: Optional[Path] = None):
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

  pushed: list[tuple[DirectoryPickerScreen, Optional[object]]] = []

  def capture_screen(screen, *args, **kwargs):
    pushed.append((screen, kwargs.get('callback')))

  monkeypatch.setattr(bushwack_app, 'push_screen', capture_screen)

  async def _interaction(pilot) -> None:
    tree = bushwack_app.query_one('#conversation_tree')
    await pilot.pause()
    node = tree.root.children[0]
    tree.select_node(node)
    bushwack_app._set_selected_from_node(node)
    bushwack_app.action_branch_conversation()
    await pilot.pause()

  run_app(bushwack_app, _interaction)
  assert pushed == []


def test_branch_conversation_error(
  monkeypatch: pytest.MonkeyPatch, bushwack_app: BushwackApp
):
  def raise_error(uuid: str, target_project_path=None):
    raise ConversationNotFoundError(uuid)

  bushwack_app.conversation_manager.branch_conversation = raise_error
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


def test_copy_move_conversation_opens_picker(
  monkeypatch: pytest.MonkeyPatch, bushwack_app: BushwackApp
) -> None:
  copy_calls: list[tuple[tuple, dict]] = []

  def record_copy(*args, **kwargs):
    copy_calls.append((args, kwargs))

  bushwack_app.conversation_manager.copy_move_conversation = record_copy

  pushed: list[tuple[DirectoryPickerScreen, Optional[object]]] = []

  def capture_screen(screen, *args, **kwargs):
    pushed.append((screen, kwargs.get('callback')))

  monkeypatch.setattr(bushwack_app, 'push_screen', capture_screen)

  async def _interaction(pilot) -> None:
    tree = bushwack_app.query_one('#conversation_tree')
    await pilot.pause()
    node = tree.root.children[0]
    tree.select_node(node)
    bushwack_app._set_selected_from_node(node)
    bushwack_app.action_copy_move_conversation()
    await pilot.pause()

  run_app(bushwack_app, _interaction)

  assert pushed, 'Copy move action should push the directory picker screen'
  screen, callback = pushed[0]
  assert isinstance(screen, DirectoryPickerScreen)
  assert callable(callback)
  assert copy_calls == []


def test_copy_move_conversation_success(
  monkeypatch: pytest.MonkeyPatch,
  bushwack_app: BushwackApp,
  populated_manager,
  conversation_factory,
  tmp_path: Path,
) -> None:
  target_path = tmp_path / 'copy-target'
  new_uuid = '66666666-6666-6666-6666-666666666666'

  def fake_copy(uuid: str, target_project_path: Path) -> ConversationFile:
    assert uuid == '11111111-1111-1111-1111-111111111111'
    assert target_project_path == target_path
    project_dir = populated_manager._path_to_project_dir(target_project_path)
    destination = populated_manager.claude_projects_dir / project_dir
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f'{new_uuid}.jsonl'
    conversation_factory(new_uuid, parent_uuid=None, summary=None)
    default_dir = '-Users-kyle-Code-my-projects-claude-bushwack'
    source_dir = populated_manager.claude_projects_dir / default_dir
    (source_dir / f'{new_uuid}.jsonl').rename(path)
    return ConversationFile(
      path=path,
      uuid=new_uuid,
      project_dir=project_dir,
      project_path=str(target_project_path),
      last_modified=datetime.now(tz=timezone.utc),
      parent_uuid=None,
    )

  bushwack_app.conversation_manager.copy_move_conversation = fake_copy
  messages = capture_status(bushwack_app, monkeypatch)
  pushed: list[tuple[DirectoryPickerScreen, Optional[object]]] = []

  def capture_screen(screen, *args, **kwargs):
    pushed.append((screen, kwargs.get('callback')))

  monkeypatch.setattr(bushwack_app, 'push_screen', capture_screen)

  async def _interaction(pilot) -> None:
    tree = bushwack_app.query_one('#conversation_tree')
    await pilot.pause()
    node = tree.root.children[0]
    tree.select_node(node)
    bushwack_app._set_selected_from_node(node)
    bushwack_app.action_copy_move_conversation()
    await pilot.pause()
    _, callback = pushed.pop(0)
    assert callback is not None
    callback(target_path)
    await pilot.pause()

  run_app(bushwack_app, _interaction)

  assert any('Copied' in message for message in messages)


def test_copy_move_conversation_error(
  monkeypatch: pytest.MonkeyPatch, bushwack_app: BushwackApp
):
  def raise_error(uuid: str, target_project_path: Path) -> None:
    raise ConversationNotFoundError(uuid)

  bushwack_app.conversation_manager.copy_move_conversation = raise_error
  messages = capture_status(bushwack_app, monkeypatch)
  pushed: list[tuple[DirectoryPickerScreen, Optional[object]]] = []

  def capture_screen(screen, *args, **kwargs):
    pushed.append((screen, kwargs.get('callback')))

  monkeypatch.setattr(bushwack_app, 'push_screen', capture_screen)

  async def _interaction(pilot) -> None:
    tree = bushwack_app.query_one('#conversation_tree')
    await pilot.pause()
    node = tree.root.children[0]
    tree.select_node(node)
    bushwack_app._set_selected_from_node(node)
    bushwack_app.action_copy_move_conversation()
    await pilot.pause()
    _, callback = pushed.pop(0)
    assert callback is not None
    callback(Path('/tmp/target'))
    await pilot.pause()

  run_app(bushwack_app, _interaction)
  assert any('Copy move failed' in message for message in messages)


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


def test_open_conversation_exits_with_command(
  monkeypatch: pytest.MonkeyPatch, bushwack_app: BushwackApp
):
  executable = '/usr/local/bin/claude'
  monkeypatch.setattr('claude_bushwack.tui.shutil.which', lambda name: executable)
  captured: List[ExternalCommand] = []
  original_exit = bushwack_app.exit

  def capture_exit(result=None):
    if result is not None:
      captured.append(result)
    original_exit(result)

  monkeypatch.setattr(bushwack_app, 'exit', capture_exit)

  async def _interaction(pilot) -> None:
    tree = bushwack_app.query_one('#conversation_tree')
    await pilot.pause()
    node = tree.root.children[0]
    tree.select_node(node)
    bushwack_app._set_selected_from_node(node)
    bushwack_app.action_open_conversation()

  run_app(bushwack_app, _interaction)
  assert captured, 'Expected the app to exit with an external command'
  command = captured[0]
  assert isinstance(command, ExternalCommand)
  assert command.executable == executable
  assert command.args == ['claude', '--resume', '11111111-1111-1111-1111-111111111111']


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


def test_all_scope_includes_project_path_column(bushwack_app: BushwackApp):
  async def _interaction(pilot) -> None:
    await pilot.pause()

    header = bushwack_app.query_one('#column_headers')
    assert hasattr(header, 'renderable')
    header_text = getattr(header.renderable, 'plain', str(header.renderable))
    assert 'Project Path' not in header_text

    bushwack_app.action_toggle_scope()
    await pilot.pause()

    header = bushwack_app.query_one('#column_headers')
    header_text = getattr(header.renderable, 'plain', str(header.renderable))
    assert 'Project Path' in header_text

    tree = bushwack_app.query_one('#conversation_tree')
    await pilot.pause()
    first = tree.root.children[0]
    assert first.label is not None
    label_text = first.label.plain
    assert label_text.count('~/') >= 1

  run_app(bushwack_app, _interaction)


def test_tree_description_labels(bushwack_app: BushwackApp):
  async def _interaction(pilot) -> None:
    tree = bushwack_app.query_one('#conversation_tree')
    await pilot.pause()

    stack = list(tree.root.children)
    nodes = []
    while stack:
      current = stack.pop()
      nodes.append(current)
      stack.extend(reversed(current.children))

    assert nodes, 'Expected populated tree'

    summary_node = next(
      (node for node in nodes if node.data and node.data.summary), None
    )
    assert summary_node is not None
    summary_label = summary_node.label.plain
    assert 'Summary:' in summary_label
    assert 'User:' not in summary_label

    preview_only_node = next(
      (
        node
        for node in nodes
        if node.data and not node.data.summary and node.data.preview
      ),
      None,
    )
    assert preview_only_node is not None
    preview_label = preview_only_node.label.plain
    assert 'User:' in preview_label
    assert 'Summary:' not in preview_label

  run_app(bushwack_app, _interaction)


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
