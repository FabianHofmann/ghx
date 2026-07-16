from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from prompt_toolkit.application import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import ConditionalContainer, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from rich.console import Console

from ghx_app.base import ListView, StyleText
from ghx_app.gh import gh_json, pr_list_args
from ghx_app.util import ellipsize

if TYPE_CHECKING:
    from prompt_toolkit.layout import AnyContainer

    from ghx_app.shell import Shell

DETAIL_MIN_ROWS = 14

REVIEW_COLORS = {
    "APPROVED": "#a6e22e",
    "CHANGES_REQUESTED": "#f92672",
    "REVIEW_REQUIRED": "#e5da74",
    "PENDING": "#88846f",
}


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


@dataclass
class Checkout:
    number: int

    def run(self, shell: Shell) -> None:
        Console().print(f"\n[bold #a6e22e]Checking out PR #{self.number}...[/]")
        subprocess.run(["gh", "pr", "checkout", str(self.number)])
        shell.on_branch_change()


class PrsView(ListView):
    label = "PRs"
    poll_interval = 30.0

    def title(self) -> str:
        return "Pull Requests"

    def counts(self) -> str:
        scope = "mine" if self.shared.mine else "open"
        return f"{len(self.items)} {scope}"

    def fetch(self) -> list[dict]:
        return gh_json(pr_list_args(self.shared.mine))

    def hints(self) -> list[tuple[str, str]]:
        return [("Enter", "checkout"), ("b", "browse"), ("m", "mine")]

    def detail_visible(self) -> bool:
        return get_app().output.get_size().rows >= DETAIL_MIN_ROWS

    def chrome_rows(self) -> int:
        return 8 if self.items and self.detail_visible() else 0

    def list_fragments(self) -> StyleText:
        prs = self.items
        col_num = 6
        col_status = 10
        col_branch = min(24, max(10, max((len(p["headRefName"]) for p in prs), default=10)))
        col_author = min(22, max(10, max((len(p["author"]["login"]) for p in prs), default=10)))
        fixed = 3 + col_num + 1 + 3 + col_branch + 3 + 1 + col_author + 3 + col_status
        col_title = max(18, min(60, self.viewport_width() - fixed))

        author_header = f"@{'Author':<{col_author - 1}}"
        header_line = (
            f"{'':<3}{'#':<{col_num}} {'Title':<{col_title}}{'':<3}"
            f"{'Branch':<{col_branch}}{'':<3}{author_header}{'':<3}{'Status':<{col_status}}\n"
        )
        separator_line = (
            f"{'':<3}{'─' * col_num} {'─' * col_title}{'':<3}"
            f"{'─' * col_branch}{'':<3}{'─' * (col_author + 1)}{'':<3}{'─' * col_status}\n"
        )
        lines: StyleText = [("class:col-header", header_line), ("class:col-header-dim", separator_line)]
        if not prs:
            return lines + self.empty_fragments("No open PRs")
        start, end = self.visible_range()
        for i in range(start, end):
            pr = prs[i]
            is_sel = i == self.cursor
            prefix = " ▶ " if is_sel else "   "
            num = ellipsize(f"#{pr['number']}", col_num).ljust(col_num)
            title = ellipsize(pr["title"], col_title).ljust(col_title)
            branch = ellipsize(pr["headRefName"], col_branch).ljust(col_branch)
            author = ellipsize(pr["author"]["login"], col_author).ljust(col_author)
            status_style, status_label = status_text(pr)
            status = f"{status_label:<{col_status}}"
            if is_sel:
                lines.extend([
                    ("class:sel-prefix", prefix),
                    ("class:sel-number", num),
                    ("class:sel-title", f" {title}   "),
                    ("class:sel-branch", branch),
                    ("class:sel-title", "   @"),
                    ("class:sel-author", author),
                    ("class:sel-title", "   "),
                    ("class:sel-state", status),
                    ("", "\n"),
                ])
            else:
                lines.extend([
                    ("class:item", prefix),
                    ("class:item-number", num),
                    ("class:item-title", f" {title}   "),
                    ("class:item-branch", branch),
                    ("class:item", "   @"),
                    ("class:item-author", author),
                    ("class:item", "   "),
                    (f"class:{status_style}", status),
                    ("class:item", "\n"),
                ])
        return lines

    def detail_header(self) -> StyleText:
        pr = self.items[self.cursor]
        return [("class:header", f"  #{pr['number']}: {pr['title']}\n")]

    def detail_text(self) -> StyleText:
        pr = self.items[self.cursor]
        review = pr.get("reviewDecision") or "PENDING"
        lines: StyleText = [
            ("class:detail-label", "  Branch: "),
            ("class:item-branch", pr["headRefName"]),
            ("class:detail-value", "\n"),
            ("class:detail-label", "  Author: "),
            ("class:item-author", f"@{pr['author']['login']}"),
            ("class:detail-value", "\n"),
            ("class:detail-label", "  Status: "),
            (REVIEW_COLORS.get(review, "#f8f8f2"), review.replace("_", " ").title()),
        ]
        if pr["isDraft"]:
            lines.append(("class:item-draft", " (draft)"))
        lines.extend([
            ("class:detail-value", "\n"),
            ("class:detail-label", "  Changes: "),
            ("#a6e22e", f"+{pr['additions']}"),
            ("class:detail-value", " / "),
            ("#f92672", f"-{pr['deletions']}"),
            ("class:detail-value", "\n"),
        ])
        return lines

    def detail_containers(self) -> list[AnyContainer]:
        visible = Condition(lambda: self.is_active() and bool(self.items) and self.detail_visible())
        section = HSplit([
            Window(char="─", height=1, style="class:border"),
            Window(FormattedTextControl(self.detail_header), height=1),
            Window(FormattedTextControl(self.detail_text), height=5),
            Window(char="─", height=1, style="class:border"),
        ])
        return [ConditionalContainer(section, filter=visible)]

    def bindings(self) -> KeyBindings:
        kb = super().bindings()

        @kb.add("b")
        def _(event) -> None:
            if self.items:
                number = self.items[self.cursor]["number"]
                subprocess.Popen(["gh", "pr", "view", str(number), "--web"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        @kb.add("enter")
        def _(event) -> None:
            if self.items:
                event.app.exit(result=Checkout(self.items[self.cursor]["number"]))

        @kb.add("m")
        def _(event) -> None:
            self.shared.mine = not self.shared.mine
            self.loaded = False
            self.ensure_loaded()

        return kb
