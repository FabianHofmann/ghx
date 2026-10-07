## Project Overview

A combined GitHub TUI (`ghx.py`) built on prompt_toolkit, run standalone via `uv run` with PEP 723 inline script metadata. Seven switchable views (All, PRs, Issues, Work, CI, Comments, Notifications) plus a non-interactive branch-context status bar.

## Running

```bash
./ghx.py             # All view (open PRs and issues combined)
./ghx.py ci          # Initial view: all, prs, issues, work, ci, comments, notifs (prefix-matched)
./ghx.py -m          # Only PRs authored by / issues assigned to current user
./ghx.py | cat       # Non-TTY: static branch-context printout
```

## Architecture

- `ghx.py` — entry script. Prefetches gh data via `subprocess.Popen` BEFORE importing prompt_toolkit (startup optimization — keep this ordering), then runs a rerun loop: `Shell.run()` returns a pending action (`Checkout`, `Reply`) or `None`; actions execute outside the TUI, then the app re-enters with view state intact. `Checkout` captures `gh pr checkout` stderr and flashes the outcome after re-entry (`checkout_error` maps known git failures to actionable messages).
- `ghx_app/base.py` — `Shared` (repo, branch, pr_number, mine) mutable app-wide state; `ListView` ABC providing cursor/scroll state, `list_capacity`/`adjust_scroll`, lazy background loading (`ensure_loaded`/`finish_load`), base nav keybindings (j/k/↑/↓, r).
- `ghx_app/search.py` — `SearchableView(ListView)`: search bar, live filter over `all_items` via `haystack`/`keep` (`filtered`), the filter persists after `Enter` (`keep_filter`); `Ctrl+G` runs GitHub search via `search_query` in `fetch`. Subclasses define `view_bindings` instead of `bindings` and extend `hints`/`chrome_rows`/`detail_containers` via `super()`. `WorkView` overrides `filtered` (tree-aware) and sets `github_search = False`.
- `ghx_app/shell.py` — layout (header / list / per-view detail panes / status bar / footer / focus accent bar), view switching (`1`–`7`, tab), global keys (`o` open PR, `q` quit), `Scheduler` thread polling the status bar (30s) and the active view (per-view `poll_interval`); terminal focus in/out reporting via F23/F24 pseudo-keys.
- `ghx_app/statusbar.py` — branch/repo/PR/linked-issues line, updates `Shared.pr_number` on poll.
- `ghx_app/views/` — one module per view (`combined.py` is the All view; `items.py` holds shared PR/issue row helpers: haystacks, detail panes, `Checkout`); each implements `fetch`, `list_fragments`, `title`, `counts`, `hints`, and optionally `detail_containers`, `poll`, `bindings`, `chrome_rows`, `on_branch_change`.
- `ghx_app/theme.py` / `gh.py` / `util.py` — Monokai dark/light palettes (`C`, picked at import by querying the terminal background via OSC 11, override with `GHX_THEME=light|dark`) and the style built from it, gh CLI/GraphQL helpers, text and shared row helpers (`status_text`, `label_fragments`).

**External dependencies**: `gh` CLI for all GitHub interactions, `zed` for opening files, `xdg-open` for URLs.

**Conventions**: Views with a text input return `True` from `capturing_input()` while typing; this disables the global keys. `chrome_rows()` must mirror each view's `ConditionalContainer` visibility so scroll capacity stays correct. Poll semantics differ intentionally: CI/Comments only flag `has_new` (manual `r` applies), Notifications auto-applies preserving selection by id.

## Usage

The `ghx` alias in `~/.zshrc` (section `# EDITOR-SCRIPT-ALIASES`) points to `ghx.py`. Keep the script executable (`chmod +x ghx.py`).
