#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["prompt_toolkit", "rich", "pygments", "pyperclip"]
# ///
import subprocess
import json
import sys
import shutil
import threading
from pathlib import Path
from prompt_toolkit import Application, prompt as pt_prompt
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from rich.console import Console
from pygments import lex
from pygments.lexers import get_lexer_for_filename, TextLexer
from pygments.token import Token
import pyperclip

TOKEN_COLORS = {
    Token.Keyword: "#e5da74",
    Token.Keyword.Constant: "#ae81ff",
    Token.Keyword.Namespace: "#e5da74",
    Token.Name.Function: "#a6e22e",
    Token.Name.Class: "#a6e22e",
    Token.Name.Decorator: "#a6e22e",
    Token.Name.Builtin: "#66d9ef",
    Token.Name.Builtin.Pseudo: "#fd971f",
    Token.String: "#e6db74",
    Token.String.Doc: "#88846f",
    Token.Number: "#ae81ff",
    Token.Operator: "#e5da74",
    Token.Comment: "#88846f",
    Token.Comment.Single: "#88846f",
    Token.Comment.Multiline: "#88846f",
    Token.Punctuation: "#f8f8f2",
    Token.Name: "#f8f8f2",
    Token.Text: "#f8f8f2",
}

MONOKAI_STYLE = Style.from_dict({
    "": "#f8f8f2 bg:#272822",
    "item": "#f8f8f2",
    "item-path": "#66d9ef",
    "item-line": "#ae81ff",
    "item-author": "#fd971f",
    "item-state": "#a6e22e",
    "sel-prefix": "#a6e22e bold bg:#3a3d34",
    "sel-path": "#66d9ef bold bg:#3a3d34",
    "sel-line": "#ae81ff bold bg:#3a3d34",
    "sel-author": "#fd971f bold bg:#3a3d34",
    "sel-state": "#a6e22e bold bg:#3a3d34",
    "col-header": "#34D399 bold",
    "col-header-dim": "#75715e",
    "border": "#75715e",
    "header": "#34D399 bold",
    "snippet": "#f8f8f2",
    "snippet-num": "#88846f",
    "snippet-highlight": "#f8f8f2 bg:#49483e",
    "snippet-highlight-num": "#e5da74 bg:#49483e bold",
    "snippet-dim": "#88846f italic",
    "comment-body": "#c6c3b4",
    "comment-header": "#34D399 bold",
    "footer": "#88846f",
    "footer-key": "#34D399 bold",
    "new-notif": "#f92672 bold",
})

ROW_SPACING_EVERY = 0


def ellipsize(text: str, width: int) -> str:
    if width <= 1:
        return text[:width]
    if len(text) <= width:
        return text
    return text[:width - 1] + "…"


