"""TUI interface for claude-bushwack using Textual."""

import json
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from rich.console import Group
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.events import Key
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import DirectoryTree, Footer, Input, Static, Tree
from textual.widgets._directory_tree import DirEntry
from textual.widgets.tree import TreeNode

from .core import ClaudeConversationManager, ConversationFile
from .exceptions import (
  AmbiguousSessionIDError,
  BranchingError,
  ConversationNotFoundError,
  InvalidUUIDError,
)

_PREVIEW_LIMIT = 30
_PREVIEW_PANE_LIMIT = 600

_BASE_COLUMN_LAYOUT = [
  ('uuid', 12, 'UUID'),
  ('modified', 12, 'Modified'),
  ('created', 12, 'Created'),
  ('children', 8, 'Branches'),
  ('messages', 6, 'Msgs'),
  ('branch', 18, 'Git Branch'),
]

_ALL_SCOPE_COLUMN = ('project', 32, 'Project Path')

_HEADER_PREFIX = '    '


@dataclass
class ConversationNodeData:
  """Data stored in tree nodes for conversations."""

  conversation: ConversationFile
  preview: str
  summary: str = ''
  created_at: Optional[datetime] = None
  message_count: int = 0
  git_branch: Optional[str] = None
  is_root: bool = False
  is_orphaned: bool = False
  child_count: int = 0


@dataclass
class ConversationDisplayData:
  """Metadata extracted from a conversation file for tree display."""

  preview: str = ''
  summary: str = ''
  created_at: Optional[datetime] = None
  message_count: int = 0
  git_branch: Optional[str] = None


@dataclass
class ExternalCommand:
  """Describes a command to execute after the TUI exits."""

  executable: str
  args: List[str]


class ProjectDirectoryTree(DirectoryTree):
  """Directory tree constrained to Claude project folders."""

  COMPONENT_CLASSES = DirectoryTree.COMPONENT_CLASSES
  DEFAULT_CSS = DirectoryTree.DEFAULT_CSS

  def __init__(
    self,
    manager: ClaudeConversationManager,
    *,
    name: Optional[str] = None,
    id: Optional[str] = None,
    classes: Optional[str] = None,
    disabled: bool = False,
  ) -> None:
    super().__init__(
      manager.claude_projects_dir, name=name, id=id, classes=classes, disabled=disabled
    )
    self._manager = manager
    self._filter_text = ''
    self._current_project_token: Optional[str] = None
    self.show_root = False

  def set_filter(self, value: str) -> None:
    normalized = value.strip().lower()
    if normalized == self._filter_text:
      return
    self._filter_text = normalized
    self.reload()

  def filter_paths(self, paths):
    directories = [path for path in paths if self._safe_is_dir(path)]
    if not self._filter_text:
      return directories
    filtered = []
    for path in directories:
      label = self._format_label(path)
      if self._filter_text in label.lower() or self._filter_text in path.name.lower():
        filtered.append(path)
    return filtered

  def _populate_node(self, node: TreeNode, content) -> None:
    node.remove_children()
    for path in content:
      if not self._safe_is_dir(path):
        continue
      label = self._format_label(path)
      child = node.add(label, data=DirEntry(path), allow_expand=False)
      child.allow_expand = False
    node.expand()

  def decode_path(self, encoded_path: Path) -> Optional[Path]:
    if encoded_path == self._manager.claude_projects_dir:
      return None
    try:
      return self._manager._project_dir_to_path(encoded_path.name)
    except Exception:
      return None

  def _format_label(self, path: Path) -> str:
    decoded = self.decode_path(path)
    return str(decoded) if decoded is not None else path.name

  def set_current_project(self, project_path: Optional[Path]) -> None:
    if project_path is None:
      self._current_project_token = None
      self.refresh(layout=True)
      return
    try:
      self._current_project_token = self._manager._path_to_project_dir(project_path)
    except Exception:
      self._current_project_token = None
    self.refresh(layout=True)

  def _is_current_project(self, node: TreeNode) -> bool:
    if self._current_project_token is None:
      return False
    data = node.data
    if data is None or not hasattr(data, 'path'):
      return False
    return data.path.name == self._current_project_token

  def render_label(  # type: ignore[override]
    self, node: TreeNode, base_style: Style, style: Style
  ) -> Text:
    data = node.data
    label = self._format_label(data.path) if data is not None else ''

    combined_style = Style()
    if isinstance(base_style, Style):
      combined_style += base_style
    if isinstance(style, Style):
      combined_style += style

    text = Text(label, style=combined_style)
    if self._is_current_project(node):
      marker_style = combined_style + Style(color='cyan')
      text.append(' • current', style=marker_style)
    return text


