from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pyperclip
from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import ConditionalContainer, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from pygments import lex
from pygments.lexers import TextLexer, get_lexer_for_filename
from rich.console import Console

from ghx_app.base import ListView, StyleText
from ghx_app.gh import graphql, open_url, run_gh
from ghx_app.theme import TOKEN_COLORS
from ghx_app.util import ellipsize

if TYPE_CHECKING:
    from prompt_toolkit.layout import AnyContainer

    from ghx_app.shell import Shell

SNIPPET_SECTION_ROWS = 11
COMMENT_SECTION_ROWS = 11

THREADS_QUERY = """
query($owner: String!, $repo: String!, $pr: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100) {
        nodes {
          id
          isResolved
          path
          line
          originalLine
          comments(first: 50) {
            nodes {
              body
              url
              author { login }
            }
          }
        }
      }
    }
  }
}
"""

RESOLVE_MUTATION = """
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread { isResolved }
  }
}
"""

REPLY_MUTATION = """
mutation($threadId: ID!, $body: String!) {
  addPullRequestReviewThreadReply(input: {
    pullRequestReviewThreadId: $threadId,
    body: $body
  }) {
    comment { id }
  }
}
"""


def get_unresolved_comments(owner: str, repo: str, pr_number: int) -> list[dict]:
    data = graphql(THREADS_QUERY, owner=owner, repo=repo, pr=pr_number)
    threads = data["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    comments = []
    for thread in threads:
        if thread["isResolved"] or not thread["comments"]["nodes"]:
            continue
        nodes = thread["comments"]["nodes"]
        first = nodes[0]
        authors = [c["author"]["login"] if c["author"] else "unknown" for c in nodes]
        comments.append({
            "thread_id": thread["id"],
            "path": thread["path"],
            "line": thread["line"] or thread["originalLine"],
            "outdated": thread["line"] is None and thread["originalLine"] is not None,
            "body": first["body"],
            "author": authors[0],
            "url": first.get("url", ""),
            "replies": [{"body": c["body"], "author": a} for c, a in zip(nodes[1:], authors[1:])],
        })
    return comments


def resolve_thread(thread_id: str) -> bool:
    result = run_gh(["api", "graphql", "-f", f"query={RESOLVE_MUTATION}", "-F", f"threadId={thread_id}"])
    return result.returncode == 0


def reply_to_thread(thread_id: str, body: str) -> bool:
    result = run_gh([
        "api", "graphql", "-f", f"query={REPLY_MUTATION}",
        "-F", f"threadId={thread_id}", "-f", f"body={body}",
    ])
    return result.returncode == 0


def get_token_color(token_type) -> str:
    while token_type:
        if token_type in TOKEN_COLORS:
            return TOKEN_COLORS[token_type]
        token_type = token_type.parent
    return "#f8f8f2"


def highlight_line(line: str, lexer, is_highlighted: bool) -> StyleText:
    result = []
    bg = " bg:#49483e" if is_highlighted else ""
    for token_type, token_value in lex(line.rstrip("\n\r"), lexer):
        token_value = token_value.rstrip("\n\r")
        if not token_value:
            continue
        result.append((f"{get_token_color(token_type)}{bg}", token_value))
    return result


def get_code_snippet(file_path: str, target_line: int | None, context: int = 3) -> StyleText:
    if not target_line:
        return [("class:snippet-dim", "  (no line number)")]
    path = Path(file_path)
    if not path.exists():
        return [("class:snippet-dim", f"  (file not found: {file_path})")]
    try:
        content = path.read_text()
    except OSError:
        return [("class:snippet-dim", "  (could not read file)")]
    lines = content.splitlines()
    try:
        lexer = get_lexer_for_filename(file_path, content)
    except Exception:
        lexer = TextLexer()
    start = max(0, target_line - context - 1)
    end = min(len(lines), target_line + context)
    result: StyleText = []
    for i in range(start, end):
        line_num = i + 1
        is_target = line_num == target_line
        if is_target:
            result.append(("class:snippet-highlight-num", f"{line_num:4d} "))
            result.append(("#f8f8f2 bg:#49483e", "│ "))
        else:
            result.append(("class:snippet-num", f"{line_num:4d} "))
            result.append(("class:snippet", "│ "))
        result.extend(highlight_line(lines[i], lexer, is_target))
        result.append(("", "\n"))
    return result


def open_in_zed(file: str, line: int | None) -> None:
    subprocess.run(["zed", f"{file}:{line}"] if line else ["zed", file])


def format_comment_thread(comment: dict) -> str:
    line_info = f"line {comment['line']}" if comment["line"] else "unknown line"
    location = f"{comment['path']}:{comment['line']}" if comment["line"] else comment["path"]
    thread = f"@{comment['author']}: {comment['body']}"
    for reply in comment["replies"]:
        thread += f"\n\n↳ @{reply['author']}: {reply['body']}"
    return f"Location: {location} ({line_info})\n\n{thread}"


def format_claude_prompt(comments: list[dict], pr_number: int, repo: str) -> str:
    if len(comments) == 1:
        return f"""Address this PR review comment on {repo} PR #{pr_number}.

{format_comment_thread(comments[0])}

Read the file, understand the reviewer's feedback, and make the necessary changes. If the comment is a question or suggestion, evaluate it and formulate a respond, that I can post."""
    threads = "\n\n---\n\n".join(format_comment_thread(c) for c in comments)
    return f"""Address these {len(comments)} PR review comments on {repo} PR #{pr_number}.

{threads}

Read the files, understand the reviewer's feedback, and make the necessary changes. If a comment is a question or suggestion, evaluate it and formulate a respond, that I can post."""


@dataclass
class Reply:
    view: CommentsView
    index: int

    def run(self, shell: Shell) -> None:
        comment = self.view.items[self.index]
        console = Console()
        console.print(f"\n[bold #e5da74]Replying to @{comment['author']}[/] on [#66d9ef]{comment['path']}:{comment['line']}[/]")
        console.print(f"[#88846f]{comment['body'][:200]}[/]\n")
        try:
            body = pt_prompt("Reply: ")
        except (EOFError, KeyboardInterrupt):
            return
        if not body.strip():
            return
        if reply_to_thread(comment["thread_id"], body):
            console.print("[bold #a6e22e]Reply sent[/]\n")
            comment["replies"].append({"body": body, "author": "you"})
        else:
            console.print("[bold #f92672]Failed to send reply[/]\n")


class CommentsView(ListView):
    label = "Comments"
    poll_interval = 30.0

    def __init__(self, shared) -> None:
        super().__init__(shared)
        self.selected: set[int] = set()

    def title(self) -> str:
        return "PR Comments"

    def counts(self) -> str:
        sel_info = f", {len(self.selected)} selected" if self.selected else ""
        return f"{len(self.items)} unresolved{sel_info}"

    def fetch(self) -> list[dict]:
        if self.shared.repo is None or self.shared.pr_number is None:
            return []
        owner, _, name = self.shared.repo.partition("/")
        return get_unresolved_comments(owner, name, self.shared.pr_number)

    def changed(self, latest: list[dict]) -> bool:
        return {c["thread_id"] for c in latest} != {c["thread_id"] for c in self.items}

    def apply(self, items: list[dict]) -> None:
        self.selected.clear()
        super().apply(items)

    def on_branch_change(self) -> None:
        self.items = []
        self.selected.clear()
        self.cursor = 0
        self.scroll = 0
        self.loaded = False
        self.has_new = False
        self.error = ""

    def hints(self) -> list[tuple[str, str]]:
        return [
            ("Space", "select"), ("Enter", "open"), ("b", "browser"),
            ("a", "answer"), ("c", "copy"), ("d", "done"),
        ]

    def snippet_visible(self) -> bool:
        return self.fits_section(SNIPPET_SECTION_ROWS + COMMENT_SECTION_ROWS)

    def comment_visible(self) -> bool:
        return self.fits_section(COMMENT_SECTION_ROWS)

    def chrome_rows(self) -> int:
        if not self.items:
            return 0
        if self.snippet_visible():
            return SNIPPET_SECTION_ROWS + COMMENT_SECTION_ROWS
        if self.comment_visible():
            return COMMENT_SECTION_ROWS
        return 0

    def list_fragments(self) -> StyleText:
        comments = self.items
        col_line = 6
        col_state = 10
        col_author = min(24, max(10, max((len(c["author"]) for c in comments), default=10)))
        fixed = 4 + col_line + 3 + 3 + 1 + col_author + 3 + col_state
        col_path = max(24, min(80, self.viewport_width() - fixed))

        author_header = f"@{'Author':<{col_author - 1}}"
        header_line = (
            f"{'':<4}{'Path':<{col_path}}{'':<3}{'Line':<{col_line}}{'':<3}"
            f"{author_header}{'':<3}{'Status':<{col_state}}\n"
        )
        separator_line = (
            f"{'':<4}{'─' * col_path}{'':<3}{'─' * col_line}{'':<3}"
            f"{'─' * (col_author + 1)}{'':<3}{'─' * col_state}\n"
        )
        lines: StyleText = [("class:col-header", header_line), ("class:col-header-dim", separator_line)]
        if not comments:
            message = "No open PR for this branch" if self.shared.pr_number is None else "No unresolved comments"
            return lines + self.empty_fragments(message)
        start, end = self.visible_range()
        for i in range(start, end):
            c = comments[i]
            is_cursor = i == self.cursor
            marker = "●" if i in self.selected else " "
            pointer = "▶" if is_cursor else " "
            prefix = f" {marker}{pointer} "
            if c["line"]:
                line_str = f"~L{c['line']}" if c["outdated"] else f"L{c['line']}"
            else:
                line_str = "L?"
            line = f"{line_str:<{col_line}}"
            path = ellipsize(c["path"], col_path).ljust(col_path)
            author = ellipsize(c["author"], col_author).ljust(col_author)
            if c["line"] is None:
                state_style, state_text = "detail-value", "unknown"
            elif c["outdated"]:
                state_style, state_text = "detail-label", "outdated"
            else:
                state_style, state_text = "item-state", "current"
            state = f"{state_text:<{col_state}}"
            if is_cursor:
                lines.extend([
                    ("class:sel-prefix", prefix),
                    ("class:sel-path", path),
                    ("class:sel-prefix", "   "),
                    ("class:sel-line", line),
                    ("class:sel-prefix", "   @"),
                    ("class:sel-author", author),
                    ("class:sel-prefix", "   "),
                    ("class:sel-state", state),
                    ("", "\n"),
                ])
            else:
                lines.extend([
                    ("class:item", prefix),
                    ("class:item-path", path),
                    ("class:item", "   "),
                    ("class:item-line", line),
                    ("class:item", "   @"),
                    ("class:item-author", author),
                    ("class:item", "   "),
                    (f"class:{state_style}", state),
                    ("class:item", "\n"),
                ])
        return lines

    def snippet_header(self) -> StyleText:
        if not self.items:
            return []
        return [("class:comment-header", f"  Code Preview: {self.items[self.cursor]['path']}\n")]

    def snippet_text(self) -> StyleText:
        if not self.items:
            return []
        c = self.items[self.cursor]
        return get_code_snippet(c["path"], c["line"])

    def comment_header(self) -> StyleText:
        if not self.items:
            return []
        return [("class:comment-header", f"  Comment by @{self.items[self.cursor]['author']}:\n")]

    def body_text(self) -> StyleText:
        if not self.items:
            return []
        c = self.items[self.cursor]
        result: StyleText = [("class:comment-body", c["body"])]
        for reply in c["replies"]:
            result.append(("", "\n\n"))
            result.append(("class:comment-header", f"  ↳ @{reply['author']}:\n"))
            result.append(("class:comment-body", reply["body"]))
        return result

    def detail_containers(self) -> list[AnyContainer]:
        active_items = lambda: self.is_active() and bool(self.items)
        snippet_section = ConditionalContainer(
            HSplit([
                Window(char="─", height=1, style="class:border"),
                Window(FormattedTextControl(self.snippet_header), height=1),
                Window(FormattedTextControl(self.snippet_text), height=9),
            ]),
            filter=Condition(lambda: active_items() and self.snippet_visible()),
        )
        comment_section = ConditionalContainer(
            HSplit([
                Window(char="─", height=1, style="class:border"),
                Window(FormattedTextControl(self.comment_header), height=1),
                Window(FormattedTextControl(self.body_text), height=8, wrap_lines=True),
                Window(char="─", height=1, style="class:border"),
            ]),
            filter=Condition(lambda: active_items() and self.comment_visible()),
        )
        return [snippet_section, comment_section]

    def bindings(self) -> KeyBindings:
        kb = super().bindings()

        @kb.add("space")
        @kb.add("x")
        def _(event) -> None:
            if not self.items:
                return
            if self.cursor in self.selected:
                self.selected.discard(self.cursor)
            else:
                self.selected.add(self.cursor)

        @kb.add("enter")
        def _(event) -> None:
            if self.items:
                c = self.items[self.cursor]
                open_in_zed(c["path"], c["line"])

        @kb.add("c")
        def _(event) -> None:
            if not self.items:
                return
            indices = sorted(self.selected) if self.selected else [self.cursor]
            picked = [self.items[i] for i in indices]
            prompt = format_claude_prompt(picked, self.shared.pr_number or 0, self.shared.repo or "")
            pyperclip.copy(prompt)
            self.shell.flash(f"copied {len(picked)} comment(s)")

        @kb.add("d")
        def _(event) -> None:
            if not self.items:
                return
            indices = sorted(self.selected, reverse=True) if self.selected else [self.cursor]
            for i in indices:
                if resolve_thread(self.items[i]["thread_id"]):
                    self.items.pop(i)
            self.selected.clear()
            self.cursor = min(self.cursor, max(0, len(self.items) - 1))
            self.adjust_scroll()

        @kb.add("b")
        def _(event) -> None:
            if self.items and self.items[self.cursor]["url"]:
                open_url(self.items[self.cursor]["url"])

        @kb.add("a")
        def _(event) -> None:
            if self.items:
                event.app.exit(result=Reply(self, self.cursor))

        return kb
