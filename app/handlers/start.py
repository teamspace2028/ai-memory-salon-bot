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
    f"Здравствуйте! Я ваш помощник из салона «{kb.SALON_NAME}». "
    "Мы предлагаем стильные и качественные стрижки для всей семьи: "
    "мужчин, женщин и детей. Чем могу помочь?"
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
            "✅ Вы в списке администраторов.\n"
            "Уведомления о записях и отменах будут приходить сюда."
        )


@router.message(Command("reset"))
@router.message(Command("clear_short"))
async def cmd_reset(message: Message) -> None:
    ai_assistant.clear_short_memory(message.from_user.id)
    await message.answer(
        "Диалог сброшен. Чем могу помочь?",
        reply_markup=keyboards.main_menu(),
    )


@router.message(Command("clear_long"))
async def cmd_clear_long(message: Message) -> None:
    long_memory.clear_user_docs(message.from_user.id)
    await message.answer("Ваши загруженные документы удалены из памяти.")


@router.message(Command("clear"))
async def cmd_clear(message: Message) -> None:
    ai_assistant.clear_short_memory(message.from_user.id)
    long_memory.clear_user_docs(message.from_user.id)
    await message.answer(
        "Диалог и ваши документы очищены. База знаний салона сохранена.",
        reply_markup=keyboards.main_menu(),
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    user_id = message.from_user.id
    short_count = len(ai_assistant.short_memory[user_id])
    docs = long_memory.get_user_collection(user_id).count()
    kb_count = long_memory.get_shared_kb_collection().count()
    gcal = "вкл" if google_calendar.is_enabled() else "выкл"
    await message.answer(
        f"Короткая память: {short_count}/{config.HISTORY_LIMIT}\n"
        f"Ваши документы: {docs} чанков\n"
        f"База знаний салона: {kb_count} чанков\n"
        f"LLM: {config.openai_endpoint_label()}\n"
        f"Google Calendar: {gcal}"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Я помогу записаться в салон «Стрижка».\n\n"
        "Кнопки меню: услуги, часы, запись, мои записи, контакты.\n"
        "Можно писать свободно — подберу слоты и оформлю запись.\n"
        "Можно прислать фото причёски — опишу стиль и подскажу услугу.\n"
        "Можно загрузить PDF/TXT/DOCX — учту как доп. документ.\n\n"
        "/mybookings — мои записи\n"
        "/status — память и Google Calendar\n"
        "/reset — сбросить диалог\n"
        "/clear — диалог + ваши документы"
    )
