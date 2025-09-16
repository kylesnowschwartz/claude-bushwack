"""Smoke tests for custom exceptions."""

from __future__ import annotations

from claude_bushwack.exceptions import (
  AmbiguousSessionIDError,
  ConversationNotFoundError,
  InvalidUUIDError,
)


def test_conversation_not_found_message() -> None:
  error = ConversationNotFoundError('abc123')
  assert 'abc123' in str(error)


def test_ambiguous_session_id_message() -> None:
  error = AmbiguousSessionIDError('deadbeef', [])
  assert 'deadbeef' in str(error)


def test_invalid_uuid_message() -> None:
  error = InvalidUUIDError('???')
  assert '???' in str(error)
