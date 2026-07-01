#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["prompt_toolkit", "rich"]
# ///
import json
import subprocess
import sys
import threading
from prompt_toolkit import Application
from prompt_toolkit.application import get_app
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Dimension, HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from rich.console import Console

ANSI_SEQUENCES["\x1b[I"] = Keys.F23
ANSI_SEQUENCES["\x1b[O"] = Keys.F24

MONOKAI_STYLE = Style.from_dict({
    "": "#f8f8f2",
    "header": "#34D399 bold",
    "header-off": "#75715e bold",
    "header-dim": "#75715e",
    "branch": "#66d9ef bold",
    "col-header": "#34D399 bold",
    "col-header-dim": "#75715e",
    "item": "#f8f8f2",
    "item-num": "#fd971f",
    "item-title": "#f8f8f2",
    "chip-kind-pr": "#c7b6ff bg:#343142 bold",
    "chip-kind-issue": "#a6e22e bg:#2c2f25 bold",
    "chip-state-open": "#a6e22e bg:#2c2f25 bold",
    "chip-state-closed": "#f92672 bg:#34232a bold",
    "chip-state-merged": "#ae81ff bg:#2f2a3a bold",
    "chip-state-draft": "#88846f bg:#2e2d28 bold",
    "sel-prefix": "#a6e22e bold bg:#3a3d34",
    "sel-num": "#fd971f bold bg:#3a3d34",
    "sel-title": "#f8f8f2 bold bg:#3a3d34",
    "footer": "#88846f",
    "footer-key": "#34D399 bold",
    "focus-bar": "#a6e22e bold",
    "focus-bar-off": "#3a3d34",
})

STATE_STYLE = {
    "open": "chip-state-open",
    "closed": "chip-state-closed",
    "merged": "chip-state-merged",
    "draft": "chip-state-draft",
}

CONTEXT_QUERY = """
query($owner: String!, $name: String!, $pr: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $pr) {
      number title state isDraft url
      labels(first: 20) { nodes { name color } }
      closingIssuesReferences(first: 30) {
        nodes {
          number title state url
          labels(first: 20) { nodes { name color } }
        }
      }
    }
  }
}
"""


def ellipsize(text: str, width: int) -> str:
    if width <= 1:
        return text[:max(0, width)]
    if len(text) <= width:
        return text
    return text[:width - 1] + "…"


def detect_repo() -> str | None:
    result = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() or None if result.returncode == 0 else None


def current_branch() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() or "(detached)"


def get_pr_number() -> int | None:
    result = subprocess.run(
        ["gh", "pr", "view", "--json", "number", "-q", ".number"],
        capture_output=True, text=True,
    )
    number = result.stdout.strip()
    return int(number) if result.returncode == 0 and number else None


def normalize_state(state: str, is_draft: bool) -> str:
    state = state.lower()
    return "draft" if state == "open" and is_draft else state


def labels_of(node: dict) -> list[dict]:
    return [{"name": l["name"], "color": l["color"]} for l in node["labels"]["nodes"]]


def fetch_context(owner: str, name: str, pr: int) -> dict | None:
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={CONTEXT_QUERY}",
         "-f", f"owner={owner}", "-f", f"name={name}", "-F", f"pr={pr}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout:
        return None
    node = (json.loads(result.stdout).get("data") or {}).get("repository", {}).get("pullRequest")
    if not node:
        return None
    return {
        "pr": {
            "kind": "pr",
            "number": node["number"],
            "title": node["title"],
            "state": normalize_state(node["state"], node["isDraft"]),
            "url": node["url"],
            "labels": labels_of(node),
        },
        "issues": [
            {
                "kind": "issue",
                "number": issue["number"],
                "title": issue["title"],
                "state": normalize_state(issue["state"], False),
                "url": issue["url"],
                "labels": labels_of(issue),
            }
            for issue in node["closingIssuesReferences"]["nodes"]
        ],
    }


def entries_of(context: dict | None) -> list[dict]:
    if context is None:
        return []
    return [context["pr"], *context["issues"]]


