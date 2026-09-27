"""MCP server that drives the Affinity design app through screenshots and mouse/keyboard.

Reuses the Telegram GUI tools (same screen, same lock); only the app launcher differs.
"""

import logging

from mcp.server.mcpserver import Image, MCPServer

from . import gui_core, gui_server

INSTRUCTIONS = """\
Controls the Affinity app (vector, pixel and layout design) on this Mac by looking at the screen and clicking.
- Call open_affinity, then screenshot. Coordinates for click/drag/scroll are pixels in the LAST screenshot.
- Every action returns a fresh screenshot by default: check it before the next step.
- drag draws shapes, moves objects and adjusts sliders; pick the tool first (toolbar click or its shortcut key).
- Prefer keyboard shortcuts and menus (hotkey, e.g. ["command", "n"] new document, ["command", "z"] undo).
- type_text pastes via clipboard into the focused field (text frames, numeric fields in panels).
- Moving the mouse into a screen corner aborts automation (pyautogui failsafe).
Actions are performed as the user: confirm with them before overwriting, closing without saving or deleting files.
"""

mcp = MCPServer(name="affinity-gui", instructions=INSTRUCTIONS)

for tool in (gui_server.screenshot, gui_server.click, gui_server.double_click, gui_server.drag,
             gui_server.type_text, gui_server.press_key, gui_server.hotkey, gui_server.scroll):
    mcp.tool()(tool)


@mcp.tool()
def open_affinity(screenshot_after: bool = True) -> list[str | Image]:
    """Launch or bring the Affinity app to the front."""
    return gui_server.act(lambda s: gui_core.open_app(s, "Affinity"), screenshot_after)


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