class DirectoryPickerScreen(ModalScreen[Optional[Path]]):
  """Modal for selecting a target Claude project directory."""

  BINDINGS = [
    Binding('escape', 'cancel', 'Cancel', show=False),
    Binding('ctrl+f', 'focus_filter', 'Focus filter', show=False),
  ]

  def __init__(
    self,
    manager: ClaudeConversationManager,
    *,
    current_project: Optional[Path] = None,
    initial_filter: str = '',
  ) -> None:
    super().__init__()
    self._manager = manager
    self._current_project = current_project
    self._initial_filter = initial_filter.strip()

  def compose(self) -> ComposeResult:
    yield Static('Select target project', id='picker_title')
    yield Input(placeholder='Filter projects…', id='picker_filter')
    yield ProjectDirectoryTree(self._manager, id='picker_tree')
    yield Static(
      'Enter to copy • Esc to cancel • Ctrl+F to focus filter', id='picker_hint'
    )

  def on_mount(self) -> None:
    filter_input = self.query_one('#picker_filter', Input)
    tree = self.query_one(ProjectDirectoryTree)
    tree.root.expand()
    tree.set_current_project(self._current_project)
    if self._initial_filter:
      filter_input.value = self._initial_filter
      tree.set_filter(self._initial_filter)
    self.set_focus(filter_input)
    if self._current_project is not None:
      self._focus_project(tree, self._current_project)
    self._ensure_selection(tree)

  def _focus_project(self, tree: ProjectDirectoryTree, project_path: Path) -> None:
    encoded = self._manager._path_to_project_dir(project_path)
    for node in tree.root.children:
      data = node.data
      if data is not None and getattr(data, 'path', None) is not None:
        if data.path.name == encoded:
          tree.select_node(node)
          break

  def _ensure_selection(self, tree: ProjectDirectoryTree) -> None:
    if tree.cursor_node is None and tree.root.children:
      tree.select_node(tree.root.children[0])

  def on_input_changed(self, event: Input.Changed) -> None:
    tree = self.query_one(ProjectDirectoryTree)
    tree.set_filter(event.value)

    def _select_first() -> None:
      if tree.root.children:
        tree.select_node(tree.root.children[0])

    self.call_after_refresh(_select_first)

  def _move_cursor(self, tree: ProjectDirectoryTree, direction: str) -> None:
    if not tree.root.children:
      return
    self._ensure_selection(tree)
    if direction == 'down':
      tree.action_cursor_down()
    elif direction == 'up':
      tree.action_cursor_up()
    if tree.cursor_node is None:
      self._ensure_selection(tree)

  def on_key(self, event: Key) -> None:
    if event.key not in {'down', 'up'}:
      return
    focused = self.focused
    if not isinstance(focused, Input) or focused.id != 'picker_filter':
      return
    tree = self.query_one(ProjectDirectoryTree)
    if not tree.root.children:
      return
    event.stop()
    self._move_cursor(tree, event.key)
    self.set_focus(tree)

  def action_focus_filter(self) -> None:
    filter_input = self.query_one('#picker_filter', Input)
    self.set_focus(filter_input)
    if hasattr(filter_input, 'cursor_position'):
      filter_input.cursor_position = len(filter_input.value)

  def on_input_submitted(self, event: Input.Submitted) -> None:
    tree = self.query_one(ProjectDirectoryTree)
    node = tree.cursor_node
    if node is None:
      return
    data = node.data
    if data is None or not hasattr(data, 'path'):
      self.dismiss(None)
      event.stop()
      return
    decoded = tree.decode_path(data.path)
    self.dismiss(decoded)
    event.stop()

  def on_directory_tree_directory_selected(
    self, event: DirectoryTree.DirectorySelected
  ) -> None:
    event.stop()
    tree = event.control
    if not isinstance(tree, ProjectDirectoryTree):
      self.dismiss(None)
      return

    decoded = tree.decode_path(event.path)
    if decoded is None:
      self.dismiss(None)
      return

    self.dismiss(decoded)

  def action_cancel(self) -> None:
    self.dismiss(None)


