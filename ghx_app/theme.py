import os
import re
import select
import sys
import termios
import tty

from prompt_toolkit.styles import Style
from pygments.token import Token

DARK = {
    "fg": "#f8f8f2", "soft": "#c6c3b4", "accent": "#34D399", "dim": "#75715e", "muted": "#88846f",
    "faint": "#5a5749", "cyan": "#66d9ef", "orange": "#fd971f", "green": "#a6e22e", "yellow": "#e5da74",
    "purple": "#ae81ff", "lilac": "#c7b6ff", "red": "#f92672", "bg": "#272822", "sel": "#3a3d34",
    "hl": "#49483e", "bg-purple": "#343142", "bg-green": "#2c2f25", "bg-red": "#34232a",
    "bg-merged": "#2f2a3a", "bg-draft": "#2e2d28",
}

LIGHT = {
    "fg": "#272822", "soft": "#49483e", "accent": "#047857", "dim": "#8a8674", "muted": "#75715e",
    "faint": "#b5b2a3", "cyan": "#0077a3", "orange": "#c25e00", "green": "#4d7f0b", "yellow": "#8f7d00",
    "purple": "#6f42c1", "lilac": "#5b3cc4", "red": "#c8174f", "bg": "#fafaf5", "sel": "#e4e2d6",
    "hl": "#ecead9", "bg-purple": "#ebe5fb", "bg-green": "#e6f0d5", "bg-red": "#f8dfe6",
    "bg-merged": "#ece4f8", "bg-draft": "#ecebe4",
}


def query_background() -> tuple[float, float, float] | None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    buf = b""
    try:
        tty.setcbreak(fd)
        os.write(sys.stdout.fileno(), b"\033]11;?\033\\\033[c")
        while not re.search(rb"\033\[\?[\d;]*c", buf) and select.select([fd], [], [], 0.2)[0]:
            buf += os.read(fd, 256)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    match = re.search(rb"rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)", buf)
    if match is None:
        return None
    return tuple(int(h, 16) / (16 ** len(h) - 1) for h in match.groups())


def is_light() -> bool:
    override = os.environ.get("GHX_THEME")
    if override:
        return override == "light"
    rgb = query_background()
    return rgb is not None and 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2] > 0.5


C = LIGHT if is_light() else DARK

STYLE = Style.from_dict({
    "": C["fg"],
    "header": f"{C['accent']} bold",
    "header-off": f"{C['dim']} bold",
    "header-dim": C["dim"],
    "branch": f"{C['cyan']} bold",
    "border": C["dim"],
    "col-header": f"{C['accent']} bold",
    "col-header-dim": C["dim"],
    "item": C["fg"],
    "item-num": C["orange"],
    "item-number": C["dim"],
    "item-title": C["fg"],
    "item-branch": C["cyan"],
    "item-author": C["orange"],
    "item-state": C["green"],
    "item-draft": f"{C['muted']} italic",
    "item-state-running": C["yellow"],
    "item-state-pending": C["yellow"],
    "item-workflow": C["purple"],
    "item-age": C["orange"],
    "item-link": C["cyan"],
    "item-path": C["cyan"],
    "item-line": C["purple"],
    "item-type": C["purple"],
    "item-repo": C["cyan"],
    "item-reason": C["orange"],
    "item-time": C["muted"],
    "sel-prefix": f"{C['green']} bold bg:{C['sel']}",
    "sel-item": f"{C['fg']} bold bg:{C['sel']}",
    "sel-num": f"{C['orange']} bold bg:{C['sel']}",
    "sel-number": f"{C['green']} bold bg:{C['sel']}",
    "sel-title": f"{C['fg']} bold bg:{C['sel']}",
    "sel-branch": f"{C['cyan']} bold bg:{C['sel']}",
    "sel-author": f"{C['orange']} bold bg:{C['sel']}",
    "sel-draft": f"{C['muted']} bold italic bg:{C['sel']}",
    "sel-state": f"{C['green']} bold bg:{C['sel']}",
    "sel-workflow": f"{C['purple']} bold bg:{C['sel']}",
    "sel-age": f"{C['orange']} bold bg:{C['sel']}",
    "sel-link": f"{C['cyan']} bold bg:{C['sel']}",
    "sel-path": f"{C['cyan']} bold bg:{C['sel']}",
    "sel-line": f"{C['purple']} bold bg:{C['sel']}",
    "sel-type": f"{C['purple']} bold bg:{C['sel']}",
    "sel-repo": f"{C['cyan']} bold bg:{C['sel']}",
    "sel-reason": f"{C['orange']} bold bg:{C['sel']}",
    "sel-time": f"{C['muted']} bold bg:{C['sel']}",
    "chip-kind-pr": f"{C['lilac']} bg:{C['bg-purple']} bold",
    "chip-kind-issue": f"{C['green']} bg:{C['bg-green']} bold",
    "chip-type": f"{C['lilac']} bg:{C['bg-purple']} bold",
    "chip-reason": f"{C['lilac']} bg:{C['bg-purple']} bold",
    "chip-state-open": f"{C['green']} bg:{C['bg-green']} bold",
    "chip-state-closed": f"{C['red']} bg:{C['bg-red']} bold",
    "chip-state-merged": f"{C['purple']} bg:{C['bg-merged']} bold",
    "chip-state-draft": f"{C['muted']} bg:{C['bg-draft']} bold",
    "detail-label": C["accent"],
    "detail-value": C["fg"],
    "snippet": C["fg"],
    "snippet-num": C["muted"],
    "snippet-highlight": f"{C['fg']} bg:{C['hl']}",
    "snippet-highlight-num": f"{C['yellow']} bg:{C['hl']} bold",
    "snippet-dim": f"{C['muted']} italic",
    "comment-body": C["soft"],
    "comment-header": f"{C['accent']} bold",
    "footer": C["muted"],
    "footer-key": f"{C['accent']} bold",
    "footer-dim": C["faint"],
    "tab": C["muted"],
    "tab-active": f"{C['bg']} bg:{C['accent']} bold",
    "new-notif": f"{C['red']} bold",
    "focus-bar": f"{C['green']} bold",
    "review-approved": C["green"],
    "review-changes_requested": C["red"],
    "review-review_required": C["yellow"],
    "review-pending": C["muted"],
    "additions": C["green"],
    "deletions": C["red"],
})

STATE_STYLE = {
    "open": "chip-state-open",
    "closed": "chip-state-closed",
    "merged": "chip-state-merged",
    "draft": "chip-state-draft",
}

TOKEN_COLORS = {
    Token.Keyword: C["yellow"],
    Token.Keyword.Constant: C["purple"],
    Token.Keyword.Namespace: C["yellow"],
    Token.Name.Function: C["green"],
    Token.Name.Class: C["green"],
    Token.Name.Decorator: C["green"],
    Token.Name.Builtin: C["cyan"],
    Token.Name.Builtin.Pseudo: C["orange"],
    Token.String: C["yellow"],
    Token.String.Doc: C["muted"],
    Token.Number: C["purple"],
    Token.Operator: C["yellow"],
    Token.Comment: C["muted"],
    Token.Comment.Single: C["muted"],
    Token.Comment.Multiline: C["muted"],
    Token.Punctuation: C["fg"],
    Token.Name: C["fg"],
    Token.Text: C["fg"],
}
