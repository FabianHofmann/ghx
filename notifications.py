#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["prompt_toolkit", "rich"]
# ///
import subprocess
import json
import sys
import threading
from datetime import datetime, timezone
from prompt_toolkit import Application
from prompt_toolkit.application import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import ConditionalContainer, Dimension, Layout, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from rich.console import Console

DETAIL_META_ROWS = 5
DETAIL_PREVIEW_ROWS = 5
DETAIL_SECTION_ROWS = DETAIL_META_ROWS + DETAIL_PREVIEW_ROWS + 3
DETAIL_MIN_ROWS = 18

ANSI_SEQUENCES["\x1b[I"] = Keys.F23
ANSI_SEQUENCES["\x1b[O"] = Keys.F24

MONOKAI_STYLE = Style.from_dict({
    "": "#f8f8f2",
    "item": "#f8f8f2",
    "item-type": "#ae81ff",
    "item-repo": "#66d9ef",
    "item-reason": "#fd971f",
    "item-time": "#88846f",
    "sel-prefix": "#a6e22e bold bg:#3a3d34",
    "sel-title": "#f8f8f2 bold bg:#3a3d34",
    "sel-type": "#ae81ff bold bg:#3a3d34",
    "sel-repo": "#66d9ef bold bg:#3a3d34",
    "sel-reason": "#fd971f bold bg:#3a3d34",
    "sel-time": "#88846f bold bg:#3a3d34",
    "col-header": "#34D399 bold",
    "col-header-dim": "#75715e",
    "chip-type": "#c7b6ff bg:#343142 bold",
    "chip-reason": "#c7b6ff bg:#343142 bold",
    "chip-state-open": "#a6e22e bg:#2c2f25 bold",
    "chip-state-closed": "#f92672 bg:#34232a bold",
    "chip-state-merged": "#ae81ff bg:#2f2a3a bold",
    "chip-state-draft": "#88846f bg:#2e2d28 bold",
    "border": "#75715e",
    "header": "#34D399 bold",
    "detail-label": "#34D399",
    "detail-value": "#f8f8f2",
    "footer": "#88846f",
    "footer-key": "#34D399 bold",
    "focus-bar": "#a6e22e bold",
    "focus-bar-off": "#3a3d34",
    "header-off": "#75715e bold",
})

ROW_SPACING_EVERY = 0

TYPE_LABELS = {
    "PullRequest": "PR",
    "Issue": "Issue",
    "Release": "Rel",
    "Discussion": "Disc",
    "CheckSuite": "CI",
    "Commit": "Commit",
}

STATE_STYLE = {
    "open": "chip-state-open",
    "closed": "chip-state-closed",
    "merged": "chip-state-merged",
    "draft": "chip-state-draft",
}

REASON_LABELS = {
    "review_requested": "review requested",
    "mention": "mentioned",
    "subscribed": "subscribed",
    "author": "author",
    "comment": "comment",
    "ci_activity": "CI",
    "state_change": "state change",
    "assign": "assigned",
    "team_mention": "team mention",
}


def ellipsize(text: str, width: int) -> str:
    if width <= 1:
        return text[:width]
    if len(text) <= width:
        return text
    return text[:width - 1] + "…"


def relative_time(iso_str: str) -> str:
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    delta = datetime.now(timezone.utc) - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    return f"{months}mo ago"


def api_url_to_browser_url(api_url: str) -> str:
    url = api_url.replace("https://api.github.com/repos/", "https://github.com/")
    url = url.replace("/pulls/", "/pull/")
    return url


def detect_repo() -> str | None:
    result = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def fetch_notifications(repo: str | None) -> list[dict]:
    if repo:
        cmd = ["gh", "api", f"/repos/{repo}/notifications"]
    else:
        cmd = ["gh", "api", "/notifications"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"Failed to fetch notifications: {result.stderr}")
    return json.loads(result.stdout)


def fetch_preview(n: dict) -> str:
    url = n["subject"].get("latest_comment_url") or n["subject"].get("url") or ""
    if not url:
        return ""
    path = url.replace("https://api.github.com", "")
    result = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    body = json.loads(result.stdout).get("body") or ""
    return " ".join(body.split())


