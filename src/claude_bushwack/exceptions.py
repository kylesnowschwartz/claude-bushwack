"""Custom exceptions for claude-bushwack."""

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
  from .core import ConversationFile


class ClaudeBushwackError(Exception):
  """Base exception for claude-bushwack errors."""

  pass


class ConversationNotFoundError(ClaudeBushwackError):
  """Raised when a conversation with the given session ID is not found."""

  def __init__(self, session_id: str):
    self.session_id = session_id
    super().__init__(f'No conversation found with ID: {session_id}')


class AmbiguousSessionIDError(ClaudeBushwackError):
  """Raised when a partial session ID matches multiple conversations."""

  def __init__(self, session_id: str, matches: List['ConversationFile']):
    self.session_id = session_id
    self.matches = matches
    super().__init__(
      f"Ambiguous session ID '{session_id}'. Found {len(matches)} matches."
    )


class BranchingError(ClaudeBushwackError):
  """Raised when branching a conversation fails."""

  def __init__(self, message: str, original_error: Exception = None):
    self.original_error = original_error
    super().__init__(message)


class InvalidUUIDError(ClaudeBushwackError):
  """Raised when provided UUID is not valid format."""

  def __init__(self, uuid_string: str):
    self.uuid_string = uuid_string
    super().__init__(f'Invalid UUID format: {uuid_string}')
