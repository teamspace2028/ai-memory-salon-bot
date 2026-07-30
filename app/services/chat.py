"""Диалог с LLM + уведомления админам."""
from __future__ import annotations

import logging

from aiogram import Bot

from app.services import ai_assistant
from app.services.notify import notify_cancelled_bookings, notify_new_bookings

logger = logging.getLogger(__name__)


async def ask_llm(
    bot: Bot,
    user_id: int,
    chat_id: int,
    text: str,
    *,
    image_bytes: bytes | None = None,
    image_mime: str = "image/jpeg",
) -> str:
    await bot.send_chat_action(chat_id, "typing")
    try:
        answer, created, cancelled = await ai_assistant.reply(
            user_id,
            chat_id,
            text,
            image_bytes=image_bytes,
            image_mime=image_mime,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Ошибка OpenAI")
        return "Извините, произошла техническая ошибка. Попробуйте ещё раз чуть позже."
    if created:
        await notify_new_bookings(bot, created, client_chat_id=chat_id)
    if cancelled:
        await notify_cancelled_bookings(bot, cancelled, client_chat_id=chat_id)
    return answer
