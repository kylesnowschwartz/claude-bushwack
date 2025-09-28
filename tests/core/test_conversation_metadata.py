"""Tests for the conversation metadata extraction utilities."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from claude_bushwack.conversation_metadata import (
  ConversationMetadata,
  extract_conversation_metadata,
)


def _write_jsonl(
  path: Path, records: list[dict], *, trailing: str | None = None
) -> None:
  with path.open('w', encoding='utf-8') as handle:
    for record in records:
      handle.write(json.dumps(record))
      handle.write('\n')
    if trailing is not None:
      handle.write(trailing)


def test_extract_metadata_from_sample(sample_conversation: Path) -> None:
  metadata = extract_conversation_metadata(sample_conversation)

  assert isinstance(metadata, ConversationMetadata)
  assert metadata.summary == 'Investigate formatting helpers'
  assert metadata.preview == 'Review the TUI timestamp rendering'
  assert metadata.git_branch == 'feature/refine-formatting'
  assert metadata.message_count == 3

  expected_created_at = datetime(2024, 8, 10, 9, 15, tzinfo=timezone.utc)
  assert metadata.created_at == expected_created_at


def test_extract_metadata_skips_session_hook(tmp_path: Path) -> None:
  path = tmp_path / 'session_hook.jsonl'
  records = [
    {'type': 'summary', 'summary': 'Branch conversation'},
    {
      'type': 'user',
      'timestamp': '2024-01-01T00:00:00Z',
      'gitBranch': 'main',
      'message': {
        'role': 'user',
        'content': ['<session-start-hook> preparing environment'],
      },
    },
    {
      'type': 'user',
      'timestamp': '2024-01-01T00:00:05Z',
      'gitBranch': 'main',
      'message': {
        'role': 'user',
        'content': [{'type': 'text', 'text': 'Real first message'}],
      },
    },
  ]
  _write_jsonl(path, records)

  metadata = extract_conversation_metadata(path)

  assert metadata.summary == 'Branch conversation'
  assert metadata.preview == 'Real first message'
  assert metadata.message_count == 2
  expected_created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
  assert metadata.created_at == expected_created_at


def test_extract_metadata_handles_non_dict_message(tmp_path: Path) -> None:
  path = tmp_path / 'non_dict.jsonl'
  records = [
    {
      'type': 'user',
      'role': 'user',
      'timestamp': '2024-05-01T00:00:00Z',
      'gitBranch': 'feature/raw',
      'message': 'inline payload',
      'text': 'Preview from text field',
    }
  ]
  # Include an invalid JSON line to ensure it is skipped without raising.
  _write_jsonl(path, records, trailing='{not json}\n')

  metadata = extract_conversation_metadata(path)

  assert metadata.summary == ''
  assert metadata.preview == 'Preview from text field'
  assert metadata.git_branch == 'feature/raw'
  assert metadata.message_count == 1
  expected_created_at = datetime(2024, 5, 1, tzinfo=timezone.utc)
  assert metadata.created_at == expected_created_at
