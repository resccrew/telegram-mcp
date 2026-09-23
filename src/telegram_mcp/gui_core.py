"""GUI automation logic: screenshots for Claude and clicks/typing mapped back to the real screen.

Claude sees a downscaled screenshot and answers with coordinates in that image. On Retina displays the
raw screenshot has twice the pixels of the logical screen pyautogui clicks in, so every coordinate goes
through one mapping: image px -> logical points. Everything here works on the `Screen` protocol, so it is
tested with a fake screen and never needs a display.
"""

import io
from dataclasses import dataclass
from typing import Protocol

from PIL import Image as PILImage

from .result import Err, Ok, Result

DEFAULT_MAX_SIDE = 1280
BUTTONS = ("left", "right", "middle")


class Screen(Protocol):
    def screenshot(self) -> Result[PILImage.Image]: ...
    def size(self) -> tuple[int, int]: ...  # logical points, the space clicks happen in
    def click(self, x: int, y: int, button: str) -> None: ...
    def double_click(self, x: int, y: int) -> None: ...
    def move(self, x: int, y: int) -> None: ...
    def scroll(self, amount: int) -> None: ...
    def hotkey(self, *keys: str) -> None: ...
    def press(self, key: str) -> None: ...
    def paste_text(self, text: str) -> None: ...
    def activate_app(self, name: str) -> Result[None]: ...


@dataclass(frozen=True)
class Shot:
    png: bytes
    width: int  # size of the image Claude sees
    height: int


@dataclass
class ScreenState:
    """Remembers the size of the last screenshot so coordinates in it can be mapped to the screen."""

    image_width: int = 0
    image_height: int = 0


def take_screenshot(screen: Screen, state: ScreenState, max_side: int = DEFAULT_MAX_SIDE) -> Result[Shot]:
    raw = screen.screenshot()
    if isinstance(raw, Err):
        return raw
    image = raw.value.convert("RGB")
    scale = min(1.0, max_side / max(image.size))
    if scale < 1.0:
        image = image.resize((round(image.width * scale), round(image.height * scale)), PILImage.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    state.image_width, state.image_height = image.size
    return Ok(Shot(png=buffer.getvalue(), width=image.width, height=image.height))


def to_screen_point(screen: Screen, state: ScreenState, x: int, y: int) -> Result[tuple[int, int]]:
    """Map a point in the last screenshot to logical screen points (handles downscaling and Retina)."""
    if state.image_width == 0:
        return Err("Take a screenshot first: coordinates are relative to the last screenshot.")
    if not (0 <= x < state.image_width and 0 <= y < state.image_height):
        return Err(f"({x}, {y}) is outside the screenshot ({state.image_width}x{state.image_height}).")
    screen_w, screen_h = screen.size()
    return Ok((round(x * screen_w / state.image_width), round(y * screen_h / state.image_height)))


def click(screen: Screen, state: ScreenState, x: int, y: int, button: str = "left") -> Result[str]:
    if button not in BUTTONS:
        return Err(f"button must be one of {', '.join(BUTTONS)}")
    point = to_screen_point(screen, state, x, y)
    if isinstance(point, Err):
        return point
    screen.click(*point.value, button)
    return Ok(f"{button}-clicked at ({x}, {y})")


def double_click(screen: Screen, state: ScreenState, x: int, y: int) -> Result[str]:
    point = to_screen_point(screen, state, x, y)
    if isinstance(point, Err):
        return point
    screen.double_click(*point.value)
    return Ok(f"double-clicked at ({x}, {y})")


def type_text(screen: Screen, text: str, press_enter: bool = False) -> Result[str]:
    """Type via the clipboard: pyautogui.write cannot type Cyrillic or emoji."""
    if not text:
        return Err("text is empty")
    screen.paste_text(text)
    if press_enter:
        screen.press("enter")
    return Ok(f"typed {len(text)} chars" + (" and pressed enter" if press_enter else ""))


def press_key(screen: Screen, key: str) -> Result[str]:
    if not key:
        return Err("key is empty")
    screen.press(key)
    return Ok(f"pressed {key}")


def hotkey(screen: Screen, keys: list[str]) -> Result[str]:
    if not keys:
        return Err("keys is empty")
    screen.hotkey(*keys)
    return Ok(f"pressed {'+'.join(keys)}")


def scroll(screen: Screen, state: ScreenState, amount: int, x: int | None = None, y: int | None = None) -> Result[str]:
    """Positive amount scrolls up, negative down. Optionally move the mouse over (x, y) first."""
    if amount == 0:
        return Err("amount must not be 0")
    if (x is None) != (y is None):
        return Err("pass both x and y, or neither")
    if x is not None and y is not None:
        point = to_screen_point(screen, state, x, y)
        if isinstance(point, Err):
            return point
        screen.move(*point.value)
    screen.scroll(amount)
    return Ok(f"scrolled {amount}")


def open_app(screen: Screen, name: str) -> Result[str]:
    opened = screen.activate_app(name)
    if isinstance(opened, Err):
        return opened
    return Ok(f"{name} is in front")


def open_telegram(screen: Screen) -> Result[str]:
    return open_app(screen, "Telegram")
