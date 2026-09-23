"""Уведомления администраторам."""
from __future__ import annotations

import logging

from aiogram import Bot

from app import config
from app.db import repository as db

logger = logging.getLogger(__name__)


def is_admin_user(user) -> bool:
    if not user:
        return False
    if user.id in config.ADMIN_CHAT_IDS:
        return True
    if user.username and user.username.lower() in config.ADMIN_USERNAMES:
        return True
    return False


def resolve_admin_chat_ids(exclude_chat_id: int | None = None) -> set[int]:
    ids = set(config.ADMIN_CHAT_IDS)
    for username in config.ADMIN_USERNAMES:
        cid = db.get_chat_id_by_username(username)
        if cid:
            ids.add(cid)
        else:
            logger.warning(
                "Адмін @%s ще не натискав /start у бота — сповіщення не дійде",
                username,
            )
    if exclude_chat_id is not None:
        ids.discard(exclude_chat_id)
    return ids


async def notify_admins(
    bot: Bot,
    text: str,
    exclude_chat_id: int | None = None,
) -> None:
    admin_ids = resolve_admin_chat_ids(exclude_chat_id=exclude_chat_id)
    if not admin_ids:
        logger.warning("Немає адмінів для сповіщення (ADMIN_ACCOUNTS / /start)")
        return
    for cid in admin_ids:
        try:
            await bot.send_message(chat_id=cid, text=text)
        except Exception:  # noqa: BLE001
            logger.exception("Не вдалося надіслати сповіщення адміну %s", cid)


async def notify_new_bookings(bot: Bot, bookings: list, client_chat_id: int) -> None:
    for b in bookings:
        text = (
            "🔔 Новий запис!\n"
            f"Послуга: {b['service']}\n"
            f"Дата: {b['date']} о {b['time']}\n"
            f"Клієнт: {b['client_name']}\n"
            f"Телефон: {b['client_phone']}"
        )
        if b.get("gcal_synced"):
            text += "\n📅 Додано до Google Calendar"
        await notify_admins(bot, text, exclude_chat_id=client_chat_id)


async def notify_cancelled_bookings(
    bot: Bot,
    bookings: list,
    client_chat_id: int,
) -> None:
    for b in bookings:
        text = (
            "❌ Скасування запису!\n"
            f"Послуга: {b['service']}\n"
            f"Було: {b['date']} о {b['time']}\n"
            f"Клієнт: {b.get('client_name')}"
        )
        if b.get("gcal_deleted"):
            text += "\n📅 Видалено з Google Calendar"
        await notify_admins(bot, text, exclude_chat_id=client_chat_id)
