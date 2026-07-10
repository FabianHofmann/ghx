from datetime import datetime, timezone


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