def get_repo_info() -> tuple[str, str]:
    result = subprocess.run(
        ["gh", "repo", "view", "--json", "owner,name"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit("Failed to get repo info")
    data = json.loads(result.stdout)
    return data["owner"]["login"], data["name"]


def get_current_pr() -> int | None:
    result = subprocess.run(
        ["gh", "pr", "view", "--json", "number"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)["number"]


def get_unresolved_comments(owner: str, repo: str, pr_number: int) -> list[dict]:
    query = """
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
    result = subprocess.run(
        [
            "gh", "api", "graphql",
            "-f", f"query={query}",
            "-F", f"owner={owner}",
            "-F", f"repo={repo}",
            "-F", f"pr={pr_number}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(f"Failed to fetch comments: {result.stderr}")

    data = json.loads(result.stdout)
    threads = data["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]

    comments = []
    for thread in threads:
        if not thread["isResolved"] and thread["comments"]["nodes"]:
            first_comment = thread["comments"]["nodes"][0]
            all_comments = [
                {
                    "body": c["body"],
                    "author": c["author"]["login"] if c["author"] else "unknown",
                }
                for c in thread["comments"]["nodes"]
            ]
            comment_url = first_comment.get("url", "")
            line = thread["line"] or thread["originalLine"]
            comments.append({
                "thread_id": thread["id"],
                "path": thread["path"],
                "line": line,
                "outdated": thread["line"] is None and thread["originalLine"] is not None,
                "body": first_comment["body"],
                "author": first_comment["author"]["login"] if first_comment["author"] else "unknown",
                "url": comment_url,
                "replies": all_comments[1:],
            })
    return comments


def resolve_thread(thread_id: str) -> bool:
    mutation = """
    mutation($threadId: ID!) {
      resolveReviewThread(input: {threadId: $threadId}) {
        thread { isResolved }
      }
    }
    """
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={mutation}", "-F", f"threadId={thread_id}"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def reply_to_thread(thread_id: str, body: str) -> bool:
    mutation = """
    mutation($threadId: ID!, $body: String!) {
      addPullRequestReviewThreadReply(input: {
        pullRequestReviewThreadId: $threadId,
        body: $body
      }) {
        comment { id }
      }
    }
    """
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={mutation}", "-F", f"threadId={thread_id}", "-f", f"body={body}"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def get_token_color(token_type) -> str:
    while token_type:
        if token_type in TOKEN_COLORS:
            return TOKEN_COLORS[token_type]
        token_type = token_type.parent
    return "#f8f8f2"


def highlight_line(line: str, lexer, is_highlighted: bool) -> list[tuple[str, str]]:
    result = []
    bg = " bg:#49483e" if is_highlighted else ""
    for token_type, token_value in lex(line.rstrip('\n\r'), lexer):
        token_value = token_value.rstrip('\n\r')
        if not token_value:
            continue
        color = get_token_color(token_type)
        result.append((f"{color}{bg}", token_value))
    return result


def get_code_snippet(file_path: str, target_line: int | None, context: int = 3) -> list[tuple[str, str]]:
    if not target_line:
        return [("class:snippet-dim", "  (no line number)")]

    path = Path(file_path)
    if not path.exists():
        return [("class:snippet-dim", f"  (file not found: {file_path})")]

    try:
        content = path.read_text()
        lines = content.splitlines()
    except Exception:
        return [("class:snippet-dim", "  (could not read file)")]

    try:
        lexer = get_lexer_for_filename(file_path, content)
    except Exception:
        lexer = TextLexer()

    start = max(0, target_line - context - 1)
    end = min(len(lines), target_line + context)

    result = []
    for i in range(start, end):
        line_num = i + 1
        line_content = lines[i] if i < len(lines) else ""
        is_target = line_num == target_line

        if is_target:
            result.append(("class:snippet-highlight-num", f"{line_num:4d} "))
            result.append(("#f8f8f2 bg:#49483e", "│ "))
            result.extend(highlight_line(line_content, lexer, True))
        else:
            result.append(("class:snippet-num", f"{line_num:4d} "))
            result.append(("class:snippet", "│ "))
            result.extend(highlight_line(line_content, lexer, False))
        result.append(("", "\n"))

    return result


def open_in_zed(file: str, line: int | None) -> None:
    if line:
        subprocess.run(["zed", f"{file}:{line}"])
    else:
        subprocess.run(["zed", file])


def format_comment_thread(comment: dict) -> str:
    line_info = f"line {comment['line']}" if comment["line"] else "unknown line"
    location = f"{comment['path']}:{comment['line']}" if comment["line"] else comment["path"]
    thread = f"@{comment['author']}: {comment['body']}"
    for reply in comment.get("replies", []):
        thread += f"\n\n↳ @{reply['author']}: {reply['body']}"
    return f"Location: {location} ({line_info})\n\n{thread}"


def format_claude_prompt(comment: dict, pr_number: int, repo: str) -> str:
    prompt = f"""Address this PR review comment on {repo} PR #{pr_number}.

{format_comment_thread(comment)}

Read the file, understand the reviewer's feedback, and make the necessary changes. If the comment is a question or suggestion, evaluate it and formulate a respond, that I can post."""

    return prompt


def format_claude_prompt_multi(comments: list[dict], pr_number: int, repo: str) -> str:
    if len(comments) == 1:
        return format_claude_prompt(comments[0], pr_number, repo)

    threads = "\n\n---\n\n".join(format_comment_thread(c) for c in comments)
    prompt = f"""Address these {len(comments)} PR review comments on {repo} PR #{pr_number}.

{threads}

Read the files, understand the reviewer's feedback, and make the necessary changes. If a comment is a question or suggestion, evaluate it and formulate a respond, that I can post."""

    return prompt


def copy_to_clipboard(text: str) -> None:
    pyperclip.copy(text)


def run_selector(comments: list[dict], pr_number: int, repo: str, owner: str = "", repo_name: str = "") -> dict | None:
    cursor = [0]
    selected: set[int] = set()
    scroll_offset = [0]
    has_new = [False]
    poll_stop = threading.Event()
    visible_count = min(len(comments), 10)
    action: list[dict | None] = [None]
    terminal_width = shutil.get_terminal_size((120, 30)).columns
    prefix_w = 4
    gap_path_line = 3
    gap_author_state = 3
    author_prefix = "@"

    col_line = 6
    col_author = min(24, max(10, max(len(c["author"]) for c in comments)))
    col_state = 10
    fixed = (
        prefix_w
        + col_line
        + gap_path_line
        + 3
        + len(author_prefix)
        + col_author
        + gap_author_state
        + col_state
    )
    col_path = max(24, min(80, terminal_width - fixed))

    def adjust_scroll():
        if cursor[0] < scroll_offset[0]:
            scroll_offset[0] = cursor[0]
        elif cursor[0] >= scroll_offset[0] + visible_count:
            scroll_offset[0] = cursor[0] - visible_count + 1

    def get_header():
        sel_info = f", {len(selected)} selected" if selected else ""
        start = scroll_offset[0] + 1
        end = min(scroll_offset[0] + visible_count, len(comments))
        return [
            ("class:header", "  PR Comments "),
            ("class:border", f"({len(comments)} unresolved{sel_info}, showing {start}-{end})\n"),
        ]

    def get_list_text():
        lines = []
        author_header = f"{author_prefix}{'Author':<{max(0, col_author - len(author_prefix))}}"
        header_line = (
            f"{'':<{prefix_w}}"
            f"{'Path':<{col_path}}"
            f"{'':<{gap_path_line}}"
            f"{'Line':<{col_line}}"
            f"{'':<3}"
            f"{author_header}"
            f"{'':<{gap_author_state}}"
            f"{'Status':<{col_state}}\n"
        )
        separator_line = (
            f"{'':<{prefix_w}}"
            f"{'─' * col_path}"
            f"{'':<{gap_path_line}}"
            f"{'─' * col_line}"
            f"{'':<3}"
            f"{'─' * (col_author + len(author_prefix))}"
            f"{'':<{gap_author_state}}"
            f"{'─' * col_state}\n"
        )
        lines.append(("class:col-header", header_line))
        lines.append(("class:col-header-dim", separator_line))
        start = scroll_offset[0]
        end = min(start + visible_count, len(comments))
        for i in range(start, end):
            c = comments[i]
            is_cursor = i == cursor[0]
            row_idx = i - start
            is_selected = i in selected
            marker = "●" if is_selected else " "
            pointer = "▶" if is_cursor else " "
            prefix = f" {marker}{pointer} "
            if c["line"]:
                line_str = f"~L{c['line']}" if c.get("outdated") else f"L{c['line']}"
            else:
                line_str = "L?"
            line = f"{line_str:<{col_line}}"
            path = ellipsize(c["path"], col_path).ljust(col_path)
            author = ellipsize(c["author"], col_author).ljust(col_author)
            if c["line"] is None:
                state_style, state_text = "detail-value", "unknown"
            elif c.get("outdated"):
                state_style, state_text = "detail-label", "outdated"
            else:
                state_style, state_text = "item-state", "current"
            state = f"{state_text:<{col_state}}"

            if is_cursor:
                lines.append(("class:sel-prefix", prefix))
                lines.append(("class:sel-path", path))
                lines.append(("class:sel-prefix", "   "))
                lines.append(("class:sel-line", line))
                lines.append(("class:sel-prefix", "   @"))
                lines.append(("class:sel-author", author))
                lines.append(("class:sel-prefix", "   "))
                lines.append(("class:sel-state", state))
                lines.append(("", "\n"))
                if ROW_SPACING_EVERY > 0 and (row_idx + 1) % ROW_SPACING_EVERY == 0:
                    lines.append(("", "\n"))
            else:
                lines.append(("class:item", prefix))
                lines.append(("class:item-path", path))
                lines.append(("class:item", "   "))
                lines.append(("class:item-line", line))
                lines.append(("class:item", "   @"))
                lines.append(("class:item-author", author))
                lines.append(("class:item", "   "))
                lines.append((f"class:{state_style}", state))
                lines.append(("class:item", "\n"))
                if ROW_SPACING_EVERY > 0 and (row_idx + 1) % ROW_SPACING_EVERY == 0:
                    lines.append(("", "\n"))
        return lines

    def get_snippet_header():
        if not comments:
            return []
        c = comments[cursor[0]]
        return [("class:comment-header", f"  Code Preview: {c['path']}\n")]

    def get_snippet_text():
        if not comments:
            return []
        c = comments[cursor[0]]
        return get_code_snippet(c["path"], c["line"])

    def get_comment_header():
        if not comments:
            return []
        c = comments[cursor[0]]
        return [("class:comment-header", f"  Comment by @{c['author']}:\n")]

    def get_body_text():
        if not comments:
            return []
        c = comments[cursor[0]]
        result = [("class:comment-body", c["body"])]
        for reply in c.get("replies", []):
            result.append(("", "\n\n"))
            result.append(("class:comment-header", f"  ↳ @{reply['author']}:\n"))
            result.append(("class:comment-body", reply["body"]))
        return result

    def get_footer():
        parts = [
            ("class:footer-key", " j/k "),
            ("class:footer", "nav  "),
            ("class:footer-key", "Space "),
            ("class:footer", "select  "),
            ("class:footer-key", "Enter "),
            ("class:footer", "open  "),
            ("class:footer-key", "b "),
            ("class:footer", "browser  "),
            ("class:footer-key", "a "),
            ("class:footer", "answer  "),
            ("class:footer-key", "c "),
            ("class:footer", "copy  "),
            ("class:footer-key", "d "),
            ("class:footer", "done  "),
            ("class:footer-key", "r "),
            ("class:footer", "refresh  "),
            ("class:footer-key", "q "),
            ("class:footer", "quit"),
        ]
        if has_new[0]:
            parts.append(("class:footer", "  "))
            parts.append(("class:new-notif", "● new comments available"))
        return parts

    header_control = FormattedTextControl(get_header)
    list_control = FormattedTextControl(get_list_text)
    snippet_header_control = FormattedTextControl(get_snippet_header)
    snippet_control = FormattedTextControl(get_snippet_text)
    comment_header_control = FormattedTextControl(get_comment_header)
    body_control = FormattedTextControl(get_body_text)
    footer_control = FormattedTextControl(get_footer)

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _(event):
        cursor[0] = max(0, cursor[0] - 1)
        adjust_scroll()

    @kb.add("down")
    @kb.add("j")
    def _(event):
        cursor[0] = min(len(comments) - 1, cursor[0] + 1)
        adjust_scroll()

    @kb.add("space")
    @kb.add("x")
    def _(event):
        if not comments:
            return
        if cursor[0] in selected:
            selected.discard(cursor[0])
        else:
            selected.add(cursor[0])

    @kb.add("enter")
    def _(event):
        if not comments:
            return
        c = comments[cursor[0]]
        open_in_zed(c["path"], c["line"])

    @kb.add("c")
    def _(event):
        if not comments:
            return
        indices = sorted(selected) if selected else [cursor[0]]
        prompt = format_claude_prompt_multi([comments[i] for i in indices], pr_number, repo)
        copy_to_clipboard(prompt)

    @kb.add("d")
    def _(event):
        if not comments:
            return
        indices = sorted(selected, reverse=True) if selected else [cursor[0]]
        for i in indices:
            if resolve_thread(comments[i]["thread_id"]):
                comments.pop(i)
        selected.clear()
        if not comments:
            event.app.exit()
        elif cursor[0] >= len(comments):
            cursor[0] = len(comments) - 1
        adjust_scroll()

    @kb.add("b")
    def _(event):
        if not comments:
            return
        c = comments[cursor[0]]
        if c["url"]:
            subprocess.Popen(
                ["xdg-open", c["url"]],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

    @kb.add("a")
    def _(event):
        if not comments:
            return
        action[0] = {"type": "reply", "index": cursor[0]}
        event.app.exit()

    @kb.add("r")
    def _(event):
        if not owner or not repo_name:
            return
        has_new[0] = False
        new_comments = get_unresolved_comments(owner, repo_name, pr_number)
        comments.clear()
        comments.extend(new_comments)
        selected.clear()
        if not comments:
            event.app.exit()
            return
        if cursor[0] >= len(comments):
            cursor[0] = len(comments) - 1
        adjust_scroll()

    @kb.add("q")
    @kb.add("escape")
    def _(event):
        event.app.exit()

    list_header_lines = 2
    list_height = visible_count + list_header_lines

    layout = Layout(
        HSplit([
            Window(header_control, height=1),
            Window(list_control, height=list_height),
            Window(char="─", height=1, style="class:border"),
            Window(snippet_header_control, height=1),
            Window(snippet_control, height=9),
            Window(char="─", height=1, style="class:border"),
            Window(comment_header_control, height=1),
            Window(body_control, wrap_lines=True),
            Window(char="─", height=1, style="class:border"),
            Window(footer_control, height=1),
        ])
    )

    app = Application(layout=layout, key_bindings=kb, style=MONOKAI_STYLE, full_screen=True)

    def poll_for_new():
        if not owner or not repo_name:
            return
        current_ids = {c["thread_id"] for c in comments}
        while not poll_stop.wait(30):
            try:
                latest = get_unresolved_comments(owner, repo_name, pr_number)
                latest_ids = {c["thread_id"] for c in latest}
                if latest_ids != current_ids:
                    has_new[0] = True
                    app.invalidate()
            except Exception:
                pass

    poll_thread = threading.Thread(target=poll_for_new, daemon=True)
    poll_thread.start()
    try:
        app.run()
    finally:
        poll_stop.set()
    return action[0]


def main() -> None:
    console = Console()

    with console.status("[bold #e5da74]Fetching PR info..."):
        pr_number = get_current_pr()
        if not pr_number:
            console.print("[#e5da74]No PR found for current branch[/]")
            sys.exit(1)

        owner, repo = get_repo_info()
        comments = get_unresolved_comments(owner, repo, pr_number)

    if not comments:
        console.print("[#e6db74]No unresolved comments on this PR[/]")
        sys.exit(0)

    console.print(f"[bold #a6e22e]Found {len(comments)} unresolved comment(s)[/]\n")

    while comments:
        result = run_selector(comments, pr_number, f"{owner}/{repo}", owner=owner, repo_name=repo)
        if not result:
            break
        if result["type"] == "reply":
            c = comments[result["index"]]
            console.print(f"\n[bold #e5da74]Replying to @{c['author']}[/] on [#66d9ef]{c['path']}:{c['line']}[/]")
            console.print(f"[#88846f]{c['body'][:200]}[/]\n")
            try:
                body = pt_prompt("Reply: ")
            except (EOFError, KeyboardInterrupt):
                continue
            if not body.strip():
                continue
            if reply_to_thread(c["thread_id"], body):
                console.print("[bold #a6e22e]Reply sent[/]\n")
                c["replies"].append({"body": body, "author": "you"})
            else:
                console.print("[bold #f92672]Failed to send reply[/]\n")


if __name__ == "__main__":
    main()
