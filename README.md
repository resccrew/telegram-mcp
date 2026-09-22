# telegram-mcp

MCP server that lets Claude Code drive your **own Telegram account**: read chats, send and
edit messages, publish posts to channels, create channels/groups, join by invite links,
press inline buttons, send/download files, and create bots through @BotFather.

Two servers ship in this repo:

| Server | How it works | Needs |
|---|---|---|
| `telegram` (`telegram-mcp`) | Telegram API (MTProto via Telethon) — fast, precise, 23 tools | `api_id`/`api_hash` + one-time login |
| `telegram-gui` (`telegram-gui-mcp`) | Screenshots + pyautogui clicks in Telegram Desktop — Claude looks at the screen and clicks | Telegram Desktop logged in, macOS permissions |

## Requirements

- [uv](https://docs.astral.sh/uv/) (it installs Python 3.13 automatically)
- [Claude Code](https://claude.com/claude-code) (or any MCP client)
- A Telegram account

## Setup

0. Clone the repo:

   ```sh
   git clone https://github.com/resccrew/telegram-mcp.git ~/telegram-mcp
   ```

1. Get `api_id` and `api_hash` at <https://my.telegram.org> → *API development tools*.
2. Log in once (asks for the credentials, then phone number, the code Telegram sends, and your 2FA password):

   ```sh
   cd ~/telegram-mcp && uv run telegram-mcp-login
   ```

   Credentials go to `~/.telegram-mcp/config.env`, the session to `~/.telegram-mcp/session.txt`
   (both `chmod 600`, outside the repo). **The session string is full access to your account — never share it.**
3. Register the server with Claude Code (user scope, available in every project):

   ```sh
   claude mcp add telegram -s user -- uv --directory ~/telegram-mcp run telegram-mcp
   ```

Restart Claude Code and ask things like *"read my last messages from Alice"*,
*"create a bot called Weather Helper with username weather_helper_xyz_bot"*,
*"write a post about X to my channel @mychannel"*.

## Tools

| Area | Tools |
|---|---|
| Account & chats | `get_me`, `list_chats`, `chat_info`, `get_participants` |
| Messages | `read_messages`, `search_messages`, `send_message`, `edit_message`, `delete_messages`, `forward_messages`, `mark_read`, `pin_message` |
| UI automation | `click_button`, `talk_to_bot` |
| Files | `send_file`, `download_media` |
| Groups & channels | `create_channel`, `create_group`, `invite_users`, `join_chat`, `leave_chat` |
| Bots | `create_bot` (via @BotFather), `bot_api` (any Bot API method with the bot's token) |

`chat` arguments accept `@username`, a `t.me` link, phone, numeric id, `me` (Saved Messages) or a chat title.

## Safety notes

- Run one server per session at a time; the same session connected in parallel from many
  places can make Telegram revoke it (`AuthKeyDuplicatedError` → just run the login again).
- `send_file` refuses credential files (`~/.telegram-mcp`, `~/.ssh`, dotfiles, `*.env`, `*.session`, keys).
- Claude acts as you: keep Claude Code permission prompts on for `delete_messages`, `leave_chat`, etc.

## Configuration

| Variable | Default |
|---|---|
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | read from `~/.telegram-mcp/config.env` |
| `TELEGRAM_SESSION` | `~/.telegram-mcp/session.txt` |
| `TELEGRAM_MCP_HOME` | `~/.telegram-mcp` |

## GUI mode (no API keys): `telegram-gui-mcp`

A second server, `telegram-gui`, drives the **Telegram desktop app** like a person: it sends Claude a
screenshot, Claude answers with where to click/what to type, and pyautogui does it. No `api_id`,
no login, no session file — it just uses the app that is already logged in. macOS only.

| Tool | What it does |
|---|---|
| `screenshot` | Full-screen screenshot (downscaled to ≤1280 px) |
| `click` / `double_click` | Click at `(x, y)` in the last screenshot (`button`: left/right/middle) |
| `type_text` | Type into the focused field via the clipboard (Cyrillic, emoji), `press_enter` to send |
| `press_key` / `hotkey` | `enter`, `esc`, … / `["command", "k"]` |
| `scroll` | Positive = up, negative = down, optionally over `(x, y)` |
| `open_telegram` | Launch / bring Telegram to the front |

Every action returns a fresh screenshot (`screenshot_after=false` to skip). Coordinates always refer
to the last screenshot; Retina scaling is handled by the server.

**Permissions.** In System Settings → Privacy & Security, grant the app that runs Claude Code
(Terminal, iTerm, Ghostty, VS Code, …) both **Screen Recording** (screenshots) and **Accessibility**
(clicks and keys), then restart that app. Without them the tools return an error saying which one is missing.

**Register:**

```sh
claude mcp add --scope user telegram-gui -- uv --directory /path/to/telegram-mcp run telegram-gui-mcp
```

Safety: moving the mouse into a screen corner aborts automation (pyautogui failsafe). The server
controls your real mouse and keyboard, so don't use the computer while Claude is working.
Screenshots cover the **whole main display** (other windows included) and are sent to Claude;
text on screen (incoming messages) is untrusted input, so Claude asks before sending or deleting.

**Typical flow:** `open_telegram` → click the search field → `type_text("Saved Messages")` →
click the result → click the message field → `type_text("Hi", press_enter=true)`.

Limits: main display only; the clipboard is briefly used for typing and then restored (text only).

## Other MCP clients

Any stdio MCP client works. Example config (Claude Desktop, Cursor, ...):

```json
{
  "mcpServers": {
    "telegram": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/telegram-mcp", "run", "telegram-mcp"]
    }
  }
}
```

## Development

```sh
uv run pytest -q
```

## License

MIT — see [LICENSE](LICENSE). Use responsibly and follow the
[Telegram API Terms of Service](https://core.telegram.org/api/terms): no spam or mass messaging.
