from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING

from prompt_toolkit.application import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import ConditionalContainer, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl

from ghx_app.base import ListView, StyleText
from ghx_app.gh import gh_json, open_url, run_gh
from ghx_app.theme import STATE_STYLE
from ghx_app.util import ellipsize, relative_time

if TYPE_CHECKING:
    from prompt_toolkit.layout import AnyContainer

DETAIL_META_ROWS = 5
DETAIL_PREVIEW_ROWS = 5
DETAIL_SECTION_ROWS = DETAIL_META_ROWS + DETAIL_PREVIEW_ROWS + 3
DETAIL_MIN_ROWS = 18

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


def api_url_to_browser_url(api_url: str) -> str:
    url = api_url.replace("https://api.github.com/repos/", "https://github.com/")
    return url.replace("/pulls/", "/pull/")


def fetch_notifications(repo: str | None) -> list[dict]:
    path = f"/repos/{repo}/notifications" if repo else "/notifications"
    return gh_json(["api", path])


def fetch_preview(n: dict) -> str:
    url = n["subject"].get("latest_comment_url") or n["subject"].get("url") or ""
    if not url:
        return ""
    result = run_gh(["api", url.replace("https://api.github.com", "")])
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
    result = run_gh(["api", "graphql", "-f", f"query={query}"])
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
    result = run_gh(["api", "-X", "PATCH", f"/notifications/threads/{thread_id}"])
    return result.returncode == 0


def signature(items: list[dict]) -> set[tuple[str, str]]:
    return {(n["id"], n["updated_at"]) for n in items}


