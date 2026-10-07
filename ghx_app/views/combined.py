from __future__ import annotations

from typing import TYPE_CHECKING

from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import ConditionalContainer

from ghx_app.base import ListView, StyleText
from ghx_app.gh import issue_list_args, merge_items, open_url, popen_gh, pr_list_args, read_json
from ghx_app.search import SearchableView
from ghx_app.util import ellipsize, label_fragments, status_text
from ghx_app.views.items import (
    DETAIL_SECTION_ROWS, Checkout, assignee_of, detail_section, item_detail_text, item_haystack, item_header,
)

if TYPE_CHECKING:
    from prompt_toolkit.layout import AnyContainer

COL_NUM = 6
COL_KIND = 5
KIND_LABEL = {"pr": "PR", "issue": "issue"}
KIND_STYLE = {"pr": "type", "issue": "num"}


def status_of(item: dict) -> tuple[str, str]:
    if item["kind"] == "pr":
        return status_text(item)
    login = assignee_of(item)
    return ("item-author", f"@{login}") if login else ("item-state", "open")


class AllView(SearchableView):
    label = "All"
    poll_interval = 30.0

    def title(self) -> str:
        return "All"

    def counts(self) -> str:
        prs = sum(item["kind"] == "pr" for item in self.items)
        scope = "mine" if self.shared.mine else "open"
        scope = "found" if self.search_query else scope
        return f"{prs} PRs, {len(self.items) - prs} issues {scope}{self.search_suffix()}"

    def fetch(self) -> list[dict]:
        procs = [popen_gh(args(self.shared.mine, self.search_query)) for args in (pr_list_args, issue_list_args)]
        prs, issues = (read_json(proc) for proc in procs)
        return merge_items(prs, issues)

    def haystack(self, item: dict) -> str:
        return item_haystack(item)

    def hints(self) -> list[tuple[str, str]]:
        return super().hints() or [("Enter", "browse"), ("c", "checkout"), ("f", "find"), ("m", "mine")]

    def detail_visible(self) -> bool:
        return self.fits_section(DETAIL_SECTION_ROWS)

    def chrome_rows(self) -> int:
        detail = DETAIL_SECTION_ROWS if self.items and self.detail_visible() else 0
        return detail + super().chrome_rows()

    def selected(self) -> dict:
        return self.items[self.cursor]

    def list_fragments(self) -> StyleText:
        items = self.items
        col_author = min(16, max(6, max((len(it["author"]["login"]) for it in items), default=6)))
        col_status = min(16, max(8, max((len(status_of(it)[1]) for it in items), default=8)))
        fixed = 3 + COL_NUM + 1 + COL_KIND + 1 + 3 + (1 + col_author) + 3 + col_status + 3
        col_title = max(18, min(60, self.viewport_width() - fixed))
        labels_width = max(0, self.viewport_width() - fixed - col_title)
        header_line = (
            f"{'':<3}{'#':<{COL_NUM}} {'Kind':<{COL_KIND}} {'Title':<{col_title}}   "
            f"{'@Author':<{col_author + 1}}   {'Status':<{col_status}}   {'Labels' if labels_width else ''}\n"
        )
        separator_line = (
            f"{'':<3}{'─' * COL_NUM} {'─' * COL_KIND} {'─' * col_title}   "
            f"{'─' * (col_author + 1)}   {'─' * col_status}   {'─' * labels_width}\n"
        )
        lines: StyleText = [("class:col-header", header_line), ("class:col-header-dim", separator_line)]
        if not items:
            return lines + self.empty_fragments("No open PRs or issues")
        start, end = self.visible_range()
        for i in range(start, end):
            it = items[i]
            sel = i == self.cursor
            cls = "sel" if sel else "item"
            fill = "class:sel-title" if sel else "class:item"
            status_style, status_label = status_of(it)
            lines.extend([
                ("class:sel-prefix" if sel else "class:item", " ▶ " if sel else "   "),
                (f"class:{cls}-number", ellipsize(f"#{it['number']}", COL_NUM).ljust(COL_NUM)),
                (fill, " "),
                (f"class:{cls}-{KIND_STYLE[it['kind']]}", KIND_LABEL[it["kind"]].ljust(COL_KIND)),
                (f"class:{cls}-title", f" {ellipsize(it['title'], col_title).ljust(col_title)}   @"),
                (f"class:{cls}-author", ellipsize(it["author"]["login"], col_author).ljust(col_author)),
                (fill, "   "),
                ("class:sel-state" if sel else f"class:{status_style}", ellipsize(status_label, col_status).ljust(col_status)),
                (fill, "   "),
                *(label_fragments(it["labels"], labels_width, sel) if labels_width else []),
                ("", "\n"),
            ])
        return lines

    def detail_containers(self) -> list[AnyContainer]:
        visible = Condition(lambda: self.is_active() and bool(self.items) and self.detail_visible())
        section = detail_section(lambda: item_header(self.selected()), lambda: item_detail_text(self.selected()))
        return [*super().detail_containers(), ConditionalContainer(section, filter=visible)]

    def view_bindings(self) -> KeyBindings:
        kb = ListView.bindings(self)

        @kb.add("enter")
        def _(event) -> None:
            if self.items:
                open_url(self.selected()["url"])

        @kb.add("c")
        def _(event) -> None:
            if not self.items:
                return
            if self.selected()["kind"] != "pr":
                self.shell.flash("not a PR")
                return
            event.app.exit(result=Checkout(self.selected()["number"]))

        @kb.add("m")
        def _(event) -> None:
            self.shared.mine = not self.shared.mine
            self.loaded = False
            self.ensure_loaded()

        return kb
