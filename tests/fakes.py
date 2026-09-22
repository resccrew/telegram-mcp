"""An in-memory stand-in for Telethon's TelegramClient."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from telethon.tl import types

ME = types.User(id=1, first_name="Nick", username="nick", phone="48000", access_hash=1, is_self=True)
ALICE = types.User(id=2, first_name="Alice", username="alice", access_hash=2)
BOTFATHER = types.User(id=93372553, first_name="BotFather", username="BotFather", bot=True, access_hash=3)
NEWS = types.Channel(
    id=5, title="Crypto News", photo=types.ChatPhotoEmpty(), date=None, username="cryptonews", access_hash=5
)
TOKEN = "7123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw1"


@dataclass
class FakeButton:
    text: str


@dataclass
class FakeMessage:
    id: int
    message: str
    out: bool = False
    sender_id: int | None = None
    date: datetime = field(default_factory=lambda: datetime(2026, 9, 22, tzinfo=UTC))
    media: Any = None
    buttons: list[list[FakeButton]] | None = None
    reply_to: Any = None
    clicked: list[Any] = field(default_factory=list)
    click_result: Any = None

    async def click(self, i=None, j=None, text=None):
        self.clicked.append((i, j) if text is None else next(b.text for r in self.buttons for b in r if text(b.text)))
        if self.click_result is not None:
            return self.click_result
        return types.messages.BotCallbackAnswer(cache_time=0, message="Done!")


@dataclass
class FakeDialog:
    entity: Any
    name: str
    unread_count: int = 0
    message: Any = None

    @property
    def id(self) -> int:
        from telethon import utils

        return utils.get_peer_id(self.entity)


class FakeClient:
    def __init__(self, botfather_script: dict[str, str] | None = None) -> None:
        self.entities = {"me": ME, "alice": ALICE, "botfather": BOTFATHER, "cryptonews": NEWS}
        self.dialogs = [
            FakeDialog(ALICE, "Alice", unread_count=2, message=FakeMessage(10, "hi there")),
            FakeDialog(NEWS, "Crypto News"),
            FakeDialog(BOTFATHER, "BotFather"),
        ]
        self.messages: dict[int, list[FakeMessage]] = {}
        self.requests: list[Any] = []
        self.calls: list[tuple[str, tuple, dict]] = []
        self.next_id = 100
        self.botfather_script = botfather_script if botfather_script is not None else default_botfather()

    # --- entities
    async def get_me(self):
        return ME

    async def get_entity(self, key):
        if isinstance(key, str):
            name = key.lower().lstrip("@").removeprefix("https://t.me/")
            if name in self.entities:
                return self.entities[name]
        raise ValueError(f"Cannot find any entity corresponding to {key!r}")

    async def iter_dialogs(self, archived=False):
        for dialog in self.dialogs:
            yield dialog

    # --- messages
    def _store(self, entity) -> list[FakeMessage]:
        return self.messages.setdefault(entity.id, [])

    def add_message(self, entity, text, out=False, **kwargs) -> FakeMessage:
        self.next_id += 1
        message = FakeMessage(self.next_id, text, out=out, **kwargs)
        self._store(entity).append(message)
        return message

    async def get_messages(self, entity, limit=20, offset_id=0, min_id=0, search=None, ids=None):
        stored = self._store(entity)
        if ids is not None:
            return next((m for m in stored if m.id == ids), None)
        found = [
            m
            for m in reversed(stored)
            if m.id > min_id and (not offset_id or m.id < offset_id) and (not search or search in m.message)
        ]
        return found[:limit]

    async def iter_messages(self, entity, search=None, limit=20):
        for stored in self.messages.values():
            for message in stored:
                if search in message.message:
                    yield message

    async def send_message(self, entity, text, **kwargs):
        self.calls.append(("send_message", (entity, text), kwargs))
        sent = self.add_message(entity, text, out=True)
        if entity is BOTFATHER and text in self.botfather_script:
            self.add_message(BOTFATHER, self.botfather_script[text])
        return sent

    async def edit_message(self, entity, message_id, text, **kwargs):
        message = next(m for m in self._store(entity) if m.id == message_id)
        message.message = text
        return message

    async def delete_messages(self, entity, ids, revoke=True):
        self.calls.append(("delete_messages", (entity, ids), {"revoke": revoke}))
        return [SimpleNamespace(pts_count=len(ids))]

    async def forward_messages(self, to, ids, from_peer):
        return [self.add_message(to, f"fwd {i}", out=True) for i in ids]

    async def send_read_acknowledge(self, entity):
        self.calls.append(("read", (entity,), {}))

    async def pin_message(self, entity, message_id, notify=False):
        self.calls.append(("pin", (entity, message_id), {"notify": notify}))

    async def send_file(self, entity, file, caption=None, force_document=False):
        self.calls.append(("send_file", (entity, file), {"caption": caption}))
        return self.add_message(entity, caption or "", out=True, media=types.MessageMediaDocument())

    async def download_media(self, message, file):
        return f"{file}/photo.jpg"

    async def get_participants(self, entity, limit=100, search=""):
        return [ME, ALICE]

    async def delete_dialog(self, entity):
        self.calls.append(("leave", (entity,), {}))

    # --- raw requests
    async def __call__(self, request):
        self.requests.append(request)
        name = type(request).__name__
        if name == "CreateChannelRequest":
            created = types.Channel(
                id=77,
                title=request.title,
                photo=types.ChatPhotoEmpty(),
                date=None,
                megagroup=request.megagroup,
                broadcast=not request.megagroup,
                access_hash=7,
            )
            return SimpleNamespace(chats=[created])
        if name == "CreateChatRequest":
            chat = types.Chat(
                id=88, title=request.title, photo=types.ChatPhotoEmpty(), participants_count=2, date=None, version=1
            )
            return SimpleNamespace(updates=SimpleNamespace(chats=[chat]), missing_invitees=[])
        if name == "ImportChatInviteRequest":
            return SimpleNamespace(chats=[NEWS])
        return True


def default_botfather() -> dict[str, str]:
    return {
        "/cancel": "No active command to cancel.",
        "/newbot": "Alright, a new bot. How are we going to call it? Please choose a name for your bot.",
        "My Bot": "Good. Now let's choose a username for your bot. It must end in `bot`.",
        "my_test_bot": f"Done! Congratulations on your new bot.\nUse this token to access the HTTP API:\n{TOKEN}\nKeep it secure",
    }
