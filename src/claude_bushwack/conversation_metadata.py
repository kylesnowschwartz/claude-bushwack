"""Utilities for extracting metadata from Claude conversation files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from .core import ConversationFile


@dataclass
class ConversationMetadata:
  """Metadata extracted from a Claude conversation transcript."""

  preview: str = ''
  summary: str = ''
  created_at: Optional[datetime] = None
  message_count: int = 0
  git_branch: Optional[str] = None


ConversationSource = Union[ConversationFile, Path, str]


def extract_conversation_metadata(source: ConversationSource) -> ConversationMetadata:
  """Parse the conversation file and return metadata for display/use."""
  path = _coerce_path(source)

  summary = ''
  preview = ''
  created_at: Optional[datetime] = None
  git_branch: Optional[str] = None
  message_count = 0

  try:
    with open(path, 'r', encoding='utf-8') as handle:
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
          parsed_timestamp = _parse_timestamp(timestamp_value)
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
            text = _coerce_text(message)
            if text and not _is_session_hook(text):
              preview = text
          continue

        if data.get('role') == 'user' and not preview:
          text = _coerce_text(data)
          if text and not _is_session_hook(text):
            preview = text

        if 'message' in data and not isinstance(message, dict):
          message_count += 1
  except OSError:
    return ConversationMetadata()

  return ConversationMetadata(
    preview=preview,
    summary=summary,
    created_at=created_at,
    message_count=message_count,
    git_branch=git_branch,
  )


def _coerce_path(source: ConversationSource) -> Path:
  if isinstance(source, ConversationFile):
    return source.path
  if isinstance(source, Path):
    return source
  return Path(source)


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


def _coerce_text(message: dict) -> str:
  if not isinstance(message, dict):
    return ''

  content = message.get('content')
  segments: list[str] = []

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


def _is_session_hook(text: str) -> bool:
  stripped = text.lstrip()
  return stripped.startswith('<session-start-hook>')
