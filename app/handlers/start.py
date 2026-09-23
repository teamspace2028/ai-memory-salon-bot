"""Команды /start, /help, /reset, /status, /clear*."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app import config, keyboards, salon_data as kb
from app.db import repository as db
from app.services import ai_assistant, google_calendar, long_memory
from app.services.notify import is_admin_user

router = Router(name="start")

GREETING = (
    f"Вітаю! Я ваш помічник із салону «{kb.SALON_NAME}». "
    "Ми пропонуємо стильні та якісні стрижки для всієї родини: "
    "чоловіків, жінок та дітей. Чим можу допомогти?"
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if message.from_user and message.from_user.username:
        db.remember_user(message.from_user.username, message.chat.id)

    ai_assistant.clear_short_memory(message.from_user.id)
    ai_assistant.append_to_history(message.from_user.id, "assistant", GREETING)
    await message.answer(GREETING, reply_markup=keyboards.main_menu())

    if is_admin_user(message.from_user):
        await message.answer(
            "✅ Ви в списку адміністраторів.\n"
            "Сповіщення про записи та скасування надходитимуть сюди."
        )


@router.message(Command("reset"))
@router.message(Command("clear_short"))
async def cmd_reset(message: Message) -> None:
    if not message.from_user or not is_admin_user(message.from_user):
        await message.answer("Доступ заборонено. Ця команда доступна лише адміністраторам.")
        return

    ai_assistant.clear_short_memory(message.from_user.id)
    await message.answer(
        "Діалог скинуто. Чим можу допомогти?",
        reply_markup=keyboards.main_menu(),
    )


@router.message(Command("clear_long"))
async def cmd_clear_long(message: Message) -> None:
    if not message.from_user or not is_admin_user(message.from_user):
        await message.answer("Доступ заборонено. Ця команда доступна лише адміністраторам.")
        return

    long_memory.clear_user_docs(message.from_user.id)
    await message.answer("Ваші завантажені документи видалено з пам'яті.")


@router.message(Command("clear"))
async def cmd_clear(message: Message) -> None:
    if not message.from_user or not is_admin_user(message.from_user):
        await message.answer("Доступ заборонено. Ця команда доступна лише адміністраторам.")
        return

    ai_assistant.clear_short_memory(message.from_user.id)
    long_memory.clear_user_docs(message.from_user.id)
    await message.answer(
        "Діалог та ваші документи очищено. Базу знань салону збережено.",
        reply_markup=keyboards.main_menu(),
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    if not message.from_user or not is_admin_user(message.from_user):
        await message.answer("Доступ заборонено. Ця команда доступна лише адміністраторам.")
        return

    user_id = message.from_user.id
    short_count = len(ai_assistant.short_memory[user_id])
    docs = long_memory.get_user_collection(user_id).count()
    kb_count = long_memory.get_shared_kb_collection().count()
    gcal = "увімк" if google_calendar.is_enabled() else "вимк"
    await message.answer(
        f"Коротка пам'ять: {short_count}/{config.HISTORY_LIMIT}\n"
        f"Ваші документи: {docs} чанків\n"
        f"База знань салону: {kb_count} чанків\n"
        f"LLM: {config.openai_endpoint_label()}\n"
        f"Google Calendar: {gcal}"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Я допоможу записатися в салон «Стрижка».\n\n"
        "Кнопки меню: послуги, години, запис, мої записи, контакти.\n"
        "Можна писати вільно — підберу слоти та оформлю запис.\n"
        "Можна надіслати фото зачіски — опишу стиль та підкажу послугу.\n"
        "Можна завантажити PDF/TXT/DOCX — врахую як дод. документ.\n\n"
        "/mybookings — мої записи\n"
        "/status — пам'ять і Google Calendar\n"
        "/reset — скинути діалог\n"
        "/clear — діалог + ваші документи"
    )
