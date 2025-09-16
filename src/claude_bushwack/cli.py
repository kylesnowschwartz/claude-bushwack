"""CLI interface for claude-bushwack."""

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from .core import ClaudeConversationManager
from .exceptions import (AmbiguousSessionIDError, BranchingError,
                         ConversationNotFoundError, InvalidUUIDError)

console = Console()


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option()
def main():
    """Claude Bushwack - Branch your Claude Code conversations."""
    pass


@main.command(name="list")
@click.option(
    "--all", "all_projects", is_flag=True, help="List conversations from all projects"
)
@click.option(
    "--project", "project_path", help="List conversations from specific project path"
)
@click.option(
    "--tree",
    is_flag=True,
    help="Show conversations in tree format (parent-child relationships)",
)
def list_conversations(all_projects, project_path, tree):
    """List available conversations."""
    try:
        manager = ClaudeConversationManager()

        # Determine filtering parameters
        if all_projects:
            conversations = manager.find_all_conversations(all_projects=True)
            scope = "all projects"
        elif project_path:
            conversations = manager.find_all_conversations(project_filter=project_path)
            scope = f"project: {project_path}"
        else:
            conversations = manager.find_all_conversations(current_project_only=True)
            current_project = manager._get_current_project_dir()
            if current_project:
                project_path_display = manager._project_dir_to_path(current_project)
                scope = f"current project: {project_path_display}"
            else:
                scope = "current project (not found)"

        if not conversations:
            console.print(f"[yellow]No conversations found for {scope}.[/yellow]")
            return

        console.print(
            f"[green]Found {len(conversations)} conversation(s) for {scope}[/green]\n"
        )

        if tree:
            # Show tree format
            roots, children_dict = manager.build_conversation_tree(conversations)

            if roots:
                tree_view = Tree("🌳 Conversation Tree")

                def add_conversation_to_tree(parent_node, conv, children):
                    # Create label with conversation info
                    parent_text = " (parent)" if not conv.parent_uuid else " (branch)"
                    label = f"[cyan]{conv.uuid[:8]}...[/cyan] - {conv.last_modified.strftime('%Y-%m-%d %H:%M')}{parent_text}"

                    conv_node = parent_node.add(label)

                    # Add children recursively
                    if conv.uuid in children:
                        for child in sorted(
                            children[conv.uuid], key=lambda c: c.last_modified
                        ):
                            add_conversation_to_tree(conv_node, child, children)

                # Add all root conversations
                for root in sorted(roots, key=lambda c: c.last_modified, reverse=True):
                    add_conversation_to_tree(tree_view, root, children_dict)

                console.print(tree_view)

            # Show orphaned branches (children whose parents aren't in the current scope)
            orphaned = [
                conv
                for conv in conversations
                if conv.parent_uuid
                and conv.parent_uuid not in [c.uuid for c in conversations]
            ]
            if orphaned:
                console.print(
                    "\n[yellow]🔗 Orphaned branches (parent not in current scope):[/yellow]"
                )
                for conv in sorted(
                    orphaned, key=lambda c: c.last_modified, reverse=True
                ):
                    console.print(
                        f"  [dim]└─[/dim] [cyan]{conv.uuid[:8]}...[/cyan] - parent: [dim]{conv.parent_uuid[:8]}...[/dim] - {conv.last_modified.strftime('%Y-%m-%d %H:%M')}"
                    )
        else:
            # Show flat format
            for conv in conversations:
                parent_info = (
                    f" (branch of {conv.parent_uuid[:8]}...)"
                    if conv.parent_uuid
                    else ""
                )
                console.print(
                    f'[cyan]{conv.uuid}[/cyan] - {conv.project_dir} - {conv.last_modified.strftime("%Y-%m-%d %H:%M")}{parent_info}'
                )

    except Exception as e:
        console.print(f"[red]Error listing conversations: {e}[/red]")
        raise click.ClickException(str(e))


