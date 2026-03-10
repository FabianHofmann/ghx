#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["prompt_toolkit", "rich"]
# ///

from collections import Counter
from datetime import datetime, timezone
import json
import shutil
import subprocess
import sys
import threading
import webbrowser
from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.table import Table


RUNNING_STATES = {
    "IN_PROGRESS",
    "PENDING",
    "QUEUED",
    "WAITING",
    "REQUESTED",
    "EXPECTED",
}


STATE_STYLES = {
    "IN_PROGRESS": "yellow",
    "PENDING": "yellow",
    "QUEUED": "yellow",
    "WAITING": "yellow",
    "REQUESTED": "yellow",
    "EXPECTED": "yellow",
    "SUCCESS": "green",
    "COMPLETED": "green",
    "FAILURE": "red",
    "FAILED": "red",
    "ERROR": "red",
    "TIMED_OUT": "red",
    "CANCELLED": "bright_black",
    "NEUTRAL": "bright_black",
    "SKIPPED": "bright_black",
}


MONOKAI_STYLE = Style.from_dict({
    "": "#f8f8f2 bg:#272822",
    "header": "#34D399 bold",
    "border": "#75715e",
    "col-header": "#34D399 bold",
    "col-header-dim": "#75715e",
    "item": "#f8f8f2",
    "item-state-running": "#e5da74",
    "item-state-pending": "#e5da74",
    "item-workflow": "#ae81ff",
    "item-age": "#fd971f",
    "item-link": "#66d9ef",
    "sel-prefix": "#a6e22e bold bg:#3a3d34",
    "sel-item": "#f8f8f2 bold bg:#3a3d34",
    "sel-workflow": "#ae81ff bold bg:#3a3d34",
    "sel-age": "#fd971f bold bg:#3a3d34",
    "sel-link": "#66d9ef bold bg:#3a3d34",
    "detail-label": "#34D399",
    "detail-value": "#f8f8f2",
    "footer": "#88846f",
    "footer-key": "#34D399 bold",
    "new-notif": "#f92672 bold",
})


