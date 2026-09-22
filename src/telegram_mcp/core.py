"""Telegram operations used by the MCP tools.

Every function takes a connected Telethon client as its first argument and returns a
Result, so the server layer never has to guess what an exception means. Keeping the
client a parameter also lets tests drive this module with a fake client.
"""

import asyncio
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from telethon import functions, utils

from .config import home_dir
from .result import Err, Ok, Result

BOTFATHER = "BotFather"
BOT_TOKEN_RE = re.compile(r"(?<![\w-])\d{6,12}:[A-Za-z0-9_-]{35}(?![\w-])")
BOT_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,28}bot$", re.IGNORECASE)
INVITE_RE = re.compile(r"(?:t\.me/(?:\+|joinchat/)|^\+(?=\d*[A-Za-z_-]))([A-Za-z0-9_-]+)")
BOT_API_METHOD_RE = re.compile(r"^[A-Za-z]+$")
MAX_TEXT = 4096
POLL_INTERVAL = 0.7
QUIET_POLLS = 2  # consecutive polls without new replies before talk_to_bot returns
MAX_TALK_TIMEOUT = 60.0
SENSITIVE_SUFFIXES = (".env", ".session", ".pem", ".key")


# ---------------------------------------------------------------- serialization


def entity_to_dict(entity: Any) -> dict[str, Any]:
    kind = type(entity).__name__.lower()
    data: dict[str, Any] = {
        "id": utils.get_peer_id(entity),
        "name": utils.get_display_name(entity),
        "type": kind,
    }
    if username := getattr(entity, "username", None):
        data["username"] = username
    if getattr(entity, "bot", False):
        data["type"] = "bot"
    elif kind == "channel":
        data["type"] = "group" if getattr(entity, "megagroup", False) else "channel"
    elif kind == "chat":
        data["type"] = "group"
    return data


def buttons_to_rows(message: Any) -> list[list[str]]:
    rows = getattr(message, "buttons", None) or []
    return [[getattr(button, "text", "") for button in row] for row in rows]


def message_to_dict(message: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": message.id,
        "date": message.date.isoformat() if getattr(message, "date", None) else None,
        "out": bool(getattr(message, "out", False)),
        "sender_id": getattr(message, "sender_id", None),
        "text": getattr(message, "message", "") or "",
    }
    sender = getattr(message, "sender", None)
    if sender is not None:
        data["sender"] = utils.get_display_name(sender)
    reply = getattr(message, "reply_to", None)
    if reply is not None and getattr(reply, "reply_to_msg_id", None):
        data["reply_to"] = reply.reply_to_msg_id
    media = getattr(message, "media", None)
    if media is not None:
        data["media"] = type(media).__name__.removeprefix("MessageMedia").lower()
        file = getattr(message, "file", None)
        if file is not None and getattr(file, "name", None):
            data["file_name"] = file.name
    if buttons := buttons_to_rows(message):
        data["buttons"] = buttons
    if (views := getattr(message, "views", None)) is not None:
        data["views"] = views
    return data


# ---------------------------------------------------------------- resolving chats


def _parse_ref(ref: str) -> str | int:
    return int(ref) if re.fullmatch(r"-?\d+", ref) else ref


async def resolve_chat(client: Any, chat: str | int) -> Result[Any]:
    """Find a chat by @username, t.me link, phone, numeric id, 'me', or dialog title."""
    ref = str(chat).strip()
    if not ref:
        return Err("chat must not be empty")

    key = _parse_ref(ref)
    try:
        return Ok(await client.get_entity(key))
    except Exception as exc:  # Telethon raises ValueError/RPCError variants; fall back to dialogs
        lookup_error = exc

    wanted = ref.lower().lstrip("@")
    exact, partial = [], []
    async for dialog in client.iter_dialogs():
        name = (dialog.name or "").lower()
        if dialog.id == key or name == wanted:
            exact.append(dialog.entity)
        elif wanted in name:
            partial.append(dialog)

    if exact:
        return Ok(exact[0])
    if len(partial) == 1:
        return Ok(partial[0].entity)
    if partial:
        names = ", ".join(f"{d.name} (id {d.id})" for d in partial[:10])
        return Err(f"'{ref}' is ambiguous, matches: {names}. Pass the id instead.")
    return Err(f"Chat '{ref}' not found ({lookup_error})")


