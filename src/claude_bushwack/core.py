"""Core functionality for claude-bushwack."""

import re
import shutil
import uuid as uuid_module
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .exceptions import (
  AmbiguousSessionIDError,
  BranchingError,
  ConversationNotFoundError,
  InvalidUUIDError,
)


@dataclass
class ConversationFile:
  """Represents a Claude conversation file."""

  path: Path
  uuid: str
  project_dir: str
  project_path: str
  last_modified: datetime


class ClaudeConversationManager:
  """Manages Claude Code conversation files."""

  def __init__(self, claude_projects_dir: Optional[Path] = None):
    if claude_projects_dir is None:
      claude_projects_dir = Path.home() / '.claude' / 'projects'
    self.claude_projects_dir = claude_projects_dir

  def _path_to_project_dir(self, path: Path) -> str:
    """Convert filesystem path to Claude project directory name."""
    # Replace forward slashes with dashes
    path_str = str(path).replace('/', '-')
    # Replace single dots with double dashes (for hidden directories like .config)
    path_str = path_str.replace('-.', '--')
    return path_str

  def _project_dir_to_path(self, project_dir: str) -> Path:
    """Convert Claude project directory name back to filesystem path."""
    # First replace double dashes with -.
    path_str = project_dir.replace('--', '-.')
    # Then replace remaining single dashes with /
    path_str = path_str.replace('-', '/')
    return Path(path_str)

  def _get_current_project_dir(self) -> Optional[str]:
    """Get project directory name for current working directory."""
    current_path = Path.cwd()
    return self._path_to_project_dir(current_path)

  def find_all_conversations(
    self,
    project_filter: Optional[str] = None,
    current_project_only: bool = True,
    all_projects: bool = False,
  ) -> List[ConversationFile]:
    """Find all conversation JSONL files in Claude projects directory.

    Args:
        project_filter: Specific project directory path to filter by
        current_project_only: Only return conversations for current working directory
        all_projects: Return conversations from all projects

    Returns:
        List of ConversationFile objects sorted by last_modified (newest first)
    """
    if not self.claude_projects_dir.exists():
      return []

    conversations = []
    uuid_pattern = re.compile(
      r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl$'
    )

    # Determine which project directories to search
    target_project_dirs = []

    if all_projects:
      # Search all project directories
      for project_dir in self.claude_projects_dir.iterdir():
        if project_dir.is_dir():
          target_project_dirs.append(project_dir.name)
    elif project_filter:
      # Search specific project directory
      project_dir_name = self._path_to_project_dir(Path(project_filter))
      if (self.claude_projects_dir / project_dir_name).exists():
        target_project_dirs.append(project_dir_name)
    elif current_project_only:
      # Search current project only
      current_project_dir = self._get_current_project_dir()
      if (
        current_project_dir
        and (self.claude_projects_dir / current_project_dir).exists()
      ):
        target_project_dirs.append(current_project_dir)

    # Collect conversation files from target directories
    for project_dir_name in target_project_dirs:
      project_dir_path = self.claude_projects_dir / project_dir_name

      try:
        if not project_dir_path.exists() or not project_dir_path.is_dir():
          continue

        for file_path in project_dir_path.iterdir():
          try:
            if file_path.is_file() and uuid_pattern.match(file_path.name):
              uuid = file_path.stem
              project_path = self._project_dir_to_path(project_dir_name)

              # Get file modification time safely
              try:
                last_modified = datetime.fromtimestamp(file_path.stat().st_mtime)
              except (OSError, OverflowError):
                # Fallback to current time if stat fails
                last_modified = datetime.now()

              conversation = ConversationFile(
                path=file_path,
                uuid=uuid,
                project_dir=project_dir_name,
                project_path=str(project_path),
                last_modified=last_modified,
              )
              conversations.append(conversation)
          except (OSError, PermissionError):
            # Skip files we can't access
            continue
      except (OSError, PermissionError):
        # Skip directories we can't access
        continue

    # Sort by last modified time (newest first)
    conversations.sort(key=lambda c: c.last_modified, reverse=True)
    return conversations

  def find_conversation(self, session_id: str) -> ConversationFile:
    """Find a specific conversation by full or partial session ID.

    Args:
        session_id: Full UUID or partial UUID string

    Returns:
        ConversationFile object

    Raises:
        ConversationNotFoundError: If no matching conversation is found
        AmbiguousSessionIDError: If partial ID matches multiple conversations
        InvalidUUIDError: If the session_id format is invalid
    """
    # Validate UUID format (allow partial UUIDs)
    if not re.match(r'^[0-9a-f-]+$', session_id.lower()):
      raise InvalidUUIDError(session_id)

    # Get all conversations
    all_conversations = self.find_all_conversations(all_projects=True)

    # First try exact match
    exact_matches = [conv for conv in all_conversations if conv.uuid == session_id]
    if exact_matches:
      return exact_matches[0]

    # Then try partial match from beginning
    partial_matches = [
      conv for conv in all_conversations if conv.uuid.startswith(session_id)
    ]

    if not partial_matches:
      raise ConversationNotFoundError(session_id)
    elif len(partial_matches) == 1:
      return partial_matches[0]
    else:
      raise AmbiguousSessionIDError(session_id, partial_matches)

  def branch_conversation(
    self, session_id: str, target_project_path: Optional[Path] = None
  ) -> ConversationFile:
    """Create a branch (copy) of an existing conversation.

    Args:
        session_id: Full or partial UUID of conversation to branch
        target_project_path: Project path for new conversation (defaults to current)

    Returns:
        ConversationFile object representing the new branched conversation

    Raises:
        ConversationNotFoundError: If source conversation not found
        BranchingError: If branching operation fails
    """
    try:
      # Find the source conversation
      source_conversation = self.find_conversation(session_id)

      # Determine target project directory
      if target_project_path is None:
        target_project_path = Path.cwd()

      target_project_dir = self._path_to_project_dir(target_project_path)
      target_dir_path = self.claude_projects_dir / target_project_dir

      # Create target directory if it doesn't exist
      target_dir_path.mkdir(parents=True, exist_ok=True)

      # Generate new UUID for the branch
      new_uuid = str(uuid_module.uuid4())
      new_filename = f'{new_uuid}.jsonl'
      target_file_path = target_dir_path / new_filename

      # Copy the conversation file
      shutil.copy2(source_conversation.path, target_file_path)

      # Create and return new ConversationFile object
      return ConversationFile(
        path=target_file_path,
        uuid=new_uuid,
        project_dir=target_project_dir,
        project_path=str(target_project_path),
        last_modified=datetime.now(),
      )

    except (ConversationNotFoundError, AmbiguousSessionIDError, InvalidUUIDError):
      # Re-raise conversation finding errors as-is
      raise
    except Exception as e:
      raise BranchingError(f'Failed to branch conversation: {e}', e)
