# telegram-mcp

## Purpose
MCP server (stdio) giving Claude Code full control of the user's own Telegram account:
reading chats, messaging, posting to channels, creating channels/groups/bots, pressing inline buttons.
Second server `telegram-gui` (GUI mode): drives the Telegram desktop app via screenshots + pyautogui —
Claude looks at the screenshot and says where to click. Needs no API keys or login.

## Stack
- Python 3.13, uv
- `mcp` 2.x SDK (`mcp.server.mcpserver.MCPServer`; FastMCP was renamed in 2.x)
- Telethon 1.45 (MTProto user client, `StringSession`)
- GUI mode: pyautogui + Pillow (macOS only)
- pytest + pytest-asyncio (`asyncio_mode = auto`)

## Architecture
- `src/telegram_mcp/core.py` — all Telegram logic. Every function takes the client as its first
  argument and returns `Result` (`Ok`/`Err` from `result.py`); no business exceptions.
- `src/telegram_mcp/server.py` — thin MCP tool layer. `run()` converts `Result` and unexpected
  Telethon RPC errors into `{"ok": bool, "result"|"error"}`. Client is created lazily so the
  server starts (and explains what to do) before login.
- `src/telegram_mcp/config.py` — credentials from env, then `~/.telegram-mcp/config.env`.
- `src/telegram_mcp/login.py` — interactive one-time login, writes the session string.
- `src/telegram_mcp/gui_core.py` — GUI logic on a `Screen` protocol: downscaled screenshots, mapping
  screenshot px → logical screen points, click/type/scroll/hotkey. Returns `Result`.
- `src/telegram_mcp/gui_screen.py` — real `MacScreen` (pyautogui, imported lazily; Accessibility check).
- `src/telegram_mcp/gui_server.py` — `telegram-gui` MCP tools; each action returns text + a fresh
  screenshot (`Image`, return annotation `list[str | Image]` so the SDK emits image content blocks).
- `tests/test_gui.py` — `FakeScreen` (Retina-like 2880x1800 physical / 1440x900 logical).
- `tests/fakes.py` — in-memory fake TelegramClient incl. a scripted @BotFather.

## Key decisions
- User account (MTProto), not Bot API: bots cannot read arbitrary chats or talk to BotFather.
- `StringSession` in a text file instead of Telethon's SQLite session: no `database is locked`.
  Still, one auth key should have one live connection — running the server in many Claude Code
  windows at once risks `AuthKeyDuplicatedError` (Telegram revokes the session; re-run login).
- `send_file` refuses `~/.telegram-mcp`, `~/.ssh`, hidden paths and `*.env/*.session/*.key/*.pem`
  (protects against prompt injection from incoming messages exfiltrating the session).
- Secret files are created with `os.open(..., 0o600)` — never world-readable, even briefly.
- `resolve_chat` tries `get_entity` first, then falls back to matching dialog titles/ids.
- `talk_to_bot` polls for replies (`POLL_INTERVAL`, patched to 0.01 in tests) instead of
  event handlers — simpler and deterministic to test.
- GUI coordinates are always in the last screenshot's space: image px × (logical size / image size).
  This covers both downscaling and Retina (screenshot is physical px, pyautogui clicks in points).
- GUI text is typed via clipboard + cmd+v (pyautogui.write can't type Cyrillic/emoji); the old
  clipboard is restored after 0.2 s.
- Without Accessibility macOS silently drops synthetic input, so `MacScreen` checks
  `AXIsProcessTrusted` before every input and returns a clear error instead; screenshots check
  `CGPreflightScreenCaptureAccess` (without it macOS silently returns only the wallpaper).
- GUI tools share one lock: the SDK runs sync tools in worker threads, parallel calls must not interleave.
- pbcopy/pbpaste run with `LANG=en_US.UTF-8`, else Cyrillic is mangled when the server has no LANG.
- Nothing may print to stdout in the server: stdout is the MCP protocol channel.

## Coding rules
- Early returns, `Result` types instead of raising in `core.py`.
- New tool = core function + test with `FakeClient` + `@mcp.tool()` wrapper + README row.
- Never modify existing tests to make them pass.

## Secrets
`~/.telegram-mcp/` (config.env, session.txt) is outside the repo, chmod 600. The session string
equals full account access. `.gitignore` also blocks `*.session`, `*.env`.

## Risks / limits
- Telegram FloodWait on bulk actions; errors are returned to Claude as `FloodWaitError: ...`.
- `talk_to_bot` returns after 2 quiet polls (timeout capped at 60s); slow bots may need a
  follow-up `read_messages(min_id=...)`.
- Incoming messages are untrusted input for Claude (prompt injection) — destructive tools rely on
  Claude Code's permission prompts.
- GUI mode controls the real mouse/keyboard — the user must not use the computer meanwhile;
  mouse into a screen corner aborts (pyautogui FAILSAFE). Screenshots can contain private data from
  other windows and go to Claude.
- GUI mode is macOS only (pbcopy, `open -a`, ApplicationServices).
- BotFather wording changes could break `create_bot` step checks (it checks for "new bot"/"username").

## Status
- Done: 23 tools, login flow, 49 tests, Critic/Security review fixes, registered in Claude Code (user scope).
- Published: https://github.com/resccrew/telegram-mcp (public, MIT).
- GUI mode (branch `feat/gui-pyautogui`): 8 tools, 19 tests (68 total green). Real screenshot works
  (Screen Recording granted to Ghostty). Accessibility NOT yet granted → clicks return an error.
- Next: grant Accessibility, register `telegram-gui` (see README), live test in Telegram;
  real-account smoke test of the API server after `telegram-mcp-login`.

## Agents
Planner, Architect, Implementer, Tester, Critic, Security, Analyst, Documenter (see ~/.claude/CLAUDE.md).