def open_url(url: str) -> None:
    subprocess.Popen(
        ["xdg-open", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )


def run_viewer(branch: str, repo: str, owner: str, name: str, pr: int | None, context: dict | None) -> None:
    state = {"pr": pr, "context": context, "entries": entries_of(context), "selected": 0, "focus": True}
    poll_stop = threading.Event()

    def load() -> tuple[int | None, dict | None]:
        pr_number = get_pr_number()
        return pr_number, (fetch_context(owner, name, pr_number) if pr_number is not None else None)

    def viewport_width() -> int:
        return get_app().output.get_size().columns - 3

    def label_tokens(labels: list[dict]) -> list[tuple[str, str]]:
        return [(f"fg:#{label['color']} bold", f" {label['name']}") for label in labels]

    def state_chip(item: dict) -> tuple[str, str]:
        return (f"class:{STATE_STYLE[item['state']]}", f" {item['state']:<7} ")

    def get_header():
        hdr = "class:header" if state["focus"] else "class:header-off"
        line1 = [(hdr, "  Branch "), ("class:branch", branch), ("class:header-dim", f"  ·  {repo}\n")]
        if not state["entries"]:
            line2 = [("class:header-dim", "  No open PR for this branch\n")]
        else:
            count = len(state["context"]["issues"])
            noun = "issue" if count == 1 else "issues"
            line2 = [("class:header-dim", f"  PR #{state['pr']} · {count} linked {noun}\n")]
        return line1 + line2

    def get_list_text():
        if not state["entries"]:
            return [("class:item", "\n   Nothing to show — open a PR or link issues to it.\n")]
        col_title = max(20, viewport_width() - 28)
        lines: list[tuple[str, str]] = []
        for i, item in enumerate(state["entries"]):
            is_sel = i == state["selected"]
            prefix = " ▶ " if is_sel else "   "
            kind_class = "chip-kind-pr" if item["kind"] == "pr" else "chip-kind-issue"
            kind_label = "PR" if item["kind"] == "pr" else "issue"
            st_style, st_chip = state_chip(item)
            title = ellipsize(item["title"], col_title)
            lines.append(("class:sel-prefix" if is_sel else "class:item", prefix))
            lines.append((f"class:{kind_class}", f" {kind_label:<5} "))
            lines.append((st_style, st_chip))
            lines.append(("class:sel-num" if is_sel else "class:item-num", f" #{item['number']:<5}"))
            lines.append(("class:sel-title" if is_sel else "class:item-title", f" {title}"))
            lines.extend(label_tokens(item["labels"]))
            lines.append(("class:item", "\n"))
        return lines

    def get_footer():
        return [
            ("class:footer-key", " ↑/k "), ("class:footer", "up  "),
            ("class:footer-key", "↓/j "), ("class:footer", "down  "),
            ("class:footer-key", "Enter/b "), ("class:footer", "browse  "),
            ("class:footer-key", "r "), ("class:footer", "refresh  "),
            ("class:footer-key", "q/Esc "), ("class:footer", "quit"),
        ]

    def apply(new_pr: int | None, new_context: dict | None) -> None:
        current = state["entries"][state["selected"]]["number"] if state["entries"] else None
        state["pr"] = new_pr
        state["context"] = new_context
        state["entries"] = entries_of(new_context)
        state["selected"] = next(
            (i for i, e in enumerate(state["entries"]) if e["number"] == current),
            min(state["selected"], max(0, len(state["entries"]) - 1)),
        )
        get_app().invalidate()

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _(event):
        state["selected"] = max(0, state["selected"] - 1)

    @kb.add("down")
    @kb.add("j")
    def _(event):
        state["selected"] = min(len(state["entries"]) - 1, state["selected"] + 1)

    @kb.add("enter")
    @kb.add("b")
    def _(event):
        if state["entries"]:
            open_url(state["entries"][state["selected"]]["url"])

    @kb.add("r")
    def _(event):
        apply(*load())

    @kb.add(Keys.F23)
    def _(event):
        state["focus"] = True
        event.app.invalidate()

    @kb.add(Keys.F24)
    def _(event):
        state["focus"] = False
        event.app.invalidate()

    @kb.add("q")
    @kb.add("escape")
    def _(event):
        event.app.exit()

    def bar_style() -> str:
        return "class:focus-bar" if state["focus"] else "class:focus-bar-off"

    layout = Layout(VSplit([
        Window(width=1, char="┃", style=bar_style),
        HSplit([
            Window(FormattedTextControl(get_header), height=2),
            Window(FormattedTextControl(get_list_text, show_cursor=False, focusable=True),
                   height=Dimension(min=1, weight=1)),
            Window(FormattedTextControl(get_footer), height=1),
        ]),
    ]))

    app = Application(layout=layout, key_bindings=kb, style=MONOKAI_STYLE, full_screen=True)

    def poll():
        while not poll_stop.wait(30):
            try:
                new_pr, latest = load()
            except Exception:
                continue
            if (new_pr, latest) != (state["pr"], state["context"]) and app.loop is not None:
                app.loop.call_soon_threadsafe(apply, new_pr, latest)

    def enable_focus_reporting() -> None:
        app.output.write_raw("\x1b[?1004h")
        app.output.flush()

    threading.Thread(target=poll, daemon=True).start()
    try:
        app.run(pre_run=enable_focus_reporting)
    finally:
        poll_stop.set()
        app.output.write_raw("\x1b[?1004l")
        app.output.flush()


STATIC_STATE_COLOR = {"open": "#a6e22e", "closed": "#f92672", "merged": "#ae81ff", "draft": "#88846f"}


def state_markup(state: str) -> str:
    return f"[{STATIC_STATE_COLOR[state]}]{state}[/]"


def print_static(branch: str, repo: str, pr: int | None, context: dict | None) -> None:
    console = Console()
    console.print(f"[bold #66d9ef]{branch}[/] [#75715e]·[/] [#75715e]{repo}[/]")
    if context is None:
        console.print("[#75715e]No open PR for this branch[/]")
        return
    p = context["pr"]
    console.print(f"[#ae81ff]PR #{p['number']}[/] {state_markup(p['state'])} {p['title']}")
    if not context["issues"]:
        console.print("[#75715e]No linked issues[/]")
    for issue in context["issues"]:
        console.print(f"  [#fd971f]#{issue['number']}[/] {state_markup(issue['state'])} {issue['title']}")


def main() -> int:
    repo = detect_repo()
    if repo is None:
        print("Not in a GitHub repository", file=sys.stderr)
        return 1
    owner, _, name = repo.partition("/")
    branch = current_branch()

    console = Console()
    with console.status("[bold #e5da74]Fetching branch context..."):
        pr = get_pr_number()
        context = fetch_context(owner, name, pr) if pr is not None else None

    if not sys.stdout.isatty():
        print_static(branch, repo, pr, context)
        return 0

    run_viewer(branch, repo, owner, name, pr, context)
    return 0


if __name__ == "__main__":
    sys.exit(main())