class BushwackApp(App):
  """Main TUI application for claude-bushwack."""

  BINDINGS = [
    Binding('j', 'cursor_down', 'Down', show=False),
    Binding('k', 'cursor_up', 'Up', show=False),
    Binding('h', 'collapse_node', 'Collapse', show=False),
    Binding('l', 'expand_node', 'Expand', show=False),
    Binding('tab', 'toggle_branch', 'Toggle branch', show=False, priority=True),
    Binding('g', 'cursor_top', 'Top', show=False),
    Binding('G', 'cursor_bottom', 'Bottom', show=False),
    Binding('b', 'branch_conversation', 'Branch', show=True, key_display='B'),
    Binding('B', 'branch_conversation', 'Branch', show=False),
    Binding('c', 'copy_move_conversation', 'Copy Move', show=True, key_display='C'),
    Binding('C', 'copy_move_conversation', 'Copy Move', show=False),
    Binding('o', 'open_conversation', 'Open', show=True, key_display='O'),
    Binding('O', 'open_conversation', 'Open', show=False),
    Binding('p', 'toggle_preview', 'Preview', show=True),
    Binding('P', 'toggle_preview', 'Preview', show=False),
    Binding('r', 'refresh_tree', 'Refresh', show=True),
    Binding('R', 'refresh_tree', 'Refresh', show=False),
    Binding('s', 'toggle_scope', 'Scope', show=True),
    Binding('S', 'toggle_scope', 'Scope', show=False),
    Binding('q', 'quit', 'Quit', show=True),
    Binding('Q', 'quit', 'Quit', show=False),
    Binding('question_mark', 'show_help', 'Help', show=False),
  ]

  def __init__(self) -> None:
    super().__init__()
    self.conversation_manager = ClaudeConversationManager()
    self.show_all_projects = False
    self._status_timer: Optional[Timer] = None
    self._selected_uuid: Optional[str] = None
    self._node_lookup: Dict[str, TreeNode] = {}
    self.preview_visible = False

  def compose(self) -> ComposeResult:
    """Create child widgets for the app."""
    header = Static('', id='column_headers')
    yield header
    conversation_tree = Tree('Conversations', id='conversation_tree')
    conversation_tree.show_root = True
    conversation_tree.show_guides = True
    conversation_tree.styles.height = '1fr'
    yield conversation_tree
    preview = Static('', id='preview_pane')
    preview.styles.height = '30%'
    preview.styles.padding = (1, 2)
    preview.styles.overflow_y = 'auto'
    preview.display = False
    yield preview
    yield Static('', id='status_line')
    yield Footer()

  def on_mount(self) -> None:
    """Called when the app starts."""
    tree = self.query_one('#conversation_tree', Tree)
    tree.focus()
    tree.root.expand()
    self._update_column_headers()
    self._apply_preview_visibility()
    self._clear_preview()
    self.load_conversations()

  def load_conversations(
    self, focus_uuid: Optional[str] = None, *, announce_scope: bool = True
  ) -> None:
    """Load conversations and populate the tree."""
    self._update_column_headers()
    tree = self.query_one('#conversation_tree', Tree)
    tree.clear()
    tree.root.label = 'Conversations'
    tree.root.expand()
    self._node_lookup = {}
    self._clear_preview()

    try:
      if self.show_all_projects:
        conversations = self.conversation_manager.find_all_conversations(
          all_projects=True
        )
        scope = 'all projects'
      else:
        conversations = self.conversation_manager.find_all_conversations(
          current_project_only=True
        )
        scope = 'current project'

      display_data = self._build_display_data(conversations)
      self.populate_tree(tree, conversations, display_data)

      target_uuid = focus_uuid or self._selected_uuid
      if target_uuid:
        self._focus_on_uuid(tree, target_uuid)
      else:
        self._focus_first_child(tree)

      if announce_scope:
        self.show_status(f'Scope: {scope}')
    except Exception as exc:  # pragma: no cover - defensive logging
      tree.root.add_leaf(f'Error loading conversations: {exc}')
      self.show_status('Unable to load conversations')

  def populate_tree(
    self,
    tree: Tree,
    conversations: List[ConversationFile],
    display_data: Dict[str, ConversationDisplayData],
  ) -> None:
    """Populate the tree widget with conversation data."""
    if not conversations:
      tree.root.add_leaf('No conversations found')
      tree.root.expand()
      return

    roots, children_dict = self.conversation_manager.build_conversation_tree(
      conversations
    )

    orphaned = [
      conv
      for conv in conversations
      if conv.parent_uuid and conv.parent_uuid not in {c.uuid for c in conversations}
    ]

    if self.show_all_projects:
      self._populate_all_projects_tree(tree, roots, children_dict, display_data)
    else:
      self._populate_current_project_tree(
        tree.root, roots, children_dict, display_data
      )

    self._add_orphaned_conversations(
      tree.root, orphaned, children_dict, display_data
    )

    tree.root.expand()

  def _populate_current_project_tree(
    self,
    parent_node: TreeNode,
    roots: List[ConversationFile],
    children_dict: Dict[str, List[ConversationFile]],
    display_data: Dict[str, ConversationDisplayData],
  ) -> None:
    for root in sorted(roots, key=lambda conv: conv.last_modified, reverse=True):
      self._add_conversation_to_tree(
        parent_node, root, children_dict, display_data, is_root=True
      )

  def _populate_all_projects_tree(
    self,
    tree: Tree,
    roots: List[ConversationFile],
    children_dict: Dict[str, List[ConversationFile]],
    display_data: Dict[str, ConversationDisplayData],
  ) -> None:
    if not roots:
      return

    project_roots: Dict[str, List[ConversationFile]] = defaultdict(list)

    for root in roots:
      project_path = root.project_path or ''
      project_roots[project_path].append(root)

    project_paths = sorted(project_roots.keys())
    project_paths.sort(
      key=lambda path: max(
        (conversation.last_modified for conversation in project_roots[path]),
        default=datetime.min,
      ),
      reverse=True,
    )

    for project_path in project_paths:
      formatted_path = self._format_project_path(project_path) or '(unknown project)'
      label = Text(formatted_path, style='bold')
      label.no_wrap = True
      project_node = tree.root.add(label)
      project_node.expand()
      for conversation in sorted(
        project_roots[project_path], key=lambda conv: conv.last_modified, reverse=True
      ):
        self._add_conversation_to_tree(
          project_node, conversation, children_dict, display_data, is_root=True
        )

  def _add_orphaned_conversations(
    self,
    parent: TreeNode,
    orphaned: List[ConversationFile],
    children_dict: Dict[str, List[ConversationFile]],
    display_data: Dict[str, ConversationDisplayData],
  ) -> None:
    if not orphaned:
      return

    orphaned_node = parent.add('Orphaned branches')
    orphaned_node.expand()
    for conv in sorted(orphaned, key=lambda item: item.last_modified, reverse=True):
      self._add_conversation_to_tree(
        orphaned_node, conv, children_dict, display_data, is_orphaned=True
      )

  def _add_conversation_to_tree(
    self,
    parent_node: TreeNode,
    conversation: ConversationFile,
    children_dict: Dict[str, List[ConversationFile]],
    display_data: Dict[str, ConversationDisplayData],
    *,
    is_root: bool = False,
    is_orphaned: bool = False,
  ) -> TreeNode:
    """Add a conversation node to the tree."""
    uuid_display = f'{conversation.uuid[:8]}...'
    modified_display = self._format_timestamp(conversation.last_modified)
    display_info = display_data.get(conversation.uuid, ConversationDisplayData())
    created_display = (
      self._format_timestamp(display_info.created_at)
      if display_info.created_at
      else '--'
    )
    branch_display = self._format_branch(display_info.git_branch)
    message_display = (
      str(display_info.message_count) if display_info.message_count else '0'
    )
    description = self._format_description(
      summary=display_info.summary or '', preview=display_info.preview or ''
    )
    child_count = len(children_dict.get(conversation.uuid, []))
    children_display = str(child_count) if child_count else '-'
    column_values = {
      'uuid': uuid_display,
      'modified': modified_display,
      'created': created_display,
      'children': children_display,
      'messages': message_display,
      'branch': branch_display,
    }
    if self.show_all_projects:
      column_values['project'] = self._format_project_path(
        conversation.project_path
      )
    label_text = self._format_columns(column_values, description)

    node_data = ConversationNodeData(
      conversation=conversation,
      preview=display_info.preview,
      summary=display_info.summary,
      created_at=display_info.created_at,
      message_count=display_info.message_count,
      git_branch=display_info.git_branch,
      is_root=is_root,
      is_orphaned=is_orphaned,
      child_count=child_count,
    )

    node = parent_node.add(label_text, data=node_data)
    self._node_lookup[conversation.uuid] = node

    if conversation.uuid in children_dict:
      for child in sorted(
        children_dict[conversation.uuid], key=lambda item: item.last_modified
      ):
        self._add_conversation_to_tree(node, child, children_dict, display_data)

    return node

  def action_cursor_down(self) -> None:
    tree = self.query_one('#conversation_tree', Tree)
    tree.action_cursor_down()
    self._set_selected_from_node(tree.cursor_node)

  def action_cursor_up(self) -> None:
    tree = self.query_one('#conversation_tree', Tree)
    tree.action_cursor_up()
    self._set_selected_from_node(tree.cursor_node)

  def action_collapse_node(self) -> None:
    tree = self.query_one('#conversation_tree', Tree)
    node = tree.cursor_node
    if node and node.is_expanded:
      node.collapse()
    elif node and node.parent:
      tree.select_node(node.parent)
    self._set_selected_from_node(tree.cursor_node)

  def action_expand_node(self) -> None:
    tree = self.query_one('#conversation_tree', Tree)
    node = tree.cursor_node
    if node and node.children and not node.is_expanded:
      node.expand()
    elif node and node.children:
      tree.select_node(node.children[0])
    self._set_selected_from_node(tree.cursor_node)

  def action_toggle_branch(self) -> None:
    tree = self.query_one('#conversation_tree', Tree)
    node = tree.cursor_node
    if node and node.children:
      if self._branch_is_expanded(node):
        self._collapse_branch(node)
      else:
        self._expand_branch(node)
      tree.select_node(node)
      self._set_selected_from_node(node)

  def action_cursor_top(self) -> None:
    tree = self.query_one('#conversation_tree', Tree)
    if tree.root.children:
      tree.select_node(tree.root.children[0])
      self._set_selected_from_node(tree.cursor_node)

  def action_cursor_bottom(self) -> None:
    tree = self.query_one('#conversation_tree', Tree)

    def find_last(target: TreeNode) -> TreeNode:
      if not target.children or not target.is_expanded:
        return target
      return find_last(target.children[-1])

    if tree.root.children:
      tree.select_node(find_last(tree.root.children[-1]))
      self._set_selected_from_node(tree.cursor_node)

  def action_branch_conversation(self) -> None:
    tree = self.query_one('#conversation_tree', Tree)
    node = tree.cursor_node
    if not node or not isinstance(node.data, ConversationNodeData):
      self.show_status('Select a conversation to branch')
      return

    conversation = node.data.conversation
    target_project = Path(conversation.project_path)
    self._perform_branch(conversation, target_project)

  def _perform_branch(
    self, conversation: ConversationFile, target_project: Path
  ) -> None:
    target = Path(target_project)
    try:
      new_conversation = self.conversation_manager.branch_conversation(
        conversation.uuid, target_project_path=target
      )
    except (
      AmbiguousSessionIDError,
      BranchingError,
      ConversationNotFoundError,
      InvalidUUIDError,
    ) as error:
      self.show_status(f'Branch failed: {error}')
      return
    except Exception as error:  # pragma: no cover - defensive logging
      self.show_status(f'Unexpected error: {error}')
      return

    target_display = str(target)
    self.show_status(
      f'Branched {conversation.uuid[:8]}... -> {new_conversation.uuid[:8]}... ({target_display})'
    )
    self._selected_uuid = new_conversation.uuid
    self.load_conversations(focus_uuid=new_conversation.uuid, announce_scope=False)

  def action_copy_move_conversation(self) -> None:
    tree = self.query_one('#conversation_tree', Tree)
    node = tree.cursor_node
    if not node or not isinstance(node.data, ConversationNodeData):
      self.show_status('Select a conversation to copy')
      return

    conversation = node.data.conversation
    current_path = Path(conversation.project_path)

    picker = DirectoryPickerScreen(
      self.conversation_manager, current_project=current_path
    )

    def _complete(selection: Optional[Path]) -> None:
      if selection is None:
        self.show_status('Copy move cancelled')
        return
      self._perform_copy_move(conversation, selection)

    self.push_screen(picker, callback=_complete)

  def _perform_copy_move(
    self, conversation: ConversationFile, target_project: Path
  ) -> None:
    target = Path(target_project)
    try:
      new_conversation = self.conversation_manager.copy_move_conversation(
        conversation.uuid, target_project_path=target
      )
    except (
      AmbiguousSessionIDError,
      BranchingError,
      ConversationNotFoundError,
      InvalidUUIDError,
    ) as error:
      self.show_status(f'Copy move failed: {error}')
      return
    except Exception as error:  # pragma: no cover - defensive logging
      self.show_status(f'Unexpected error: {error}')
      return

    target_display = str(target)
    self.show_status(
      f'Copied {conversation.uuid[:8]}... -> {new_conversation.uuid[:8]}... ({target_display})'
    )
    self._selected_uuid = new_conversation.uuid
    self.load_conversations(focus_uuid=new_conversation.uuid, announce_scope=False)

  def action_open_conversation(self) -> None:
    tree = self.query_one('#conversation_tree', Tree)
    node = tree.cursor_node
    if not node or not isinstance(node.data, ConversationNodeData):
      self.show_status('Select a conversation to open')
      return

    conversation = node.data.conversation
    executable = shutil.which('claude')
    if not executable:
      self.show_status('claude CLI not found on PATH')
      return

    command = ExternalCommand(
      executable=executable, args=['claude', '--resume', conversation.uuid]
    )
    self.exit(command)

  def action_refresh_tree(self) -> None:
    self.show_status('Refreshing conversations...')
    self.load_conversations(focus_uuid=self._selected_uuid)

  def action_toggle_scope(self) -> None:
    self.show_all_projects = not self.show_all_projects
    scope = 'all projects' if self.show_all_projects else 'current project'
    self.show_status(f'Switched to {scope}')
    self.load_conversations(focus_uuid=self._selected_uuid)

  def action_toggle_preview(self) -> None:
    self.preview_visible = not self.preview_visible
    self._apply_preview_visibility()
    if self.preview_visible:
      tree = self.query_one('#conversation_tree', Tree)
      self._set_selected_from_node(tree.cursor_node)
    state = 'shown' if self.preview_visible else 'hidden'
    self.show_status(f'Preview {state}')

  def action_show_help(self) -> None:
    help_lines = [
      'Navigation:',
      '  j/k or arrows  Move selection',
      '  h/l            Collapse/expand',
      '  Tab           Toggle whole branch',
      '  g / G          Jump to top/bottom',
      '',
      'Actions:',
      '  B              Branch selected conversation',
      '  O              Open in claude CLI',
      '  r              Refresh conversations',
      '  p              Toggle preview pane',
      '  s              Toggle project scope',
      '  q              Quit',
    ]
    self.notify('\n'.join(help_lines))

  def action_quit(self) -> None:
    self.exit()

  def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
    self._set_selected_from_node(event.node)

  def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
    self._set_selected_from_node(event.node)

  def show_status(self, message: str, duration: float = 3.0) -> None:
    status_line = self.query_one('#status_line', Static)
    status_line.update(message)
    if self._status_timer:
      self._status_timer.stop()
    self._status_timer = self.set_timer(duration, self._clear_status)

  def _clear_status(self) -> None:
    try:
      status_line = self.query_one('#status_line', Static)
    except NoMatches:
      return
    status_line.update('')
    if self._status_timer:
      self._status_timer.stop()
      self._status_timer = None

  def _apply_preview_visibility(self) -> None:
    try:
      preview = self.query_one('#preview_pane', Static)
    except NoMatches:
      return
    preview.display = self.preview_visible

  def _clear_preview(self) -> None:
    try:
      preview = self.query_one('#preview_pane', Static)
    except NoMatches:
      return
    placeholder = Panel(
      Text('Select a conversation to view details'),
      title='Conversation Preview',
      border_style='cyan',
    )
    preview.update(placeholder)

  def _update_preview_content(self, data: ConversationNodeData) -> None:
    try:
      preview = self.query_one('#preview_pane', Static)
    except NoMatches:
      return
    preview.update(self._build_preview_renderable(data))

  def _build_preview_renderable(self, data: ConversationNodeData) -> Panel:
    conversation = data.conversation

    metadata = Table.grid(padding=(0, 1))
    metadata.add_column(style='bold cyan', justify='right', no_wrap=True)
    metadata.add_column()

    metadata.add_row('UUID', conversation.uuid)
    metadata.add_row(
      'Project', self._format_project_path(conversation.project_path)
    )
    metadata.add_row('File', str(conversation.path))
    metadata.add_row(
      'Last Modified', self._format_timestamp(conversation.last_modified)
    )
    created_display = (
      self._format_timestamp(data.created_at) if data.created_at else '--'
    )
    metadata.add_row('Created', created_display)
    metadata.add_row('Messages', str(data.message_count))
    metadata.add_row('Branches', str(data.child_count))
    metadata.add_row('Git Branch', data.git_branch or '-')

    segments: List[Text] = [metadata]

    summary_source = (data.summary or '').strip()
    if summary_source:
      segments.extend(
        [
          Text(),
          Text('[ Assistant summary ]', style='bold'),
          Text(self._truncate_preview_text(summary_source)),
        ]
      )

    preview_source = (data.preview or '').strip()
    if preview_source:
      segments.extend(
        [
          Text(),
          Text('[ First user prompt ]', style='bold'),
          Text(self._truncate_preview_text(preview_source)),
        ]
      )

    if len(segments) == 1:
      segments.extend([Text(), Text('No preview details available', style='bold')])

    content = Group(*segments)

    return Panel(content, title='Conversation Preview', border_style='cyan')

  def _focus_on_uuid(self, tree: Tree, uuid: str) -> None:
    node = self._node_lookup.get(uuid)
    if node:
      self._expand_node_path(node)
      tree.select_node(node)
      self._set_selected_from_node(node)
      tree.scroll_to_node(node, animate=False)
    else:
      self._focus_first_child(tree)

  def _focus_first_child(self, tree: Tree) -> None:
    if tree.root.children:
      first_child = tree.root.children[0]
      tree.select_node(first_child)
      self._set_selected_from_node(first_child)
      tree.scroll_to_node(first_child, animate=False)

  def _set_selected_from_node(self, node: Optional[TreeNode]) -> None:
    if node and isinstance(node.data, ConversationNodeData):
      self._selected_uuid = node.data.conversation.uuid
      self._update_preview_content(node.data)
    else:
      self._selected_uuid = None
      self._clear_preview()

  def _expand_node_path(self, node: TreeNode) -> None:
    path: List[TreeNode] = []
    current: Optional[TreeNode] = node

    while current is not None:
      path.append(current)
      current = current.parent

    for ancestor in reversed(path):
      ancestor.expand()

  def _branch_is_expanded(self, node: TreeNode) -> bool:
    if not node.is_expanded:
      return False
    return any(child.is_expanded for child in node.children) or bool(node.children)

  def _expand_branch(self, node: TreeNode) -> None:
    stack: List[TreeNode] = [node]
    while stack:
      current = stack.pop()
      current.expand()
      stack.extend(reversed(current.children))

  def _collapse_branch(self, node: TreeNode) -> None:
    stack: List[TreeNode] = [node]
    while stack:
      current = stack.pop()
      stack.extend(current.children)
      current.collapse()

  def _build_display_data(
    self, conversations: List[ConversationFile]
  ) -> Dict[str, ConversationDisplayData]:
    display_data: Dict[str, ConversationDisplayData] = {}
    for conversation in conversations:
      display_data[conversation.uuid] = self._extract_display_data(conversation)
    return display_data

  def _extract_display_data(
    self, conversation: ConversationFile
  ) -> ConversationDisplayData:
    summary = ''
    preview = ''
    created_at: Optional[datetime] = None
    git_branch: Optional[str] = None
    message_count = 0

    try:
      with open(conversation.path, 'r', encoding='utf-8') as handle:
        for line_number, raw_line in enumerate(handle):
          line = raw_line.strip()
          if not line:
            continue
          try:
            data = json.loads(line)
          except json.JSONDecodeError:
            continue

          if line_number == 0 and data.get('type') == 'summary':
            summary_value = data.get('summary')
            if isinstance(summary_value, str):
              summary = summary_value
            continue

          if created_at is None:
            timestamp_value = data.get('timestamp')
            parsed_timestamp = self._parse_timestamp(timestamp_value)
            if parsed_timestamp is not None:
              created_at = parsed_timestamp

          if git_branch is None:
            branch_value = data.get('gitBranch')
            if isinstance(branch_value, str):
              branch_stripped = branch_value.strip()
              if branch_stripped:
                git_branch = branch_stripped

          message = data.get('message')
          if isinstance(message, dict):
            message_count += 1
            if (
              not preview
              and message.get('role') == 'user'
              and data.get('isMeta') is not True
            ):
              text = self._coerce_text(message)
              if text and not self._is_session_hook(text):
                preview = text
            continue

          if data.get('role') == 'user' and not preview:
            text = self._coerce_text(data)
            if text and not self._is_session_hook(text):
              preview = text

          if 'message' in data and not isinstance(message, dict):
            message_count += 1
    except OSError:
      return ConversationDisplayData()

    return ConversationDisplayData(
      preview=preview,
      summary=summary,
      created_at=created_at,
      message_count=message_count,
      git_branch=git_branch,
    )

  @staticmethod
  def _parse_timestamp(value: object) -> Optional[datetime]:
    if not isinstance(value, str):
      return None

    timestamp = value.strip()
    if not timestamp:
      return None

    if timestamp.endswith('Z'):
      timestamp = f'{timestamp[:-1]}+00:00'

    try:
      return datetime.fromisoformat(timestamp)
    except ValueError:
      return None

  @staticmethod
  def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is not None:
      try:
        localized = value.astimezone()
      except ValueError:
        localized = value
    else:
      localized = value
    return localized.strftime('%m-%d %H:%M')

  @staticmethod
  def _format_branch(branch: Optional[str]) -> str:
    if not branch:
      return '-'
    trimmed = branch.strip()
    if not trimmed:
      return '-'
    if len(trimmed) <= 32:
      return trimmed
    return f'{trimmed[:29]}...'

  @staticmethod
  def _format_project_path(project_path: Optional[str]) -> str:
    if not project_path:
      return ''
    path_str = str(project_path)
    home = str(Path.home())
    if path_str == home:
      return '~'
    home_prefix = f'{home}/'
    if path_str.startswith(home_prefix):
      return f'~/{path_str[len(home_prefix):]}'
    return path_str

  @staticmethod
  def _coerce_text(message: Dict[str, object]) -> str:
    if not isinstance(message, dict):
      return ''

    content = message.get('content')
    segments: List[str] = []

    if isinstance(content, list):
      for item in content:
        if isinstance(item, str):
          segments.append(item)
          continue
        if not isinstance(item, dict):
          continue
        if item.get('type') == 'text':
          text_value = item.get('text')
          if isinstance(text_value, str):
            segments.append(text_value)
            continue
        text_value = item.get('text') or item.get('content')
        if isinstance(text_value, str):
          segments.append(text_value)
      if segments:
        return ' '.join(segments)

    if isinstance(content, str):
      return content

    text_field = message.get('text')
    if isinstance(text_field, str):
      return text_field
    if isinstance(text_field, dict):
      inner_text = text_field.get('text')
      if isinstance(inner_text, str):
        return inner_text
    if isinstance(text_field, list):
      for item in text_field:
        if isinstance(item, str):
          segments.append(item)
        elif isinstance(item, dict):
          segment_text = item.get('text') or item.get('content')
          if isinstance(segment_text, str):
            segments.append(segment_text)
      if segments:
        return ' '.join(segments)

    body = message.get('body')
    if isinstance(body, str):
      return body

    return ''

  @staticmethod
  def _is_session_hook(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith('<session-start-hook>')

  @staticmethod
  def _format_preview(preview: str) -> str:
    return BushwackApp._format_snippet(preview, '[no user message]')

  @staticmethod
  def _format_summary(summary: str) -> str:
    return BushwackApp._format_snippet(summary, '[no summary]')

  def _format_description(self, *, summary: str, preview: str) -> str:
    if summary:
      summary_formatted = self._format_summary(summary)
      return f'Summary: {summary_formatted}'

    preview_formatted = self._format_preview(preview)
    return f'User: {preview_formatted}'

  @staticmethod
  def _format_snippet(value: str, placeholder: str) -> str:
    if not value:
      return placeholder

    compressed = ' '.join(value.split())
    if len(compressed) <= _PREVIEW_LIMIT:
      return compressed
    return f'{compressed[: _PREVIEW_LIMIT - 3]}...'

  @staticmethod
  def _truncate_preview_text(value: str, limit: int = _PREVIEW_PANE_LIMIT) -> str:
    if len(value) <= limit:
      return value
    return f'{value[: limit - 3]}...'

  def _format_columns(
    self, column_values: Dict[str, str], trailing: str, *, prefix: str = ''
  ) -> Text:
    segments = []
    for key, width, _ in self._column_layout():
      value = column_values.get(key, '')
      segments.append(self._pad_column(value, width))

    line = f'{prefix}{"  ".join(segments)}'
    if trailing:
      line = f'{line}  {trailing}' if line else trailing

    text = Text(line)
    text.no_wrap = True
    return text

  @staticmethod
  def _pad_column(value: str, width: int) -> str:
    if width <= 0:
      return value

    content = value or ''
    if len(content) <= width:
      return content.ljust(width)

    if width <= 3:
      return content[:width]

    return f'{content[: width - 3]}...'

  def _update_column_headers(self) -> None:
    header = self.query_one('#column_headers', Static)
    header.update(self._render_column_headers())

  def _render_column_headers(self) -> Text:
    values = {key: label for key, _, label in self._column_layout()}
    header_text = self._format_columns(
      values, 'Summary or user message', prefix=_HEADER_PREFIX
    )
    header_text.stylize('bold')
    return header_text

  def _column_layout(self) -> List[tuple[str, int, str]]:
    layout: List[tuple[str, int, str]] = list(_BASE_COLUMN_LAYOUT)
    if self.show_all_projects:
      layout.append(_ALL_SCOPE_COLUMN)
    return layout


if __name__ == '__main__':
  app = BushwackApp()
  app.run()
