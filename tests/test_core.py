import pytest

from telegram_mcp import core
from telegram_mcp.result import Err, Ok

from .fakes import ALICE, BOTFATHER, NEWS, TOKEN, FakeButton, FakeClient


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch):
    monkeypatch.setattr(core, "POLL_INTERVAL", 0.01)


@pytest.fixture
def client():
    return FakeClient()


def ok(result):
    assert isinstance(result, Ok), result
    return result.value


def err(result):
    assert isinstance(result, Err), result
    return result.error


# ---------------------------------------------------------------- resolving


async def test_resolve_by_username_and_link(client):
    assert ok(await core.resolve_chat(client, "@alice")) is ALICE
    assert ok(await core.resolve_chat(client, "https://t.me/cryptonews")) is NEWS


async def test_resolve_falls_back_to_dialog_title(client):
    assert ok(await core.resolve_chat(client, "crypto news")) is NEWS
    assert ok(await core.resolve_chat(client, "crypto")) is NEWS


async def test_resolve_by_numeric_peer_id(client):
    assert ok(await core.resolve_chat(client, "-1000000000005")) is NEWS


async def test_resolve_ambiguous_and_missing(client):
    client.dialogs[2].name = "Alice bot"
    assert "ambiguous" in err(await core.resolve_chat(client, "ali"))
    assert "not found" in err(await core.resolve_chat(client, "nobody"))
    assert "empty" in err(await core.resolve_chat(client, "  "))


# ---------------------------------------------------------------- chats


async def test_get_me(client):
    me = ok(await core.get_me(client))
    assert me["username"] == "nick" and me["phone"] == "48000"


async def test_list_chats_types_and_filters(client):
    chats = ok(await core.list_chats(client))
    assert [c["type"] for c in chats] == ["user", "channel", "bot"]
    assert chats[0]["unread"] == 2 and chats[0]["last_message"] == "hi there"
    assert [c["name"] for c in ok(await core.list_chats(client, query="crypto"))] == ["Crypto News"]
    assert [c["name"] for c in ok(await core.list_chats(client, unread_only=True))] == ["Alice"]
    assert len(ok(await core.list_chats(client, limit=1))) == 1


async def test_chat_info_and_participants(client):
    info = ok(await core.chat_info(client, "alice"))
    assert info["first_name"] == "Alice" and info["type"] == "user"
    members = ok(await core.get_participants(client, "cryptonews"))
    assert {m["username"] for m in members} == {"nick", "alice"}


# ---------------------------------------------------------------- messages


async def test_send_and_read_messages(client):
    sent = ok(await core.send_message(client, "alice", "**hello**"))
    assert sent["out"] and sent["text"] == "**hello**"
    client.add_message(ALICE, "reply from alice", sender_id=2)
    messages = ok(await core.read_messages(client, "alice"))
    assert [m["text"] for m in messages] == ["reply from alice", "**hello**"]
    newer = ok(await core.read_messages(client, "alice", min_id=sent["id"]))
    assert [m["text"] for m in newer] == ["reply from alice"]
    found = ok(await core.read_messages(client, "alice", search="reply"))
    assert len(found) == 1


async def test_send_message_validation(client):
    assert "empty" in err(await core.send_message(client, "alice", "   "))
    assert "4096" in err(await core.send_message(client, "alice", "x" * 5000))
    assert "not found" in err(await core.send_message(client, "ghost", "hi"))


async def test_post_to_channel_passes_options(client):
    ok(await core.send_message(client, "Crypto News", "Post", parse_mode="html", silent=True))
    name, (entity, text), kwargs = client.calls[-1]
    assert entity is NEWS and kwargs["parse_mode"] == "html" and kwargs["silent"] is True


async def test_edit_delete_forward_read_pin(client):
    sent = ok(await core.send_message(client, "alice", "draft"))
    assert ok(await core.edit_message(client, "alice", sent["id"], "final"))["text"] == "final"
    assert ok(await core.delete_messages(client, "alice", [sent["id"]])) == 1
    assert "empty" in err(await core.delete_messages(client, "alice", []))
    forwarded = ok(await core.forward_messages(client, "alice", [sent["id"]], "cryptonews"))
    assert len(forwarded) == 1
    assert ok(await core.mark_read(client, "alice")) is True
    assert ok(await core.pin_message(client, "alice", sent["id"])) is True
    assert {"delete_messages", "read", "pin"} <= {c[0] for c in client.calls}


async def test_search_global(client):
    client.add_message(ALICE, "bitcoin to the moon")
    results = ok(await core.search_global(client, "bitcoin"))
    assert results[0]["text"] == "bitcoin to the moon"
    assert "empty" in err(await core.search_global(client, " "))


