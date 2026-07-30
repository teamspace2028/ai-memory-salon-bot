"""Мои записи, выбор услуги, отмена."""
from __future__ import annotations

import asyncio
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app import config, keyboards, salon_data as kb
from app.db import repository as db
from app.services import google_calendar
from app.services.chat import ask_llm
from app.services.notify import notify_admins

router = Router(name="bookings")


async def show_my_bookings(message: Message) -> None:
    chat_id = message.chat.id
    now_iso = datetime.now(config.TZ).isoformat()
    rows = db.get_upcoming_bookings(chat_id, now_iso)
    if not rows:
        await message.answer("У вас пока нет активных записей.")
        return
    await message.answer("Ваши записи:")
    for b in rows:
        start = datetime.fromisoformat(b["start"])
        text = (
            f"• {b['service']} — "
            f"{start.strftime('%Y-%m-%d')} в {start.strftime('%H:%M')}"
        )
        await message.answer(text, reply_markup=keyboards.cancel_inline(b["id"]))


@router.message(Command("mybookings"))
async def cmd_my_bookings(message: Message) -> None:
    await show_my_bookings(message)


@router.callback_query(F.data.startswith("book:"))
async def on_service_chosen(callback: CallbackQuery) -> None:
    await callback.answer()
    key = callback.data.split(":", 1)[1]
    service = kb.SERVICES.get(key)
    if service is None:
        await callback.message.edit_text("Услуга не найдена. Попробуйте ещё раз.")
        return

    name = service[0]
    await callback.message.edit_text(f"Записываю на «{name}».")

    if callback.from_user and callback.from_user.username:
        db.remember_user(callback.from_user.username, callback.message.chat.id)

    answer = await ask_llm(
        callback.bot,
        callback.from_user.id,
        callback.message.chat.id,
        f"Хочу записаться на услугу «{name}».",
    )
    await callback.message.answer(answer)


@router.callback_query(F.data.startswith("cancel:"))
async def on_cancel_booking(callback: CallbackQuery) -> None:
    await callback.answer()
    chat_id = callback.message.chat.id
    booking_id = int(callback.data.split(":", 1)[1])
    row = db.get_booking(booking_id, chat_id)
    if row is None:
        await callback.message.edit_text("Запись не найдена или уже отменена.")
        return

    gcal_deleted = False
    if row.get("gcal_event_id"):
        gcal_deleted = await asyncio.to_thread(
            google_calendar.delete_event, row["gcal_event_id"]
        )
    db.delete_booking(booking_id, chat_id)

    start = datetime.fromisoformat(row["start"])
    await callback.message.edit_text(
        f"Запись отменена: {row['service']} — "
        f"{start.strftime('%Y-%m-%d')} в {start.strftime('%H:%M')}."
    )
    text = (
        "❌ Отмена записи!\n"
        f"Услуга: {row['service']}\n"
        f"Было: {start.strftime('%Y-%m-%d')} в {start.strftime('%H:%M')}\n"
        f"Клиент: {row.get('client_name')}"
    )
    if gcal_deleted:
        text += "\n📅 Удалено из Google Calendar"
    await notify_admins(callback.bot, text, exclude_chat_id=chat_id)
