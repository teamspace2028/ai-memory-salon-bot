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
        await message.answer("У вас поки немає активних записів.")
        return
    await message.answer("Ваші записи:")
    for b in rows:
        start = datetime.fromisoformat(b["start"])
        text = (
            f"• {b['service']} — "
            f"{start.strftime('%Y-%m-%d')} о {start.strftime('%H:%M')}"
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
        await callback.message.edit_text("Послугу не знайдено. Спробуйте ще раз.")
        return

    name = service[0]
    await callback.message.edit_text(f"Записую на «{name}».")

    if callback.from_user and callback.from_user.username:
        db.remember_user(callback.from_user.username, callback.message.chat.id)

    answer = await ask_llm(
        callback.bot,
        callback.from_user.id,
        callback.message.chat.id,
        f"Хочу записатися на послугу «{name}».",
    )
    await callback.message.answer(answer)


@router.callback_query(F.data.startswith("cancel:"))
async def on_cancel_booking(callback: CallbackQuery) -> None:
    await callback.answer()
    chat_id = callback.message.chat.id
    booking_id = int(callback.data.split(":", 1)[1])
    row = db.get_booking(booking_id, chat_id)
    if row is None:
        await callback.message.edit_text("Запис не знайдено або вже скасовано.")
        return

    gcal_deleted = False
    if row.get("gcal_event_id"):
        gcal_deleted = await asyncio.to_thread(
            google_calendar.delete_event, row["gcal_event_id"]
        )
    db.delete_booking(booking_id, chat_id)

    start = datetime.fromisoformat(row["start"])
    await callback.message.edit_text(
        f"Запис скасовано: {row['service']} — "
        f"{start.strftime('%Y-%m-%d')} о {start.strftime('%H:%M')}."
    )
    text = (
        "❌ Скасування запису!\n"
        f"Послуга: {row['service']}\n"
        f"Було: {start.strftime('%Y-%m-%d')} о {start.strftime('%H:%M')}\n"
        f"Клієнт: {row.get('client_name')}"
    )
    if gcal_deleted:
        text += "\n📅 Видалено з Google Calendar"
    await notify_admins(callback.bot, text, exclude_chat_id=chat_id)
