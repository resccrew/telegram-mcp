import json

import pytest

from telegram_mcp import core, server
from telegram_mcp.config import load_config, read_env_file, write_env_file, write_session
from telegram_mcp.result import Err, Ok

from .fakes import FakeClient


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_MCP_HOME", str(tmp_path))
    for key in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION"):
        monkeypatch.delenv(key, raising=False)
    return tmp_path


def test_missing_credentials_is_err():
    result = load_config()
    assert isinstance(result, Err) and "my.telegram.org" in result.error


def test_credentials_from_file(isolated_home):
    write_env_file(isolated_home / "config.env", {"TELEGRAM_API_ID": "123", "TELEGRAM_API_HASH": "abc"})
    assert (isolated_home / "config.env").stat().st_mode & 0o777 == 0o600
    result = load_config()
    assert isinstance(result, Ok)
    assert result.value.api_id == 123 and result.value.session_path == isolated_home / "session.txt"


def test_env_overrides_file_and_validates(isolated_home, monkeypatch):
    write_env_file(isolated_home / "config.env", {"TELEGRAM_API_ID": "123", "TELEGRAM_API_HASH": "abc"})
    monkeypatch.setenv("TELEGRAM_API_ID", "not-a-number")
    result = load_config()
    assert isinstance(result, Err) and "must be a number" in result.error


def test_read_env_file_ignores_comments(tmp_path):
    path = tmp_path / "x.env"
    path.write_text('# comment\nA="1"\n\nB = two\ngarbage\n')
    assert read_env_file(path) == {"A": "1", "B": "two"}


async def test_all_tools_registered():
    names = {tool.name for tool in await server.mcp.list_tools()}
    expected = {
        "get_me", "list_chats", "chat_info", "get_participants", "read_messages", "search_messages",
        "send_message", "edit_message", "delete_messages", "forward_messages", "mark_read", "pin_message",
        "click_button", "send_file", "download_media", "create_channel", "create_group", "invite_users",
        "join_chat", "leave_chat", "talk_to_bot", "create_bot", "bot_api",
    }  # fmt: skip
    assert expected <= names


async def test_tool_reports_missing_login_as_error():
    response = await server.list_chats()
    assert response["ok"] is False and "my.telegram.org" in response["error"]


async def test_tool_success_and_exception_paths(monkeypatch):
    fake = FakeClient()

    async def get():
        return Ok(fake)

    monkeypatch.setattr(server.clients, "get", get)
    response = await server.send_message("alice", "hi")
    assert response["ok"] is True and response["result"]["text"] == "hi"
    assert json.dumps(response)  # tool output must be JSON-serializable

    async def boom(client, *args):
        raise RuntimeError("FloodWait 30s")

    monkeypatch.setattr(core, "mark_read", boom)
    response = await server.mark_read("alice")
    assert response == {"ok": False, "error": "RuntimeError: FloodWait 30s"}


async def test_call_tool_through_mcp(monkeypatch):
    fake = FakeClient()

    async def get():
        return Ok(fake)

    monkeypatch.setattr(server.clients, "get", get)
    result = await server.mcp.call_tool("list_chats", {"limit": 2})
    text = json.dumps(result, default=lambda o: getattr(o, "model_dump", lambda: str(o))())
    assert "Alice" in text and "Crypto News" in text


async def test_unauthorized_session(monkeypatch, isolated_home):
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "h")

    class Unauthorized:
        def __init__(self, *args):
            self.disconnected = False

        async def connect(self):
            pass

        async def is_user_authorized(self):
            return False

        async def disconnect(self):
            self.disconnected = True

    monkeypatch.setattr(server, "TelegramClient", Unauthorized)
    monkeypatch.setattr(server, "StringSession", lambda s: s)
    assert "No Telegram session" in (await server.ClientManager().get()).error
    write_session(isolated_home / "session.txt", "1AbCdEf")
    assert (isolated_home / "session.txt").stat().st_mode & 0o777 == 0o600
    result = await server.ClientManager().get()
    assert isinstance(result, Err) and "telegram-mcp-login" in result.error


def test_secret_files_created_private(isolated_home):
    target = isolated_home / "fresh" / "session.txt"
    write_session(target, "abc")
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.parent.stat().st_mode & 0o777 == 0o700
    loose = isolated_home / "loose.env"
    loose.write_text("x")
    loose.chmod(0o644)
    write_env_file(loose, {"A": "1"})
    assert loose.stat().st_mode & 0o777 == 0o600


async def test_connection_errors_become_tool_errors(monkeypatch):
    async def broken():
        raise ConnectionError("network down")

    monkeypatch.setattr(server.clients, "get", broken)
    assert await server.get_me() == {"ok": False, "error": "ConnectionError: network down"}


async def test_dropped_client_is_disconnected_before_reconnect(monkeypatch):
    class Dropped:
        disconnected = False

        def is_connected(self):
            return False

        async def disconnect(self):
            self.disconnected = True

    manager = server.ClientManager()
    old = Dropped()
    manager._client = old
    result = await manager.get()  # no credentials in the isolated home -> Err, but old client must be closed
    assert isinstance(result, Err) and old.disconnected and manager._client is None
