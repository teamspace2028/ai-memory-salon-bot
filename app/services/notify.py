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
                "Админ @%s ещё не нажимал /start у бота — уведомление не дойдёт",
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
        logger.warning("Нет админов для уведомления (ADMIN_ACCOUNTS / /start)")
        return
    for cid in admin_ids:
        try:
            await bot.send_message(chat_id=cid, text=text)
        except Exception:  # noqa: BLE001
            logger.exception("Не удалось отправить уведомление админу %s", cid)


async def notify_new_bookings(bot: Bot, bookings: list, client_chat_id: int) -> None:
    for b in bookings:
        text = (
            "🔔 Новая запись!\n"
            f"Услуга: {b['service']}\n"
            f"Дата: {b['date']} в {b['time']}\n"
            f"Клиент: {b['client_name']}\n"
            f"Телефон: {b['client_phone']}"
        )
        if b.get("gcal_synced"):
            text += "\n📅 Добавлено в Google Calendar"
        await notify_admins(bot, text, exclude_chat_id=client_chat_id)


async def notify_cancelled_bookings(
    bot: Bot,
    bookings: list,
    client_chat_id: int,
) -> None:
    for b in bookings:
        text = (
            "❌ Отмена записи!\n"
            f"Услуга: {b['service']}\n"
            f"Было: {b['date']} в {b['time']}\n"
            f"Клиент: {b.get('client_name')}"
        )
        if b.get("gcal_deleted"):
            text += "\n📅 Удалено из Google Calendar"
        await notify_admins(bot, text, exclude_chat_id=client_chat_id)