@main.command()
@click.argument("session_id")
@click.option(
    "--project",
    "target_project",
    help="Target project path for the branch (defaults to current directory)",
)
def branch(session_id, target_project):
    """Branch (copy) a conversation to current or specified project.

    Creates a copy of the conversation and sets up parent-child relationship
    for tracking conversation lineage. Use 'tree' command to view ancestry."""
    try:
        manager = ClaudeConversationManager()

        # Parse target project path
        target_path = Path(target_project) if target_project else None

        # Create the branch
        new_conversation = manager.branch_conversation(session_id, target_path)

        # Success message
        console.print(
            f"[green]Successfully branched conversation![/green]\n"
            f"  Source: {session_id}\n"
            f"  New ID: [cyan]{new_conversation.uuid}[/cyan]\n"
            f"  Project: {new_conversation.project_path}\n"
            f"  File: {new_conversation.path}"
        )

    except ConversationNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print(
            "[yellow]Tip: Use 'claude-bushwack list --all' to see all available conversations[/yellow]"
        )
        raise click.ClickException(str(e))

    except AmbiguousSessionIDError as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print("[yellow]Matching conversations:[/yellow]")

        table = Table(show_header=True, header_style="bold blue")
        table.add_column("Session ID", style="cyan")
        table.add_column("Project", style="green")
        table.add_column("Modified", style="yellow")

        for match in e.matches:
            table.add_row(
                match.uuid,
                match.project_path,
                match.last_modified.strftime("%Y-%m-%d %H:%M"),
            )

        console.print(table)
        console.print(
            "[yellow]Use a longer session ID prefix to uniquely identify the conversation[/yellow]"
        )
        raise click.ClickException(str(e))

    except (InvalidUUIDError, BranchingError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.ClickException(str(e))

    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
        raise click.ClickException(str(e))


@main.command()
@click.argument("session_id")
def tree(session_id):
    """Show the full ancestry tree for a conversation."""
    try:
        manager = ClaudeConversationManager()

        # Get the ancestry chain
        ancestry = manager.get_conversation_ancestry(session_id)

        if len(ancestry) == 1:
            console.print(
                f"[cyan]{ancestry[0].uuid}[/cyan] has no parent (original conversation)"
            )
            return

        console.print("[green]Conversation Ancestry Chain:[/green]\n")

        # Display the ancestry chain
        for i, conv in enumerate(ancestry):
            is_current = i == len(ancestry) - 1
            is_root = i == 0

            if is_root:
                prefix = "🌱"
                suffix = " (original)"
            elif is_current:
                prefix = "📍"
                suffix = " (current)"
            else:
                prefix = "├─"
                suffix = ""

            console.print(
                f"{prefix} [cyan]{conv.uuid[:8]}...[/cyan] - {conv.project_path} - {conv.last_modified.strftime('%Y-%m-%d %H:%M')}{suffix}"
            )

        # Show children if any
        all_conversations = manager.find_all_conversations(all_projects=True)
        children = [
            conv for conv in all_conversations if conv.parent_uuid == ancestry[-1].uuid
        ]

        if children:
            console.print("\n[green]Children of current conversation:[/green]")
            for child in sorted(children, key=lambda c: c.last_modified):
                console.print(
                    f"  └─ [cyan]{child.uuid[:8]}...[/cyan] - {child.project_path} - {child.last_modified.strftime('%Y-%m-%d %H:%M')}"
                )

    except ConversationNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print(
            "[yellow]Tip: Use 'claude-bushwack list --all' to see all available conversations[/yellow]"
        )
        raise click.ClickException(str(e))

    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
        raise click.ClickException(str(e))


@main.command()
def tui():
    """Launch the interactive TUI (Terminal User Interface)."""
    try:
        from .tui import BushwackApp

        app = BushwackApp()
        app.run()
    except ImportError as e:
        if "textual" in str(e):
            console.print("[red]Error: Textual is not installed.[/red]")
            console.print("[yellow]Install it with: poetry add textual[/yellow]")
        else:
            console.print(f"[red]Import error: {e}[/red]")
        raise click.ClickException(str(e))
    except Exception as e:
        console.print(f"[red]Error launching TUI: {e}[/red]")
        raise click.ClickException(str(e))


if __name__ == "__main__":
    main()
