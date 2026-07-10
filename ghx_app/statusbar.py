from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from prompt_toolkit.application import get_app

from ghx_app.base import Shared, StyleText
from ghx_app.gh import fetch_context, get_pr_number
from ghx_app.theme import STATE_STYLE
from ghx_app.util import ellipsize

if TYPE_CHECKING:
    from ghx_app.shell import Shell


class StatusBar:
    poll_interval: float = 30.0

    shell: Shell

    def __init__(self, shared: Shared) -> None:
        self.shared = shared
        self.context: dict | None = None
        self.loaded = False
        self.loading = False

    def ready(self) -> bool:
        return self.loaded

    def reset(self) -> None:
        self.loaded = False
        self.context = None

    def load(self) -> tuple[int | None, dict | None]:
        pr = get_pr_number()
        if self.shared.repo is None or pr is None:
            return pr, None
        return pr, fetch_context(self.shared.repo, pr)

    def ensure_loaded(self) -> None:
        if self.loaded or self.loading:
            return
        self.loading = True

        def work() -> None:
            try:
                pr, context = self.load()
            except Exception:
                self.loading = False
                return
            self.shell.schedule(lambda: self.apply(pr, context))

        threading.Thread(target=work, daemon=True).start()

    def apply(self, pr: int | None, context: dict | None) -> None:
        self.loading = False
        self.loaded = True
        self.shared.pr_number = pr
        self.context = context
        self.shell.invalidate()

    def poll(self) -> None:
        pr, context = self.load()
        if (pr, context) != (self.shared.pr_number, self.context):
            self.shell.schedule(lambda: self.apply(pr, context))

    def fragments(self) -> StyleText:
        parts: StyleText = [("class:branch", f"  {self.shared.branch}")]
        if self.shared.repo is None:
            parts.append(("class:header-dim", "  ·  (no repo) — notifications across all repos"))
            return parts
        parts.append(("class:header-dim", f"  ·  {self.shared.repo}  ·  "))
        if not self.loaded:
            parts.append(("class:header-dim", "…"))
            return parts
        if self.context is None:
            parts.append(("class:header-dim", "no open PR"))
            return parts
        pr = self.context["pr"]
        head: StyleText = [
            ("class:item-num", f"PR #{pr['number']} "),
            (f"class:{STATE_STYLE[pr['state']]}", f" {pr['state']} "),
        ]
        tail: StyleText = []
        for issue in self.context["issues"]:
            tail.append(("class:header-dim", "  ⇒  " if not tail else "  "))
            tail.append(("class:item-num", f"#{issue['number']} "))
            tail.append((f"class:{STATE_STYLE[issue['state']]}", f" {issue['state']} "))
        width = get_app().output.get_size().columns
        used = sum(len(text) for _, text in [*parts, *head, *tail]) + 2
        title = ellipsize(pr["title"], max(8, width - used))
        return [*parts, *head, ("", f" {title}"), *tail]
