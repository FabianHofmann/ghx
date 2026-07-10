from __future__ import annotations

import threading
import time
from typing import Any, Callable

from prompt_toolkit import Application
from prompt_toolkit.filters import Condition
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.key_binding import ConditionalKeyBindings, KeyBindings, merge_key_bindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Dimension, HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl

from ghx_app.base import ListView, Shared, StyleText
from ghx_app.gh import current_branch, get_pr_number, open_pr_in_browser
from ghx_app.statusbar import StatusBar
from ghx_app.theme import MONOKAI_STYLE

ANSI_SEQUENCES["\x1b[I"] = Keys.F23
ANSI_SEQUENCES["\x1b[O"] = Keys.F24


class Scheduler(threading.Thread):
    def __init__(self, shell: Shell, stop: threading.Event) -> None:
        super().__init__(daemon=True)
        self.shell = shell
        self.stop = stop
        self.last: dict[int, float] = {}

    def run(self) -> None:
        while not self.stop.wait(1.0):
            now = time.monotonic()
            for source in (self.shell.statusbar, self.shell.active_view):
                if source.poll_interval is None or not source.ready():
                    continue
                if now - self.last.setdefault(id(source), now) < source.poll_interval:
                    continue
                self.last[id(source)] = now
                try:
                    source.poll()
                except Exception:
                    pass


class Shell:
    def __init__(self, shared: Shared, views: list[ListView], statusbar: StatusBar, initial: int) -> None:
        self.shared = shared
        self.views = views
        self.statusbar = statusbar
        self.active_view = views[initial]
        self.focus = True
        self.message = ""
        self.app: Application[Any] | None = None
        self.stop = threading.Event()
        statusbar.shell = self
        for view in views:
            view.shell = self

    def schedule(self, fn: Callable[[], None]) -> None:
        app = self.app
        if app is not None and app.loop is not None:
            app.loop.call_soon_threadsafe(fn)
        else:
            fn()

    def invalidate(self) -> None:
        if self.app is not None:
            self.app.invalidate()

    def switch(self, index: int) -> None:
        view = self.views[index]
        if view is self.active_view:
            return
        self.active_view = view
        self.message = ""
        view.on_activate()
        self.invalidate()

    def flash(self, text: str) -> None:
        self.message = text
        self.invalidate()

    def on_branch_change(self) -> None:
        self.shared.branch = current_branch()
        self.shared.pr_number = get_pr_number()
        self.message = ""
        self.statusbar.reset()
        for view in self.views:
            view.on_branch_change()

    def header_fragments(self) -> StyleText:
        hdr = "class:header" if self.focus else "class:header-off"
        view = self.active_view
        start, end = view.visible_range()
        shown = f", showing {start + 1}-{end}" if view.items else ""
        return [(hdr, f"  {view.title()} "), ("class:border", f"({view.counts()}{shown})")]

    def footer_fragments(self) -> StyleText:
        parts: StyleText = []
        for i, view in enumerate(self.views):
            style = "class:footer-key" if view is self.active_view else "class:footer"
            parts.append((style, f" {i + 1}:{view.label}"))
        parts.append(("class:footer", "  │"))
        for key, label in self.active_view.hints():
            parts.append(("class:footer-key", f" {key} "))
            parts.append(("class:footer", label))
        parts.append(("class:footer-key", " r "))
        parts.append(("class:footer", "refresh"))
        parts.append(("class:footer-key", " o "))
        parts.append(("class:footer", "pr"))
        parts.append(("class:footer-key", " q "))
        parts.append(("class:footer", "quit"))
        if self.active_view.has_new:
            parts.append(("class:new-notif", "  ● new"))
        if self.message:
            parts.append(("class:footer", f"  {self.message}"))
        return parts

    def global_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        for index in range(len(self.views)):
            @kb.add(str(index + 1))
            def _(event, index: int = index) -> None:
                self.switch(index)

        @kb.add("tab")
        def _(event) -> None:
            self.switch((self.views.index(self.active_view) + 1) % len(self.views))

        @kb.add("s-tab")
        def _(event) -> None:
            self.switch((self.views.index(self.active_view) - 1) % len(self.views))

        @kb.add("o")
        def _(event) -> None:
            if self.shared.pr_number is None:
                self.flash("no open PR for this branch")
            else:
                open_pr_in_browser(self.shared.pr_number)

        @kb.add(Keys.F23)
        def _(event) -> None:
            self.focus = True
            event.app.invalidate()

        @kb.add(Keys.F24)
        def _(event) -> None:
            self.focus = False
            event.app.invalidate()

        @kb.add("q")
        @kb.add("escape")
        def _(event) -> None:
            event.app.exit()

        return kb

    def build_app(self) -> Application[Any]:
        header = Window(FormattedTextControl(self.header_fragments), height=1)
        list_window = Window(
            FormattedTextControl(lambda: self.active_view.list_fragments(), show_cursor=False, focusable=True),
            height=Dimension(min=1, weight=1),
        )
        details = [container for view in self.views for container in view.detail_containers()]
        status = Window(FormattedTextControl(self.statusbar.fragments), height=1)
        footer = Window(FormattedTextControl(self.footer_fragments), height=1)
        accent = Window(height=1, char=lambda: "━" if self.focus else " ", style="class:focus-bar")
        layout = Layout(HSplit([header, list_window, *details, status, footer, accent]))
        view_bindings = [
            ConditionalKeyBindings(view.bindings(), Condition(lambda view=view: self.active_view is view))
            for view in self.views
        ]
        bindings = merge_key_bindings([self.global_bindings(), *view_bindings])
        return Application(layout=layout, key_bindings=bindings, style=MONOKAI_STYLE, full_screen=True)

    def run(self) -> Any:
        self.stop = threading.Event()
        app = self.build_app()
        self.app = app
        self.statusbar.ensure_loaded()
        self.active_view.on_activate()
        for view in self.views:
            view.on_run_start()
        Scheduler(self, self.stop).start()

        def enable_focus_reporting() -> None:
            app.output.write_raw("\x1b[?1004h")
            app.output.flush()

        try:
            return app.run(pre_run=enable_focus_reporting)
        finally:
            self.stop.set()
            app.output.write_raw("\x1b[?1004l")
            app.output.flush()
            self.app = None
