from __future__ import annotations

from typing import TYPE_CHECKING

from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import ConditionalContainer

from ghx_app.base import ListView, Shared, StyleText
from ghx_app.gh import fetch_work, open_url
from ghx_app.search import SearchableView
from ghx_app.util import ellipsize, label_fragments, status_text
from ghx_app.views.items import (
    DETAIL_SECTION_ROWS, Checkout, assignee_of, detail_section, item_detail_text, item_haystack, item_header,
)

if TYPE_CHECKING:
    from prompt_toolkit.layout import AnyContainer

IN_PROGRESS = "In progress"
LONE_PRS = "PRs without issue"
LONE_ISSUES = "Issues without PR"
GROUPS = (IN_PROGRESS, LONE_PRS, LONE_ISSUES)
COL_NUM = 6
COL_BRANCH = 16
COL_STATUS = 8
COL_META = 36
INDENT = 5


def build_trees(prs: list[dict], issues: list[dict]) -> list[dict]:
    open_numbers = {issue["number"] for issue in issues}
    trees = []
    for issue in issues:
        children = [pr for pr in prs if issue["number"] in pr["closes"]]
        trees.append({"group": IN_PROGRESS if children else LONE_ISSUES, "item": issue, "children": children})
    trees.extend({"group": LONE_PRS, "item": pr, "children": []} for pr in prs if not open_numbers & set(pr["closes"]))
    return trees


def who(item: dict) -> str:
    return item["author"]["login"] if item["kind"] == "pr" else assignee_of(item)


