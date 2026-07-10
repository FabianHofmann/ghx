from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from prompt_toolkit.application import get_app
from prompt_toolkit.key_binding import KeyBindings

if TYPE_CHECKING:
    from prompt_toolkit.layout import AnyContainer

    from ghx_app.shell import Shell

StyleText = list[tuple[str, str]]

SHELL_CHROME_ROWS = 6


@dataclass
class Shared:
    repo: str | None
    branch: str
    pr_number: int | None
    mine: bool


class ListView(ABC):
    label: ClassVar[str]
    poll_interval: ClassVar[float | None] = None

    shell: Shell

    def __init__(self, shared: Shared) -> None:
        self.shared = shared
        self.items: list[dict] = []
        self.cursor = 0
        self.scroll = 0
        self.loaded = False
        self.loading = False
        self.has_new = False
        self.error = ""
        self.last_fetch = 0.0

    @abstractmethod
    def title(self) -> str: ...

    @abstractmethod
    def counts(self) -> str: ...

    @abstractmethod
    def fetch(self) -> list[dict]: ...

    @abstractmethod
    def list_fragments(self) -> StyleText: ...

    @abstractmethod
    def hints(self) -> list[tuple[str, str]]: ...

    def detail_containers(self) -> list[AnyContainer]:
        return []

    def chrome_rows(self) -> int:
        return 0

    def poll(self) -> None:
        pass

    def on_run_start(self) -> None:
        pass

    def on_branch_change(self) -> None:
        pass

    def is_active(self) -> bool:
        return self.shell.active_view is self

    def ready(self) -> bool:
        return self.loaded

    def viewport_width(self) -> int:
        return get_app().output.get_size().columns

    def list_capacity(self) -> int:
        rows = get_app().output.get_size().rows
        return max(1, rows - SHELL_CHROME_ROWS - self.chrome_rows())

    def visible_range(self) -> tuple[int, int]:
        return self.scroll, min(self.scroll + self.list_capacity(), len(self.items))

    def adjust_scroll(self) -> None:
        capacity = self.list_capacity()
        if self.cursor < self.scroll:
            self.scroll = self.cursor
        elif self.cursor >= self.scroll + capacity:
            self.scroll = self.cursor - capacity + 1

    def move(self, delta: int) -> None:
        self.cursor = max(0, min(len(self.items) - 1, self.cursor + delta))
        self.adjust_scroll()

    def seed(self, items: list[dict]) -> None:
        self.items = items
        self.loaded = True
        self.last_fetch = time.monotonic()

    def ensure_loaded(self) -> None:
        if self.loaded or self.loading:
            return
        self.loading = True
        self.error = ""

        def work() -> None:
            try:
                items = self.fetch()
            except Exception as exc:
                message = str(exc)
                self.shell.schedule(lambda: self.fail_load(message))
                return
            self.shell.schedule(lambda: self.finish_load(items))

        threading.Thread(target=work, daemon=True).start()

    def finish_load(self, items: list[dict]) -> None:
        self.loading = False
        self.loaded = True
        self.last_fetch = time.monotonic()
        self.apply(items)

    def fail_load(self, message: str) -> None:
        self.loading = False
        self.error = message
        self.shell.invalidate()

    def apply(self, items: list[dict]) -> None:
        self.items = items
        self.cursor = min(self.cursor, max(0, len(items) - 1))
        self.adjust_scroll()
        self.shell.invalidate()

    def refresh(self) -> None:
        self.has_new = False
        self.last_fetch = time.monotonic()
        self.apply(self.fetch())

    def on_activate(self) -> None:
        stale = self.poll_interval is not None and time.monotonic() - self.last_fetch > self.poll_interval
        if self.loaded and stale:
            self.loaded = False
        self.ensure_loaded()

    def empty_fragments(self, message: str) -> StyleText:
        if self.error:
            return [("class:new-notif", f"\n   {self.error}\n")]
        if self.loading:
            return [("class:item-time", "\n   loading…\n")]
        return [("class:item-time", f"\n   {message}\n")]

    def bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def _(event) -> None:
            self.move(-1)

        @kb.add("down")
        @kb.add("j")
        def _(event) -> None:
            self.move(1)

        @kb.add("r")
        def _(event) -> None:
            self.refresh()

        return kb
