"""Tests for the directory picker modal."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

from rich.style import Style

from textual.app import App
from textual.widgets import Input

from claude_bushwack.tui import DirectoryPickerScreen, ProjectDirectoryTree


class _PickerHarness(App):
  """Minimal app to drive the picker screen for tests."""

  def __init__(self, screen: DirectoryPickerScreen) -> None:
    super().__init__()
    self._screen = screen
    self.result: Path | None = None

  def on_mount(self) -> None:
    self.push_screen(self._screen, self._capture_result)

  def _capture_result(self, result: Path | None) -> None:
    self.result = result


def test_directory_picker_filters_and_selects(
  manager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  """Typing in the filter narrows options and selection dismisses the screen."""
  base = manager.claude_projects_dir
  first_path = Path('/Users/kyle/Code/projects/alpha')
  second_path = Path('/Users/kyle/Code/projects/beta-tools')
  third_path = Path('/Users/kyle/Code/projects/beta-another')

  for path in [first_path, second_path, third_path]:
    encoded = manager._path_to_project_dir(path)
    (base / encoded).mkdir(exist_ok=True)

  screen = DirectoryPickerScreen(manager)

  captured: List[Path | None] = []
  selected: List[Path] = []

  def record(value: Path | None = None) -> None:
    captured.append(value)

  monkeypatch.setattr(screen, 'dismiss', record)

  app = _PickerHarness(screen)

  async def _exercise() -> None:
    async with app.run_test() as pilot:
      await pilot.pause()

      input_widget = screen.query_one(Input)
      input_widget.value = 'beta'
      await pilot.pause()

      tree = screen.query_one(ProjectDirectoryTree)
      visible = [
        manager._project_dir_to_path(node.data.path.name) for node in tree.root.children
      ]
      expected = {
        manager._project_dir_to_path(manager._path_to_project_dir(second_path)),
        manager._project_dir_to_path(manager._path_to_project_dir(third_path)),
      }
      assert set(visible) == expected

      target = visible[0]
      selected.append(target)
      encoded = tree.root.children[0].data.path
      event = SimpleNamespace(path=encoded, control=tree, stop=lambda: None)
      screen.on_directory_tree_directory_selected(event)

  asyncio.run(_exercise())

  assert captured[-1] == selected[-1]


def test_directory_picker_marks_current_project(manager) -> None:
  """The current project is annotated with a cyan marker."""

  base = manager.claude_projects_dir
  first_path = Path('/Users/kyle/Code/projects/alpha')
  current_path = Path('/Users/kyle/Code/projects/beta')

  for path in [first_path, current_path]:
    encoded = manager._path_to_project_dir(path)
    (base / encoded).mkdir(exist_ok=True)

  screen = DirectoryPickerScreen(manager, current_project=current_path)
  app = _PickerHarness(screen)

  async def _exercise() -> None:
    async with app.run_test() as pilot:
      await pilot.pause()

      tree = screen.query_one(ProjectDirectoryTree)
      target_token = manager._path_to_project_dir(current_path)
      target_node = next(
        child for child in tree.root.children if child.data.path.name == target_token
      )

      label = tree.render_label(target_node, None, None)
      assert '• current' in label.plain

      for span in label.spans:
        segment = label.plain[span.start : span.end]
        if segment == ' • current':
          assert span.style is not None
          style = span.style
          if isinstance(style, str):
            assert style == 'cyan'
          else:
            assert style.color is not None
            assert style.color.name == 'cyan'
          break
      else:  # pragma: no cover - defensive
        pytest.fail('Missing cyan style for current marker')

      styled = tree.render_label(target_node, Style(color='white'), Style())
      marker_spans = [
        span
        for span in styled.spans
        if styled.plain[span.start : span.end] == ' • current'
      ]
      assert marker_spans
      marker_style = marker_spans[0].style
      if isinstance(marker_style, str):
        assert marker_style == 'cyan'
      else:
        assert marker_style.color is not None
        assert marker_style.color.name == 'cyan'

  asyncio.run(_exercise())
