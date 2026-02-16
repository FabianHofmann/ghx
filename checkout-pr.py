#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["prompt_toolkit", "rich"]
# ///
import argparse
import subprocess
import json
import sys
import shutil
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
    "sel-prefix": "#a6e22e bold bg:#3a3d34",
    "sel-number": "#a6e22e bold bg:#3a3d34",
    "sel-title": "#f8f8f2 bold bg:#3a3d34",
    "sel-branch": "#66d9ef bold bg:#3a3d34",
    "sel-author": "#fd971f bold bg:#3a3d34",
    "sel-draft": "#88846f bold italic bg:#3a3d34",
    "sel-state": "#a6e22e bold bg:#3a3d34",
    "col-header": "#34D399 bold",
    "col-header-dim": "#75715e",
    "border": "#75715e",
    "header": "#34D399 bold",
    "detail-label": "#34D399",
    "detail-value": "#f8f8f2",
    "footer": "#88846f",
    "footer-key": "#34D399 bold",
})

ROW_SPACING_EVERY = 0


def ellipsize(text: str, width: int) -> str:
    if width <= 1:
        return text[:width]
    if len(text) <= width:
        return text
    return text[:width - 1] + "…"


def status_text(pr: dict) -> tuple[str, str]:
    if pr["isDraft"]:
        return "item-draft", "draft"
    review = pr.get("reviewDecision") or "PENDING"
    if review == "APPROVED":
        return "item-state", "approved"
    if review == "CHANGES_REQUESTED":
        return "item-author", "changes"
    if review == "REVIEW_REQUIRED":
        return "detail-label", "review"
    return "detail-value", "pending"


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
    terminal_width = shutil.get_terminal_size((120, 30)).columns
    prefix_w = 3
    gap_num_title = 1
    gap_title_branch = 3
    gap_author_status = 3
    author_prefix = "@"
    col_num = 6
    col_branch = min(24, max(10, max(len(pr["headRefName"]) for pr in prs)))
    col_author = min(22, max(10, max(len(pr["author"]["login"]) for pr in prs)))
    col_status = 10
    fixed = (
        prefix_w
        + col_num
        + gap_num_title
        + gap_title_branch
        + col_branch
        + 3
        + len(author_prefix)
        + col_author
        + gap_author_status
        + col_status
    )
    col_title = max(18, min(60, terminal_width - fixed))

    def adjust_scroll():
        if selected[0] < scroll_offset[0]:
            scroll_offset[0] = selected[0]
        elif selected[0] >= scroll_offset[0] + visible_count:
            scroll_offset[0] = selected[0] - visible_count + 1

    def get_header():
        start = scroll_offset[0] + 1
        end = min(scroll_offset[0] + visible_count, len(prs))
        return [
            ("class:header", "  Pull Requests "),
            ("class:border", f"({len(prs)} open, showing {start}-{end})\n"),
        ]

    def get_list_text():
        lines = []
        author_header = f"{author_prefix}{'Author':<{max(0, col_author - len(author_prefix))}}"
        header_line = (
            f"{'':<{prefix_w}}"
            f"{'#':<{col_num}}"
            f"{'':<{gap_num_title}}"
            f"{'Title':<{col_title}}"
            f"{'':<{gap_title_branch}}"
            f"{'Branch':<{col_branch}}"
            f"{'':<3}"
            f"{author_header}"
            f"{'':<{gap_author_status}}"
            f"{'Status':<{col_status}}\n"
        )
        separator_line = (
            f"{'':<{prefix_w}}"
            f"{'─' * col_num}"
            f"{'':<{gap_num_title}}"
            f"{'─' * col_title}"
            f"{'':<{gap_title_branch}}"
            f"{'─' * col_branch}"
            f"{'':<3}"
            f"{'─' * (col_author + len(author_prefix))}"
            f"{'':<{gap_author_status}}"
            f"{'─' * col_status}\n"
        )
        lines.append(("class:col-header", header_line))
        lines.append(("class:col-header-dim", separator_line))
        start = scroll_offset[0]
        end = min(start + visible_count, len(prs))
        for i in range(start, end):
            pr = prs[i]
            is_sel = i == selected[0]
            row_idx = i - start
            prefix = " ▶ " if is_sel else "   "
            num = ellipsize(f"#{pr['number']}", col_num).ljust(col_num)
            title = ellipsize(pr["title"], col_title).ljust(col_title)
            branch = ellipsize(pr["headRefName"], col_branch).ljust(col_branch)
            author = ellipsize(pr["author"]["login"], col_author).ljust(col_author)
            status_style, status_label = status_text(pr)
            status = f"{status_label:<{col_status}}"

            if is_sel:
                lines.append(("class:sel-prefix", prefix))
                lines.append(("class:sel-number", num))
                lines.append(("class:sel-title", " " * gap_num_title))
                lines.append(("class:sel-title", title))
                lines.append(("class:sel-title", " " * gap_title_branch))
                lines.append(("class:sel-branch", branch))
                lines.append(("class:sel-title", "   @"))
                lines.append(("class:sel-author", author))
                lines.append(("class:sel-title", " " * gap_author_status))
                lines.append((f"class:sel-state", status))
                lines.append(("", "\n"))
                if ROW_SPACING_EVERY > 0 and (row_idx + 1) % ROW_SPACING_EVERY == 0:
                    lines.append(("", "\n"))
            else:
                lines.append(("class:item", prefix))
                lines.append(("class:item-number", num))
                lines.append(("class:item", " " * gap_num_title))
                lines.append(("class:item-title", title))
                lines.append(("class:item", " " * gap_title_branch))
                lines.append(("class:item-branch", branch))
                lines.append(("class:item", "   @"))
                lines.append(("class:item-author", author))
                lines.append(("class:item", " " * gap_author_status))
                lines.append((f"class:{status_style}", status))
                lines.append(("class:item", "\n"))
                if ROW_SPACING_EVERY > 0 and (row_idx + 1) % ROW_SPACING_EVERY == 0:
                    lines.append(("", "\n"))
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
            ("class:footer-key", "b "),
            ("class:footer", "browse  "),
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

    @kb.add("b")
    def _(event):
        pr = prs[selected[0]]
        subprocess.Popen(["gh", "pr", "view", str(pr["number"]), "--web"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @kb.add("enter")
    def _(event):
        pr = prs[selected[0]]
        event.app.exit(result=pr["number"])

    @kb.add("q")
    @kb.add("escape")
    def _(event):
        event.app.exit(result=None)

    list_header_lines = 2
    list_height = visible_count + list_header_lines

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
