---
context_repo: claude-bushwack
example_conversation_files_dir: /Users/kyle/backups/claude/projects/-Users-kyle-Code-my-projects-claude-bushwack
textual_docs_root: /Users/kyle/Code/Cloned-Sources/textual
primary_widgets:
  - docs/widgets/tree.md
  - docs/widgets/directory_tree.md
  - src/textual/widgets/_tree.py
key_guides:
  - docs/guide/input.md
  - docs/guide/actions.md
notes: |
  Reference Textual source/docs above before introducing new patterns. Preserve
  minimalist styling and reuse existing CLI/core helpers when extending the TUI.
---

# TUI Plan
- Compose a minimalist `App` that yields only the conversation `Tree` plus an optional
  lightweight footer so focus stays on the list, relying on Textual's default dock
  layout rather than extra containers.
- Populate the tree by reusing `ClaudeConversationManager` lookups
  (`src/claude_bushwack/core.py:20`) and building nodes via `Tree.root.add` /
  `TreeNode.add_leaf`, mirroring the structure described for `TreeNode` usage
  (`docs/widgets/tree.md:16`).
- Store `ConversationNodeData` on each node so selection actions can resolve metadata
  (UUID, timestamps, first user message preview) without requerying disk, and refresh
  the tree by clearing / repopulating when scopes change. Truncate the preview for
  long conversations and note when no user message exists.
- Map vim-style keys at the `App.BINDINGS` level (`docs/guide/input.md:76`) to the
  widget's built-in actions such as `cursor_up/down`, `cursor_parent`, `toggle_node`,
  and `toggle_expand_all` (`src/textual/widgets/_tree.py:1468`), while leaving arrow
  keys available for parity.
- Keep styling "terminal-native" by mostly inheriting `Tree.DEFAULT_CSS`
  (`src/textual/widgets/_tree.py:524`), avoiding heavy customizations. Research what
  Textual exposes for matching the user's terminal palette and only adjust padding or
  focus hints when necessary; expose settings like `show_root` / `show_guides`
  (`docs/widgets/tree.md:28`) to let users pick their preferred look.
- Surface feedback unobtrusively: use the footer for key reminders (including `R` for
  refresh to pave the way for a future auto-refresh toggle), a transient status line
  for scope / refresh notices, and optional notifications for errors. Display node
  labels with UUID, timestamp, and the first user message snippet so users recognize
  the conversation they plan to branch.
- Bind `B` / `shift+b` to invoke the existing CLI branching workflow for the selected
  conversation without prompting, and keep arrow keys alongside vim-style bindings.
- Treat auto-refresh as a stretch goal: begin with manual refresh and leave hooks for
  future filesystem watcher integration.

## Documentation Notes
- `docs/widgets/tree.md:16` – outlines constructing trees via the root node and child
  `add` / `add_leaf` helpers.
- `docs/widgets/tree.md:28` – lists reactive flags (`show_root`, `show_guides`,
  `guide_depth`) useful for dialing back visual chrome.
- `docs/guide/input.md:76` – explains defining `BINDINGS` on apps / widgets, which we
  will use for vim-style keys.
- `src/textual/widgets/_tree.py:524` and `src/textual/widgets/_tree.py:1468` – provide
  the default bindings / CSS and the action methods we can reuse for navigation
  semantics.

## Completed So Far
- Implemented minimalist tree-first layout with footer/status strip and focus
  management (`src/claude_bushwack/tui.py:60`).
- Added node metadata: UUID, timestamp, and first user message snippet with graceful
  fallbacks for missing data (`src/claude_bushwack/tui.py:172`).
- Wired vim-style navigation plus `B` branching, `r` refresh, and `p` scope toggle to
  existing `ClaudeConversationManager` actions (`src/claude_bushwack/tui.py:202`).
- Preserved default Textual styling while keeping hooks to explore terminal palette
  matching later; no heavy CSS overrides introduced (current CSS-free layout).
- Introduced Phase 2 tree refinements: child-count indicators, 30-char previews,
  inline `O` resume action, automatic focus/scroll after branching, and smarter
  preview extraction that skips session hooks and meta caveats
  (`src/claude_bushwack/tui.py`).

## Phase 2 Requirements
- Display per-node depth / child indicators directly in each label so users can see
  which conversations have descendants without expanding them. ✅
- After branching, automatically refresh and focus the new branch so it is visible in
  the tree without requiring manual input. ✅
- Bind `O` to an "open" action that launches a terminal window in a new tab if possible,
  running `claude --resume <session_id>` for the selected conversation. ✅ (inline)
- Ensure conversation labels continue to show a truncated initial user prompt for
  quick identification, adjusting truncation length / formatting as needed for
  readability in combination with new depth indicators. ✅
