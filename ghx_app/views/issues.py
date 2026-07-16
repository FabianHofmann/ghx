from __future__ import annotations

from typing import TYPE_CHECKING

from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import ConditionalKeyBindings, KeyBindings, merge_key_bindings
from prompt_toolkit.layout import ConditionalContainer, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl

from ghx_app.base import ListView, StyleText
from ghx_app.gh import gh_json, issue_list_args, open_url
from ghx_app.util import ellipsize, label_fg, relative_time

if TYPE_CHECKING:
    from prompt_toolkit.layout import AnyContainer

LABEL_PANEL_ROWS = 10


def assignee_of(issue: dict) -> str:
    return issue["assignees"][0]["login"] if issue["assignees"] else ""


class IssuesView(ListView):
    label = "Issues"
    poll_interval = 30.0

    def __init__(self, shared) -> None:
        super().__init__(shared)
        self.all_items: list[dict] = []
        self.active_labels: set[str] = set()
        self.label_mode = False
        self.label_cursor = 0

    def title(self) -> str:
        return "Issues"

    def counts(self) -> str:
        scope = "assigned" if self.shared.mine else "open"
        base = f"{len(self.items)} {scope}"
        if self.active_labels:
            base += f", filtered: {' + '.join(sorted(self.active_labels))}"
        return base

    def fetch(self) -> list[dict]:
        return gh_json(issue_list_args(self.shared.mine))

    def changed(self, latest: list[dict]) -> bool:
        return latest != self.all_items

    def apply(self, items: list[dict]) -> None:
        self.all_items = items
        self.apply_filter()
        self.shell.invalidate()

    def seed(self, items: list[dict]) -> None:
        super().seed(items)
        self.all_items = items
        self.apply_filter()

    def apply_filter(self) -> None:
        if self.active_labels:
            self.items = [it for it in self.all_items if self.active_labels <= {l["name"] for l in it["labels"]}]
        else:
            self.items = list(self.all_items)
        self.cursor = min(self.cursor, max(0, len(self.items) - 1))
        self.adjust_scroll()

    def available_labels(self) -> list[tuple[str, str, int]]:
        seen: dict[str, list] = {}
        for it in self.all_items:
            for l in it["labels"]:
                entry = seen.setdefault(l["name"], [l["color"], 0])
                entry[1] += 1
        return sorted(((name, color, count) for name, (color, count) in seen.items()), key=lambda x: x[0])

    def hints(self) -> list[tuple[str, str]]:
        if self.label_mode:
            return [("j/k", "move"), ("Space", "toggle"), ("c", "clear"), ("Esc", "close")]
        return [("Enter/b", "browse"), ("m", "mine"), ("l", "labels")]

    def chrome_rows(self) -> int:
        return LABEL_PANEL_ROWS + 3 if self.label_mode else 0

    def label_fragments(self, labels: list[dict], max_width: int, selected: bool) -> StyleText:
        fill = "class:sel-title" if selected else "class:item"
        out: StyleText = []
        used = 0
        for l in labels:
            chip = f" {l['name']} "
            if used + len(chip) + 1 > max_width:
                out.append(("class:item-time", "…"))
                break
            color = l["color"] or "88846f"
            out.append((f"fg:{label_fg(color)} bg:#{color}", chip))
            out.append((fill, " "))
            used += len(chip) + 1
        return out

    def list_fragments(self) -> StyleText:
        issues = self.items
        width = self.viewport_width()
        col_num = 6
        col_assignee = min(16, max(6, max((len(assignee_of(it)) for it in issues), default=6)))
        col_when = 8
        labels_min = 12
        fixed = 3 + col_num + 1 + 3 + (1 + col_assignee) + 3 + col_when + 3
        col_title = max(18, min(52, width - fixed - labels_min))
        labels_width = max(labels_min, width - fixed - col_title - 1)

        header_line = (
            f"{'':<3}{'#':<{col_num}} {'Title':<{col_title}}   "
            f"{'@Assignee':<{col_assignee + 1}}   {'When':<{col_when}}   Labels\n"
        )
        separator_line = (
            f"{'':<3}{'─' * col_num} {'─' * col_title}   "
            f"{'─' * (col_assignee + 1)}   {'─' * col_when}   {'─' * labels_width}\n"
        )
        lines: StyleText = [("class:col-header", header_line), ("class:col-header-dim", separator_line)]
        if not issues:
            return lines + self.empty_fragments("No open issues")
        start, end = self.visible_range()
        for i in range(start, end):
            it = issues[i]
            is_sel = i == self.cursor
            prefix = " ▶ " if is_sel else "   "
            num = ellipsize(f"#{it['number']}", col_num).ljust(col_num)
            title = ellipsize(it["title"], col_title).ljust(col_title)
            login = assignee_of(it)
            assignee = ("@" + ellipsize(login, col_assignee)) if login else "—"
            assignee = assignee.ljust(col_assignee + 1)
            when = f"{relative_time(it['updatedAt'])} ago".ljust(col_when)
            chips = self.label_fragments(it["labels"], labels_width, is_sel)
            if is_sel:
                lines.extend([
                    ("class:sel-prefix", prefix),
                    ("class:sel-number", num),
                    ("class:sel-title", f" {title}   "),
                    ("class:sel-author", assignee),
                    ("class:sel-title", "   "),
                    ("class:sel-time", when),
                    ("class:sel-title", "   "),
                    *chips,
                    ("", "\n"),
                ])
            else:
                lines.extend([
                    ("class:item", prefix),
                    ("class:item-number", num),
                    ("class:item-title", f" {title}   "),
                    ("class:item-author", assignee),
                    ("class:item", "   "),
                    ("class:item-time", when),
                    ("class:item", "   "),
                    *chips,
                    ("class:item", "\n"),
                ])
        return lines

    def label_panel_header(self) -> StyleText:
        return [
            ("class:header", "  Labels "),
            ("class:border", "(j/k move · space toggle · c clear · esc close)\n"),
        ]

    def label_panel_list(self) -> StyleText:
        labels = self.available_labels()
        if not labels:
            return [("class:item-time", "   (no labels on loaded issues)")]
        if len(labels) > LABEL_PANEL_ROWS:
            start = max(0, min(self.label_cursor - LABEL_PANEL_ROWS // 2, len(labels) - LABEL_PANEL_ROWS))
        else:
            start = 0
        lines: StyleText = []
        for i in range(start, min(start + LABEL_PANEL_ROWS, len(labels))):
            name, color, count = labels[i]
            is_sel = i == self.label_cursor
            prefix = " ▶ " if is_sel else "   "
            mark = "[x]" if name in self.active_labels else "[ ]"
            chip = f" {name} "
            color = color or "88846f"
            row_style = "class:sel-title" if is_sel else "class:item"
            lines.extend([
                ("class:sel-prefix" if is_sel else "class:item", prefix),
                (row_style, f"{mark} "),
                (f"fg:{label_fg(color)} bg:#{color}", chip),
                (row_style, f"  ({count})\n"),
            ])
        return lines

    def detail_containers(self) -> list[AnyContainer]:
        visible = Condition(lambda: self.is_active() and self.label_mode)
        section = HSplit([
            Window(char="─", height=1, style="class:border"),
            Window(FormattedTextControl(self.label_panel_header), height=1),
            Window(FormattedTextControl(self.label_panel_list), height=LABEL_PANEL_ROWS),
            Window(char="─", height=1, style="class:border"),
        ])
        return [ConditionalContainer(section, filter=visible)]

    def label_move(self, delta: int) -> None:
        total = len(self.available_labels())
        self.label_cursor = max(0, min(total - 1, self.label_cursor + delta))

    def toggle_label(self) -> None:
        labels = self.available_labels()
        if not labels:
            return
        name = labels[self.label_cursor][0]
        if name in self.active_labels:
            self.active_labels.discard(name)
        else:
            self.active_labels.add(name)
        self.apply_filter()

    def bindings(self) -> KeyBindings:
        normal = KeyBindings()

        @normal.add("up")
        @normal.add("k")
        def _(event) -> None:
            self.move(-1)

        @normal.add("down")
        @normal.add("j")
        def _(event) -> None:
            self.move(1)

        @normal.add("enter")
        @normal.add("b")
        def _(event) -> None:
            if self.items:
                open_url(self.items[self.cursor]["url"])

        label = KeyBindings()

        @label.add("up")
        @label.add("k")
        def _(event) -> None:
            self.label_move(-1)

        @label.add("down")
        @label.add("j")
        def _(event) -> None:
            self.label_move(1)

        @label.add(" ")
        def _(event) -> None:
            self.toggle_label()
            event.app.invalidate()

        @label.add("c")
        def _(event) -> None:
            self.active_labels.clear()
            self.apply_filter()
            event.app.invalidate()

        @label.add("escape")
        def _(event) -> None:
            self.label_mode = False
            self.adjust_scroll()
            event.app.invalidate()

        common = KeyBindings()

        @common.add("r")
        def _(event) -> None:
            self.refresh()

        @common.add("m")
        def _(event) -> None:
            self.shared.mine = not self.shared.mine
            self.loaded = False
            self.ensure_loaded()

        @common.add("l")
        def _(event) -> None:
            self.label_mode = not self.label_mode
            self.label_cursor = 0
            self.adjust_scroll()
            event.app.invalidate()

        return merge_key_bindings([
            common,
            ConditionalKeyBindings(normal, Condition(lambda: not self.label_mode)),
            ConditionalKeyBindings(label, Condition(lambda: self.label_mode)),
        ])