# ---------------------------------------------------------------- account & chats


async def get_me(client: Any) -> Result[dict[str, Any]]:
    me = await client.get_me()
    if me is None:
        return Err("Not logged in. Run `telegram-mcp-login`.")
    data = entity_to_dict(me)
    data["phone"] = getattr(me, "phone", None)
    return Ok(data)


async def list_chats(
    client: Any, limit: int = 50, query: str | None = None, archived: bool = False, unread_only: bool = False
) -> Result[list[dict[str, Any]]]:
    wanted = (query or "").lower()
    chats = []
    async for dialog in client.iter_dialogs(archived=archived):
        if wanted and wanted not in (dialog.name or "").lower():
            continue
        if unread_only and not dialog.unread_count:
            continue
        item = entity_to_dict(dialog.entity)
        item["unread"] = dialog.unread_count
        if dialog.message is not None:
            item["last_message"] = (getattr(dialog.message, "message", "") or "")[:200]
            item["last_date"] = dialog.message.date.isoformat() if dialog.message.date else None
        chats.append(item)
        if len(chats) >= limit:
            break
    return Ok(chats)


async def chat_info(client: Any, chat: str) -> Result[dict[str, Any]]:
    resolved = await resolve_chat(client, chat)
    if isinstance(resolved, Err):
        return resolved
    entity = resolved.value
    data = entity_to_dict(entity)
    for field in ("participants_count", "verified", "scam", "phone", "first_name", "last_name"):
        if (value := getattr(entity, field, None)) is not None:
            data[field] = value
    return Ok(data)


async def get_participants(client: Any, chat: str, limit: int = 100, search: str = "") -> Result[list[dict[str, Any]]]:
    resolved = await resolve_chat(client, chat)
    if isinstance(resolved, Err):
        return resolved
    users = await client.get_participants(resolved.value, limit=limit, search=search)
    return Ok([entity_to_dict(user) for user in users])


# ---------------------------------------------------------------- messages


async def read_messages(
    client: Any,
    chat: str,
    limit: int = 20,
    offset_id: int = 0,
    min_id: int = 0,
    search: str | None = None,
) -> Result[list[dict[str, Any]]]:
    resolved = await resolve_chat(client, chat)
    if isinstance(resolved, Err):
        return resolved
    messages = await client.get_messages(
        resolved.value, limit=limit, offset_id=offset_id, min_id=min_id, search=search or None
    )
    return Ok([message_to_dict(m) for m in messages])


async def search_global(client: Any, query: str, limit: int = 20) -> Result[list[dict[str, Any]]]:
    if not query.strip():
        return Err("query must not be empty")
    results = []
    async for message in client.iter_messages(None, search=query, limit=limit):
        item = message_to_dict(message)
        item["chat_id"] = getattr(message, "chat_id", None)
        results.append(item)
    return Ok(results)


async def send_message(
    client: Any,
    chat: str,
    text: str,
    reply_to: int | None = None,
    parse_mode: str | None = "md",
    silent: bool = False,
    link_preview: bool = True,
) -> Result[dict[str, Any]]:
    if not text.strip():
        return Err("text must not be empty")
    if len(text) > MAX_TEXT:
        return Err(f"text is {len(text)} chars; Telegram limit is {MAX_TEXT}. Split it into several messages.")
    resolved = await resolve_chat(client, chat)
    if isinstance(resolved, Err):
        return resolved
    sent = await client.send_message(
        resolved.value, text, reply_to=reply_to, parse_mode=parse_mode, silent=silent, link_preview=link_preview
    )
    return Ok(message_to_dict(sent))


async def edit_message(
    client: Any, chat: str, message_id: int, text: str, parse_mode: str | None = "md"
) -> Result[dict[str, Any]]:
    if not text.strip():
        return Err("text must not be empty")
    resolved = await resolve_chat(client, chat)
    if isinstance(resolved, Err):
        return resolved
    edited = await client.edit_message(resolved.value, message_id, text, parse_mode=parse_mode)
    return Ok(message_to_dict(edited))