class WorkView(SearchableView):
    label = "Work"
    poll_interval = 30.0

    def __init__(self, shared: Shared) -> None:
        super().__init__(shared)
        self.viewer = ""
        self.folded: set[str] = set()

    def title(self) -> str:
        return "Work"

    def counts(self) -> str:
        trees = [tree for trees in self.visible().values() for tree in trees]
        issues = sum(item["kind"] == "issue" for item, _ in trees)
        prs = {pr["number"] for item, kids in trees for pr in [item, *kids] if pr["kind"] == "pr"}
        scope = " mine" if self.shared.mine else ""
        return f"{issues} issues, {len(prs)} PRs{scope}{self.search_suffix()}"

    def fetch(self) -> list[dict]:
        self.viewer, prs, issues = fetch_work(self.shared.repo)
        return build_trees(prs, issues)

    def haystack(self, item: dict) -> str:
        return item_haystack(item)

    def keep(self, item: dict) -> bool:
        if not self.shared.mine:
            return True
        if item["kind"] == "pr":
            return item["author"]["login"] == self.viewer
        return self.viewer in {item["author"]["login"], *(a["login"] for a in item["assignees"])}

    def filter_terms(self) -> list[str]:
        return self.search_buffer.text.lower().split()

    def visible(self) -> dict[str, list[tuple[dict, list[dict]]]]:
        groups: dict[str, list[tuple[dict, list[dict]]]] = {group: [] for group in GROUPS}
        for tree in self.all_items:
            own = self.matches(tree["item"])
            kids = tree["children"] if own else [pr for pr in tree["children"] if self.matches(pr)]
            if own or kids:
                groups[tree["group"]].append((tree["item"], kids))
        return groups

    def filtered(self) -> list[dict]:
        rows: list[dict] = []
        for group, trees in self.visible().items():
            if not trees:
                continue
            rows.append({"kind": "header", "group": group, "count": len(trees)})
            if group in self.folded:
                continue
            for item, kids in trees:
                rows.append(item)
                rows.extend({**pr, "tree": "└ " if pr is kids[-1] else "├ "} for pr in kids)
        return rows

    def end_search(self, event, query: str) -> None:
        self.search_mode = False
        self.search_query = query
        self.search_buffer.text = query
        event.app.layout.focus(self.shell.list_window)
        self.apply_filter()

    def on_activate(self) -> None:
        super().on_activate()
        self.apply_filter()

    def hints(self) -> list[tuple[str, str]]:
        if self.search_mode:
            return [("Enter", "filter"), ("Esc", "clear")]
        return [("Enter", "browse"), ("c", "checkout"), ("Space", "fold"), ("f", "find"), ("m", "mine")]

    def detail_visible(self) -> bool:
        return self.fits_section(DETAIL_SECTION_ROWS)

    def chrome_rows(self) -> int:
        detail = DETAIL_SECTION_ROWS if self.items and self.detail_visible() else 0
        return detail + super().chrome_rows()

    def selected(self) -> dict:
        return self.items[self.cursor]

    def list_fragments(self) -> StyleText:
        rows = self.items
        entries = [row for row in rows if row["kind"] != "header"]
        col_who = min(16, max(6, max((len(who(row)) for row in entries), default=6)))
        fixed = INDENT + COL_NUM + 1 + 3 + (1 + col_who) + 3 + COL_META
        col_title = max(18, min(60, self.viewport_width() - fixed))
        header_line = (
            f"{'':<{INDENT}}{'#':<{COL_NUM}} {'Title':<{col_title}}   "
            f"{'@Who':<{col_who + 1}}   Branch / Status / Changes · Labels\n"
        )
        separator_line = (
            f"{'':<{INDENT}}{'─' * COL_NUM} {'─' * col_title}   "
            f"{'─' * (col_who + 1)}   {'─' * COL_META}\n"
        )
        lines: StyleText = [("class:col-header", header_line), ("class:col-header-dim", separator_line)]
        if not rows:
            return lines + self.empty_fragments("No open issues or PRs")
        start, end = self.visible_range()
        for i in range(start, end):
            row = rows[i]
            sel = i == self.cursor
            cls = "sel" if sel else "item"
            fill = "class:sel-title" if sel else "class:item"
            lines.append(("class:sel-prefix" if sel else "class:item", " ▶ " if sel else "   "))
            if row["kind"] == "header":
                arrow = "▸" if row["group"] in self.folded else "▾"
                lines.extend([
                    ("class:sel-title" if sel else "class:header", f"{arrow} {row['group']} "),
                    ("class:sel-title" if sel else "class:border", f"({row['count']})"),
                    ("", "\n"),
                ])
                continue
            tree = row.get("tree", "")
            width = col_title - len(tree)
            login = who(row)
            assignee = (f"@{ellipsize(login, col_who)}" if login else "—").ljust(col_who + 1)
            lines.extend([
                (fill, f"  {tree}"),
                (f"class:{cls}-number", ellipsize(f"#{row['number']}", COL_NUM).ljust(COL_NUM)),
                (f"class:{cls}-title", f" {ellipsize(row['title'], width).ljust(width)}   "),
                (f"class:{cls}-author", assignee),
                (fill, "   "),
                *(self.pr_meta(row, sel) if row["kind"] == "pr" else label_fragments(row["labels"], COL_META, sel)),
                ("", "\n"),
            ])
        return lines

    def pr_meta(self, pr: dict, sel: bool) -> StyleText:
        fill = "class:sel-title" if sel else "class:item"
        status_style, status_label = status_text(pr)
        return [
            ("class:sel-branch" if sel else "class:item-branch", ellipsize(pr["headRefName"], COL_BRANCH).ljust(COL_BRANCH)),
            (fill, "  "),
            ("class:sel-state" if sel else f"class:{status_style}", status_label.ljust(COL_STATUS)),
            (fill, "  "),
            ("class:additions", f"+{pr['additions']}"),
            (fill, " "),
            ("class:deletions", f"−{pr['deletions']}"),
        ]

    def detail_header(self) -> StyleText:
        row = self.selected()
        if row["kind"] == "header":
            return [("class:header", f"  {row['group']} "), ("class:border", f"({row['count']})\n")]
        return item_header(row)

    def detail_text(self) -> StyleText:
        row = self.selected()
        if row["kind"] == "header":
            return [("class:item-time", "  Space folds/unfolds this group\n")]
        return item_detail_text(row)

    def detail_containers(self) -> list[AnyContainer]:
        visible = Condition(lambda: self.is_active() and bool(self.items) and self.detail_visible())
        section = detail_section(self.detail_header, self.detail_text)
        return [*super().detail_containers(), ConditionalContainer(section, filter=visible)]

    def view_bindings(self) -> KeyBindings:
        kb = ListView.bindings(self)

        @kb.add("enter")
        def _(event) -> None:
            if self.items and self.selected()["kind"] != "header":
                open_url(self.selected()["url"])

        @kb.add("c")
        def _(event) -> None:
            if self.items and self.selected()["kind"] == "pr":
                event.app.exit(result=Checkout(self.selected()["number"]))

        @kb.add(" ")
        def _(event) -> None:
            if self.items and self.selected()["kind"] == "header":
                self.folded ^= {self.selected()["group"]}
                self.apply_filter()

        @kb.add("m")
        def _(event) -> None:
            self.shared.mine = not self.shared.mine
            self.apply_filter()

        return kb
