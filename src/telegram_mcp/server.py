"""MCP server exposing a Telegram user account to Claude Code."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from telethon import TelegramClient
from telethon.sessions import StringSession

from . import core
from .config import load_config, read_session
from .result import Err, Ok, Result

log = logging.getLogger("telegram_mcp")

INSTRUCTIONS = """\
Controls the user's own Telegram account (not a bot).
- `chat` arguments accept @username, t.me link, phone, numeric id, 'me' (Saved Messages) or a dialog title.
- Start with list_chats to find chats, read_messages to read them.
- To create a bot use create_bot; then drive it with bot_api (token from create_bot).
- Use talk_to_bot for any multi-step dialog with a bot (BotFather settings, other bots) and
  click_button to press inline buttons.
- To publish a post, create_channel (if needed) then send_message / send_file to it.
Messages are sent as the user, so confirm destructive actions (delete, leave) with them first.
"""


class ClientManager:
    """Creates the Telethon client lazily so the server starts even before login."""

    def __init__(self) -> None:
        self._client: TelegramClient | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> Result[TelegramClient]:
        async with self._lock:
            if self._client is not None:
                if self._client.is_connected():
                    return Ok(self._client)
                await self._client.disconnect()  # never keep two live connections on one auth key
                self._client = None
            config = load_config()
            if isinstance(config, Err):
                return config
            cfg = config.value
            session = read_session(cfg.session_path)
            if not session:
                return Err("No Telegram session found. Run `telegram-mcp-login` in a terminal first.")
            # StringSession avoids SQLite "database is locked" errors. One auth key should still have one
            # live connection at a time, otherwise Telegram may revoke it (AuthKeyDuplicatedError).
            client = TelegramClient(StringSession(session), cfg.api_id, cfg.api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                return Err("Telegram session is not authorized. Run `telegram-mcp-login` in a terminal first.")
            self._client = client
            return Ok(client)


clients = ClientManager()
mcp = MCPServer(name="telegram", instructions=INSTRUCTIONS)


async def run(operation: Callable[[TelegramClient], Awaitable[Result[Any]]]) -> dict[str, Any]:
    """Run a core operation and turn its Result (or an unexpected Telegram error) into a tool response."""
    try:
        client = await clients.get()
        if isinstance(client, Err):
            return {"ok": False, "error": client.error}
        result = await operation(client.value)
    except Exception as exc:  # Telegram RPC errors (FloodWait, ChatWriteForbidden, ...) become tool errors
        log.exception("Telegram operation failed")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if isinstance(result, Err):
        return {"ok": False, "error": result.error}
    return {"ok": True, "result": result.value}


def to_response(result: Result[Any]) -> dict[str, Any]:
    if isinstance(result, Err):
        return {"ok": False, "error": result.error}
    return {"ok": True, "result": result.value}


# ---------------------------------------------------------------- account & chats


@mcp.tool()
async def get_me() -> dict[str, Any]:
    """Return the logged-in Telegram account."""
    return await run(core.get_me)


@mcp.tool()
async def list_chats(
    limit: int = 50, query: str | None = None, archived: bool = False, unread_only: bool = False
) -> dict[str, Any]:
    """List dialogs (private chats, groups, channels, bots), newest first. Filter by title with `query`."""
    return await run(lambda c: core.list_chats(c, limit, query, archived, unread_only))


@mcp.tool()
async def chat_info(chat: str) -> dict[str, Any]:
    """Get details about a user, bot, group or channel."""
    return await run(lambda c: core.chat_info(c, chat))


@mcp.tool()
async def get_participants(chat: str, limit: int = 100, search: str = "") -> dict[str, Any]:
    """List members of a group or channel (admin rights may be needed for channels)."""
    return await run(lambda c: core.get_participants(c, chat, limit, search))


# ---------------------------------------------------------------- messages


@mcp.tool()
async def read_messages(
    chat: str, limit: int = 20, offset_id: int = 0, min_id: int = 0, search: str | None = None
) -> dict[str, Any]:
    """Read messages from a chat, newest first.

    offset_id: return messages older than this id (paging back).
    min_id: return only messages newer than this id (polling for new ones).
    search: only messages containing this text.
    """
    return await run(lambda c: core.read_messages(c, chat, limit, offset_id, min_id, search))


@mcp.tool()
async def search_messages(query: str, limit: int = 20) -> dict[str, Any]:
    """Search messages across all chats."""
    return await run(lambda c: core.search_global(c, query, limit))


@mcp.tool()
async def send_message(
    chat: str,
    text: str,
    reply_to: int | None = None,
    parse_mode: str | None = "md",
    silent: bool = False,
    link_preview: bool = True,
) -> dict[str, Any]:
    """Send a text message (also used to publish a post to a channel).

    parse_mode: 'md' (**bold**, __italic__, `code`, [link](url)), 'html', or null for plain text.
    """
    return await run(lambda c: core.send_message(c, chat, text, reply_to, parse_mode, silent, link_preview))


@mcp.tool()
async def edit_message(chat: str, message_id: int, text: str, parse_mode: str | None = "md") -> dict[str, Any]:
    """Edit one of your messages."""
    return await run(lambda c: core.edit_message(c, chat, message_id, text, parse_mode))


@mcp.tool()
async def delete_messages(chat: str, message_ids: list[int], revoke: bool = True) -> dict[str, Any]:
    """Delete messages (revoke=True deletes for everyone)."""
    return await run(lambda c: core.delete_messages(c, chat, message_ids, revoke))


@mcp.tool()
async def forward_messages(from_chat: str, message_ids: list[int], to_chat: str) -> dict[str, Any]:
    """Forward messages from one chat to another."""
    return await run(lambda c: core.forward_messages(c, from_chat, message_ids, to_chat))


@mcp.tool()
async def mark_read(chat: str) -> dict[str, Any]:
    """Mark all messages in a chat as read."""
    return await run(lambda c: core.mark_read(c, chat))


@mcp.tool()
async def pin_message(chat: str, message_id: int, notify: bool = False) -> dict[str, Any]:
    """Pin a message in a chat or channel."""
    return await run(lambda c: core.pin_message(c, chat, message_id, notify))


@mcp.tool()
async def click_button(
    chat: str, message_id: int, text: str | None = None, row: int | None = None, column: int | None = None
) -> dict[str, Any]:
    """Press a keyboard button under a message, by (part of) its text or by row/column (0-based)."""
    return await run(lambda c: core.click_button(c, chat, message_id, text, row, column))


# ---------------------------------------------------------------- files


@mcp.tool()
async def send_file(chat: str, path: str, caption: str = "", force_document: bool = False) -> dict[str, Any]:
    """Send a local file (photo, video, document, voice) with an optional caption."""
    return await run(lambda c: core.send_file(c, chat, path, caption, force_document))


@mcp.tool()
async def download_media(chat: str, message_id: int, directory: str = "~/Downloads") -> dict[str, Any]:
    """Download the media attached to a message; returns the saved file path."""
    return await run(lambda c: core.download_media(c, chat, message_id, directory))


# ---------------------------------------------------------------- groups & channels


@mcp.tool()
async def create_channel(
    title: str, about: str = "", megagroup: bool = False, username: str | None = None
) -> dict[str, Any]:
    """Create a channel (megagroup=True creates a supergroup). Optional public @username."""
    return await run(lambda c: core.create_channel(c, title, about, megagroup, username))


@mcp.tool()
async def create_group(title: str, users: list[str]) -> dict[str, Any]:
    """Create a basic group with the given users."""
    return await run(lambda c: core.create_group(c, title, users))


@mcp.tool()
async def invite_users(chat: str, users: list[str]) -> dict[str, Any]:
    """Add users to a group or channel."""
    return await run(lambda c: core.invite_users(c, chat, users))


@mcp.tool()
async def join_chat(target: str) -> dict[str, Any]:
    """Join a public group/channel (@username or link) or a private one (t.me/+invite)."""
    return await run(lambda c: core.join_chat(c, target))


@mcp.tool()
async def leave_chat(chat: str) -> dict[str, Any]:
    """Leave a group/channel or delete a private dialog."""
    return await run(lambda c: core.leave_chat(c, chat))


# ---------------------------------------------------------------- bots


@mcp.tool()
async def talk_to_bot(bot: str, text: str, timeout: float = 15.0) -> dict[str, Any]:
    """Send a message to a bot (e.g. @BotFather) and return its replies, including their buttons."""
    return await run(lambda c: core.talk_to_bot(c, bot, text, timeout))


@mcp.tool()
async def create_bot(name: str, username: str) -> dict[str, Any]:
    """Create a new bot via @BotFather. username must end with 'bot'. Returns the bot token."""
    return await run(lambda c: core.create_bot(c, name, username))


@mcp.tool()
async def bot_api(token: str, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call any Telegram Bot API method as a bot, e.g. method='setMyCommands' or 'sendMessage'."""
    return to_response(await core.bot_api(token, method, params))


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