def fetch_states(items: list[dict]) -> dict[str, str]:
    targets = []
    for n in items:
        if n["subject"]["type"] not in ("PullRequest", "Issue"):
            continue
        url = n["subject"].get("url") or ""
        owner, _, name = n["repository"]["full_name"].partition("/")
        number = url.rstrip("/").rsplit("/", 1)[-1]
        if not (owner and name and number.isdigit()):
            continue
        targets.append((n["id"], owner, name, int(number)))
    if not targets:
        return {}
    aliases = [
        f'n{idx}: repository(owner: "{owner}", name: "{name}") {{ '
        f"issueOrPullRequest(number: {number}) {{ __typename "
        f"... on PullRequest {{ state isDraft }} ... on Issue {{ state }} }} }}"
        for idx, (_, owner, name, number) in enumerate(targets)
    ]
    query = "query {\n" + "\n".join(aliases) + "\n}"
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={query}"],
        capture_output=True, text=True,
    )
    if not result.stdout:
        return {}
    data = json.loads(result.stdout).get("data") or {}
    states: dict[str, str] = {}
    for idx, (nid, *_rest) in enumerate(targets):
        node = (data.get(f"n{idx}") or {}).get("issueOrPullRequest") or {}
        state = (node.get("state") or "").lower()
        if node.get("__typename") == "PullRequest" and state == "open" and node.get("isDraft"):
            state = "draft"
        states[nid] = state
    return states


