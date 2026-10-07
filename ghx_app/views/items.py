from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

import pyperclip
from prompt_toolkit.layout import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from rich.console import Console

from ghx_app.base import StyleText
from ghx_app.theme import C
from ghx_app.util import label_fragments, relative_time

if TYPE_CHECKING:
    from ghx_app.shell import Shell

DETAIL_SECTION_ROWS = 8
DETAIL_LABELS_WIDTH = 36
WORKTREE_RE = re.compile(r"is already used by worktree at '(.+)'")


def label_names(item: dict) -> str:
    return " ".join(l["name"] for l in item["labels"])


def pr_haystack(pr: dict) -> str:
    return f"#{pr['number']} {pr['title']} {pr['headRefName']} {pr['author']['login']} {label_names(pr)}"


def issue_haystack(issue: dict) -> str:
    return f"#{issue['number']} {issue['title']} {issue['author']['login']} {label_names(issue)}"


def item_haystack(item: dict) -> str:
    return pr_haystack(item) if item["kind"] == "pr" else issue_haystack(item)


def assignee_of(issue: dict) -> str:
    return issue["assignees"][0]["login"] if issue["assignees"] else ""


def item_header(item: dict) -> StyleText:
    return [("class:header", f"  #{item['number']}: {item['title']}\n")]


def pr_detail_text(pr: dict) -> StyleText:
    review = pr.get("reviewDecision") or "PENDING"
    lines: StyleText = [
        ("class:detail-label", "  Branch: "),
        ("class:item-branch", pr["headRefName"]),
        ("class:detail-value", "\n"),
        ("class:detail-label", "  Author: "),
        ("class:item-author", f"@{pr['author']['login']}"),
        ("class:detail-value", "\n"),
        ("class:detail-label", "  Status: "),
        (f"class:review-{review.lower()}", review.replace("_", " ").title()),
    ]
    if pr["isDraft"]:
        lines.append(("class:item-draft", " (draft)"))
    lines.extend([
        ("class:detail-value", "\n"),
        ("class:detail-label", "  Changes: "),
        ("class:additions", f"+{pr['additions']}"),
        ("class:detail-value", " / "),
        ("class:deletions", f"-{pr['deletions']}"),
        ("class:detail-value", "\n"),
    ])
    return lines


def issue_detail_text(issue: dict) -> StyleText:
    assignees = ", ".join(f"@{a['login']}" for a in issue["assignees"]) or "—"
    return [
        ("class:detail-label", "  Author: "),
        ("class:item-author", f"@{issue['author']['login']}"),
        ("class:detail-value", "\n"),
        ("class:detail-label", "  Assignees: "),
        ("class:item-author", assignees),
        ("class:detail-value", "\n"),
        ("class:detail-label", "  Updated: "),
        ("class:item-time", f"{relative_time(issue['updatedAt'])} ago"),
        ("class:detail-value", "\n"),
        ("class:detail-label", "  Labels: "),
        *label_fragments(issue["labels"], DETAIL_LABELS_WIDTH, False),
        ("class:detail-value", "\n"),
    ]


def item_detail_text(item: dict) -> StyleText:
    return pr_detail_text(item) if item["kind"] == "pr" else issue_detail_text(item)


def detail_section(header: Callable[[], StyleText], text: Callable[[], StyleText]) -> HSplit:
    return HSplit([
        Window(char="─", height=1, style="class:border"),
        Window(FormattedTextControl(header), height=1),
        Window(FormattedTextControl(text), height=5),
        Window(char="─", height=1, style="class:border"),
    ])


def checkout_error(stderr: str) -> str:
    if worktree := WORKTREE_RE.search(stderr):
        pyperclip.copy(worktree[1])
        return f"branch is checked out in worktree {worktree[1]} (path copied)"
    if "would be overwritten by checkout" in stderr:
        return "uncommitted changes would be overwritten, commit or stash first"
    if "Not possible to fast-forward" in stderr:
        return "local branch diverged from the PR, rebase/merge or run `gh pr checkout -f`"
    lines = [line for line in stderr.splitlines() if line.strip() and not line.startswith(("hint:", "failed to run git"))]
    return lines[-1] if lines else "unknown error"


@dataclass
class Checkout:
    number: int

    def run(self, shell: Shell) -> None:
        Console().print(f"\n[bold {C['green']}]Checking out PR #{self.number}...[/]")
        result = subprocess.run(["gh", "pr", "checkout", str(self.number)], stderr=subprocess.PIPE, text=True)
        shell.on_branch_change()
        if result.returncode == 0:
            shell.flash(f"checked out PR #{self.number}")
        else:
            shell.flash(f"checkout of PR #{self.number} failed: {checkout_error(result.stderr)}")
