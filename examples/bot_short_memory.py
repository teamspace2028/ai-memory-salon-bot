"""
Telegram-бот с короткой памятью (history buffer).
Хранит последние N сообщений диалога в оперативке для каждого user_id.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict, deque
from typing import Deque, Dict, List

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

# --- Конфиг ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
HISTORY_LIMIT = 10  # последние N сообщений (user + assistant)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в окружении")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY не задан в окружении")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# user_id -> очередь сообщений в формате OpenAI ({role, content})
short_memory: Dict[int, Deque[dict]] = defaultdict(
    lambda: deque(maxlen=HISTORY_LIMIT)
)

SYSTEM_PROMPT = (
    "Ты полезный ассистент в Telegram. "
    "Отвечай кратко и по делу, учитывая историю диалога."
)


def get_history(user_id: int) -> List[dict]:
    """Вернуть текущую короткую память пользователя."""
    return list(short_memory[user_id])


def append_to_history(user_id: int, role: str, content: str) -> None:
    """Добавить сообщение в короткую память (автоматически обрезает до N)."""
    short_memory[user_id].append({"role": role, "content": content})


def clear_history(user_id: int) -> None:
    """Очистить короткую память пользователя."""
    short_memory[user_id].clear()


async def chat_with_memory(user_id: int, user_text: str) -> str:
    """
    Собрать промпт: system + история + текущее сообщение,
    вызвать ChatCompletion и обновить память.
    """
    append_to_history(user_id, "user", user_text)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(get_history(user_id))

    response = await openai_client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.7,
    )
    answer = response.choices[0].message.content or ""
    append_to_history(user_id, "assistant", answer)
    return answer


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Я бот с короткой памятью.\n"
        "Помню последние 10 сообщений нашего диалога.\n"
        "Команды: /clear — очистить память, /help — справка."
    )


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Просто пиши сообщения — я отвечу с учётом недавней истории.\n"
        "/clear — сбросить короткую память\n"
        "/help — эта справка"
    )


@dp.message(Command("clear"))
async def cmd_clear(message: Message) -> None:
    clear_history(message.from_user.id)
    await message.answer("Короткая память очищена.")


@dp.message(F.text)
async def handle_text(message: Message) -> None:
    user_id = message.from_user.id
    text = message.text.strip()
    if not text:
        return

    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        answer = await chat_with_memory(user_id, text)
        await message.answer(answer)
    except Exception:
        logger.exception("Ошибка OpenAI для user_id=%s", user_id)
        # Откатываем последнее user-сообщение при ошибке API
        hist = short_memory[user_id]
        if hist and hist[-1].get("role") == "user":
            hist.pop()
        await message.answer("Не удалось получить ответ. Попробуй ещё раз.")


async def main() -> None:
    logger.info("Запуск бота с короткой памятью...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