# ---------------------------------------------------------------- buttons


async def test_click_button_by_text_and_position(client):
    message = client.add_message(
        BOTFATHER, "Choose", buttons=[[FakeButton("Edit Name"), FakeButton("Edit About")], [FakeButton("Back")]]
    )
    assert ok(await core.click_button(client, "botfather", message.id, text="About"))["answer"] == "Done!"
    ok(await core.click_button(client, "botfather", message.id, row=1))
    assert message.clicked == ["Edit About", (1, 0)]


async def test_click_button_errors(client):
    plain = client.add_message(BOTFATHER, "no buttons")
    assert "no buttons" in err(await core.click_button(client, "botfather", plain.id, text="x"))
    keyboard = client.add_message(BOTFATHER, "k", buttons=[[FakeButton("A")]])
    assert "No button containing" in err(await core.click_button(client, "botfather", keyboard.id, text="Z"))
    assert "row 3" in err(await core.click_button(client, "botfather", keyboard.id, row=3))
    assert "either" in err(await core.click_button(client, "botfather", keyboard.id))
    assert "not found" in err(await core.click_button(client, "botfather", 9999, text="A"))


# ---------------------------------------------------------------- files


async def test_send_file(client, tmp_path):
    photo = tmp_path / "pic.jpg"
    photo.write_bytes(b"jpg")
    sent = ok(await core.send_file(client, "alice", str(photo), caption="look"))
    assert sent["media"] == "document" and sent["text"] == "look"
    assert "File not found" in err(await core.send_file(client, "alice", str(tmp_path / "nope.jpg")))


async def test_download_media(client, tmp_path):
    from telethon.tl import types

    with_media = client.add_message(ALICE, "", media=types.MessageMediaPhoto())
    without = client.add_message(ALICE, "text only")
    saved = ok(await core.download_media(client, "alice", with_media.id, str(tmp_path)))
    assert saved.endswith("photo.jpg")
    assert "no media" in err(await core.download_media(client, "alice", without.id, str(tmp_path)))


# ---------------------------------------------------------------- groups & channels


async def test_create_channel_and_supergroup(client):
    channel = ok(await core.create_channel(client, "My Channel", about="posts"))
    assert channel["type"] == "channel" and channel["name"] == "My Channel"
    group = ok(await core.create_channel(client, "Team", megagroup=True, username="@team_chat"))
    assert group["type"] == "group" and group["username"] == "team_chat"
    assert type(client.requests[-1]).__name__ == "UpdateUsernameRequest"
    assert "empty" in err(await core.create_channel(client, " "))


async def test_create_group(client):
    group = ok(await core.create_group(client, "Friends", ["alice"]))
    assert group["name"] == "Friends" and group["type"] == "group"
    assert "at least one" in err(await core.create_group(client, "Solo", []))
    assert "not found" in err(await core.create_group(client, "X", ["ghost"]))


async def test_invite_join_leave(client):
    assert ok(await core.invite_users(client, "cryptonews", ["alice"])) == 1
    assert type(client.requests[-1]).__name__ == "InviteToChannelRequest"
    assert ok(await core.join_chat(client, "https://t.me/+AbCdEf123"))["username"] == "cryptonews"
    assert client.requests[-1].hash == "AbCdEf123"
    ok(await core.join_chat(client, "@cryptonews"))
    assert type(client.requests[-1]).__name__ == "JoinChannelRequest"
    assert ok(await core.leave_chat(client, "cryptonews")) is True


# ---------------------------------------------------------------- bots


async def test_talk_to_bot_returns_replies(client):
    replies = ok(await core.talk_to_bot(client, "@BotFather", "/newbot"))
    assert "choose a name" in replies[0]["text"]


async def test_talk_to_bot_timeout(client):
    assert "No reply" in err(await core.talk_to_bot(client, "@BotFather", "silence", timeout=0.05))


async def test_create_bot_happy_path(client):
    bot = ok(await core.create_bot(client, "My Bot", "@my_test_bot"))
    assert bot == {"name": "My Bot", "username": "my_test_bot", "token": TOKEN, "link": "https://t.me/my_test_bot"}
    sent = [c[1][1] for c in client.calls if c[0] == "send_message"]
    assert sent == ["/cancel", "/newbot", "My Bot", "my_test_bot"]


async def test_create_bot_username_validation(client):
    assert "end with 'bot'" in err(await core.create_bot(client, "X", "notabot_name"))
    assert "end with 'bot'" in err(await core.create_bot(client, "X", "bot"))
    assert "empty" in err(await core.create_bot(client, " ", "good_bot"))


