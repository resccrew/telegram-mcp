"""The real macOS screen, driven by pyautogui. Imported lazily so tests never need a display."""

import ctypes
import os
import subprocess
import time
from typing import Any

from PIL import Image as PILImage

from .result import Err, Ok, Result

PERMISSIONS_HINT = (
    "grant {what} to the app that runs Claude Code (Terminal, iTerm, VS Code, ...) in "
    "System Settings → Privacy & Security → {what}, then restart that app."
)
APP_START_WAIT = 1.5
APPLICATION_SERVICES = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
CORE_GRAPHICS = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
# pbcopy/pbpaste pick the text encoding from LANG; MCP servers often start without it and Cyrillic gets mangled.
UTF8_ENV = {**os.environ, "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"}


def accessibility_granted() -> bool:
    """Without Accessibility macOS silently drops synthetic clicks and keys, so check it up front."""
    lib = ctypes.cdll.LoadLibrary(APPLICATION_SERVICES)
    lib.AXIsProcessTrusted.restype = ctypes.c_bool
    return bool(lib.AXIsProcessTrusted())


def screen_recording_granted() -> bool:
    """Without Screen Recording macOS returns only the wallpaper, which can't be told apart from a real screen."""
    lib = ctypes.cdll.LoadLibrary(CORE_GRAPHICS)
    lib.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
    return bool(lib.CGPreflightScreenCaptureAccess())


class MacScreen:
    def __init__(self) -> None:
        self._pyautogui: Any = None

    def _gui(self) -> Any:
        if self._pyautogui is None:
            import pyautogui

            pyautogui.FAILSAFE = True  # slam the mouse into a screen corner to abort
            pyautogui.PAUSE = 0.1
            self._pyautogui = pyautogui
        return self._pyautogui

    def _input(self) -> Any:
        if not accessibility_granted():
            raise PermissionError("clicks and keys are ignored: " + PERMISSIONS_HINT.format(what="Accessibility"))
        return self._gui()

    def screenshot(self) -> Result[PILImage.Image]:
        if not screen_recording_granted():
            return Err("Screen Recording is missing: " + PERMISSIONS_HINT.format(what="Screen Recording"))
        try:
            image = self._gui().screenshot()
        except Exception as exc:  # screencapture fails without the Screen Recording permission
            return Err(f"Screenshot failed ({exc}): " + PERMISSIONS_HINT.format(what="Screen Recording"))
        if image.convert("L").getextrema() == (0, 0):
            return Err("Screenshot is completely black: " + PERMISSIONS_HINT.format(what="Screen Recording"))
        return Ok(image)

    def size(self) -> tuple[int, int]:
        width, height = self._gui().size()
        return int(width), int(height)

    def click(self, x: int, y: int, button: str) -> None:
        self._input().click(x, y, button=button)

    def double_click(self, x: int, y: int) -> None:
        self._input().doubleClick(x, y)

    def move(self, x: int, y: int) -> None:
        self._input().moveTo(x, y)

    def scroll(self, amount: int) -> None:
        self._input().scroll(amount)

    def hotkey(self, *keys: str) -> None:
        self._input().hotkey(*keys)

    def press(self, key: str) -> None:
        self._input().press(key)

    def paste_text(self, text: str) -> None:
        gui = self._input()  # check permissions before touching the user's clipboard
        previous = subprocess.run(["pbpaste"], capture_output=True, encoding="utf-8", env=UTF8_ENV).stdout
        subprocess.run(["pbcopy"], input=text, encoding="utf-8", env=UTF8_ENV, check=True)
        try:
            gui.hotkey("command", "v")
            time.sleep(0.2)  # let the app read the clipboard before it is restored
        finally:
            if previous:  # empty = clipboard held no text (image, files): pbcopy can't restore that anyway
                subprocess.run(["pbcopy"], input=previous, encoding="utf-8", env=UTF8_ENV)

    def activate_app(self, name: str) -> Result[None]:
        done = subprocess.run(["open", "-a", name], capture_output=True, text=True)
        if done.returncode != 0:
            return Err(f"Could not open {name}: {done.stderr.strip()}")
        time.sleep(APP_START_WAIT)
        return Ok(None)
