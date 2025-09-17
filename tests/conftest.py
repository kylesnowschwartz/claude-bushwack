"""Shared fixtures for claude-bushwack tests."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

import pytest

from claude_bushwack.core import ClaudeConversationManager

TESTS_DIR = Path(__file__).parent
SAMPLE_CONVERSATION_PATH = TESTS_DIR / 'assets' / 'sample_conversation.jsonl'


@dataclass
class ConversationLine:
  """Represents a single JSONL record for a test conversation."""

  type: str
  content: dict


@pytest.fixture
def projects_root(tmp_path: Path) -> Path:
  """Create an isolated Claude projects root for tests."""
  root = tmp_path / 'projects'
  root.mkdir()
  return root


@pytest.fixture
def project_dir(projects_root: Path) -> Path:
  """Return the project directory mirroring the real claude path."""
  project = projects_root / '-Users-kyle-Code-my-projects-claude-bushwack'
  project.mkdir()
  return project


@pytest.fixture
def conversation_factory(project_dir: Path) -> Callable[..., Path]:
  """Factory for authoring minimal Claude JSONL conversations."""

  def _create_conversation(
    uuid: str,
    *,
    parent_uuid: Optional[str] = None,
    summary: Optional[str] = None,
    preview_text: str = 'Initial prompt',
    assistant_text: str = 'Assistant reply',
    created_at: Optional[datetime] = None,
    git_branch: Optional[str] = None,
    extra_lines: Optional[Iterable[ConversationLine]] = None,
  ) -> Path:
    created = created_at or datetime(2024, 1, 1, tzinfo=timezone.utc)
    file_path = project_dir / f'{uuid}.jsonl'

    records: list[dict] = []
    if summary is not None:
      records.append({'type': 'summary', 'summary': summary})

    base_user_uuid = f'{uuid}-user'
    records.append(
      {
        'uuid': base_user_uuid,
        'parentUuid': parent_uuid,
        'type': 'user',
        'timestamp': created.isoformat().replace('+00:00', 'Z'),
        'gitBranch': git_branch or 'main',
        'message': {
          'role': 'user',
          'content': [{'type': 'text', 'text': preview_text}],
        },
      }
    )

    records.append(
      {
        'uuid': f'{uuid}-assistant',
        'parentUuid': base_user_uuid,
        'type': 'assistant',
        'timestamp': created.isoformat().replace('+00:00', 'Z'),
        'gitBranch': git_branch or 'main',
        'message': {
          'role': 'assistant',
          'content': [{'type': 'text', 'text': assistant_text}],
        },
      }
    )

    for line in extra_lines or []:
      record = dict(line.content)
      record.setdefault('type', line.type)
      records.append(record)

    with file_path.open('w', encoding='utf-8') as handle:
      for record in records:
        handle.write(json.dumps(record))
        handle.write('\n')

    return file_path

  return _create_conversation


@pytest.fixture
def manager(projects_root: Path) -> ClaudeConversationManager:
  """ClaudeConversationManager pointing at the isolated projects root."""
  return ClaudeConversationManager(claude_projects_dir=projects_root)


@pytest.fixture
def populated_manager(
  manager: ClaudeConversationManager,
  conversation_factory: Callable[..., Path],
  project_dir: Path,
) -> ClaudeConversationManager:
  """Manager preloaded with a small conversation tree."""
  # Root conversation without parent
  root_uuid = '11111111-1111-1111-1111-111111111111'
  conversation_factory(
    root_uuid, summary='Root summary', preview_text='Root preview', git_branch='main'
  )

  # Child conversation referencing root
  child_uuid = '22222222-2222-2222-2222-222222222222'
  conversation_factory(
    child_uuid,
    parent_uuid=root_uuid,
    summary=None,
    preview_text='Child preview',
    git_branch='feature/child',
  )

  # Orphan conversation referencing non-existent parent
  orphan_uuid = '33333333-3333-3333-3333-333333333333'
  conversation_factory(
    orphan_uuid,
    parent_uuid='99999999-9999-9999-9999-999999999999',
    summary=None,
    preview_text='Orphan preview',
    git_branch='feature/orphan',
  )

  return manager


@pytest.fixture
def sample_conversation(tmp_path: Path) -> Path:
  """Provide a deterministic conversation file for parsing tests."""
  if not SAMPLE_CONVERSATION_PATH.exists():
    raise FileNotFoundError(f'Missing sample conversation: {SAMPLE_CONVERSATION_PATH}')
  target = tmp_path / 'sample_conversation.jsonl'
  shutil.copy2(SAMPLE_CONVERSATION_PATH, target)
  return target


@pytest.fixture
def project_cwd(monkeypatch: pytest.MonkeyPatch) -> Path:
  """Patch ``Path.cwd`` to the claude-bushwack project path."""
  target = Path('/Users/kyle/Code/my-projects/claude-bushwack')
  monkeypatch.setattr('claude_bushwack.core.Path.cwd', lambda: target)
  return target