async def delete_messages(client: Any, chat: str, message_ids: list[int], revoke: bool = True) -> Result[int]:
    if not message_ids:
        return Err("message_ids must not be empty")
    resolved = await resolve_chat(client, chat)
    if isinstance(resolved, Err):
        return resolved
    affected = await client.delete_messages(resolved.value, message_ids, revoke=revoke)
    return Ok(sum(getattr(item, "pts_count", 0) for item in affected or []) or len(message_ids))


async def forward_messages(
    client: Any, from_chat: str, message_ids: list[int], to_chat: str
) -> Result[list[dict[str, Any]]]:
    if not message_ids:
        return Err("message_ids must not be empty")
    source = await resolve_chat(client, from_chat)
    if isinstance(source, Err):
        return source
    target = await resolve_chat(client, to_chat)
    if isinstance(target, Err):
        return target
    forwarded = await client.forward_messages(target.value, message_ids, source.value)
    if not isinstance(forwarded, list):
        forwarded = [forwarded]
    return Ok([message_to_dict(m) for m in forwarded if m is not None])


async def mark_read(client: Any, chat: str) -> Result[bool]:
    resolved = await resolve_chat(client, chat)
    if isinstance(resolved, Err):
        return resolved
    await client.send_read_acknowledge(resolved.value)
    return Ok(True)


async def pin_message(client: Any, chat: str, message_id: int, notify: bool = False) -> Result[bool]:
    resolved = await resolve_chat(client, chat)
    if isinstance(resolved, Err):
        return resolved
    await client.pin_message(resolved.value, message_id, notify=notify)
    return Ok(True)


async def _get_message(client: Any, entity: Any, message_id: int) -> Result[Any]:
    message = await client.get_messages(entity, ids=message_id)
    if message is None:
        return Err(f"Message {message_id} not found")
    return Ok(message)


async def click_button(
    client: Any,
    chat: str,
    message_id: int,
    text: str | None = None,
    row: int | None = None,
    column: int | None = None,
) -> Result[dict[str, Any]]:
    """Press an inline/reply keyboard button by its text or its (row, column) position."""
    if text is None and row is None:
        return Err("Pass either the button text or its row (and optional column)")
    resolved = await resolve_chat(client, chat)
    if isinstance(resolved, Err):
        return resolved
    found = await _get_message(client, resolved.value, message_id)
    if isinstance(found, Err):
        return found
    message = found.value
    rows = buttons_to_rows(message)
    if not rows:
        return Err(f"Message {message_id} has no buttons")

    if text is not None:
        if not any(text in label for r in rows for label in r):
            return Err(f"No button containing '{text}'. Buttons: {rows}")
        answer = await message.click(text=lambda label: text in label)
    else:
        col = column or 0
        if row >= len(rows) or col >= len(rows[row]):
            return Err(f"No button at row {row}, column {col}. Buttons: {rows}")
        answer = await message.click(row, col)

    result: dict[str, Any] = {"clicked": True}
    if isinstance(answer, str):  # URL buttons return the link instead of pressing anything
        result["url"] = answer
    elif type(answer).__name__ == "BotCallbackAnswer":
        if answer.message:
            result["answer"] = answer.message
        if answer.url:
            result["url"] = answer.url
    elif answer is not None and hasattr(answer, "id"):  # reply-keyboard buttons send the label as a message
        result["sent_message"] = message_to_dict(answer)
    return Ok(result)


# ---------------------------------------------------------------- files


def check_upload_path(path: str) -> Result[Path]:
    """Refuse files that could leak credentials (session, keys, dotfiles) to a chat."""
    file = Path(path).expanduser().resolve()
    if not file.is_file():
        return Err(f"File not found: {file}")
    protected = [home_dir().expanduser().resolve(), (Path.home() / ".ssh").resolve()]
    if any(file.is_relative_to(root) for root in protected):
        return Err(f"Refusing to send {file}: it is in a protected credentials directory")
    if any(part.startswith(".") for part in file.parts) or file.name.lower().endswith(SENSITIVE_SUFFIXES):
        return Err(f"Refusing to send {file}: hidden or credential-like files are blocked")
    return Ok(file)


