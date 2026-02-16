#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["prompt_toolkit", "rich"]
# ///
import subprocess
import json
import sys
from datetime import datetime, timezone
from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from rich.console import Console

MONOKAI_STYLE = Style.from_dict({
    "": "#f8f8f2 bg:#272822",
    "item": "#f8f8f2",
    "item-type": "#ae81ff",
    "item-repo": "#66d9ef",
    "item-reason": "#fd971f",
    "item-time": "#88846f",
    "sel-prefix": "#a6e22e bold",
    "sel-title": "#f8f8f2 bold",
    "sel-type": "#ae81ff bold",
    "sel-repo": "#66d9ef bold",
    "sel-reason": "#fd971f bold",
    "sel-time": "#88846f bold",
    "border": "#75715e",
    "header": "#e5da74 bold",
    "detail-label": "#e5da74",
    "detail-value": "#f8f8f2",
    "footer": "#88846f",
    "footer-key": "#e5da74 bold",
})

TYPE_LABELS = {
    "PullRequest": "PR",
    "Issue": "Issue",
    "Release": "Rel",
    "Discussion": "Disc",
    "CheckSuite": "CI",
    "Commit": "Commit",
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


def mark_as_done(thread_id: str) -> bool:
    result = subprocess.run(
        ["gh", "api", "-X", "PATCH", f"/notifications/threads/{thread_id}"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def run_selector(notifications: list[dict], all_repos: bool) -> None:
    selected = [0]
    scroll_offset = [0]
    visible_count = min(len(notifications), 12)

    col_type = 5
    col_title = min(60, max(len(n["subject"]["title"][:60]) for n in notifications))
    col_repo = max(len(n["repository"]["full_name"]) for n in notifications) if all_repos else 0
    col_reason = max(len(REASON_LABELS.get(n["reason"], n["reason"])) for n in notifications)

    def adjust_scroll():
        if selected[0] < scroll_offset[0]:
            scroll_offset[0] = selected[0]
        elif selected[0] >= scroll_offset[0] + visible_count:
            scroll_offset[0] = selected[0] - visible_count + 1

    def get_header():
        return [
            ("class:header", "  Notifications "),
            ("class:border", f"({len(notifications)} unread)\n"),
        ]

    def get_list_text():
        lines = []
        start = scroll_offset[0]
        end = min(start + visible_count, len(notifications))
        for i in range(start, end):
            n = notifications[i]
            is_sel = i == selected[0]
            prefix = " ▶ " if is_sel else "   "
            type_label = TYPE_LABELS.get(n["subject"]["type"], n["subject"]["type"][:4])
            title = n["subject"]["title"][:60].ljust(col_title)
            repo = n["repository"]["full_name"].ljust(col_repo) if all_repos else ""
            reason = REASON_LABELS.get(n["reason"], n["reason"]).ljust(col_reason)
            time_str = relative_time(n["updated_at"])

            if is_sel:
                lines.append(("class:sel-prefix", prefix))
                lines.append(("class:sel-type", f"{type_label:<{col_type}}"))
                lines.append(("class:sel-title", f"{title}  "))
                if all_repos:
                    lines.append(("class:sel-repo", f"{repo}  "))
                lines.append(("class:sel-reason", f"{reason}  "))
                lines.append(("class:sel-time", time_str))
                lines.append(("", "\n"))
            else:
                lines.append(("class:item", prefix))
                lines.append(("class:item-type", f"{type_label:<{col_type}}"))
                lines.append(("class:item", f"{title}  "))
                if all_repos:
                    lines.append(("class:item-repo", f"{repo}  "))
                lines.append(("class:item-reason", f"{reason}  "))
                lines.append(("class:item-time", time_str))
                lines.append(("class:item", "\n"))
        return lines

    def get_detail_header():
        n = notifications[selected[0]]
        return [("class:header", f"  {n['subject']['title']}\n")]

    def get_detail_text():
        n = notifications[selected[0]]
        type_label = TYPE_LABELS.get(n["subject"]["type"], n["subject"]["type"])
        reason = REASON_LABELS.get(n["reason"], n["reason"])
        lines = [
            ("class:detail-label", "  Repo: "),
            ("class:item-repo", n["repository"]["full_name"]),
            ("class:detail-value", "\n"),
            ("class:detail-label", "  Type: "),
            ("class:item-type", type_label),
            ("class:detail-value", "\n"),
            ("class:detail-label", "  Reason: "),
            ("class:item-reason", reason),
            ("class:detail-value", "\n"),
            ("class:detail-label", "  Updated: "),
            ("class:item-time", relative_time(n["updated_at"])),
            ("class:detail-value", "\n"),
        ]
        return lines

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
        selected[0] = min(len(notifications) - 1, selected[0] + 1)
        adjust_scroll()

    @kb.add("enter")
    @kb.add("b")
    def _(event):
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
        n = notifications[selected[0]]
        if mark_as_done(n["id"]):
            notifications.pop(selected[0])
            if not notifications:
                event.app.exit()
                return
            if selected[0] >= len(notifications):
                selected[0] = len(notifications) - 1
            adjust_scroll()

    @kb.add("q")
    @kb.add("escape")
    def _(event):
        event.app.exit()

    layout = Layout(
        HSplit([
            Window(header_control, height=1),
            Window(list_control, height=visible_count),
            Window(char="─", height=1, style="class:border"),
            Window(detail_header_control, height=1),
            Window(detail_control, height=5),
            Window(char="─", height=1, style="class:border"),
            Window(footer_control, height=1),
        ])
    )

    app = Application(layout=layout, key_bindings=kb, style=MONOKAI_STYLE, full_screen=True)
    app.run()


def main() -> int:
    console = Console()

    with console.status("[bold #e5da74]Fetching notifications..."):
        repo = detect_repo()
        notifications = fetch_notifications(repo)

    if not notifications:
        scope = f"for {repo}" if repo else ""
        console.print(f"[#e6db74]No unread notifications {scope}[/]")
        return 0

    all_repos = repo is None
    scope = f"in {repo}" if repo else "across all repos"
    console.print(f"[bold #a6e22e]Found {len(notifications)} unread notification(s) {scope}[/]\n")

    run_selector(notifications, all_repos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
