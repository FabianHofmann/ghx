from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import ConditionalKeyBindings, KeyBindings, merge_key_bindings
from prompt_toolkit.layout import ConditionalContainer, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl

from ghx_app.base import ListView, Shared

if TYPE_CHECKING:
    from prompt_toolkit.layout import AnyContainer

SEARCH_PROMPT = "  Search: "
SEARCH_HINTS = [("Enter", "search GitHub"), ("Esc", "clear")]


class SearchableView(ListView):
    def __init__(self, shared: Shared) -> None:
        super().__init__(shared)
        self.all_items: list[dict] = []
        self.search_mode = False
        self.search_query = ""
        self.unsearched_items: list[dict] = []
        self.search_buffer = Buffer(multiline=False, on_text_changed=lambda _: self.apply_filter())

    @abstractmethod
    def haystack(self, item: dict) -> str: ...

    @abstractmethod
    def view_bindings(self) -> KeyBindings: ...

    def keep(self, item: dict) -> bool:
        return True

    def search_suffix(self) -> str:
        return f", search: {self.search_query}" if self.search_query else ""

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

    def filter_terms(self) -> list[str]:
        return self.search_buffer.text.lower().split() if self.search_mode else []

    def matches(self, item: dict) -> bool:
        return self.keep(item) and all(term in self.haystack(item).lower() for term in self.filter_terms())

    def filtered(self) -> list[dict]:
        return [it for it in self.all_items if self.matches(it)]

    def apply_filter(self) -> None:
        self.items = self.filtered()
        self.cursor = min(self.cursor, max(0, len(self.items) - 1))
        self.adjust_scroll()

    def hints(self) -> list[tuple[str, str]]:
        return SEARCH_HINTS if self.search_mode else []

    def capturing_input(self) -> bool:
        return self.search_mode

    def search_bar_visible(self) -> bool:
        return self.search_mode or bool(self.search_query)

    def chrome_rows(self) -> int:
        return int(self.search_bar_visible())

    def detail_containers(self) -> list[AnyContainer]:
        search_bar = VSplit([
            Window(FormattedTextControl([("class:header", SEARCH_PROMPT)]), width=len(SEARCH_PROMPT)),
            Window(BufferControl(self.search_buffer)),
        ], height=1)
        visible = Condition(lambda: self.is_active() and self.search_bar_visible())
        return [ConditionalContainer(search_bar, filter=visible)]

    def start_search(self, event) -> None:
        self.search_mode = True
        self.adjust_scroll()
        event.app.layout.focus(self.search_buffer)

    def end_search(self, event, query: str) -> None:
        self.search_mode = False
        event.app.layout.focus(self.shell.list_window)
        if query == self.search_query:
            self.apply_filter()
            return
        if not self.search_query:
            self.unsearched_items = self.all_items
        self.search_query = query
        self.search_buffer.text = query
        self.cursor = 0
        self.scroll = 0
        if not query:
            self.apply(self.unsearched_items)
        self.loaded = False
        self.ensure_loaded()

    def bindings(self) -> KeyBindings:
        normal = KeyBindings()

        @normal.add("f")
        def _(event) -> None:
            self.start_search(event)

        search = KeyBindings()

        @search.add("enter")
        def _(event) -> None:
            self.end_search(event, self.search_buffer.text.strip())

        @search.add("escape", eager=True)
        def _(event) -> None:
            self.search_buffer.text = ""
            self.end_search(event, "")

        return merge_key_bindings([
            ConditionalKeyBindings(merge_key_bindings([self.view_bindings(), normal]), Condition(lambda: not self.search_mode)),
            ConditionalKeyBindings(search, Condition(lambda: self.search_mode)),
        ])