async def send_file(
    client: Any, chat: str, path: str, caption: str = "", force_document: bool = False
) -> Result[dict[str, Any]]:
    checked = check_upload_path(path)
    if isinstance(checked, Err):
        return checked
    file = checked.value
    resolved = await resolve_chat(client, chat)
    if isinstance(resolved, Err):
        return resolved
    sent = await client.send_file(resolved.value, str(file), caption=caption or None, force_document=force_document)
    return Ok(message_to_dict(sent))


async def download_media(client: Any, chat: str, message_id: int, directory: str = "~/Downloads") -> Result[str]:
    resolved = await resolve_chat(client, chat)
    if isinstance(resolved, Err):
        return resolved
    found = await _get_message(client, resolved.value, message_id)
    if isinstance(found, Err):
        return found
    if getattr(found.value, "media", None) is None:
        return Err(f"Message {message_id} has no media")
    target = Path(directory).expanduser()
    target.mkdir(parents=True, exist_ok=True)
    saved = await client.download_media(found.value, file=str(target))
    if not saved:
        return Err("Download failed")
    return Ok(str(saved))


# ---------------------------------------------------------------- groups & channels


def _first_chat(updates: Any) -> Any:
    updates = getattr(updates, "updates", updates)  # CreateChatRequest wraps updates in InvitedUsers
    chats = getattr(updates, "chats", None) or []
    return chats[0] if chats else None


async def create_channel(
    client: Any, title: str, about: str = "", megagroup: bool = False, username: str | None = None
) -> Result[dict[str, Any]]:
    """Create a broadcast channel (or a supergroup when megagroup=True)."""
    if not title.strip():
        return Err("title must not be empty")
    updates = await client(functions.channels.CreateChannelRequest(title=title, about=about, megagroup=megagroup))
    channel = _first_chat(updates)
    if channel is None:
        return Err("Telegram did not return the created channel")
    data = entity_to_dict(channel)
    if username:
        await client(functions.channels.UpdateUsernameRequest(channel=channel, username=username.lstrip("@")))
        data["username"] = username.lstrip("@")
    return Ok(data)


async def create_group(client: Any, title: str, users: list[str]) -> Result[dict[str, Any]]:
    if not title.strip():
        return Err("title must not be empty")
    if not users:
        return Err("A basic group needs at least one other user; use create_channel(megagroup=True) otherwise")
    entities = []
    for user in users:
        resolved = await resolve_chat(client, user)
        if isinstance(resolved, Err):
            return resolved
        entities.append(resolved.value)
    updates = await client(functions.messages.CreateChatRequest(users=entities, title=title))
    chat = _first_chat(updates)
    if chat is None:
        return Err("Telegram did not return the created group")
    return Ok(entity_to_dict(chat))


async def invite_users(client: Any, chat: str, users: list[str]) -> Result[int]:
    resolved = await resolve_chat(client, chat)
    if isinstance(resolved, Err):
        return resolved
    entities = []
    for user in users:
        found = await resolve_chat(client, user)
        if isinstance(found, Err):
            return found
        entities.append(found.value)
    if type(resolved.value).__name__ == "Channel":
        await client(functions.channels.InviteToChannelRequest(channel=resolved.value, users=entities))
    else:
        for entity in entities:
            await client(functions.messages.AddChatUserRequest(chat_id=resolved.value.id, user_id=entity, fwd_limit=50))
    return Ok(len(entities))


async def join_chat(client: Any, target: str) -> Result[dict[str, Any]]:
    """Join by @username / public link, or by private invite link (t.me/+HASH)."""
    ref = target.strip()
    if match := INVITE_RE.search(ref):
        updates = await client(functions.messages.ImportChatInviteRequest(hash=match.group(1)))
        chat = _first_chat(updates)
        if chat is None:
            return Err("Joined, but Telegram did not return the chat")
        return Ok(entity_to_dict(chat))
    resolved = await resolve_chat(client, ref)
    if isinstance(resolved, Err):
        return resolved
    await client(functions.channels.JoinChannelRequest(channel=resolved.value))
    return Ok(entity_to_dict(resolved.value))


