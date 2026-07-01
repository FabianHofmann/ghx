## Project Overview

Standalone Python CLI scripts for GitHub workflows using `uv run` with PEP 723 inline script metadata. Each script is self-contained with its dependencies declared inline.

## Running Scripts

Scripts are executed directly via `uv run`:
```bash
./open-pr.py          # Opens current branch's PR in browser
./pr-ci.py            # Shows running CI checks for current branch's PR
./checkout-pr.py      # Interactive PR selector and checkout
./checkout-pr.py -m   # Show only PRs authored by current user
./select-comments.py  # Browse unresolved PR comments, open in Zed
./notifications.py    # Show unread notifications
./branch-context.py   # Show current branch's PR and its linked issues
```

## Architecture

**Script Pattern**: Each script uses the shebang `#!/usr/bin/env -S uv run` with inline dependency declarations:
```python
# /// script
# requires-python = ">=3.11"
# dependencies = ["prompt_toolkit", "rich"]
# ///
```

**External Dependencies**:
- `gh` CLI for all GitHub API interactions
- `zed` editor for opening files from `select-comments.py`

**UI Pattern**: Interactive scripts use `prompt_toolkit` with Monokai-style themes for TUI selectors with vim-style navigation (j/k/↑/↓).

**Usage**: 

The scripts are referenced in ~/.zshrc with aliases in the section beginning with `# EDITOR-SCRIPT-ALIASES` following the pattern `alias <short-command>=<script_path>`. Adjust relevant aliases as needed. Make sure the scripts are executable (`chmod +x <script_path>`).
