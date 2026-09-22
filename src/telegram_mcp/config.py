"""Configuration: API credentials and session location.

Values come from environment variables first, then from ~/.telegram-mcp/config.env
(KEY=VALUE lines). The directory lives outside the repo so secrets never get committed.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from .result import Err, Ok, Result

DEFAULT_HOME = Path.home() / ".telegram-mcp"


@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    session_path: Path


def home_dir() -> Path:
    return Path(os.environ.get("TELEGRAM_MCP_HOME", DEFAULT_HOME)).expanduser()


def config_file() -> Path:
    return home_dir() / "config.env"


def read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_private(path: Path, content: str) -> None:
    """Write a secret file that is never readable by others, not even for a moment."""
    if not path.parent.exists():
        path.parent.mkdir(parents=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(content)
    path.chmod(0o600)  # the file may have existed before with wider permissions


def write_env_file(path: Path, values: dict[str, str]) -> None:
    write_private(path, "".join(f"{k}={v}\n" for k, v in values.items()))


def read_session(path: Path) -> str:
    return path.read_text().strip() if path.is_file() else ""


def write_session(path: Path, session: str) -> None:
    write_private(path, session)


def load_config() -> Result[Config]:
    file_values = read_env_file(config_file())

    def get(key: str) -> str:
        return os.environ.get(key) or file_values.get(key, "")

    api_id_raw = get("TELEGRAM_API_ID")
    api_hash = get("TELEGRAM_API_HASH")
    if not api_id_raw or not api_hash:
        return Err(
            "Telegram API credentials are missing. Get api_id/api_hash at "
            "https://my.telegram.org -> API development tools, then run `telegram-mcp-login`."
        )
    if not api_id_raw.isdigit():
        return Err(f"TELEGRAM_API_ID must be a number, got {api_id_raw!r}")

    session = get("TELEGRAM_SESSION") or str(home_dir() / "session.txt")
    return Ok(Config(api_id=int(api_id_raw), api_hash=api_hash, session_path=Path(session).expanduser()))
