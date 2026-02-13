#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["prompt_toolkit", "rich", "pygments", "pyperclip"]
# ///
import subprocess
import json
import sys
from pathlib import Path
from prompt_toolkit import Application
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
    "sel-prefix": "#a6e22e bold",
    "sel-path": "#66d9ef bold",
    "sel-line": "#ae81ff bold",
    "sel-author": "#fd971f bold",
    "border": "#75715e",
    "header": "#e5da74 bold",
    "snippet": "#f8f8f2",
    "snippet-num": "#88846f",
    "snippet-highlight": "#f8f8f2 bg:#49483e",
    "snippet-highlight-num": "#e5da74 bg:#49483e bold",
    "snippet-dim": "#88846f italic",
    "comment-body": "#a6e22e",
    "comment-header": "#e5da74 bold",
    "footer": "#88846f",
    "footer-key": "#e5da74 bold",
})


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
            line = thread["line"] or thread["originalLine"]
            comments.append({
                "thread_id": thread["id"],
                "path": thread["path"],
                "line": line,
                "outdated": thread["line"] is None and thread["originalLine"] is not None,
                "body": first_comment["body"],
                "author": first_comment["author"]["login"] if first_comment["author"] else "unknown",
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

Read the file, understand the reviewer's feedback, and make the necessary changes. If the comment is a question or suggestion, evaluate it and respond appropriately."""

    escaped = prompt.replace("'", "'\\''")
    return f"co '{escaped}'"


def format_claude_prompt_multi(comments: list[dict], pr_number: int, repo: str) -> str:
    if len(comments) == 1:
        return format_claude_prompt(comments[0], pr_number, repo)

    threads = "\n\n---\n\n".join(format_comment_thread(c) for c in comments)
    prompt = f"""Address these {len(comments)} PR review comments on {repo} PR #{pr_number}.

{threads}

Read the files, understand the reviewer's feedback, and make the necessary changes. If a comment is a question or suggestion, evaluate it and respond appropriately."""

    escaped = prompt.replace("'", "'\\''")
    return f"co '{escaped}'"


def copy_to_clipboard(text: str) -> None:
    pyperclip.copy(text)


def run_selector(comments: list[dict], pr_number: int, repo: str) -> None:
    cursor = [0]
    selected: set[int] = set()
    scroll_offset = [0]
    visible_count = min(len(comments), 10)

    def adjust_scroll():
        if cursor[0] < scroll_offset[0]:
            scroll_offset[0] = cursor[0]
        elif cursor[0] >= scroll_offset[0] + visible_count:
            scroll_offset[0] = cursor[0] - visible_count + 1

    def get_header():
        sel_info = f", {len(selected)} selected" if selected else ""
        return [
            ("class:header", "  PR Comments "),
            ("class:border", f"({len(comments)} unresolved{sel_info})\n"),
        ]

    def get_list_text():
        lines = []
        start = scroll_offset[0]
        end = min(start + visible_count, len(comments))
        for i in range(start, end):
            c = comments[i]
            is_cursor = i == cursor[0]
            is_selected = i in selected
            marker = "●" if is_selected else " "
            pointer = "▶" if is_cursor else " "
            prefix = f" {marker}{pointer} "
            if c["line"]:
                line_str = f"~L{c['line']}" if c.get("outdated") else f"L{c['line']}"
            else:
                line_str = "L?"

            if is_cursor:
                lines.append(("class:sel-prefix", prefix))
                lines.append(("class:sel-path", c["path"]))
                lines.append(("class:sel-prefix", ":"))
                lines.append(("class:sel-line", line_str))
                lines.append(("class:sel-prefix", " @"))
                lines.append(("class:sel-author", c["author"]))
                lines.append(("", "\n"))
            else:
                lines.append(("class:item", prefix))
                lines.append(("class:item-path", c["path"]))
                lines.append(("class:item", ":"))
                lines.append(("class:item-line", line_str))
                lines.append(("class:item", " @"))
                lines.append(("class:item-author", c["author"]))
                lines.append(("class:item", "\n"))
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
        return [
            ("class:footer-key", " j/k "),
            ("class:footer", "nav  "),
            ("class:footer-key", "Space "),
            ("class:footer", "select  "),
            ("class:footer-key", "Enter "),
            ("class:footer", "open  "),
            ("class:footer-key", "c "),
            ("class:footer", "copy  "),
            ("class:footer-key", "r "),
            ("class:footer", "resolve  "),
            ("class:footer-key", "q "),
            ("class:footer", "quit"),
        ]

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

    @kb.add("r")
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

    @kb.add("q")
    @kb.add("escape")
    def _(event):
        event.app.exit()

    list_height = visible_count

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
    app.run()


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
    console.print("[#88846f]j/k nav, Space select, Enter open, c copy, r resolve, q quit[/]\n")

    run_selector(comments, pr_number, f"{owner}/{repo}")


if __name__ == "__main__":
    main()
