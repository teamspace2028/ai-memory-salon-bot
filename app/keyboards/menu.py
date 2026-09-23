"""Клавиатуры aiogram 3: нижнее меню и инлайн-кнопки."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from app import salon_data as kb

BTN_SERVICES = "✂️ Послуги та ціни"
BTN_HOURS = "🕐 Години роботи"
BTN_BOOK = "📅 Записатися"
BTN_CONTACTS = "📍 Адреса та контакти"
BTN_MY_BOOKINGS = "🗓 Мої записи"


def main_menu() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text=BTN_SERVICES), KeyboardButton(text=BTN_HOURS))
    builder.row(KeyboardButton(text=BTN_BOOK), KeyboardButton(text=BTN_MY_BOOKINGS))
    builder.row(KeyboardButton(text=BTN_CONTACTS))
    return builder.as_markup(resize_keyboard=True)


def cancel_inline(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Скасувати запис",
                    callback_data=f"cancel:{booking_id}",
                )
            ]
        ]
    )


def services_inline() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, (name, price, _minutes) in kb.SERVICES.items():
        builder.row(
            InlineKeyboardButton(
                text=f"{name} — {price} грн",
                callback_data=f"book:{key}",
            )
        )
    return builder.as_markup()