class NotificationsView(ListView):
    label = "Notifs"
    poll_interval = 20.0
    background_load = True

    def __init__(self, shared) -> None:
        super().__init__(shared)
        self.detail_expanded = False
        self.preview_cache: dict[str, str | None] = {}
        self.state_cache: dict[str, str | None] = {}
        self.seen_ids: set[str] = set()
        self.workers_stop: threading.Event | None = None

    def all_repos(self) -> bool:
        return self.shared.repo is None

    def title(self) -> str:
        return "Notifications"

    def counts(self) -> str:
        return f"{len(self.items)} unread"

    def fetch(self) -> list[dict]:
        return fetch_notifications(self.shared.repo)

    def changed(self, latest: list[dict]) -> bool:
        return signature(latest) != signature(self.items)

    def tab_badge(self) -> str:
        count = len(self.items)
        if not count:
            return ""
        return f"●{count}" if self.has_new else f"({count})"

    def on_activate(self) -> None:
        super().on_activate()
        self.seen_ids = {n["id"] for n in self.items}
        self.has_new = False

    def apply(self, items: list[dict]) -> None:
        prev_updated = {n["id"]: n["updated_at"] for n in self.items}
        current_id = self.items[self.cursor]["id"] if self.items else None
        for n in items:
            if prev_updated.get(n["id"]) != n["updated_at"]:
                self.state_cache.pop(n["id"], None)
                self.preview_cache.pop(n["id"], None)
        self.items = items
        self.cursor = next(
            (i for i, n in enumerate(items) if n["id"] == current_id),
            min(self.cursor, max(0, len(items) - 1)),
        )
        self.adjust_scroll()
        if self.is_active():
            self.seen_ids = {n["id"] for n in items}
            self.has_new = False
        else:
            self.has_new = any(n["id"] not in self.seen_ids for n in items)
        self.shell.invalidate()

    def finish_load(self, items: list[dict]) -> None:
        super().finish_load(items)
        self.start_workers()

    def on_run_start(self) -> None:
        if self.loaded:
            self.start_workers()

    def start_workers(self) -> None:
        stop = self.shell.stop
        if self.workers_stop is stop:
            return
        self.workers_stop = stop
        threading.Thread(target=self.preview_worker, args=(stop,), daemon=True).start()
        threading.Thread(target=self.state_worker, args=(stop,), daemon=True).start()

    def preview_worker(self, stop: threading.Event) -> None:
        while not stop.wait(0.1):
            if not self.is_active() or not self.detail_expanded or not self.items:
                continue
            n = self.items[min(self.cursor, len(self.items) - 1)]
            if n["id"] in self.preview_cache:
                continue
            self.preview_cache[n["id"]] = None
            self.preview_cache[n["id"]] = fetch_preview(n)
            self.shell.invalidate()

    def state_worker(self, stop: threading.Event) -> None:
        while not stop.wait(0.1):
            if not self.is_active():
                continue
            pending = [n for n in list(self.items) if n["id"] not in self.state_cache]
            if not pending:
                continue
            for n in pending:
                self.state_cache[n["id"]] = None
            for start in range(0, len(pending), 50):
                chunk = pending[start:start + 50]
                states = fetch_states(chunk)
                for n in chunk:
                    self.state_cache[n["id"]] = states.get(n["id"], "")
                self.shell.invalidate()

    def hints(self) -> list[tuple[str, str]]:
        return [
            ("Enter/b", "browse"), ("d", "done"),
            ("Space", "hide" if self.detail_expanded else "details"),
        ]

    def detail_visible(self) -> bool:
        return self.detail_expanded and get_app().output.get_size().rows >= DETAIL_MIN_ROWS

    def chrome_rows(self) -> int:
        return (DETAIL_SECTION_ROWS + 2) if self.items and self.detail_visible() else 0

    def state_cell(self, n: dict, selected_row: bool) -> tuple[str, str]:
        col_state = 8
        state_padding = 2
        if n["subject"]["type"] not in ("PullRequest", "Issue"):
            return ("class:sel-title" if selected_row else "class:item", f"{'':<{col_state + state_padding}}")
        state = self.state_cache.get(n["id"])
        if state is None:
            return ("class:item-time", f" {'…':<{col_state + state_padding - 1}}")
        if not state:
            return ("class:sel-title" if selected_row else "class:item", f"{'':<{col_state + state_padding}}")
        chip = f" {state:<{col_state - 2}} "
        return (f"class:{STATE_STYLE[state]}", chip + " " * state_padding)

    def list_fragments(self) -> StyleText:
        notifications = self.items
        all_repos = self.all_repos()
        col_type = 10
        col_state = 8
        state_padding = 2
        title_padding = 4
        reason_lens = [len(REASON_LABELS.get(n["reason"], n["reason"])) for n in notifications]
        col_reason = min(26, max(12, max(reason_lens, default=12)))
        repo_lens = [len(n["repository"]["full_name"]) for n in notifications]
        col_repo = min(24, max(10, max(repo_lens, default=10))) if all_repos else 0
        col_time = 8
        fixed = (
            3 + col_type + col_state + state_padding + title_padding
            + (col_repo + 3 if all_repos else 0) + col_reason + 3 + col_time
        )
        col_title = max(20, self.viewport_width() - 1 - fixed)

        header_line = f"{'':<3}{'Type':<{col_type}}{'State':<{col_state + state_padding}}{'Title':<{col_title + title_padding}}"
        sep = f"{'':<3}{'─' * col_type}{'─' * (col_state + state_padding)}{'─' * (col_title + title_padding)}"
        if all_repos:
            header_line += f"{'Repo':<{col_repo + 3}}"
            sep += f"{'─' * (col_repo + 3)}"
        header_line += f"{'Reason':<{col_reason + 3}}{'When':<{col_time}}\n"
        sep += f"{'─' * (col_reason + 3)}{'─' * col_time}"
        lines: StyleText = [("class:col-header", header_line), ("class:col-header-dim", f"{sep}\n")]
        if not notifications:
            return lines + self.empty_fragments("Inbox zero — watching for new notifications…")
        start, end = self.visible_range()
        for i in range(start, end):
            n = notifications[i]
            is_sel = i == self.cursor
            prefix = " ▶ " if is_sel else "   "
            type_label = TYPE_LABELS.get(n["subject"]["type"], n["subject"]["type"][:4])
            type_chip = f" {ellipsize(type_label, col_type - 2):<{col_type - 2}} "
            state_style, state_chip = self.state_cell(n, is_sel)
            title = ellipsize(n["subject"]["title"], col_title).ljust(col_title)
            repo = ellipsize(n["repository"]["full_name"], col_repo).ljust(col_repo) if all_repos else ""
            reason_label = REASON_LABELS.get(n["reason"], n["reason"])
            reason_chip = f" {ellipsize(reason_label, col_reason - 2):<{col_reason - 2}} "
            time_col = f"{relative_time(n['updated_at']) + ' ago':<{col_time}}"
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
        return lines

    def detail_header(self) -> StyleText:
        if not self.items:
            return []
        return [("class:header", f"  {self.items[self.cursor]['subject']['title']}\n")]

    def detail_text(self) -> StyleText:
        if not self.items:
            return []
        n = self.items[self.cursor]
        type_label = TYPE_LABELS.get(n["subject"]["type"], n["subject"]["type"])
        reason = REASON_LABELS.get(n["reason"], n["reason"])
        state = self.state_cache.get(n["id"])
        if n["subject"]["type"] not in ("PullRequest", "Issue"):
            state_part = [("class:item-time", "n/a")]
        elif state is None:
            state_part = [("class:item-time", "loading…")]
        elif not state:
            state_part = [("class:item-time", "unknown")]
        else:
            state_part = [(f"class:{STATE_STYLE[state]}", f" {state} ")]
        return [
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
            ("class:item-time", f"{relative_time(n['updated_at'])} ago"),
            ("class:detail-value", "\n"),
        ]

    def preview_text(self) -> StyleText:
        if not self.items:
            return []
        label: StyleText = [("class:detail-label", "  Preview: ")]
        cached = self.preview_cache.get(self.items[self.cursor]["id"])
        if cached is None:
            return label + [("class:item-time", "loading…")]
        if not cached:
            return label + [("class:item-time", "(no preview)")]
        max_chars = (DETAIL_PREVIEW_ROWS - 1) * max(1, self.viewport_width() - 4)
        return label + [("class:detail-value", "\n  " + ellipsize(cached, max_chars))]

    def detail_containers(self) -> list[AnyContainer]:
        visible = Condition(lambda: self.is_active() and bool(self.items) and self.detail_visible())
        section = HSplit([
            Window(char="─", height=1, style="class:border"),
            Window(FormattedTextControl(self.detail_header), height=1),
            Window(FormattedTextControl(self.detail_text), height=DETAIL_META_ROWS),
            Window(FormattedTextControl(self.preview_text), height=DETAIL_PREVIEW_ROWS, wrap_lines=True),
            Window(char="─", height=1, style="class:border"),
        ])
        return [ConditionalContainer(section, filter=visible)]

    def bindings(self) -> KeyBindings:
        kb = super().bindings()

        @kb.add("enter")
        @kb.add("b")
        def _(event) -> None:
            if not self.items:
                return
            url = self.items[self.cursor]["subject"].get("url", "")
            if url:
                open_url(api_url_to_browser_url(url))

        @kb.add("d")
        def _(event) -> None:
            if not self.items:
                return
            if mark_as_done(self.items[self.cursor]["id"]):
                self.items.pop(self.cursor)
                self.cursor = min(self.cursor, max(0, len(self.items) - 1))
                self.adjust_scroll()

        @kb.add(" ")
        def _(event) -> None:
            self.detail_expanded = not self.detail_expanded
            self.adjust_scroll()
            event.app.invalidate()

        return kb