async def leave_chat(client: Any, chat: str) -> Result[bool]:
    resolved = await resolve_chat(client, chat)
    if isinstance(resolved, Err):
        return resolved
    await client.delete_dialog(resolved.value)
    return Ok(True)


# ---------------------------------------------------------------- bots


async def talk_to_bot(
    client: Any, bot: str, text: str, timeout: float = 15.0
) -> Result[list[dict[str, Any]]]:
    """Send a message and wait for the replies that come back (for bots or any chat)."""
    resolved = await resolve_chat(client, bot)
    if isinstance(resolved, Err):
        return resolved
    entity = resolved.value
    sent = await client.send_message(entity, text)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + min(timeout, MAX_TALK_TIMEOUT)
    replies: list[Any] = []
    quiet = 0
    while loop.time() < deadline:
        await asyncio.sleep(POLL_INTERVAL)
        fresh = await client.get_messages(entity, min_id=sent.id, limit=20)
        incoming = [m for m in fresh if not getattr(m, "out", False)]
        if not incoming:
            continue
        if len(incoming) > len(replies):
            replies, quiet = incoming, 0
            continue
        quiet += 1
        if quiet >= QUIET_POLLS:
            break  # the bot has stopped answering
    if not replies:
        return Err(f"No reply from {bot} within {timeout:.0f}s")
    return Ok([message_to_dict(m) for m in sorted(replies, key=lambda m: m.id)])


def _joined_text(replies: list[dict[str, Any]]) -> str:
    return "\n".join(r["text"] for r in replies)


async def create_bot(client: Any, name: str, username: str, timeout: float = 15.0) -> Result[dict[str, Any]]:
    """Create a bot through @BotFather and return its token."""
    username = username.lstrip("@")
    if not name.strip():
        return Err("name must not be empty")
    if not (5 <= len(username) <= 32 and BOT_USERNAME_RE.match(username)):
        return Err("username must be 5-32 chars (letters, digits, _), start with a letter and end with 'bot'")

    await talk_to_bot(client, BOTFATHER, "/cancel", timeout=5)
    steps = [("/newbot", "new bot"), (name, "username")]
    for text, expected in steps:
        reply = await talk_to_bot(client, BOTFATHER, text, timeout=timeout)
        if isinstance(reply, Err):
            return reply
        answer = _joined_text(reply.value)
        if expected not in answer.lower():
            return Err(f"Unexpected BotFather reply: {answer}")

    reply = await talk_to_bot(client, BOTFATHER, username, timeout=timeout)
    if isinstance(reply, Err):
        return reply
    answer = _joined_text(reply.value)
    token = BOT_TOKEN_RE.search(answer)
    if token is None:
        return Err(f"BotFather did not issue a token: {answer}")
    return Ok({"name": name, "username": username, "token": token.group(0), "link": f"https://t.me/{username}"})


def _bot_api_request(token: str, method: str, params: dict[str, Any], timeout: float) -> Result[Any]:
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(params).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        return Err(f"Bot API unreachable: {exc}")
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return Err(f"Bot API returned a non-JSON response: {raw[:200]!r}")
    if not body.get("ok"):
        return Err(f"Bot API error: {body.get('description', body)}")
    return Ok(body.get("result"))


async def bot_api(token: str, method: str, params: dict[str, Any] | None = None, timeout: float = 30.0) -> Result[Any]:
    """Call any Bot API method (sendMessage, setMyCommands, setWebhook, ...) as a bot."""
    if not BOT_TOKEN_RE.fullmatch(token):
        return Err("token does not look like a bot token (123456:ABC...)")
    if not BOT_API_METHOD_RE.match(method):
        return Err(f"Invalid Bot API method name: {method!r}")
    return await asyncio.to_thread(_bot_api_request, token, method, params or {}, timeout)
