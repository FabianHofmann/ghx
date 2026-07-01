# ghx

Standalone Python CLI scripts for GitHub workflows. Each script is self-contained using `uv run` with [PEP 723](https://peps.python.org/pep-0723/) inline script metadata — no virtual environment or `pip install` needed.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- [gh](https://cli.github.com/) CLI (authenticated)
- [Zed](https://zed.dev/) editor (for `select-comments.py`)

## Scripts

| Script | Description |
|---|---|
| `open-pr.py` | Opens current branch's PR in the browser |
| `pr-ci.py` | Interactive TUI to browse CI check statuses for the current branch's PR |
| `checkout-pr.py` | Interactive PR selector with checkout |
| `select-comments.py` | Browse unresolved PR review comments with code preview, reply, resolve, and clipboard copy |
| `notifications.py` | Browse unread GitHub notifications |
| `branch-context.py` | Live TUI showing the current branch's PR and its linked issues |

### open-pr.py

Opens the current branch's PR in your default browser. No TUI, just fire-and-forget.

### pr-ci.py

Full-screen TUI showing CI check statuses with background polling (15s). Falls back to a static Rich table when piped.

| Key | Action |
|---|---|
| `j/k`, `↑/↓` | Navigate |
| `Enter` | Open check URL |
| `r` | Refresh |
| `q`, `Esc` | Quit |

### checkout-pr.py

Interactive PR selector showing PR number, title, branch, author, and review status (draft/approved/changes-requested).

```
./checkout-pr.py       # All open PRs
./checkout-pr.py -m    # Only your PRs
```

| Key | Action |
|---|---|
| `j/k`, `↑/↓` | Navigate |
| `Enter` | Checkout PR |
| `b` | Open in browser |
| `q`, `Esc` | Quit |

### select-comments.py

Browse unresolved PR review threads with syntax-highlighted code snippets. Background polling (30s).

| Key | Action |
|---|---|
| `j/k` | Navigate |
| `Space`, `x` | Multi-select |
| `Enter` | Open in Zed |
| `b` | Open in browser |
| `a` | Reply inline |
| `c` | Copy Claude-formatted prompt to clipboard |
| `d` | Resolve thread |
| `r` | Refresh |
| `q` | Quit |

### notifications.py

Browse unread GitHub notifications. Auto-scopes to current repo when inside a git repo. Background polling (30s).

| Key | Action |
|---|---|
| `j/k`, `↑/↓` | Navigate |
| `Enter`, `b` | Open in browser |
| `d` | Mark done |
| `r` | Refresh |
| `q`, `Esc` | Quit |

### branch-context.py

Full-screen TUI showing the current branch's PR and the issues it closes (`closingIssuesReferences`), with their state and labels. Background polling (30s). Falls back to a static listing when piped.

| Key | Action |
|---|---|
| `j/k`, `↑/↓` | Navigate |
| `Enter`, `b` | Open in browser |
| `r` | Refresh |
| `q`, `Esc` | Quit |

## Setup

Add shell aliases to your `~/.zshrc` (or equivalent), adjusting the path:

```bash
alias ghb='/path/to/ghx/open-pr.py'
alias gha='/path/to/ghx/pr-ci.py'
alias ghp='/path/to/ghx/checkout-pr.py'
alias ghc='/path/to/ghx/select-comments.py'
alias ghn='/path/to/ghx/notifications.py'
alias ghx='/path/to/ghx/branch-context.py'
```

| Alias | Script | Mnemonic |
|---|---|---|
| `ghb` | `open-pr.py` | **b**rowser |
| `gha` | `pr-ci.py` | **a**ctions |
| `ghp` | `checkout-pr.py` | **p**ull requests |
| `ghc` | `select-comments.py` | **c**omments |
| `ghn` | `notifications.py` | **n**otifications |
| `ghx` | `branch-context.py` | conte**x**t |

Make sure the scripts are executable:

```bash
chmod +x /path/to/ghx/*.py
```

All interactive scripts share a Monokai dark theme and vim-style navigation.
