"""MCP server that drives the Telegram desktop app through screenshots and mouse/keyboard (pyautogui)."""

import logging
import threading
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import Image, MCPServer

from . import gui_core
from .gui_core import Screen, ScreenState
from .result import Err, Result

log = logging.getLogger("telegram_mcp.gui")

INSTRUCTIONS = """\
Controls the Telegram desktop app on this Mac by looking at the screen and clicking, like a person.
- Call open_telegram, then screenshot. Coordinates for click/scroll are pixels in the LAST screenshot.
- Every action returns a fresh screenshot by default: check it before the next step.
- type_text types into the focused field (Cyrillic and emoji work); click the field first.
- Moving the mouse into a screen corner aborts automation (pyautogui failsafe).
Actions are performed as the user, so confirm sending/deleting with them first.
"""

mcp = MCPServer(name="telegram-gui", instructions=INSTRUCTIONS)
state = ScreenState()
_screen: Screen | None = None
# The SDK runs sync tools in worker threads; parallel tool calls must not move the mouse at the same time.
_gui_lock = threading.Lock()


def get_screen() -> Screen:
    global _screen
    if _screen is None:
        from .gui_screen import MacScreen

        _screen = MacScreen()
    return _screen


def set_screen(screen: Screen) -> None:
    """Swap the screen (used by tests)."""
    global _screen
    _screen = screen
    state.image_width = state.image_height = 0


def snapshot(note: str) -> list[Any]:
    try:
        shot = gui_core.take_screenshot(get_screen(), state)
    except Exception as exc:
        log.exception("screenshot failed")
        return [f"{note}\nscreenshot failed: {type(exc).__name__}: {exc}"]
    if isinstance(shot, Err):
        return [f"{note}\nscreenshot failed: {shot.error}"]
    return [f"{note}\nscreenshot {shot.value.width}x{shot.value.height}", Image(data=shot.value.png, format="png")]


def act(operation: Callable[[Screen], Result[str]], screenshot_after: bool) -> list[str | Image]:
    with _gui_lock:
        return _act(operation, screenshot_after)


def _act(operation: Callable[[Screen], Result[str]], screenshot_after: bool) -> list[str | Image]:
    try:
        result = operation(get_screen())
    except Exception as exc:  # pyautogui failsafe, missing Accessibility permission, ...
        log.exception("GUI action failed")
        return [f"error: {type(exc).__name__}: {exc}"]
    if isinstance(result, Err):
        return [f"error: {result.error}"]
    if not screenshot_after:
        return [result.value]
    return snapshot(result.value)


@mcp.tool()
def screenshot() -> list[str | Image]:
    """Take a screenshot of the whole screen. Coordinates for other tools refer to this image."""
    with _gui_lock:
        return snapshot("ok")


@mcp.tool()
def click(x: int, y: int, button: str = "left", screenshot_after: bool = True) -> list[str | Image]:
    """Click at (x, y) in the last screenshot. button: left, right or middle."""
    return act(lambda s: gui_core.click(s, state, x, y, button), screenshot_after)


@mcp.tool()
def double_click(x: int, y: int, screenshot_after: bool = True) -> list[str | Image]:
    """Double-click at (x, y) in the last screenshot."""
    return act(lambda s: gui_core.double_click(s, state, x, y), screenshot_after)


@mcp.tool()
def type_text(text: str, press_enter: bool = False, screenshot_after: bool = True) -> list[str | Image]:
    """Type text into the focused field (via clipboard, so any language works). press_enter sends it."""
    return act(lambda s: gui_core.type_text(s, text, press_enter), screenshot_after)


@mcp.tool()
def press_key(key: str, screenshot_after: bool = True) -> list[str | Image]:
    """Press one key, e.g. enter, esc, tab, up, down, backspace."""
    return act(lambda s: gui_core.press_key(s, key), screenshot_after)


@mcp.tool()
def hotkey(keys: list[str], screenshot_after: bool = True) -> list[str | Image]:
    """Press a key combination, e.g. ["command", "k"] for Telegram search."""
    return act(lambda s: gui_core.hotkey(s, keys), screenshot_after)


@mcp.tool()
def scroll(amount: int, x: int | None = None, y: int | None = None, screenshot_after: bool = True) -> list[str | Image]:
    """Scroll: positive = up, negative = down. Pass x, y (last screenshot) to scroll over a specific area."""
    return act(lambda s: gui_core.scroll(s, state, amount, x, y), screenshot_after)


@mcp.tool()
def open_telegram(screenshot_after: bool = True) -> list[str | Image]:
    """Launch or bring the Telegram desktop app to the front."""
    return act(gui_core.open_telegram, screenshot_after)


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
