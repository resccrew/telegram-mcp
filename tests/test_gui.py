import io

import pytest
from PIL import Image as PILImage

from telegram_mcp import gui_core, gui_server
from telegram_mcp.gui_core import ScreenState
from telegram_mcp.result import Err, Ok


class FakeScreen:
    """A Retina-like screen: 2880x1800 physical pixels, 1440x900 logical points."""

    def __init__(self, physical=(2880, 1800), logical=(1440, 900), fail_screenshot=None):
        self.physical = physical
        self.logical = logical
        self.fail_screenshot = fail_screenshot
        self.calls: list[tuple] = []

    def screenshot(self):
        if self.fail_screenshot:
            return Err(self.fail_screenshot)
        return Ok(PILImage.new("RGB", self.physical, (40, 120, 200)))

    def size(self):
        return self.logical

    def click(self, x, y, button):
        self.calls.append(("click", x, y, button))

    def double_click(self, x, y):
        self.calls.append(("double_click", x, y))

    def move(self, x, y):
        self.calls.append(("move", x, y))

    def scroll(self, amount):
        self.calls.append(("scroll", amount))

    def hotkey(self, *keys):
        self.calls.append(("hotkey", *keys))

    def press(self, key):
        self.calls.append(("press", key))

    def paste_text(self, text):
        self.calls.append(("paste", text))

    def activate_app(self, name):
        self.calls.append(("activate", name))
        return Ok(None)


@pytest.fixture
def screen():
    fake = FakeScreen()
    gui_server.set_screen(fake)
    return fake


def shoot(screen, max_side=gui_core.DEFAULT_MAX_SIDE):
    state = ScreenState()
    shot = gui_core.take_screenshot(screen, state, max_side)
    assert isinstance(shot, Ok)
    return state, shot.value


def test_screenshot_is_downscaled_to_max_side(screen):
    state, shot = shoot(screen)
    assert (shot.width, shot.height) == (1280, 800)
    assert PILImage.open(io.BytesIO(shot.png)).size == (1280, 800)
    assert (state.image_width, state.image_height) == (1280, 800)


def test_small_screenshot_is_not_upscaled():
    state, shot = shoot(FakeScreen(physical=(800, 600), logical=(800, 600)))
    assert (shot.width, shot.height) == (800, 600)


def test_click_maps_screenshot_to_logical_points_on_retina(screen):
    state, _ = shoot(screen)
    assert gui_core.click(screen, state, 640, 400) == Ok("left-clicked at (640, 400)")
    # 1280x800 image -> 1440x900 logical points
    assert screen.calls == [("click", 720, 450, "left")]


def test_click_without_downscale_on_retina():
    fake = FakeScreen(physical=(1200, 800), logical=(600, 400))
    state, _ = shoot(fake)
    gui_core.click(fake, state, 1000, 500, "right")
    assert fake.calls == [("click", 500, 250, "right")]


def test_click_outside_screenshot_is_err(screen):
    state, _ = shoot(screen)
    result = gui_core.click(screen, state, 1280, 10)
    assert isinstance(result, Err) and "outside" in result.error
    assert isinstance(gui_core.double_click(screen, state, -1, 5), Err)
    assert screen.calls == []


def test_click_before_screenshot_is_err(screen):
    result = gui_core.click(screen, ScreenState(), 10, 10)
    assert isinstance(result, Err) and "screenshot first" in result.error


def test_click_rejects_unknown_button(screen):
    state, _ = shoot(screen)
    assert isinstance(gui_core.click(screen, state, 1, 1, "side"), Err)


def test_type_text_uses_paste_and_optional_enter(screen):
    assert isinstance(gui_core.type_text(screen, "Привет 👋", press_enter=True), Ok)
    assert screen.calls == [("paste", "Привет 👋"), ("press", "enter")]
    assert isinstance(gui_core.type_text(screen, ""), Err)


