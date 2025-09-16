"""TUI interface for claude-bushwack using Textual."""

import json
import os
import shutil
from dataclasses import dataclass
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


@dataclass
class ConversationNodeData:
  """Data stored in tree nodes for conversations."""

  conversation: ConversationFile
  preview: str
  is_root: bool = False
  is_orphaned: bool = False


class BushwackApp(App):
  """Main TUI application for claude-bushwack."""

  BINDINGS = [
    Binding("j", "cursor_down", "Down", show=False),
    Binding("k", "cursor_up", "Up", show=False),
    Binding("h", "collapse_node", "Collapse", show=False),
    Binding("l", "expand_node", "Expand", show=False),
    Binding("g", "cursor_top", "Top", show=False),
    Binding("G", "cursor_bottom", "Bottom", show=False),
    Binding("B", "branch_conversation", "Branch", show=True),
    Binding("shift+b", "branch_conversation", "Branch", show=False),
    Binding("O", "open_conversation", "Open", show=True),
    Binding("shift+o", "open_conversation", "Open", show=False),
    Binding("r", "refresh_tree", "Refresh", show=True),
    Binding("p", "toggle_scope", "Scope", show=True),
    Binding("question_mark", "show_help", "Help", show=False),
    Binding("q", "quit", "Quit", show=True),
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
    conversation_tree = Tree("Conversations", id="conversation_tree")
    conversation_tree.show_root = True
    conversation_tree.show_guides = True
    yield conversation_tree
    yield Static("", id="status_line")
    yield Footer()

  def on_mount(self) -> None:
    """Called when the app starts."""
    tree = self.query_one("#conversation_tree", Tree)
    tree.focus()
    tree.root.expand()
    self.load_conversations()

  def load_conversations(
    self,
    focus_uuid: Optional[str] = None,
    *,
    announce_scope: bool = True,
  ) -> None:
    """Load conversations and populate the tree."""
    tree = self.query_one("#conversation_tree", Tree)
    tree.clear()
    tree.root.label = "Conversations"
    tree.root.expand()
    self._node_lookup = {}

    try:
      if self.show_all_projects:
        conversations = self.conversation_manager.find_all_conversations(
          all_projects=True
        )
        scope = "all projects"
      else:
        conversations = self.conversation_manager.find_all_conversations(
          current_project_only=True
        )
        scope = "current project"

      previews = self._build_previews(conversations)
      self.populate_tree(tree, conversations, previews)

      target_uuid = focus_uuid or self._selected_uuid
      if target_uuid:
        self._focus_on_uuid(tree, target_uuid)
      else:
        self._focus_first_child(tree)

      if announce_scope:
        self.show_status(f"Scope: {scope}")
    except Exception as exc:  # pragma: no cover - defensive logging
      tree.root.add_leaf(f"Error loading conversations: {exc}")
      self.show_status("Unable to load conversations")

  def populate_tree(
    self,
    tree: Tree,
    conversations: List[ConversationFile],
    previews: Dict[str, str],
  ) -> None:
    """Populate the tree widget with conversation data."""
    if not conversations:
      tree.root.add_leaf("No conversations found")
      tree.root.expand()
      return

    roots, children_dict = self.conversation_manager.build_conversation_tree(
      conversations
    )

    for root in sorted(roots, key=lambda conv: conv.last_modified, reverse=True):
      self._add_conversation_to_tree(
        tree.root,
        root,
        children_dict,
        previews,
        is_root=True,
      )

    orphaned = [
      conv
      for conv in conversations
      if conv.parent_uuid
      and conv.parent_uuid not in {c.uuid for c in conversations}
    ]

    if orphaned:
      orphaned_node = tree.root.add("Orphaned branches")
      orphaned_node.expand()
      for conv in sorted(
        orphaned,
        key=lambda item: item.last_modified,
        reverse=True,
      ):
        self._add_conversation_to_tree(
          orphaned_node,
          conv,
          children_dict,
          previews,
          is_orphaned=True,
        )

    tree.root.expand()

  def _add_conversation_to_tree(
    self,
    parent_node: TreeNode,
    conversation: ConversationFile,
    children_dict: Dict[str, List[ConversationFile]],
    previews: Dict[str, str],
    *,
    is_root: bool = False,
    is_orphaned: bool = False,
  ) -> TreeNode:
    """Add a conversation node to the tree."""
    uuid_display = f"{conversation.uuid[:8]}..."
    modified_display = conversation.last_modified.strftime("%Y-%m-%d %H:%M")
    preview = previews.get(conversation.uuid, "")
    preview_display = self._format_preview(preview)
    child_count = len(children_dict.get(conversation.uuid, []))
    child_indicator = f"[{child_count}]"
    label_text = Text.assemble(
      uuid_display,
      " ",
      modified_display,
      " ",
      child_indicator,
      " | ",
      preview_display,
    )
    label_text.no_wrap = True

    node_data = ConversationNodeData(
      conversation=conversation,
      preview=preview_display,
      is_root=is_root,
      is_orphaned=is_orphaned,
    )

    node = parent_node.add(label_text, data=node_data)
    self._node_lookup[conversation.uuid] = node

    if conversation.uuid in children_dict:
      for child in sorted(
        children_dict[conversation.uuid], key=lambda item: item.last_modified
      ):
        self._add_conversation_to_tree(
          node,
          child,
          children_dict,
          previews,
        )

    return node

  def action_cursor_down(self) -> None:
    tree = self.query_one("#conversation_tree", Tree)
    tree.action_cursor_down()
    self._set_selected_from_node(tree.cursor_node)

  def action_cursor_up(self) -> None:
    tree = self.query_one("#conversation_tree", Tree)
    tree.action_cursor_up()
    self._set_selected_from_node(tree.cursor_node)

  def action_collapse_node(self) -> None:
    tree = self.query_one("#conversation_tree", Tree)
    node = tree.cursor_node
    if node and node.is_expanded:
      node.collapse()
    elif node and node.parent:
      tree.cursor_node = node.parent
    self._set_selected_from_node(tree.cursor_node)

  def action_expand_node(self) -> None:
    tree = self.query_one("#conversation_tree", Tree)
    node = tree.cursor_node
    if node and node.children and not node.is_expanded:
      node.expand()
    elif node and node.children:
      tree.cursor_node = node.children[0]
    self._set_selected_from_node(tree.cursor_node)

  def action_cursor_top(self) -> None:
    tree = self.query_one("#conversation_tree", Tree)
    if tree.root.children:
      tree.cursor_node = tree.root.children[0]
      self._set_selected_from_node(tree.cursor_node)

  def action_cursor_bottom(self) -> None:
    tree = self.query_one("#conversation_tree", Tree)

    def find_last(target: TreeNode) -> TreeNode:
      if not target.children or not target.is_expanded:
        return target
      return find_last(target.children[-1])

    if tree.root.children:
      tree.cursor_node = find_last(tree.root.children[-1])
      self._set_selected_from_node(tree.cursor_node)

  def action_branch_conversation(self) -> None:
    tree = self.query_one("#conversation_tree", Tree)
    node = tree.cursor_node
    if not node or not isinstance(node.data, ConversationNodeData):
      self.show_status("Select a conversation to branch")
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
      self.show_status(f"Branch failed: {error}")
      return
    except Exception as error:  # pragma: no cover - defensive logging
      self.show_status(f"Unexpected error: {error}")
      return

    self.show_status(
      f"Branched {conversation.uuid[:8]}... -> {new_conversation.uuid[:8]}..."
    )
    self._selected_uuid = new_conversation.uuid
    self.load_conversations(
      focus_uuid=new_conversation.uuid,
      announce_scope=False,
    )

  def action_open_conversation(self) -> None:
    tree = self.query_one("#conversation_tree", Tree)
    node = tree.cursor_node
    if not node or not isinstance(node.data, ConversationNodeData):
      self.show_status("Select a conversation to open")
      return

    conversation = node.data.conversation
    executable = shutil.which("claude")
    if not executable:
      self.show_status("claude CLI not found on PATH")
      return

    command = ["claude", "--resume", conversation.uuid]

    try:
      os.execv(executable, command)
    except OSError as error:  # pragma: no cover - defensive fallback
      self.show_status(f"Open failed: {error}")

  def action_refresh_tree(self) -> None:
    self.show_status("Refreshing conversations...")
    self.load_conversations(focus_uuid=self._selected_uuid)

  def action_toggle_scope(self) -> None:
    self.show_all_projects = not self.show_all_projects
    scope = "all projects" if self.show_all_projects else "current project"
    self.show_status(f"Switched to {scope}")
    self.load_conversations(focus_uuid=self._selected_uuid)

  def action_show_help(self) -> None:
    help_lines = [
      "Navigation:",
      "  j/k or arrows  Move selection",
      "  h/l            Collapse/expand",
      "  g / G          Jump to top/bottom",
      "",
      "Actions:",
      "  B              Branch selected conversation",
      "  O              Open in claude CLI",
      "  r              Refresh conversations",
      "  p              Toggle project scope",
      "  q              Quit",
    ]
    self.notify("\n".join(help_lines))

  def action_quit(self) -> None:
    self.exit()

  def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
    self._set_selected_from_node(event.node)

  def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
    self._set_selected_from_node(event.node)

  def show_status(self, message: str, duration: float = 3.0) -> None:
    status_line = self.query_one("#status_line", Static)
    status_line.update(message)
    if self._status_timer:
      self._status_timer.stop()
    self._status_timer = self.set_timer(duration, self._clear_status)

  def _clear_status(self) -> None:
    status_line = self.query_one("#status_line", Static)
    status_line.update("")
    if self._status_timer:
      self._status_timer.stop()
    self._status_timer = None

  def _focus_on_uuid(self, tree: Tree, uuid: str) -> None:
    node = self._node_lookup.get(uuid)
    if node:
      tree.cursor_node = node
      parent = node.parent
      while parent:
        parent.expand()
        parent = parent.parent
      self._set_selected_from_node(node)
      tree.scroll_to_node(node, animate=False)
    else:
      self._focus_first_child(tree)

  def _focus_first_child(self, tree: Tree) -> None:
    if tree.root.children:
      first_child = tree.root.children[0]
      tree.cursor_node = first_child
      self._set_selected_from_node(first_child)
      tree.scroll_to_node(first_child, animate=False)

  def _set_selected_from_node(self, node: Optional[TreeNode]) -> None:
    if node and isinstance(node.data, ConversationNodeData):
      self._selected_uuid = node.data.conversation.uuid

  def _build_previews(
    self, conversations: List[ConversationFile]
  ) -> Dict[str, str]:
    previews: Dict[str, str] = {}
    for conversation in conversations:
      previews[conversation.uuid] = self._extract_first_user_message(conversation)
    return previews

  def _extract_first_user_message(self, conversation: ConversationFile) -> str:
    try:
      with open(conversation.path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
          line = raw_line.strip()
          if not line:
            continue
          try:
            data = json.loads(line)
          except json.JSONDecodeError:
            continue

          message = data.get("message")
          if isinstance(message, dict) and message.get("role") == "user":
            if data.get("isMeta") is True:
              continue
            text = self._coerce_text(message)
            if text and not self._is_session_hook(text):
              return text

          if data.get("role") == "user":
            text = self._coerce_text(data)
            if text and not self._is_session_hook(text):
              return text
    except OSError:
      return ""
    return ""

  @staticmethod
  def _coerce_text(message: Dict[str, object]) -> str:
    if not isinstance(message, dict):
      return ""

    content = message.get("content")
    segments: List[str] = []

    if isinstance(content, list):
      for item in content:
        if isinstance(item, str):
          segments.append(item)
          continue
        if not isinstance(item, dict):
          continue
        if item.get("type") == "text":
          text_value = item.get("text")
          if isinstance(text_value, str):
            segments.append(text_value)
            continue
        text_value = item.get("text") or item.get("content")
        if isinstance(text_value, str):
          segments.append(text_value)
      if segments:
        return " ".join(segments)

    if isinstance(content, str):
      return content

    text_field = message.get("text")
    if isinstance(text_field, str):
      return text_field
    if isinstance(text_field, dict):
      inner_text = text_field.get("text")
      if isinstance(inner_text, str):
        return inner_text
    if isinstance(text_field, list):
      for item in text_field:
        if isinstance(item, str):
          segments.append(item)
        elif isinstance(item, dict):
          segment_text = item.get("text") or item.get("content")
          if isinstance(segment_text, str):
            segments.append(segment_text)
      if segments:
        return " ".join(segments)

    body = message.get("body")
    if isinstance(body, str):
      return body

    return ""

  @staticmethod
  def _is_session_hook(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("<session-start-hook>")

  @staticmethod
  def _format_preview(preview: str) -> str:
    if not preview:
      return "[no user message]"

    compressed = " ".join(preview.split())
    if len(compressed) <= _PREVIEW_LIMIT:
      return compressed
    return f"{compressed[:_PREVIEW_LIMIT - 3]}..."


if __name__ == "__main__":
  app = BushwackApp()
  app.run()
