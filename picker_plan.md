---
source_path: /Users/kyle/Code/Cloned-Sources/textual
references:
  - path: src/textual/screen.py
    lines: 1876-1891
    description: ModalScreen base styling and semantics
  - path: src/textual/app.py
    lines: 2756-2790
    description: App.push_screen usage and screen-stack handling
  - path: src/textual/widgets/_directory_tree.py
    lines: 32-489
    description: DirectoryTree structure, filtering, and reload logic
  - path: docs/examples/widgets/directory_tree_filtered.py
    lines: 8-15
    description: Example of DirectoryTree subclass filtering entries
  - path: src/textual/widgets/_input.py
    lines: 70-296
    description: Input widget bindings, reactivity, and change messages
---

## Purpose

Enable conversation copies to target any Claude project by giving users an in-app directory picker that feeds the existing branch/copy workflow and updates metadata safely.

## Directory Picker Integration Plan

- Implement a folder-only selector by subclassing Textual's `DirectoryTree`, filtering non-directory entries, and reacting to `DirectorySelected` events for user confirmation.
- Wrap the picker in a `ModalScreen` so it can be pushed over the TUI, matching Textual's screen-stack behavior and dimming the background for focus.
- Add an `Input` field to drive live filtering of the tree; connect its change events to the tree's `reload()` logic and filter hook to keep the listing responsive in large project sets.
- Integrate the selected directory with the conversation copy flow: resolve the Claude project directory name, copy the JSONL, rewrite any project-specific metadata, then dismiss the modal and refresh the conversations view.

## Unknowns & Open Requirements

- Audit conversation metadata to determine fields requiring updates when relocating files (see `src/claude_bushwack/core.py` and sample transcripts under `tests/assets/`). Identify path- or project-dependent keys and design rewrite steps for the copy workflow.
- Which JSONL fields beyond `parentUuid`/`gitBranch` encode project-specific paths and must be rewritten? Need to inspect real conversation exports for additional metadata.
- UX entry point: do we trigger the picker from the existing `branch` binding, a new command, or both TUI and CLI? Requires alignment with `BushwackApp` command model.
- User-friendly labeling: how should we display Claude’s encoded project directory names so selections map clearly to actual paths (`_path_to_project_dir` vs. `_project_dir_to_path`)?
- Copied conversation behavior: should we maintain timestamps/ordering or adjust them when placing the conversation in the new project? Clarify expectations.
- Cross-project permissions: do we need to guard against copying into non-existent or restricted directories outside `~/.claude/projects`, or is the picker constrained to that root?

## Testing

- Unit test metadata rewriting with fixture transcripts to ensure project-specific fields (e.g., `gitBranch`, relative paths) adapt to new destinations.
- Add Textual widget tests exercising the modal picker: simulate typing in the search input, confirm filtered nodes, and validate that `DirectorySelected` dismisses the screen with the chosen path.
- Run end-to-end CLI/TUI tests that invoke the copy flow, verifying the new file lands in `~/.claude/projects/<target>` and maintains parent-child linkage without corrupting timestamps.

## Status Notes (2025-02-14)

- Core rewrite logic now runs during `branch_conversation`; JSONL records update `gitBranch`, `projectDir`, and `workspaceRoot` automatically, but double-check other Claude export keys (e.g., nested `workspace*` variants) once we have more sample data.
- TUI picker modal (`DirectoryPickerScreen`) and filtered `ProjectDirectoryTree` are wired in; tests cover typing filters and selection callbacks. Manual TUI pass still recommended to validate focus/scroll behaviour with large project sets.
- CLI branch flow exercises metadata rewriting via new test, so regression coverage exists end-to-end; if we later expose picker in CLI, revisit interface contract.
- Remaining questions: confirm how to surface friendly project names in the picker (current label shows decoded path), decide whether to constrain to `~/.claude/projects` or allow browsing elsewhere, and capture requirements around timestamp adjustments before closing the plan.