def test_scroll_moves_mouse_to_mapped_point(screen):
    state, _ = shoot(screen)
    gui_core.scroll(screen, state, -5, 128, 80)
    assert screen.calls == [("move", 144, 90), ("scroll", -5)]
    assert isinstance(gui_core.scroll(screen, state, 3, x=10), Err)
    assert isinstance(gui_core.scroll(screen, state, 0), Err)


def test_hotkey_and_press(screen):
    gui_core.hotkey(screen, ["command", "k"])
    gui_core.press_key(screen, "esc")
    assert screen.calls == [("hotkey", "command", "k"), ("press", "esc")]
    assert isinstance(gui_core.hotkey(screen, []), Err)


def test_screenshot_error_is_passed_through():
    fake = FakeScreen(fail_screenshot="grant Screen Recording")
    result = gui_core.take_screenshot(fake, ScreenState())
    assert result == Err("grant Screen Recording")


async def test_screenshot_tool_returns_image_content(screen):
    result = await gui_server.mcp.call_tool("screenshot", {})
    kinds = [block.type for block in result.content]
    assert kinds == ["text", "image"]
    assert "1280x800" in result.content[0].text
    assert result.content[1].mime_type == "image/png"


async def test_click_tool_clicks_and_returns_fresh_screenshot(screen):
    await gui_server.mcp.call_tool("screenshot", {})
    result = await gui_server.mcp.call_tool("click", {"x": 640, "y": 400})
    assert screen.calls == [("click", 720, 450, "left")]
    assert [block.type for block in result.content] == ["text", "image"]


async def test_action_without_screenshot_after(screen):
    result = await gui_server.mcp.call_tool("open_telegram", {"screenshot_after": False})
    assert [block.type for block in result.content] == ["text"]
    assert screen.calls == [("activate", "Telegram")]


async def test_tool_reports_err_as_text(screen):
    result = await gui_server.mcp.call_tool("click", {"x": 5, "y": 5})
    assert result.content[0].text.startswith("error: Take a screenshot first")


async def test_tool_reports_unexpected_exception(screen, monkeypatch):
    def boom(*args):
        raise RuntimeError("FailSafeException")

    monkeypatch.setattr(screen, "hotkey", boom)
    result = await gui_server.mcp.call_tool("hotkey", {"keys": ["command", "k"]})
    assert result.content[0].text == "error: RuntimeError: FailSafeException"


class ExplodingScreen(FakeScreen):
    def screenshot(self):
        raise OSError("CoreGraphics unavailable")


def test_screenshot_exception_becomes_error_text():
    gui_server.set_screen(ExplodingScreen())
    out = gui_server.screenshot()
    assert len(out) == 1 and "screenshot failed: OSError" in out[0]


def test_paste_restores_clipboard_even_if_paste_fails(monkeypatch):
    from telegram_mcp import gui_screen

    runs = []

    class Done:
        stdout = "old clipboard"

    def fake_run(cmd, **kwargs):
        runs.append((cmd[0], kwargs.get("input"), kwargs["env"]["LANG"]))
        return Done()

    class Boom:
        def hotkey(self, *keys):
            raise RuntimeError("failsafe")

    monkeypatch.setattr(gui_screen.subprocess, "run", fake_run)
    screen = gui_screen.MacScreen()
    monkeypatch.setattr(screen, "_input", lambda: Boom())
    with pytest.raises(RuntimeError):
        screen.paste_text("привет")
    assert runs == [
        ("pbpaste", None, "en_US.UTF-8"),
        ("pbcopy", "привет", "en_US.UTF-8"),
        ("pbcopy", "old clipboard", "en_US.UTF-8"),
    ]


def test_screenshot_reports_missing_screen_recording(monkeypatch):
    from telegram_mcp import gui_screen

    monkeypatch.setattr(gui_screen, "screen_recording_granted", lambda: False)
    result = gui_screen.MacScreen().screenshot()
    assert isinstance(result, Err) and "Screen Recording" in result.error