def mark_as_done(thread_id: str) -> bool:
    result = subprocess.run(
        ["gh", "api", "-X", "PATCH", f"/notifications/threads/{thread_id}"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def run_selector(notifications: list[dict], all_repos: bool, repo: str | None) -> None:
    selected = [0]
    scroll_offset = [0]
    has_focus = [True]
    detail_expanded = [False]
    preview_cache: dict[str, str | None] = {}
    state_cache: dict[str, str | None] = {}
    poll_stop = threading.Event()
    list_header_lines = 2

    def viewport_width() -> int:
        return get_app().output.get_size().columns - 1

    def detail_visible() -> bool:
        return detail_expanded[0] and get_app().output.get_size().rows >= DETAIL_MIN_ROWS

    def list_capacity() -> int:
        total = get_app().output.get_size().rows
        chrome = (DETAIL_SECTION_ROWS + 2) if detail_visible() else 2
        return max(1, total - chrome - list_header_lines)

    prefix_w = 3
    title_padding = 4
    repo_padding = 3
    reason_padding = 3

    col_type = 10
    col_state = 8
    state_padding = 2
    reason_lens = [len(REASON_LABELS.get(n["reason"], n["reason"])) for n in notifications]
    col_reason = min(26, max(12, max(reason_lens, default=12)))
    repo_lens = [len(n["repository"]["full_name"]) for n in notifications]
    col_repo = min(24, max(10, max(repo_lens, default=10))) if all_repos else 0
    col_time = 8
    fixed = (
        prefix_w
        + col_type
        + col_state
        + state_padding
        + title_padding
        + (col_repo + repo_padding if all_repos else 0)
        + col_reason
        + reason_padding
        + col_time
    )

    def title_width() -> int:
        return max(20, viewport_width() - fixed)

    def adjust_scroll():
        capacity = list_capacity()
        if selected[0] < scroll_offset[0]:
            scroll_offset[0] = selected[0]
        elif selected[0] >= scroll_offset[0] + capacity:
            scroll_offset[0] = selected[0] - capacity + 1

    def get_header():
        hdr = "class:header" if has_focus[0] else "class:header-off"
        if not notifications:
            return [(hdr, "  Notifications "), ("class:border", "(0 unread)\n")]
        start = scroll_offset[0] + 1
        end = min(scroll_offset[0] + list_capacity(), len(notifications))
        return [
            (hdr, "  Notifications "),
            ("class:border", f"({len(notifications)} unread, showing {start}-{end})\n"),
        ]

    def state_cell(n: dict, selected_row: bool) -> tuple[str, str]:
        if n["subject"]["type"] not in ("PullRequest", "Issue"):
            return ("class:sel-title" if selected_row else "class:item", f"{'':<{col_state + state_padding}}")
        state = state_cache.get(n["id"])
        if state is None:
            return ("class:item-time", f" {'…':<{col_state + state_padding - 1}}")
        if not state:
            return ("class:sel-title" if selected_row else "class:item", f"{'':<{col_state + state_padding}}")
        chip = f" {state:<{col_state - 2}} "
        return (f"class:{STATE_STYLE[state]}", chip + " " * state_padding)

    def get_list_text():
        col_title = title_width()
        lines = []
        header_line = f"{'':<{prefix_w}}{'Type':<{col_type}}{'State':<{col_state + state_padding}}{'Title':<{col_title + title_padding}}"
        if all_repos:
            header_line += f"{'Repo':<{col_repo + repo_padding}}"
        header_line += f"{'Reason':<{col_reason + reason_padding}}{'When':<{col_time}}\n"
        sep = f"{'':<{prefix_w}}{'─' * col_type}{'─' * (col_state + state_padding)}{'─' * (col_title + title_padding)}"
        if all_repos:
            sep += f"{'─' * (col_repo + repo_padding)}"
        sep += f"{'─' * (col_reason + reason_padding)}{'─' * col_time}"
        lines.append(("class:col-header", header_line))
        lines.append(("class:col-header-dim", f"{sep}\n"))
        if not notifications:
            lines.append(("class:item-time", "\n   Inbox zero — watching for new notifications…\n"))
            return lines
        start = scroll_offset[0]
        end = min(start + list_capacity(), len(notifications))
        for i in range(start, end):
            n = notifications[i]
            is_sel = i == selected[0]
            row_idx = i - start
            prefix = " ▶ " if is_sel else "   "
            type_label = TYPE_LABELS.get(n["subject"]["type"], n["subject"]["type"][:4])
            type_chip = f" {ellipsize(type_label, col_type - 2):<{col_type - 2}} "
            state_style, state_chip = state_cell(n, is_sel)
            title = ellipsize(n["subject"]["title"], col_title).ljust(col_title)
            repo = ellipsize(n["repository"]["full_name"], col_repo).ljust(col_repo) if all_repos else ""
            reason_label = REASON_LABELS.get(n["reason"], n["reason"])
            reason_chip = f" {ellipsize(reason_label, col_reason - 2):<{col_reason - 2}} "
            time_col = f"{relative_time(n['updated_at']):<{col_time}}"

            if is_sel:
                lines.append(("class:sel-prefix", prefix))
                lines.append(("class:chip-type", type_chip))
                lines.append((state_style, state_chip))
                lines.append(("class:sel-title", f" {title}   "))
                if all_repos:
                    lines.append(("class:sel-repo", f"{repo}   "))
                lines.append(("class:chip-reason", reason_chip))
                lines.append(("class:sel-title", "   "))
                lines.append(("class:sel-time", time_col))
                lines.append(("", "\n"))
                if ROW_SPACING_EVERY > 0 and (row_idx + 1) % ROW_SPACING_EVERY == 0:
                    lines.append(("", "\n"))
            else:
                lines.append(("class:item", prefix))
                lines.append(("class:chip-type", type_chip))
                lines.append((state_style, state_chip))
                lines.append(("class:item", f" {title}   "))
                if all_repos:
                    lines.append(("class:item-repo", f"{repo}   "))
                lines.append(("class:chip-reason", reason_chip))
                lines.append(("class:item", "   "))
                lines.append(("class:item-time", time_col))
                lines.append(("class:item", "\n"))
                if ROW_SPACING_EVERY > 0 and (row_idx + 1) % ROW_SPACING_EVERY == 0:
                    lines.append(("", "\n"))
        return lines

    def get_detail_header():
        if not notifications:
            return []
        n = notifications[selected[0]]
        return [("class:header", f"  {n['subject']['title']}\n")]

    def get_detail_text():
        if not notifications:
            return []
        n = notifications[selected[0]]
        type_label = TYPE_LABELS.get(n["subject"]["type"], n["subject"]["type"])
        reason = REASON_LABELS.get(n["reason"], n["reason"])
        state = state_cache.get(n["id"])
        if n["subject"]["type"] not in ("PullRequest", "Issue"):
            state_part = [("class:item-time", "n/a")]
        elif state is None:
            state_part = [("class:item-time", "loading…")]
        elif not state:
            state_part = [("class:item-time", "unknown")]
        else:
            state_part = [(f"class:{STATE_STYLE[state]}", f" {state} ")]
        lines = [
            ("class:detail-label", "  Repo: "),
            ("class:item-repo", n["repository"]["full_name"]),
            ("class:detail-value", "\n"),
            ("class:detail-label", "  Type: "),
            ("class:sel-type", type_label),
            ("class:detail-value", "\n"),
            ("class:detail-label", "  State: "),
            *state_part,
            ("class:detail-value", "\n"),
            ("class:detail-label", "  Reason: "),
            ("class:item-reason", reason),
            ("class:detail-value", "\n"),
            ("class:detail-label", "  Updated: "),
            ("class:item-time", relative_time(n["updated_at"])),
            ("class:detail-value", "\n"),
        ]
        return lines

    def get_preview_text():
        if not notifications:
            return []
        label = [("class:detail-label", "  Preview: ")]
        cached = preview_cache.get(notifications[selected[0]]["id"])
        if cached is None:
            return label + [("class:item-time", "loading…")]
        if not cached:
            return label + [("class:item-time", "(no preview)")]
        max_chars = (DETAIL_PREVIEW_ROWS - 1) * max(1, viewport_width() - 3)
        return label + [("class:detail-value", "\n  " + ellipsize(cached, max_chars))]

    def get_footer():
        return [
            ("class:footer-key", " ↑/k "),
            ("class:footer", "up  "),
            ("class:footer-key", "↓/j "),
            ("class:footer", "down  "),
            ("class:footer-key", "Enter/b "),
            ("class:footer", "browse  "),
            ("class:footer-key", "d "),
            ("class:footer", "done  "),
            ("class:footer-key", "Space "),
            ("class:footer", f"{'hide' if detail_expanded[0] else 'details'}  "),
            ("class:footer-key", "r "),
            ("class:footer", "refresh  "),
            ("class:footer-key", "q/Esc "),
            ("class:footer", "quit"),
        ]

    header_control = FormattedTextControl(get_header)
    list_control = FormattedTextControl(get_list_text, show_cursor=False, focusable=True)
    detail_header_control = FormattedTextControl(get_detail_header)
    detail_control = FormattedTextControl(get_detail_text)
    preview_control = FormattedTextControl(get_preview_text)
    footer_control = FormattedTextControl(get_footer)

    def apply_notifications(new_notifications: list[dict]) -> None:
        prev_updated = {n["id"]: n["updated_at"] for n in notifications}
        current_id = notifications[selected[0]]["id"] if notifications else None
        notifications.clear()
        notifications.extend(new_notifications)
        for n in notifications:
            if prev_updated.get(n["id"]) != n["updated_at"]:
                state_cache.pop(n["id"], None)
                preview_cache.pop(n["id"], None)
        selected[0] = next(
            (i for i, n in enumerate(notifications) if n["id"] == current_id),
            min(selected[0], max(0, len(notifications) - 1)),
        )
        adjust_scroll()
        get_app().invalidate()

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _(event):
        if not notifications:
            return
        selected[0] = max(0, selected[0] - 1)
        adjust_scroll()

    @kb.add("down")
    @kb.add("j")
    def _(event):
        if not notifications:
            return
        selected[0] = min(len(notifications) - 1, selected[0] + 1)
        adjust_scroll()

    @kb.add("enter")
    @kb.add("b")
    def _(event):
        if not notifications:
            return
        n = notifications[selected[0]]
        url = n["subject"].get("url", "")
        if url:
            browser_url = api_url_to_browser_url(url)
            subprocess.Popen(
                ["xdg-open", browser_url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

    @kb.add("d")
    def _(event):
        if not notifications:
            return
        n = notifications[selected[0]]
        if mark_as_done(n["id"]):
            notifications.pop(selected[0])
            if selected[0] >= len(notifications):
                selected[0] = max(0, len(notifications) - 1)
            adjust_scroll()

    @kb.add(" ")
    def _(event):
        detail_expanded[0] = not detail_expanded[0]
        adjust_scroll()
        event.app.invalidate()

    @kb.add("r")
    def _(event):
        apply_notifications(fetch_notifications(repo))

    @kb.add(Keys.F23)
    def _(event):
        has_focus[0] = True
        event.app.invalidate()

    @kb.add(Keys.F24)
    def _(event):
        has_focus[0] = False
        event.app.invalidate()

    @kb.add("q")
    @kb.add("escape")
    def _(event):
        event.app.exit()

    detail_section = ConditionalContainer(
        HSplit([
            Window(char="─", height=1, style="class:border"),
            Window(detail_header_control, height=1),
            Window(detail_control, height=DETAIL_META_ROWS),
            Window(preview_control, height=DETAIL_PREVIEW_ROWS, wrap_lines=True),
            Window(char="─", height=1, style="class:border"),
        ]),
        filter=Condition(detail_visible),
    )

    def bar_style() -> str:
        return "class:focus-bar" if has_focus[0] else "class:focus-bar-off"

    accent_bar = Window(width=1, char="┃", style=bar_style)

    layout = Layout(
        VSplit([
            accent_bar,
            HSplit([
                Window(header_control, height=1),
                Window(list_control, height=Dimension(min=1, weight=1)),
                detail_section,
                Window(footer_control, height=1),
            ]),
        ])
    )

    app = Application(layout=layout, key_bindings=kb, style=MONOKAI_STYLE, full_screen=True)

    def signature(items: list[dict]) -> set[tuple[str, str]]:
        return {(n["id"], n["updated_at"]) for n in items}

    def poll_for_new():
        while not poll_stop.wait(30):
            try:
                latest = fetch_notifications(repo)
            except Exception:
                continue
            if signature(latest) != signature(notifications) and app.loop is not None:
                app.loop.call_soon_threadsafe(apply_notifications, latest)

    def preview_worker():
        while not poll_stop.wait(0.1):
            idx = selected[0]
            if not detail_expanded[0] or not notifications or idx >= len(notifications):
                continue
            n = notifications[idx]
            if n["id"] in preview_cache:
                continue
            preview_cache[n["id"]] = None
            preview_cache[n["id"]] = fetch_preview(n)
            if app.loop is not None:
                app.loop.call_soon_threadsafe(app.invalidate)

    def state_worker():
        while not poll_stop.wait(0.1):
            pending = [n for n in list(notifications) if n["id"] not in state_cache]
            if not pending:
                continue
            for n in pending:
                state_cache[n["id"]] = None
            for start in range(0, len(pending), 50):
                chunk = pending[start:start + 50]
                states = fetch_states(chunk)
                for n in chunk:
                    state_cache[n["id"]] = states.get(n["id"], "")
                if app.loop is not None:
                    app.loop.call_soon_threadsafe(app.invalidate)

    def enable_focus_reporting() -> None:
        app.output.write_raw("\x1b[?1004h")
        app.output.flush()

    poll_thread = threading.Thread(target=poll_for_new, daemon=True)
    poll_thread.start()
    preview_thread = threading.Thread(target=preview_worker, daemon=True)
    preview_thread.start()
    state_thread = threading.Thread(target=state_worker, daemon=True)
    state_thread.start()
    try:
        app.run(pre_run=enable_focus_reporting)
    finally:
        poll_stop.set()
        app.output.write_raw("\x1b[?1004l")
        app.output.flush()


def main() -> int:
    console = Console()

    with console.status("[bold #e5da74]Fetching notifications..."):
        repo = detect_repo()
        notifications = fetch_notifications(repo)

    all_repos = repo is None
    scope = f"in {repo}" if repo else "across all repos"
    console.print(f"[bold #a6e22e]Found {len(notifications)} unread notification(s) {scope}[/]\n")

    run_selector(notifications, all_repos, repo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
