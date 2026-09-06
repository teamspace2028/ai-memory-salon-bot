"""Текстовые сообщения и кнопки меню."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app import keyboards, salon_data as kb
from app.db import repository as db
from app.handlers.bookings import show_my_bookings
from app.services.chat import ask_llm

router = Router(name="chat")


@router.message(F.text)
async def handle_text(message: Message) -> None:
    if message.from_user and message.from_user.username:
        db.remember_user(message.from_user.username, message.chat.id)

    text = (message.text or "").strip()
    if not text:
        return

    if text.startswith("/"):
        await message.answer("Неизвестная команда. Воспользуйтесь /help.")
        return

    if text == keyboards.BTN_HOURS:
        await message.answer(kb.hours_text())
        return
    if text == keyboards.BTN_CONTACTS:
        await message.answer(kb.contacts_text())
        return
    if text == keyboards.BTN_SERVICES:
        await message.answer("Наши услуги:\n" + kb.services_text())
        return
    if text == keyboards.BTN_MY_BOOKINGS:
        await show_my_bookings(message)
        return
    if text == keyboards.BTN_BOOK:
        await message.answer(
            "Выберите услугу для записи:",
            reply_markup=keyboards.services_inline(),
        )
        return

    answer = await ask_llm(message.bot, message.from_user.id, message.chat.id, text)
    await message.answer(answer)
