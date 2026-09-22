"""One-time interactive login: stores API credentials and the Telegram session string."""

import asyncio
import getpass

from telethon import TelegramClient
from telethon.sessions import StringSession

from .config import config_file, load_config, read_env_file, write_env_file, write_session
from .result import Err


def ask_credentials() -> None:
    print("Get api_id and api_hash at https://my.telegram.org -> API development tools.")
    api_id = input("api_id: ").strip()
    api_hash = getpass.getpass("api_hash (hidden): ").strip()
    values = read_env_file(config_file())
    values.update({"TELEGRAM_API_ID": api_id, "TELEGRAM_API_HASH": api_hash})
    write_env_file(config_file(), values)
    print(f"Saved credentials to {config_file()} (chmod 600).")


async def login() -> int:
    config = load_config()
    if isinstance(config, Err):
        ask_credentials()
        config = load_config()
    if isinstance(config, Err):
        print(config.error)
        return 1
    cfg = config.value
    client = TelegramClient(StringSession(), cfg.api_id, cfg.api_hash)
    await client.start()  # prompts for phone, code and 2FA password
    me = await client.get_me()
    write_session(cfg.session_path, client.session.save())
    await client.disconnect()
    print(f"Logged in as {me.first_name} (@{me.username}). Session saved to {cfg.session_path} (chmod 600).")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(login()))


if __name__ == "__main__":
    main()
