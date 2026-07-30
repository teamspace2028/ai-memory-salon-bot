"""Точка входа: python -m app  или  python bot.py"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher

from app import config, salon_data as kb
from app.db import repository as db
from app.handlers import setup_routers
from app.services import google_calendar, long_memory

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    config.validate()
    db.init_db()
    backfilled = db.backfill_client_profiles()

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()
    setup_routers(dp)

    logger.info(
        "Запуск салона «%s». LLM=%s, GCal=%s, memory=%s, profiles_backfill=%s",
        kb.SALON_NAME,
        config.openai_endpoint_label(),
        google_calendar.is_enabled(),
        Path(config.MEMORY_DIR).resolve(),
        backfilled,
    )
    await asyncio.to_thread(long_memory.seed_shared_knowledge_base)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
