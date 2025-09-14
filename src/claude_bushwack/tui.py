"""TUI interface for claude-bushwack using Textual."""

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static


class BushwackApp(App):
  """Main TUI application for claude-bushwack."""

  def compose(self) -> ComposeResult:
    """Create child widgets for the app."""
    yield Header()
    yield Static('Claude Bushwack TUI - Starting from scratch')
    yield Footer()


if __name__ == '__main__':
  app = BushwackApp()
  app.run()