def get_current_pr_number() -> int | None:
    result = subprocess.run(
        ["gh", "pr", "view", "--json", "number", "-q", ".number"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    number = result.stdout.strip()
    if not number:
        return None
    return int(number)


def get_pr_checks(pr_number: int) -> list[dict]:
    result = subprocess.run(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--json",
            "statusCheckRollup",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(f"Failed to fetch CI checks: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    return data.get("statusCheckRollup") or []


def check_state(check: dict) -> str:
    state = (check.get("state") or check.get("status") or "").upper()
    conclusion = (check.get("conclusion") or "").upper()
    if state == "COMPLETED":
        if conclusion in {"SUCCESS"}:
            return "SUCCESS"
        if conclusion in {"CANCELLED", "SKIPPED", "NEUTRAL"}:
            return conclusion
        if conclusion:
            return "FAILED"
    return state


def check_name(check: dict) -> str:
    return (
        check.get("name")
        or check.get("context")
        or check.get("displayName")
        or check.get("__typename")
        or "unknown"
    )


def check_workflow(check: dict) -> str:
    workflow = check.get("workflowName") or ""
    if workflow:
        return workflow
    suite = check.get("checkSuite") or {}
    run = suite.get("workflowRun") or {}
    workflow_obj = run.get("workflow") or {}
    return workflow_obj.get("name") or ""


def check_started_at(check: dict) -> str:
    return check.get("startedAt") or check.get("createdAt") or "n/a"


def check_link(check: dict) -> str:
    return check.get("detailsUrl") or check.get("targetUrl") or check.get("url") or ""


def relative_time(iso_str: str) -> str:
    if not iso_str or iso_str == "n/a":
        return "-"
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    delta = datetime.now(timezone.utc) - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    return f"{days}d"


def style_state(state: str) -> str:
    style = STATE_STYLES.get(state, "white")
    return f"[{style}]{state}[/{style}]"


def ellipsize(text: str, width: int) -> str:
    if width <= 1:
        return text[:width]
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def make_rows(checks: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for check in checks:
        workflow = check_workflow(check).strip() or "-"
        name = check_name(check).strip()
        state = check_state(check) or "UNKNOWN"
        started_at = check_started_at(check)
        started_display = started_at.replace("T", " ").replace("Z", " UTC") if started_at != "n/a" else "-"
        link = check_link(check)
        rows.append(
            {
                "state": state,
                "workflow": workflow,
                "name": name,
                "started_at": started_at,
                "started_display": started_display,
                "age": relative_time(started_at),
                "link": link,
            }
        )
    rows.sort(
        key=lambda row: (
            row["started_at"] != "n/a",
            row["started_at"],
        ),
        reverse=True,
    )
    return rows


def open_link(url: str) -> bool:
    if not url:
        return False
    gh = subprocess.run(
        ["gh", "browse", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if gh.returncode == 0:
        return True
    return webbrowser.open(url)


def render_table(
    console: Console,
    pr_number: int,
    rows: list[dict],
    checks: list[dict],
    state_counts: Counter,
    running_count: int,
) -> None:
    table = Table(
        title=f"CI Checks for PR #{pr_number}",
        show_header=True,
        header_style="bold cyan",
        box=None,
        pad_edge=False,
    )
    table.add_column("State", style="white", no_wrap=True)
    table.add_column("Workflow", style="magenta")
    table.add_column("Check", style="white")
    table.add_column("Started", style="dim", no_wrap=True)
    table.add_column("Age", style="yellow", no_wrap=True)
    table.add_column("Details", style="cyan")
    for row in rows:
        details_display = f"[link={row['link']}]open[/link]" if row["link"] else "-"
        table.add_row(
            style_state(row["state"]),
            row["workflow"],
            row["name"],
            row["started_display"],
            row["age"],
            details_display,
        )
    summary = ", ".join(f"{state.lower()}={count}" for state, count in sorted(state_counts.items()))
    console.print(table)
    console.print(f"[dim]Summary: total={len(checks)}, running={running_count}[/dim]")
    if summary:
        console.print(f"[dim]States: {summary}[/dim]")


def run_selector(rows: list[dict], pr_number: int) -> None:
    selected = [0]
    scroll_offset = [0]
    action_message = ["Enter opens selected run"]
    has_new = [False]
    poll_stop = threading.Event()
    visible_count = min(len(rows), 12)
    terminal_width = shutil.get_terminal_size((120, 30)).columns

    prefix_w = 3
    col_state = max(9, min(14, max(len(r["state"]) for r in rows)))
    col_workflow = min(22, max(8, max(len(r["workflow"]) for r in rows)))
    col_age = 6
    col_link = 7
    fixed = prefix_w + col_state + 2 + col_workflow + 2 + col_age + 2 + col_link
    col_check = max(24, min(76, terminal_width - fixed))

    def adjust_scroll() -> None:
        if selected[0] < scroll_offset[0]:
            scroll_offset[0] = selected[0]
        elif selected[0] >= scroll_offset[0] + visible_count:
            scroll_offset[0] = selected[0] - visible_count + 1

    def get_header():
        start = scroll_offset[0] + 1
        end = min(scroll_offset[0] + visible_count, len(rows))
        return [
            ("class:header", f"  CI Checks for PR #{pr_number} "),
            ("class:border", f"({len(rows)} checks, showing {start}-{end})\n"),
        ]

    def state_style(state: str) -> str:
        if state in RUNNING_STATES:
            if state == "PENDING":
                return "item-state-pending"
            return "item-state-running"
        return "item"

    def get_list_text():
        lines = []
        header_line = (
            f"{'':<{prefix_w}}"
            f"{'State':<{col_state}}  "
            f"{'Workflow':<{col_workflow}}  "
            f"{'Check':<{col_check}}  "
            f"{'Age':<{col_age}}  "
            f"{'Open':<{col_link}}\n"
        )
        sep_line = (
            f"{'':<{prefix_w}}"
            f"{'─' * col_state}  "
            f"{'─' * col_workflow}  "
            f"{'─' * col_check}  "
            f"{'─' * col_age}  "
            f"{'─' * col_link}\n"
        )
        lines.append(("class:col-header", header_line))
        lines.append(("class:col-header-dim", sep_line))

        start = scroll_offset[0]
        end = min(start + visible_count, len(rows))
        for i in range(start, end):
            row = rows[i]
            is_sel = i == selected[0]
            prefix = " ▶ " if is_sel else "   "
            state = ellipsize(row["state"], col_state).ljust(col_state)
            workflow = ellipsize(row["workflow"], col_workflow).ljust(col_workflow)
            check_name = ellipsize(row["name"], col_check).ljust(col_check)
            age = row["age"].ljust(col_age)
            link_label = ("open" if row["link"] else "-").ljust(col_link)

            if is_sel:
                lines.append(("class:sel-prefix", prefix))
                lines.append(("class:sel-item", state))
                lines.append(("class:sel-item", "  "))
                lines.append(("class:sel-workflow", workflow))
                lines.append(("class:sel-item", "  "))
                lines.append(("class:sel-item", check_name))
                lines.append(("class:sel-item", "  "))
                lines.append(("class:sel-age", age))
                lines.append(("class:sel-item", "  "))
                lines.append(("class:sel-link", link_label))
                lines.append(("", "\n"))
            else:
                lines.append(("class:item", prefix))
                lines.append((f"class:{state_style(row['state'])}", state))
                lines.append(("class:item", "  "))
                lines.append(("class:item-workflow", workflow))
                lines.append(("class:item", "  "))
                lines.append(("class:item", check_name))
                lines.append(("class:item", "  "))
                lines.append(("class:item-age", age))
                lines.append(("class:item", "  "))
                lines.append(("class:item-link", link_label))
                lines.append(("class:item", "\n"))
        return lines

    def get_detail_header():
        row = rows[selected[0]]
        return [("class:header", f"  {row['name']}\n")]

    def get_detail_text():
        row = rows[selected[0]]
        lines = [
            ("class:detail-label", "  State: "),
            ("class:detail-value", row["state"]),
            ("class:detail-value", "\n"),
            ("class:detail-label", "  Workflow: "),
            ("class:detail-value", row["workflow"]),
            ("class:detail-value", "\n"),
            ("class:detail-label", "  Started: "),
            ("class:detail-value", row["started_display"]),
            ("class:detail-value", "\n"),
            ("class:detail-label", "  Age: "),
            ("class:detail-value", row["age"]),
            ("class:detail-value", "\n"),
            ("class:detail-label", "  URL: "),
            ("class:detail-value", row["link"] or "-"),
            ("class:detail-value", "\n"),
        ]
        return lines

    def get_footer():
        parts = [
            ("class:footer-key", " ↑/k "),
            ("class:footer", "up  "),
            ("class:footer-key", "↓/j "),
            ("class:footer", "down  "),
            ("class:footer-key", "Enter "),
            ("class:footer", "open run  "),
            ("class:footer-key", "r "),
            ("class:footer", "refresh  "),
            ("class:footer-key", "q/Esc "),
            ("class:footer", f"quit  |  {action_message[0]}"),
        ]
        if has_new[0]:
            parts.append(("class:footer", "  "))
            parts.append(("class:new-notif", "● checks updated"))
        return parts

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
        selected[0] = min(len(rows) - 1, selected[0] + 1)
        adjust_scroll()

    @kb.add("enter")
    def _(event):
        url = rows[selected[0]]["link"]
        if not url:
            action_message[0] = "No URL for selected run"
            event.app.invalidate()
            return
        if open_link(url):
            action_message[0] = "Opened selected run"
        else:
            action_message[0] = "Failed to open selected run"
        event.app.invalidate()

    @kb.add("r")
    def _(event):
        has_new[0] = False
        checks = get_pr_checks(pr_number)
        new_rows = make_rows(checks)
        rows.clear()
        rows.extend(new_rows)
        if not rows:
            event.app.exit(result=None)
            return
        if selected[0] >= len(rows):
            selected[0] = len(rows) - 1
        adjust_scroll()

    @kb.add("q")
    @kb.add("escape")
    def _(event):
        event.app.exit(result=None)

    list_header_lines = 2
    list_height = visible_count + list_header_lines
    layout = Layout(
        HSplit(
            [
                Window(header_control, height=1),
                Window(list_control, height=list_height),
                Window(char="─", height=1, style="class:border"),
                Window(detail_header_control, height=1),
                Window(detail_control, height=5),
                Window(char="─", height=1, style="class:border"),
                Window(footer_control, height=1),
            ]
        )
    )

    app = Application(layout=layout, key_bindings=kb, style=MONOKAI_STYLE, full_screen=True)

    def poll_for_new():
        current_states = {(r["name"], r["state"]) for r in rows}
        while not poll_stop.wait(15):
            try:
                checks = get_pr_checks(pr_number)
                new_rows = make_rows(checks)
                new_states = {(r["name"], r["state"]) for r in new_rows}
                if new_states != current_states:
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


def main() -> int:
    console = Console()
    pr_number = get_current_pr_number()
    if pr_number is None:
        console.print("[yellow]No PR attached to the current branch.[/yellow]")
        return 0

    checks = get_pr_checks(pr_number)
    running_checks = [c for c in checks if check_state(c) in RUNNING_STATES]
    state_counts = Counter(check_state(c) or "UNKNOWN" for c in checks)

    rows = make_rows(checks)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        render_table(console, pr_number, rows, checks, state_counts, len(running_checks))
        return 0

    run_selector(rows, pr_number)

    return 0


if __name__ == "__main__":
    sys.exit(main())
