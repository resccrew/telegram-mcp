# telegram-mcp

MCP server that lets Claude Code drive your **own Telegram account**: read chats, send and
edit messages, publish posts to channels, create channels/groups, join by invite links,
press inline buttons, send/download files, and create bots through @BotFather.

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
