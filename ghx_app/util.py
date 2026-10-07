from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ghx_app.base import StyleText


def label_fg(bg_hex: str) -> str:
    r, g, b = (int(bg_hex[i:i + 2], 16) for i in (0, 2, 4))
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#000000" if luminance > 140 else "#ffffff"


def ellipsize(text: str, width: int) -> str:
    if width <= 1:
        return text[:max(0, width)]
    if len(text) <= width:
        return text
    return text[:width - 1] + "…"


def relative_time(iso_str: str) -> str:
    if not iso_str or iso_str == "n/a":
        return "-"
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    seconds = int((datetime.now(timezone.utc) - dt).total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    if days < 30:
        return f"{days}d"
    return f"{days // 30}mo"


def status_text(pr: dict) -> tuple[str, str]:
    if pr["isDraft"]:
        return "item-draft", "draft"
    review = pr.get("reviewDecision") or "PENDING"
    if review == "APPROVED":
        return "item-state", "approved"
    if review == "CHANGES_REQUESTED":
        return "item-author", "changes"
    if review == "REVIEW_REQUIRED":
        return "detail-label", "review"
    return "detail-value", "pending"


def label_fragments(labels: list[dict], max_width: int, selected: bool) -> StyleText:
    fill = "class:sel-title" if selected else "class:item"
    out: StyleText = []
    used = 0
    for l in labels:
        chip = f" {l['name']} "
        room = max_width - used - 1
        if len(chip) > room and room < 4:
            out.append(("class:item-time", "…"))
            break
        color = l["color"] or "88846f"
        out.append((f"fg:{label_fg(color)} bg:#{color}", f" {ellipsize(l['name'], room - 2)} "))
        out.append((fill, " "))
        if len(chip) > room:
            break
        used += len(chip) + 1
    return out
