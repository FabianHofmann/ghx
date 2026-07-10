## Project Overview

A combined GitHub TUI (`ghx.py`) built on prompt_toolkit, run standalone via `uv run` with PEP 723 inline script metadata. Four switchable views (PRs, CI, Comments, Notifications) plus a non-interactive branch-context status bar.

## Running

```bash
./ghx.py             # PRs view
./ghx.py ci          # Initial view: prs, ci, comments, notifs (prefix-matched)
./ghx.py -m          # Only PRs authored by current user
./ghx.py | cat       # Non-TTY: static branch-context printout
```

## Architecture

- `ghx.py` — entry script. Prefetches gh data via `subprocess.Popen` BEFORE importing prompt_toolkit (startup optimization — keep this ordering), then runs a rerun loop: `Shell.run()` returns a pending action (`Checkout`, `Reply`) or `None`; actions execute outside the TUI, then the app re-enters with view state intact.
- `ghx_app/base.py` — `Shared` (repo, branch, pr_number, mine) mutable app-wide state; `ListView` ABC providing cursor/scroll state, `list_capacity`/`adjust_scroll`, lazy background loading (`ensure_loaded`/`finish_load`), base nav keybindings (j/k/↑/↓, r).
- `ghx_app/shell.py` — layout (header / list / per-view detail panes / status bar / footer / focus accent bar), view switching (`1`–`4`, tab), global keys (`o` open PR, `q` quit), `Scheduler` thread polling the status bar (30s) and the active view (per-view `poll_interval`); terminal focus in/out reporting via F23/F24 pseudo-keys.
- `ghx_app/statusbar.py` — branch/repo/PR/linked-issues line, updates `Shared.pr_number` on poll.
- `ghx_app/views/` — one module per view; each implements `fetch`, `list_fragments`, `title`, `counts`, `hints`, and optionally `detail_containers`, `poll`, `bindings`, `chrome_rows`, `on_branch_change`.
- `ghx_app/theme.py` / `gh.py` / `util.py` — merged Monokai style dict, gh CLI/GraphQL helpers, text helpers.

**External dependencies**: `gh` CLI for all GitHub interactions, `zed` for opening files, `xdg-open` for URLs.

**Conventions**: `chrome_rows()` must mirror each view's `ConditionalContainer` visibility so scroll capacity stays correct. Poll semantics differ intentionally: CI/Comments only flag `has_new` (manual `r` applies), Notifications auto-applies preserving selection by id.

## Usage

The `ghx` alias in `~/.zshrc` (section `# EDITOR-SCRIPT-ALIASES`) points to `ghx.py`. Keep the script executable (`chmod +x ghx.py`).
