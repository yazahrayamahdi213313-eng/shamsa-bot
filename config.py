import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _parse_ids(value: str) -> set[int]:
    result: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if item:
            result.add(int(item))
    return result


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: set[int]
    db_path: str


def get_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set in .env")
    return Settings(
        bot_token=token,
        admin_ids=_parse_ids(os.getenv("ADMIN_IDS", "")),
        db_path=os.getenv("DB_PATH", "data/bot.db"),
    )
