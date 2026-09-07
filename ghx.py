#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["prompt_toolkit", "rich", "pygments", "pyperclip"]
# ///
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ghx_app import gh

VIEW_NAMES = ["prs", "issues", "ci", "comments", "notifs"]

STATIC_STATE_COLOR = {"open": "#a6e22e", "closed": "#f92672", "merged": "#ae81ff", "draft": "#88846f"}


def resolve_view(name: str) -> str:
    matches = [v for v in VIEW_NAMES if v.startswith(name)]
    if len(matches) != 1:
        sys.exit(f"Unknown view '{name}' (choose from: {', '.join(VIEW_NAMES)})")
    return matches[0]


def print_static(branch: str, repo: str | None, context: dict | None) -> None:
    from rich.console import Console
    console = Console()
    console.print(f"[bold #66d9ef]{branch}[/] [#75715e]·[/] [#75715e]{repo or '(no repo)'}[/]")
    if context is None:
        console.print("[#75715e]No open PR for this branch[/]")
        return
    pr = context["pr"]
    pr_state = f"[{STATIC_STATE_COLOR[pr['state']]}]{pr['state']}[/]"
    console.print(f"[#ae81ff]PR #{pr['number']}[/] {pr_state} {pr['title']}")
    if not context["issues"]:
        console.print("[#75715e]No linked issues[/]")
    for issue in context["issues"]:
        issue_state = f"[{STATIC_STATE_COLOR[issue['state']]}]{issue['state']}[/]"
        console.print(f"  [#fd971f]#{issue['number']}[/] {issue_state} {issue['title']}")


def popen(args: list[str]) -> subprocess.Popen[str]:
    return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def read_output(proc: subprocess.Popen[str]) -> str:
    out, _ = proc.communicate()
    return out.strip() if proc.returncode == 0 else ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Combined GitHub TUI: PRs, issues, CI, review comments, notifications")
    parser.add_argument("view", nargs="?", default="prs", help=f"initial view: {', '.join(VIEW_NAMES)} (prefix ok)")
    parser.add_argument("-m", "--mine", action="store_true", help="show only PRs authored by me / issues assigned to me")
    parser.add_argument("-o", "--open", action="store_true", help="open the current branch's PR in the browser and exit")
    args = parser.parse_args()
    view_name = resolve_view(args.view)

    if args.open:
        number = gh.get_pr_number()
        if number is None:
            print("No open PR for this branch", file=sys.stderr)
            return 1
        print("Opening related GitHub page")
        gh.open_pr_in_browser(number)
        return 0

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        repo = gh.detect_repo()
        pr_number = gh.get_pr_number()
        context = gh.fetch_context(repo, pr_number) if repo and pr_number else None
        print_static(gh.current_branch(), repo, context)
        return 0

    prefetch = {
        "repo": popen(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]),
        "pr": popen(["gh", "pr", "view", "--json", "number", "-q", ".number"]),
    }
    if view_name == "prs":
        prefetch["prs"] = popen(["gh", *gh.pr_list_args(args.mine)])
    elif view_name == "issues":
        prefetch["issues"] = popen(["gh", *gh.issue_list_args(args.mine)])

    from ghx_app.base import Shared
    from ghx_app.shell import Shell
    from ghx_app.statusbar import StatusBar
    from ghx_app.views import build_views

    branch = gh.current_branch()
    repo = read_output(prefetch["repo"]) or None
    pr_text = read_output(prefetch["pr"])
    pr_number = int(pr_text) if pr_text.isdigit() else None

    if repo is None and view_name != "notifs":
        print("Not in a GitHub repository (only 'ghx notifs' works here)", file=sys.stderr)
        return 1

    shared = Shared(repo=repo, branch=branch, pr_number=pr_number, mine=args.mine)
    views = build_views(shared)
    for name in ("prs", "issues"):
        if name in prefetch:
            out, _ = prefetch[name].communicate()
            if prefetch[name].returncode == 0:
                views[VIEW_NAMES.index(name)].seed(json.loads(out))

    shell = Shell(shared, views, StatusBar(shared), VIEW_NAMES.index(view_name))
    while True:
        action = shell.run()
        if action is None:
            return 0
        action.run(shell)


if __name__ == "__main__":
    sys.exit(main())
