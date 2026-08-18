from __future__ import annotations

import subprocess
import webbrowser
from typing import TYPE_CHECKING

from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import ConditionalContainer, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl

from ghx_app.base import ListView, StyleText
from ghx_app.gh import gh_json
from ghx_app.util import ellipsize, relative_time

if TYPE_CHECKING:
    from prompt_toolkit.layout import AnyContainer

DETAIL_SECTION_ROWS = 8

RUNNING_STATES = {"IN_PROGRESS", "PENDING", "QUEUED", "WAITING", "REQUESTED", "EXPECTED"}


def check_state(check: dict) -> str:
    state = (check.get("state") or check.get("status") or "").upper()
    conclusion = (check.get("conclusion") or "").upper()
    if state == "COMPLETED":
        if conclusion == "SUCCESS":
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


def check_link(check: dict) -> str:
    return check.get("detailsUrl") or check.get("targetUrl") or check.get("url") or ""


def make_rows(checks: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for check in checks:
        started_at = check.get("startedAt") or check.get("createdAt") or "n/a"
        started_display = started_at.replace("T", " ").replace("Z", " UTC") if started_at != "n/a" else "-"
        rows.append({
            "state": check_state(check) or "UNKNOWN",
            "workflow": check_workflow(check).strip() or "-",
            "name": check_name(check).strip(),
            "started_at": started_at,
            "started_display": started_display,
            "age": relative_time(started_at),
            "link": check_link(check),
        })
    rows.sort(key=lambda row: (row["started_at"] != "n/a", row["started_at"]), reverse=True)
    return rows


def open_link(url: str) -> bool:
    gh = subprocess.run(["gh", "browse", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True if gh.returncode == 0 else webbrowser.open(url)


class CiView(ListView):
    label = "CI"
    poll_interval = 15.0

    def title(self) -> str:
        pr = self.shared.pr_number
        return f"CI Checks for PR #{pr}" if pr is not None else "CI Checks"

    def counts(self) -> str:
        return f"{len(self.items)} checks"

    def fetch(self) -> list[dict]:
        pr = self.shared.pr_number
        if pr is None:
            return []
        data = gh_json(["pr", "view", str(pr), "--json", "statusCheckRollup"])
        return make_rows(data.get("statusCheckRollup") or [])

    def changed(self, latest: list[dict]) -> bool:
        return {(r["name"], r["state"]) for r in latest} != {(r["name"], r["state"]) for r in self.items}

    def on_branch_change(self) -> None:
        self.items = []
        self.cursor = 0
        self.scroll = 0
        self.loaded = False
        self.has_new = False
        self.error = ""

    def hints(self) -> list[tuple[str, str]]:
        return [("Enter", "open run")]

    def detail_visible(self) -> bool:
        return self.fits_section(DETAIL_SECTION_ROWS)

    def chrome_rows(self) -> int:
        return DETAIL_SECTION_ROWS if self.items and self.detail_visible() else 0

    def state_style(self, state: str) -> str:
        if state in RUNNING_STATES:
            return "item-state-pending" if state == "PENDING" else "item-state-running"
        return "item"

    def list_fragments(self) -> StyleText:
        rows = self.items
        col_state = max(9, min(14, max((len(r["state"]) for r in rows), default=9)))
        col_workflow = min(22, max(8, max((len(r["workflow"]) for r in rows), default=8)))
        col_age = 6
        col_link = 7
        fixed = 3 + col_state + 2 + col_workflow + 2 + col_age + 2 + col_link
        col_check = max(24, min(76, self.viewport_width() - fixed))

        header_line = (
            f"{'':<3}{'State':<{col_state}}  {'Workflow':<{col_workflow}}  "
            f"{'Check':<{col_check}}  {'Age':<{col_age}}  {'Open':<{col_link}}\n"
        )
        sep_line = (
            f"{'':<3}{'─' * col_state}  {'─' * col_workflow}  "
            f"{'─' * col_check}  {'─' * col_age}  {'─' * col_link}\n"
        )
        lines: StyleText = [("class:col-header", header_line), ("class:col-header-dim", sep_line)]
        if not rows:
            message = "No open PR for this branch" if self.shared.pr_number is None else "No checks found"
            return lines + self.empty_fragments(message)
        start, end = self.visible_range()
        for i in range(start, end):
            row = rows[i]
            is_sel = i == self.cursor
            prefix = " ▶ " if is_sel else "   "
            state = ellipsize(row["state"], col_state).ljust(col_state)
            workflow = ellipsize(row["workflow"], col_workflow).ljust(col_workflow)
            name = ellipsize(row["name"], col_check).ljust(col_check)
            age = row["age"].ljust(col_age)
            link_label = ("open" if row["link"] else "-").ljust(col_link)
            if is_sel:
                lines.extend([
                    ("class:sel-prefix", prefix),
                    ("class:sel-item", f"{state}  "),
                    ("class:sel-workflow", workflow),
                    ("class:sel-item", f"  {name}  "),
                    ("class:sel-age", age),
                    ("class:sel-item", "  "),
                    ("class:sel-link", link_label),
                    ("", "\n"),
                ])
            else:
                lines.extend([
                    ("class:item", prefix),
                    (f"class:{self.state_style(row['state'])}", state),
                    ("class:item", "  "),
                    ("class:item-workflow", workflow),
                    ("class:item", f"  {name}  "),
                    ("class:item-age", age),
                    ("class:item", "  "),
                    ("class:item-link", link_label),
                    ("class:item", "\n"),
                ])
        return lines

    def detail_header(self) -> StyleText:
        return [("class:header", f"  {self.items[self.cursor]['name']}\n")]

    def detail_text(self) -> StyleText:
        row = self.items[self.cursor]
        return [
            ("class:detail-label", "  State: "),
            ("class:detail-value", f"{row['state']}\n"),
            ("class:detail-label", "  Workflow: "),
            ("class:detail-value", f"{row['workflow']}\n"),
            ("class:detail-label", "  Started: "),
            ("class:detail-value", f"{row['started_display']}\n"),
            ("class:detail-label", "  Age: "),
            ("class:detail-value", f"{row['age']}\n"),
            ("class:detail-label", "  URL: "),
            ("class:detail-value", f"{row['link'] or '-'}\n"),
        ]

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

        @kb.add("enter")
        def _(event) -> None:
            if not self.items:
                return
            url = self.items[self.cursor]["link"]
            if not url:
                self.shell.flash("no URL for selected run")
            elif open_link(url):
                self.shell.flash("opened selected run")
            else:
                self.shell.flash("failed to open selected run")

        return kb
