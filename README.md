# ghx

A combined GitHub TUI for everyday PR workflows: browse open PRs and issues in one list, checkout PRs, watch CI checks, work through unresolved review comments, triage notifications, and see which issues are being worked on — all in one full-screen app with a persistent branch-context status bar.

Runs standalone via `uv run` with [PEP 723](https://peps.python.org/pep-0723/) inline script metadata — no virtual environment or `pip install` needed.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- [gh](https://cli.github.com/) CLI (authenticated)
- [Zed](https://zed.dev/) editor (for opening review comments)

## Usage

```bash
./ghx.py             # Start on the All view
./ghx.py ci          # Start on a specific view (prefix-matched: all, prs, issues, work, ci, comments, notifs)
./ghx.py -m          # Only PRs authored by me / issues assigned to me
./ghx.py | cat       # Non-interactive: print branch context (current PR + linked issues)
```

Outside a git repository only `ghx notifs` works (notifications across all repos).

## Views

Switch views with `1`–`7` or `Tab`/`Shift-Tab`. Global keys everywhere:

| Key | Action |
|---|---|
| `1`–`7`, `Tab` | Switch view |
| `j/k`, `↑/↓` | Navigate |
| `r` | Refresh active view |
| `o` | Open current branch's PR in browser |
| `q`, `Esc` | Quit |

### 1 · All

Open PRs and open issues (latest 50 each, two `gh` list calls) in one flat list, newest number first. Prefetched before the TUI imports, together with the PRs and Issues views.

```
   #      Kind  Title                              @Author      Status     Labels
   ────── ───── ────────────────────────────────── ──────────── ────────── ──────────
 ▶ #433   PR    Add CSV export                     @fabian      review     enh
   #431   PR    tz-tests                           @lisa        draft
   #412   issue Fix tz handling in loader          @anna        @fabian    bug
   #405   issue Docs: install on Windows           @tom         open       docs
```

Status is the review status for PRs and the first assignee (else `open`) for issues. When one list hits the 50 cap, items older than its oldest entry are dropped, so the merged list never looks more complete than it is. Background polling (30s).

| Key | Action |
|---|---|
| `Enter` | Open in browser |
| `c` | Checkout PR (PR rows only) |
| `f` | Find: filter live by number, title, author, labels or branch; `Enter` searches GitHub (PRs and issues); `Esc` clears |
| `m` | Toggle "mine": PRs authored by me, issues assigned to me |

### 2 · PRs

Open PRs with branch, author, and review status (draft/approved/changes/review/pending). Prefetched before the TUI imports for a fast start.

| Key | Action |
|---|---|
| `Enter` | Open in browser |
| `c` | Checkout PR |
| `f` | Find: filter loaded PRs live by number, title, branch, author or label; `Enter` searches GitHub; `Esc` clears |
| `m` | Toggle "only my PRs" filter |

### 3 · Issues

Open issues (latest 50) with assignee and colored label chips.

| Key | Action |
|---|---|
| `Enter` | Open in browser |
| `f` | Find: filter loaded issues live by number, title, author or label; `Enter` searches GitHub (all issues, whole words, [search syntax](https://docs.github.com/en/search-github/searching-on-github/searching-issues-and-pull-requests)); `Esc` clears |
| `l` | Label filter panel |
| `m` | Toggle "assigned to me" filter |

### 4 · Work

Open issues and open PRs (latest 50 each, one GraphQL query) as a tree, linked via the PRs' closing issue references:

```
 ▾ In progress (1)
   #412   Fix tz handling in loader          @anna     bug
   ├ #430   Fix tz offsets                   @fabian   fix-tz    approved  +40 −3
   └ #431   Add tz tests                     @lisa     tz-tests  draft     +12 −0
 ▾ PRs without issue (1)
   #427   Bump deps                          @bot      bump-deps pending   +3 −3
 ▾ Issues without PR (1)
   #405   Docs: install on Windows           —         docs
```

A PR closing several open issues is listed under each; a PR closing only issues outside the loaded list counts as "without issue". Background polling (30s).

| Key | Action |
|---|---|
| `Enter` | Open issue/PR in browser |
| `c` | Checkout PR |
| `Space` | Fold/unfold group (on a group header) |
| `f` | Find: filter the tree live by number, title, branch, author or label (a match keeps its parent issue / child PRs visible); `Enter` keeps the filter (local only, no GitHub search); `Esc` clears |
| `m` | Toggle "mine": PRs authored by me, issues assigned to or opened by me |

### 5 · CI

CI check statuses for the current branch's PR. Background polling (15s) flags updates with `● new`; `r` applies them.

| Key | Action |
|---|---|
| `Enter` | Open check URL |

### 6 · Comments

Unresolved PR review threads with syntax-highlighted code preview and full thread bodies. Background polling (30s).

| Key | Action |
|---|---|
| `Space`, `x` | Multi-select |
| `Enter` | Open in browser |
| `e` | Open in Zed |
| `a` | Reply inline |
| `c` | Copy Claude-formatted prompt to clipboard |
| `d` | Resolve thread(s) |

### 7 · Notifs

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
- `gh.py` — gh CLI / GraphQL helpers, branch-context and work-tree queries, `merge_items` for the All view
- `util.py` — text and shared row helpers (`ellipsize`, `relative_time`, PR `status_text`, `label_fragments` chips)
- `base.py` — `Shared` state and the `ListView` base class (cursor/scroll, lazy loading, nav keys)
- `search.py` — `SearchableView`: `f` search bar with live local filter and GitHub search (All, PRs, Issues; Work filters locally only)
- `shell.py` — app shell: layout, view switching, global keys, footer, poll scheduler
- `statusbar.py` — branch-context status bar
- `views/` — the seven views, plus `items.py` with shared PR/issue row helpers

Actions that must leave the TUI (checkout, inline reply) exit the app with a pending action; a rerun loop in `ghx.py` executes it and re-enters with view state intact. The terminal focus in/out state is reflected by the bottom accent bar.
