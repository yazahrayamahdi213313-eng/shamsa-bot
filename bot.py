from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from config import get_settings
from db import Database
from handlers import router


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    db = Database(settings.db_path)
    await db.init()

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    dp["db"] = db
    dp["admin_ids"] = settings.admin_ids
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
