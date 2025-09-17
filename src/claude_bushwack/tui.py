"""TUI interface for claude-bushwack using Textual."""

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from rich.text import Text

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.timer import Timer
from textual.widgets import Footer, Static, Tree
from textual.widgets.tree import TreeNode

from .core import ClaudeConversationManager, ConversationFile
from .exceptions import (
  AmbiguousSessionIDError,
  BranchingError,
  ConversationNotFoundError,
  InvalidUUIDError,
)

_PREVIEW_LIMIT = 30

_COLUMN_LAYOUT = [
  ('uuid', 12, 'UUID'),
  ('modified', 12, 'Modified'),
  ('created', 12, 'Created'),
  ('children', 8, 'Branches'),
  ('messages', 6, 'Msgs'),
  ('branch', 18, 'Git Branch'),
]

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
    Binding('B', 'branch_conversation', 'Branch', show=True),
    Binding('shift+b', 'branch_conversation', 'Branch', show=False),
    Binding('O', 'open_conversation', 'Open', show=True),
    Binding('shift+o', 'open_conversation', 'Open', show=False),
    Binding('r', 'refresh_tree', 'Refresh', show=True),
    Binding('p', 'toggle_scope', 'Scope', show=True),
    Binding('question_mark', 'show_help', 'Help', show=False),
    Binding('q', 'quit', 'Quit', show=True),
  ]

  def __init__(self) -> None:
    super().__init__()
    self.conversation_manager = ClaudeConversationManager()
    self.show_all_projects = False
    self._status_timer: Optional[Timer] = None
    self._selected_uuid: Optional[str] = None
    self._node_lookup: Dict[str, TreeNode] = {}

  def compose(self) -> ComposeResult:
    """Create child widgets for the app."""
    header = Static('', id='column_headers')
    yield header
    conversation_tree = Tree('Conversations', id='conversation_tree')
    conversation_tree.show_root = True
    conversation_tree.show_guides = True
    yield conversation_tree
    yield Static('', id='status_line')
    yield Footer()

  def on_mount(self) -> None:
    """Called when the app starts."""
    tree = self.query_one('#conversation_tree', Tree)
    tree.focus()
    tree.root.expand()
    self._update_column_headers()
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

    for root in sorted(roots, key=lambda conv: conv.last_modified, reverse=True):
      self._add_conversation_to_tree(
        tree.root, root, children_dict, display_data, is_root=True
      )

    orphaned = [
      conv
      for conv in conversations
      if conv.parent_uuid and conv.parent_uuid not in {c.uuid for c in conversations}
    ]

    if orphaned:
      orphaned_node = tree.root.add('Orphaned branches')
      orphaned_node.expand()
      for conv in sorted(orphaned, key=lambda item: item.last_modified, reverse=True):
        self._add_conversation_to_tree(
          orphaned_node, conv, children_dict, display_data, is_orphaned=True
        )

    tree.root.expand()

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
    preview_formatted = self._format_preview(display_info.preview)
    summary_formatted = (
      self._format_summary(display_info.summary) if display_info.summary else ''
    )
    if summary_formatted:
      description = summary_formatted
      if (
        display_info.preview
        and preview_formatted
        and preview_formatted != summary_formatted
      ):
        description = f'{summary_formatted} · {preview_formatted}'
    else:
      description = preview_formatted
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
    try:
      new_conversation = self.conversation_manager.branch_conversation(
        conversation.uuid
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

    self.show_status(
      f'Branched {conversation.uuid[:8]}... -> {new_conversation.uuid[:8]}...'
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
      executable=executable,
      args=['claude', '--resume', conversation.uuid],
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
      '  p              Toggle project scope',
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
    status_line = self.query_one('#status_line', Static)
    status_line.update('')
    if self._status_timer:
      self._status_timer.stop()
    self._status_timer = None

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

  @staticmethod
  def _format_snippet(value: str, placeholder: str) -> str:
    if not value:
      return placeholder

    compressed = ' '.join(value.split())
    if len(compressed) <= _PREVIEW_LIMIT:
      return compressed
    return f'{compressed[:_PREVIEW_LIMIT - 3]}...'

  def _format_columns(
    self, column_values: Dict[str, str], trailing: str, *, prefix: str = ''
  ) -> Text:
    segments = []
    for key, width, _ in _COLUMN_LAYOUT:
      value = column_values.get(key, '')
      segments.append(self._pad_column(value, width))

    line = f"{prefix}{'  '.join(segments)}"
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

    return f'{content[:width - 3]}...'

  def _update_column_headers(self) -> None:
    header = self.query_one('#column_headers', Static)
    header.update(self._render_column_headers())

  def _render_column_headers(self) -> Text:
    values = {key: label for key, _, label in _COLUMN_LAYOUT}
    header_text = self._format_columns(
      values, 'Summary / Preview', prefix=_HEADER_PREFIX
    )
    header_text.stylize('bold')
    return header_text


if __name__ == '__main__':
  app = BushwackApp()
  app.run()
