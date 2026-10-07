# ghx

A combined GitHub TUI for everyday PR workflows: browse and checkout PRs, watch CI checks, work through unresolved review comments, and triage notifications — all in one full-screen app with a persistent branch-context status bar.

Runs standalone via `uv run` with [PEP 723](https://peps.python.org/pep-0723/) inline script metadata — no virtual environment or `pip install` needed.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- [gh](https://cli.github.com/) CLI (authenticated)
- [Zed](https://zed.dev/) editor (for opening review comments)

## Usage

```bash
./ghx.py             # Start on the PRs view
./ghx.py ci          # Start on a specific view (prefix-matched: prs, ci, comments, notifs)
./ghx.py -m          # PRs view filtered to PRs authored by me
./ghx.py | cat       # Non-interactive: print branch context (current PR + linked issues)
```

Outside a git repository only `ghx notifs` works (notifications across all repos).

## Views

Switch views with `1`–`5` or `Tab`/`Shift-Tab`. Global keys everywhere:

| Key | Action |
|---|---|
| `1`–`5`, `Tab` | Switch view |
| `j/k`, `↑/↓` | Navigate |
| `r` | Refresh active view |
| `o` | Open current branch's PR in browser |
| `q`, `Esc` | Quit |

### 1 · PRs

Open PRs with branch, author, and review status (draft/approved/changes/review/pending). Prefetched before the TUI imports for a fast start.

| Key | Action |
|---|---|
| `Enter` | Open in browser |
| `c` | Checkout PR |
| `f` | Find: filter loaded PRs live by number, title, branch or author; `Enter` searches GitHub; `Esc` clears |
| `m` | Toggle "only my PRs" filter |

### 2 · Issues

Open issues (latest 50) with assignee and colored label chips.

| Key | Action |
|---|---|
| `Enter` | Open in browser |
| `f` | Find: filter loaded issues live by number, title, author or label; `Enter` searches GitHub (all issues, whole words, [search syntax](https://docs.github.com/en/search-github/searching-on-github/searching-issues-and-pull-requests)); `Esc` clears |
| `l` | Label filter panel |
| `m` | Toggle "assigned to me" filter |

### 3 · CI

CI check statuses for the current branch's PR. Background polling (15s) flags updates with `● new`; `r` applies them.

| Key | Action |
|---|---|
| `Enter` | Open check URL |

### 4 · Comments

Unresolved PR review threads with syntax-highlighted code preview and full thread bodies. Background polling (30s).

| Key | Action |
|---|---|
| `Space`, `x` | Multi-select |
| `Enter` | Open in browser |
| `e` | Open in Zed |
| `a` | Reply inline |
| `c` | Copy Claude-formatted prompt to clipboard |
| `d` | Resolve thread(s) |

### 5 · Notifs

Unread GitHub notifications, auto-scoped to the current repo (all repos when outside one). Auto-refreshes every 30s; PR/issue open/closed state and body previews load lazily in the background.

| Key | Action |
|---|---|
| `Enter` | Open in browser |
| `d` | Mark done |
| `Space` | Toggle detail pane |

## Status bar

The bottom status bar (no selection, always visible) shows the current branch context and refreshes every 30s:

```
feat/xyz · owner/repo · PR #123 open Add the thing ⇒ #45 open #46 closed
```

Branch, repository, the branch's PR with state, and the issues it closes (`closingIssuesReferences`) with their states.

## Setup

Add a shell alias to your `~/.zshrc` (or equivalent), adjusting the path:

```bash
alias ghx='/path/to/ghx/ghx.py'
```

Make sure the script is executable:

```bash
chmod +x /path/to/ghx/ghx.py
```

## Architecture

`ghx.py` is a thin PEP 723 entry script that prefetches gh data with `subprocess.Popen` before the heavy TUI imports, then hands over to the local `ghx_app/` package:

- `theme.py` — shared Monokai style, state chips, pygments token colors
- `gh.py` — gh CLI / GraphQL helpers, branch-context query
- `util.py` — text helpers (`ellipsize`, `relative_time`)
- `base.py` — `Shared` state and the `ListView` base class (cursor/scroll, lazy loading, nav keys)
- `search.py` — `SearchableView`: `f` search bar with live local filter and GitHub search (PRs, Issues)
- `shell.py` — app shell: layout, view switching, global keys, footer, poll scheduler
- `statusbar.py` — branch-context status bar
- `views/` — the five views

Actions that must leave the TUI (checkout, inline reply) exit the app with a pending action; a rerun loop in `ghx.py` executes it and re-enters with view state intact. The terminal focus in/out state is reflected by the bottom accent bar.
