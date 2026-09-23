"""MCP server that drives the TradeLocker desktop app through screenshots and mouse/keyboard.

Reuses the Telegram GUI tools (same screen, same lock); only the app launcher differs.
"""

import logging

from mcp.server.mcpserver import Image, MCPServer

from . import gui_core, gui_server

INSTRUCTIONS = """\
Controls the TradeLocker desktop app on this Mac (Studio bots, backtests, charts) by looking at the screen and clicking.
- Call open_tradelocker, then screenshot. Coordinates for click/scroll are pixels in the LAST screenshot.
- Every action returns a fresh screenshot by default: check it before the next step.
- type_text pastes via clipboard into the focused field (use it for bot code in the Studio editor).
- Moving the mouse into a screen corner aborts automation (pyautogui failsafe).
Actions are performed as the user: confirm with them before Launch Bot, placing or closing trades.
"""

mcp = MCPServer(name="tradelocker-gui", instructions=INSTRUCTIONS)

for tool in (gui_server.screenshot, gui_server.click, gui_server.double_click, gui_server.type_text,
             gui_server.press_key, gui_server.hotkey, gui_server.scroll):
    mcp.tool()(tool)


@mcp.tool()
def open_tradelocker(screenshot_after: bool = True) -> list[str | Image]:
    """Launch or bring the TradeLocker desktop app to the front."""
    return gui_server.act(lambda s: gui_core.open_app(s, "TradeLocker"), screenshot_after)


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
