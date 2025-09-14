"""CLI interface for claude-bushwack."""

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .core import ClaudeConversationManager
from .exceptions import (
  AmbiguousSessionIDError,
  BranchingError,
  ConversationNotFoundError,
  InvalidUUIDError,
)

console = Console()


@click.group(context_settings={'help_option_names': ['-h', '--help']})
@click.version_option()
def main():
  """Claude Bushwack - Branch your Claude Code conversations."""
  pass


@main.command(name='list')
@click.option(
  '--all', 'all_projects', is_flag=True, help='List conversations from all projects'
)
@click.option(
  '--project', 'project_path', help='List conversations from specific project path'
)
def list_conversations(all_projects, project_path):
  """List available conversations."""
  try:
    manager = ClaudeConversationManager()

    # Determine filtering parameters
    if all_projects:
      conversations = manager.find_all_conversations(all_projects=True)
      scope = 'all projects'
    elif project_path:
      conversations = manager.find_all_conversations(project_filter=project_path)
      scope = f'project: {project_path}'
    else:
      conversations = manager.find_all_conversations(current_project_only=True)
      current_project = manager._get_current_project_dir()
      if current_project:
        project_path_display = manager._project_dir_to_path(current_project)
        scope = f'current project: {project_path_display}'
      else:
        scope = 'current project (not found)'

    if not conversations:
      console.print(f'[yellow]No conversations found for {scope}.[/yellow]')
      return

    console.print(
      f'[green]Found {len(conversations)} conversation(s) for {scope}[/green]\n'
    )

    for conv in conversations:
      console.print(
        f"[cyan]{conv.uuid[:8]}...[/cyan] - {conv.project_dir} - {conv.last_modified.strftime('%Y-%m-%d %H:%M')}"
      )

  except Exception as e:
    console.print(f'[red]Error listing conversations: {e}[/red]')
    raise click.ClickException(str(e))


@main.command()
@click.argument('session_id')
@click.option(
  '--project',
  'target_project',
  help='Target project path for the branch (defaults to current directory)',
)
def branch(session_id, target_project):
  """Branch (copy) a conversation to current or specified project."""
  try:
    manager = ClaudeConversationManager()

    # Parse target project path
    target_path = Path(target_project) if target_project else None

    # Create the branch
    new_conversation = manager.branch_conversation(session_id, target_path)

    # Success message
    console.print(
      f'[green]Successfully branched conversation![/green]\n'
      f'  Source: {session_id}\n'
      f'  New ID: [cyan]{new_conversation.uuid}[/cyan]\n'
      f'  Project: {new_conversation.project_path}\n'
      f'  File: {new_conversation.path}'
    )

  except ConversationNotFoundError as e:
    console.print(f'[red]Error: {e}[/red]')
    console.print(
      "[yellow]Tip: Use 'claude-bushwack list --all' to see all available conversations[/yellow]"
    )
    raise click.ClickException(str(e))

  except AmbiguousSessionIDError as e:
    console.print(f'[red]Error: {e}[/red]')
    console.print('[yellow]Matching conversations:[/yellow]')

    table = Table(show_header=True, header_style='bold blue')
    table.add_column('Session ID', style='cyan')
    table.add_column('Project', style='green')
    table.add_column('Modified', style='yellow')

    for match in e.matches:
      table.add_row(
        match.uuid, match.project_path, match.last_modified.strftime('%Y-%m-%d %H:%M')
      )

    console.print(table)
    console.print(
      '[yellow]Use a longer session ID prefix to uniquely identify the conversation[/yellow]'
    )
    raise click.ClickException(str(e))

  except (InvalidUUIDError, BranchingError) as e:
    console.print(f'[red]Error: {e}[/red]')
    raise click.ClickException(str(e))

  except Exception as e:
    console.print(f'[red]Unexpected error: {e}[/red]')
    raise click.ClickException(str(e))


if __name__ == '__main__':
  main()