async def test_create_bot_username_taken():
    script = FakeClient().botfather_script | {"taken_bot": "Sorry, this username is already taken."}
    client = FakeClient(botfather_script=script)
    assert "already taken" in err(await core.create_bot(client, "My Bot", "taken_bot", timeout=0.2))


async def test_create_bot_unexpected_reply():
    script = FakeClient().botfather_script | {"/newbot": "Sorry, too many attempts. Please try again in 8 seconds."}
    client = FakeClient(botfather_script=script)
    assert "Unexpected BotFather reply" in err(await core.create_bot(client, "My Bot", "my_test_bot", timeout=0.2))


async def test_bot_api_validation():
    assert "bot token" in err(await core.bot_api("bad", "getMe"))
    assert "Invalid Bot API method" in err(await core.bot_api(TOKEN, "../getMe"))


async def test_bot_api_request(monkeypatch):
    captured = {}

    def fake_request(token, method, params, timeout):
        captured.update(token=token, method=method, params=params)
        return Ok({"id": 7123456789, "is_bot": True})

    monkeypatch.setattr(core, "_bot_api_request", fake_request)
    assert ok(await core.bot_api(TOKEN, "getMe"))["is_bot"] is True
    assert captured == {"token": TOKEN, "method": "getMe", "params": {}}


# ---------------------------------------------------------------- review fixes


async def test_click_url_and_reply_keyboard_buttons(client):
    url_button = client.add_message(BOTFATHER, "k", buttons=[[FakeButton("Open")]], click_result="https://example.com")
    assert ok(await core.click_button(client, "botfather", url_button.id, text="Open")) == {
        "clicked": True,
        "url": "https://example.com",
    }
    sent = client.add_message(BOTFATHER, "Yes", out=True)
    reply_button = client.add_message(BOTFATHER, "k", buttons=[[FakeButton("Yes")]], click_result=sent)
    result = ok(await core.click_button(client, "botfather", reply_button.id, text="Yes"))
    assert result["sent_message"]["text"] == "Yes" and "answer" not in result


@pytest.mark.parametrize(
    "path_factory",
    [
        lambda home, tmp: home / "session.txt",
        lambda home, tmp: tmp / ".hidden" / "secret.txt",
        lambda home, tmp: tmp / "prod.env",
        lambda home, tmp: tmp / "bot.session",
    ],
)
async def test_send_file_blocks_credentials(client, tmp_path, monkeypatch, path_factory):
    home = tmp_path / "tgmcp"
    monkeypatch.setenv("TELEGRAM_MCP_HOME", str(home))
    target = path_factory(home, tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("secret")
    assert "Refusing" in err(await core.send_file(client, "alice", str(target)))
    assert not [c for c in client.calls if c[0] == "send_file"]


async def test_join_chat_does_not_treat_phone_as_invite(client):
    assert core.INVITE_RE.search("+79991234567") is None
    assert core.INVITE_RE.search("+AbC123").group(1) == "AbC123"
    assert core.INVITE_RE.search("https://t.me/joinchat/XyZ").group(1) == "XyZ"


def test_bot_token_regex_is_strict():
    assert core.BOT_TOKEN_RE.search(f"token:\n{TOKEN}\nKeep it").group(0) == TOKEN
    assert core.BOT_TOKEN_RE.search(TOKEN + "extra") is None
    assert core.BOT_TOKEN_RE.fullmatch("123456:short") is None


async def test_talk_to_bot_collects_late_second_reply(client, monkeypatch):
    original = client.get_messages
    polls = {"n": 0}

    async def get_messages(entity, **kwargs):
        polls["n"] += 1
        if polls["n"] == 2 and entity is BOTFATHER:
            client.add_message(BOTFATHER, "second part")
        return await original(entity, **kwargs)

    monkeypatch.setattr(client, "get_messages", get_messages)
    replies = ok(await core.talk_to_bot(client, "botfather", "/newbot"))
    assert [r["text"] for r in replies][-1] == "second part" and len(replies) == 2


async def test_create_bot_rejects_stale_cancel_reply():
    script = FakeClient().botfather_script | {"/newbot": "No active command to cancel. What name?"}
    client = FakeClient(botfather_script=script)
    assert "Unexpected BotFather reply" in err(await core.create_bot(client, "My Bot", "my_test_bot", timeout=0.2))


async def test_bot_api_non_json_response(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"<html>502 Bad Gateway</html>"

    monkeypatch.setattr(core.urllib.request, "urlopen", lambda *a, **k: Response())
    assert "non-JSON" in err(await core.bot_api(TOKEN, "getMe"))
