#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["prompt_toolkit", "rich"]
# ///
import subprocess
import json
import sys
import shutil
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
    "border": "#75715e",
    "header": "#34D399 bold",
    "detail-label": "#34D399",
    "detail-value": "#f8f8f2",
    "footer": "#88846f",
    "footer-key": "#34D399 bold",
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


def mark_as_done(thread_id: str) -> bool:
    result = subprocess.run(
        ["gh", "api", "-X", "PATCH", f"/notifications/threads/{thread_id}"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def run_selector(notifications: list[dict], all_repos: bool, repo: str | None) -> None:
    selected = [0]
    scroll_offset = [0]
    visible_count = min(len(notifications), 12)
    terminal_width = shutil.get_terminal_size((120, 30)).columns
    prefix_w = 3
    title_padding = 4
    repo_padding = 3
    reason_padding = 3

    col_type = 10
    col_reason = min(26, max(12, max(len(REASON_LABELS.get(n["reason"], n["reason"])) for n in notifications)))
    col_repo = min(24, max(10, max(len(n["repository"]["full_name"]) for n in notifications))) if all_repos else 0
    col_time = 8
    fixed = (
        prefix_w
        + col_type
        + title_padding
        + (col_repo + repo_padding if all_repos else 0)
        + col_reason
        + reason_padding
        + col_time
    )
    col_title = max(20, min(64, terminal_width - fixed))

    def adjust_scroll():
        if selected[0] < scroll_offset[0]:
            scroll_offset[0] = selected[0]
        elif selected[0] >= scroll_offset[0] + visible_count:
            scroll_offset[0] = selected[0] - visible_count + 1

    def get_header():
        if not notifications:
            return [("class:header", "  Notifications "), ("class:border", "(0 unread)\n")]
        start = scroll_offset[0] + 1
        end = min(scroll_offset[0] + visible_count, len(notifications))
        return [
            ("class:header", "  Notifications "),
            ("class:border", f"({len(notifications)} unread, showing {start}-{end})\n"),
        ]

    def get_list_text():
        if not notifications:
            return []
        lines = []
        header_line = f"{'':<{prefix_w}}{'Type':<{col_type}}{'Title':<{col_title + title_padding}}"
        if all_repos:
            header_line += f"{'Repo':<{col_repo + repo_padding}}"
        header_line += f"{'Reason':<{col_reason + reason_padding}}{'When':<{col_time}}\n"
        sep = f"{'':<{prefix_w}}{'─' * col_type}{'─' * (col_title + title_padding)}"
        if all_repos:
            sep += f"{'─' * (col_repo + repo_padding)}"
        sep += f"{'─' * (col_reason + reason_padding)}{'─' * col_time}"
        lines.append(("class:col-header", header_line))
        lines.append(("class:col-header-dim", f"{sep}\n"))
        start = scroll_offset[0]
        end = min(start + visible_count, len(notifications))
        for i in range(start, end):
            n = notifications[i]
            is_sel = i == selected[0]
            row_idx = i - start
            prefix = " ▶ " if is_sel else "   "
            type_label = TYPE_LABELS.get(n["subject"]["type"], n["subject"]["type"][:4])
            type_chip = f" {ellipsize(type_label, col_type - 2):<{col_type - 2}} "
            title = ellipsize(n["subject"]["title"], col_title).ljust(col_title)
            repo = ellipsize(n["repository"]["full_name"], col_repo).ljust(col_repo) if all_repos else ""
            reason_label = REASON_LABELS.get(n["reason"], n["reason"])
            reason_chip = f" {ellipsize(reason_label, col_reason - 2):<{col_reason - 2}} "
            time_col = f"{relative_time(n['updated_at']):<{col_time}}"

            if is_sel:
                lines.append(("class:sel-prefix", prefix))
                lines.append(("class:chip-type", type_chip))
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
        lines = [
            ("class:detail-label", "  Repo: "),
            ("class:item-repo", n["repository"]["full_name"]),
            ("class:detail-value", "\n"),
            ("class:detail-label", "  Type: "),
            ("class:sel-type", type_label),
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
            ("class:footer-key", "r "),
            ("class:footer", "refresh  "),
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

    @kb.add("r")
    def _(event):
        new_notifications = fetch_notifications(repo)
        notifications.clear()
        notifications.extend(new_notifications)
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

    list_header_lines = 2

    layout = Layout(
        HSplit([
            Window(header_control, height=1),
            Window(list_control, height=visible_count + list_header_lines),
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

    run_selector(notifications, all_repos, repo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
