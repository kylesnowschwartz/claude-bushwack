"""Core functionality for claude-bushwack."""

import json
import re
import shutil
import uuid as uuid_module
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
  parent_uuid: Optional[str] = None


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

  def _get_parent_uuid(self, conversation_file: Path) -> Optional[str]:
    """Extract parentUuid from the first line of a JSONL conversation file."""
    try:
      with open(conversation_file, 'r') as f:
        first_line = f.readline().strip()
        if first_line:
          data = json.loads(first_line)
          parent_uuid = data.get('parentUuid')
          return parent_uuid if parent_uuid else None
      return None
    except (OSError, json.JSONDecodeError):
      return None

  def _set_parent_uuid_in_jsonl(
    self, conversation_file: Path, parent_uuid: str
  ) -> None:
    """Set the parentUuid in the first line of a JSONL conversation file."""
    try:
      # Read the file
      with open(conversation_file, 'r') as f:
        first_line = f.readline()
        rest_of_file = f.read()

      # Parse and modify the first line
      data = json.loads(first_line)
      data['parentUuid'] = parent_uuid

      # Write back to file
      with open(conversation_file, 'w') as f:
        f.write(json.dumps(data) + '\n')
        f.write(rest_of_file)
    except (OSError, json.JSONDecodeError) as e:
      raise BranchingError(f'Failed to set parentUuid in JSONL file: {e}', e)

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

              # Get parent UUID from JSONL file
              parent_uuid = self._get_parent_uuid(file_path)

              conversation = ConversationFile(
                path=file_path,
                uuid=uuid,
                project_dir=project_dir_name,
                project_path=str(project_path),
                last_modified=last_modified,
                parent_uuid=parent_uuid,
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
      else:
        target_project_path = Path(target_project_path)

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

      # Set the parentUuid in the copied file
      self._set_parent_uuid_in_jsonl(target_file_path, source_conversation.uuid)

      source_project_path = Path(source_conversation.project_path)
      git_branch = self._detect_git_branch(target_project_path)
      self._rewrite_project_metadata(
        target_file_path,
        source_project_path,
        target_project_path,
        source_conversation.project_dir,
        target_project_dir,
        git_branch,
      )

      # Create and return new ConversationFile object
      return ConversationFile(
        path=target_file_path,
        uuid=new_uuid,
        project_dir=target_project_dir,
        project_path=str(target_project_path),
        last_modified=datetime.now(),
        parent_uuid=source_conversation.uuid,
      )

    except (ConversationNotFoundError, AmbiguousSessionIDError, InvalidUUIDError):
      # Re-raise conversation finding errors as-is
      raise
    except Exception as e:
      raise BranchingError(f'Failed to branch conversation: {e}', e)

  def _detect_git_branch(self, project_path: Path) -> Optional[str]:
    git_dir = project_path / '.git'
    head_file = git_dir / 'HEAD'
    try:
      head_content = head_file.read_text(encoding='utf-8').strip()
    except OSError:
      return None

    if not head_content:
      return None

    if head_content.startswith('ref:'):
      ref = head_content[4:].strip()
      if not ref:
        return None
      return Path(ref).name

    return head_content

  def _rewrite_project_metadata(
    self,
    conversation_file: Path,
    source_project_path: Path,
    target_project_path: Path,
    source_project_dir: str,
    target_project_dir: str,
    git_branch: Optional[str],
  ) -> None:
    try:
      with conversation_file.open('r', encoding='utf-8') as handle:
        lines = handle.readlines()
    except OSError:
      return

    parsed_records: List[Tuple[str, Optional[Any]]] = []
    for raw_line in lines:
      stripped = raw_line.rstrip('\n')
      record: Optional[Any]
      if not stripped.strip():
        record = None
      else:
        try:
          record = json.loads(stripped)
        except json.JSONDecodeError:
          record = None
      parsed_records.append((stripped, record))

    source_path_candidates = {str(source_project_path)}
    source_dir_candidates = {source_project_dir}

    for _, data in parsed_records:
      if data is not None:
        self._collect_metadata_candidates(
          data, source_path_candidates, source_dir_candidates
        )

    updated_lines: List[str] = []
    for stripped, data in parsed_records:
      if data is None:
        updated_lines.append(stripped)
        continue

      mutated = self._rewrite_metadata_node(
        data,
        source_project_path,
        target_project_path,
        source_project_dir,
        target_project_dir,
        git_branch,
        source_path_candidates,
        source_dir_candidates,
      )
      updated_lines.append(json.dumps(mutated))

    try:
      with conversation_file.open('w', encoding='utf-8') as handle:
        for line in updated_lines:
          handle.write(f'{line}\n')
    except OSError:
      # Ignore write errors; the copy already exists even if metadata isn't ideal.
      return

  _BRANCH_KEYS = {'gitBranch'}
  _PROJECT_DIR_KEYS = {'projectDir', 'projectDirectory'}
  _PROJECT_PATH_KEYS = {
    'workspaceRoot',
    'workspacePath',
    'projectPath',
    'projectRoot',
    'cwd',
    'repoPath',
  }

  def _collect_metadata_candidates(
    self,
    value: Any,
    path_candidates: set[str],
    dir_candidates: set[str],
    *,
    key: Optional[str] = None,
  ) -> None:
    if isinstance(value, dict):
      for field, field_value in value.items():
        self._collect_metadata_candidates(
          field_value, path_candidates, dir_candidates, key=field
        )
      return

    if isinstance(value, list):
      for item in value:
        self._collect_metadata_candidates(
          item, path_candidates, dir_candidates, key=key
        )
      return

    if not isinstance(value, str):
      return

    if key in self._PROJECT_PATH_KEYS:
      path_candidates.add(value)
    if key in self._PROJECT_DIR_KEYS:
      dir_candidates.add(value)

  def _rewrite_metadata_node(
    self,
    value: Any,
    source_project_path: Path,
    target_project_path: Path,
    source_project_dir: str,
    target_project_dir: str,
    git_branch: Optional[str],
    source_path_candidates: set[str],
    source_dir_candidates: set[str],
    *,
    key: Optional[str] = None,
  ) -> Any:
    if isinstance(value, dict):
      return {
        field: self._rewrite_metadata_node(
          field_value,
          source_project_path,
          target_project_path,
          source_project_dir,
          target_project_dir,
          git_branch,
          source_path_candidates,
          source_dir_candidates,
          key=field,
        )
        for field, field_value in value.items()
      }

    if isinstance(value, list):
      return [
        self._rewrite_metadata_node(
          item,
          source_project_path,
          target_project_path,
          source_project_dir,
          target_project_dir,
          git_branch,
          source_path_candidates,
          source_dir_candidates,
          key=key,
        )
        for item in value
      ]

    if isinstance(value, str):
      return self._rewrite_metadata_string(
        key,
        value,
        source_project_path,
        target_project_path,
        source_project_dir,
        target_project_dir,
        git_branch,
        source_path_candidates,
        source_dir_candidates,
      )

    return value

  def _rewrite_metadata_string(
    self,
    key: Optional[str],
    value: str,
    source_project_path: Path,
    target_project_path: Path,
    source_project_dir: str,
    target_project_dir: str,
    git_branch: Optional[str],
    source_path_candidates: set[str],
    source_dir_candidates: set[str],
  ) -> str:
    if git_branch and key in self._BRANCH_KEYS:
      return git_branch

    if key in self._PROJECT_DIR_KEYS:
      for candidate in source_dir_candidates:
        swapped = self._swap_metadata_value(value, candidate, target_project_dir)
        if swapped != value:
          return swapped
      return value

    if key in self._PROJECT_PATH_KEYS:
      target_path_str = str(target_project_path)
      for candidate in source_path_candidates:
        swapped = self._swap_metadata_value(value, candidate, target_path_str)
        if swapped != value:
          return swapped
      return value

    if value in source_dir_candidates:
      return target_project_dir

    target_path_str = str(target_project_path)
    if value in source_path_candidates:
      return target_path_str

    return value

  @staticmethod
  def _swap_metadata_value(value: str, old: str, new: str) -> str:
    if not old:
      return value
    if value == old:
      return new
    if old in value:
      return value.replace(old, new)
    return value

  def build_conversation_tree(
    self, conversations: List[ConversationFile]
  ) -> Tuple[List[ConversationFile], Dict[str, List[ConversationFile]]]:
    """Build a tree structure from conversations based on parent-child relationships.

    Args:
        conversations: List of ConversationFile objects

    Returns:
        Tuple of (root_conversations, children_dict)
        - root_conversations: Conversations with no parent
        - children_dict: Dict mapping parent UUID to list of child conversations
    """
    children_dict = defaultdict(list)
    roots = []

    for conversation in conversations:
      if conversation.parent_uuid:
        children_dict[conversation.parent_uuid].append(conversation)
      else:
        roots.append(conversation)

    return roots, children_dict

  def get_conversation_ancestry(self, session_id: str) -> List[ConversationFile]:
    """Get the full ancestry chain for a conversation (from root to current).

    Args:
        session_id: UUID of the conversation to trace

    Returns:
        List of ConversationFile objects representing the ancestry chain

    Raises:
        ConversationNotFoundError: If session_id not found
    """
    conversation = self.find_conversation(session_id)
    ancestry = [conversation]

    # Walk up the parent chain
    current = conversation
    seen_uuids = {current.uuid}  # Prevent infinite loops

    while current.parent_uuid and current.parent_uuid not in seen_uuids:
      seen_uuids.add(current.parent_uuid)
      try:
        parent = self.find_conversation(current.parent_uuid)
        ancestry.insert(0, parent)  # Add to beginning
        current = parent
      except ConversationNotFoundError:
        # Parent not found, stop traversing
        break

    return ancestry
