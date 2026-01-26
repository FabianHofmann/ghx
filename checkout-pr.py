#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["prompt_toolkit", "rich"]
# ///
import argparse
import subprocess
import json
import sys
from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from rich.console import Console

MONOKAI_STYLE = Style.from_dict({
    "": "#f8f8f2 bg:#272822",
    "item": "#f8f8f2",
    "item-number": "#75715e",
    "item-title": "#f8f8f2",
    "item-branch": "#66d9ef",
    "item-author": "#fd971f",
    "item-state": "#a6e22e",
    "item-draft": "#88846f italic",
    "sel-prefix": "#a6e22e bold",
    "sel-number": "#a6e22e bold",
    "sel-title": "#f8f8f2 bold",
    "sel-branch": "#66d9ef bold",
    "sel-author": "#fd971f bold",
    "sel-draft": "#88846f bold italic",
    "border": "#75715e",
    "header": "#e5da74 bold",
    "detail-label": "#e5da74",
    "detail-value": "#f8f8f2",
    "footer": "#88846f",
    "footer-key": "#e5da74 bold",
})


def get_prs(mine_only: bool = False) -> list[dict]:
    cmd = [
        "gh", "pr", "list", "--json",
        "number,title,headRefName,author,isDraft,state,reviewDecision,additions,deletions",
        "--limit", "50",
    ]
    if mine_only:
        cmd.extend(["--author", "@me"])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"Failed to fetch PRs: {result.stderr}")
    return json.loads(result.stdout)


def checkout_pr(number: int) -> None:
    subprocess.run(["gh", "pr", "checkout", str(number)])


def run_selector(prs: list[dict]) -> None:
    selected = [0]
    scroll_offset = [0]
    visible_count = min(len(prs), 12)
    col_num = 6
    col_title = max(len(pr["title"][:50]) for pr in prs)
    col_branch = max(len(pr["headRefName"][:30]) for pr in prs)
    col_author = max(len(pr["author"]["login"]) for pr in prs)

    def adjust_scroll():
        if selected[0] < scroll_offset[0]:
            scroll_offset[0] = selected[0]
        elif selected[0] >= scroll_offset[0] + visible_count:
            scroll_offset[0] = selected[0] - visible_count + 1

    def get_header():
        return [
            ("class:header", "  Pull Requests "),
            ("class:border", f"({len(prs)} open)\n"),
        ]

    def get_list_text():
        lines = []
        start = scroll_offset[0]
        end = min(start + visible_count, len(prs))
        for i in range(start, end):
            pr = prs[i]
            is_sel = i == selected[0]
            prefix = " ▶ " if is_sel else "   "
            num = f"#{pr['number']:<{col_num}}"
            title = pr["title"][:50].ljust(col_title)
            branch = pr["headRefName"][:30].ljust(col_branch)
            author = pr["author"]["login"].ljust(col_author)

            if is_sel:
                lines.append(("class:sel-prefix", prefix))
                lines.append(("class:sel-number", num))
                lines.append(("class:sel-title", f" {title}  "))
                lines.append(("class:sel-branch", branch))
                lines.append(("class:sel-title", "  @"))
                lines.append(("class:sel-author", author))
                if pr["isDraft"]:
                    lines.append(("class:sel-draft", " [draft]"))
                lines.append(("", "\n"))
            else:
                lines.append(("class:item", prefix))
                lines.append(("class:item-number", num))
                lines.append(("class:item", " "))
                lines.append(("class:item-title", title))
                lines.append(("class:item", "  "))
                lines.append(("class:item-branch", branch))
                lines.append(("class:item", "  @"))
                lines.append(("class:item-author", author))
                if pr["isDraft"]:
                    lines.append(("class:item-draft", " [draft]"))
                lines.append(("class:item", "\n"))
        return lines

    def get_detail_header():
        pr = prs[selected[0]]
        return [("class:header", f"  #{pr['number']}: {pr['title']}\n")]

    def get_detail_text():
        pr = prs[selected[0]]
        review = pr.get("reviewDecision") or "PENDING"
        review_colors = {
            "APPROVED": "#a6e22e",
            "CHANGES_REQUESTED": "#f92672",
            "REVIEW_REQUIRED": "#e5da74",
            "PENDING": "#88846f",
        }
        review_color = review_colors.get(review, "#f8f8f2")

        lines = [
            ("class:detail-label", "  Branch: "),
            ("class:item-branch", pr["headRefName"]),
            ("class:detail-value", "\n"),
            ("class:detail-label", "  Author: "),
            ("class:item-author", f"@{pr['author']['login']}"),
            ("class:detail-value", "\n"),
            ("class:detail-label", "  Status: "),
            (review_color, review.replace("_", " ").title()),
        ]
        if pr["isDraft"]:
            lines.append(("class:item-draft", " (draft)"))
        lines.append(("class:detail-value", "\n"))
        lines.append(("class:detail-label", "  Changes: "))
        lines.append(("#a6e22e", f"+{pr['additions']}"))
        lines.append(("class:detail-value", " / "))
        lines.append(("#f92672", f"-{pr['deletions']}"))
        lines.append(("class:detail-value", "\n"))
        return lines

    def get_footer():
        return [
            ("class:footer-key", " ↑/k "),
            ("class:footer", "up  "),
            ("class:footer-key", "↓/j "),
            ("class:footer", "down  "),
            ("class:footer-key", "Enter "),
            ("class:footer", "checkout  "),
            ("class:footer-key", "q/Esc "),
            ("class:footer", "quit"),
        ]

    header_control = FormattedTextControl(get_header)
    list_control = FormattedTextControl(get_list_text)
    detail_header_control = FormattedTextControl(get_detail_header)
    detail_control = FormattedTextControl(get_detail_text)
    footer_control = FormattedTextControl(get_footer)

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _(event):
        selected[0] = max(0, selected[0] - 1)
        adjust_scroll()

    @kb.add("down")
    @kb.add("j")
    def _(event):
        selected[0] = min(len(prs) - 1, selected[0] + 1)
        adjust_scroll()

    @kb.add("enter")
    def _(event):
        pr = prs[selected[0]]
        event.app.exit(result=pr["number"])

    @kb.add("q")
    @kb.add("escape")
    def _(event):
        event.app.exit(result=None)

    list_height = visible_count

    layout = Layout(
        HSplit([
            Window(header_control, height=1),
            Window(list_control, height=list_height),
            Window(char="─", height=1, style="class:border"),
            Window(detail_header_control, height=1),
            Window(detail_control, height=5),
            Window(char="─", height=1, style="class:border"),
            Window(footer_control, height=1),
        ])
    )

    app = Application(layout=layout, key_bindings=kb, style=MONOKAI_STYLE, full_screen=True)
    return app.run()


def main() -> int:
    parser = argparse.ArgumentParser(description="Browse and checkout PRs")
    parser.add_argument("-m", "--mine", action="store_true", help="Only show PRs authored by me")
    args = parser.parse_args()

    console = Console()

    with console.status("[bold #e5da74]Fetching PRs..."):
        prs = get_prs(mine_only=args.mine)

    if not prs:
        console.print("[#e6db74]No open PRs found[/]")
        return 0

    label = "my" if args.mine else "open"
    console.print(f"[bold #a6e22e]Found {len(prs)} {label} PR(s)[/]\n")

    pr_number = run_selector(prs)

    if pr_number:
        console.print(f"\n[bold #a6e22e]Checking out PR #{pr_number}...[/]")
        checkout_pr(pr_number)

    return 0


if __name__ == "__main__":
    sys.exit(main())
