"""Запуск бота: python bot.py"""
from __future__ import annotations

import asyncio

from app.__main__ import main

if __name__ == "__main__":
    asyncio.run(main())
