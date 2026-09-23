"""Загрузка документов и фото."""
from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from aiogram import F, Router
from aiogram.types import Message

from app.db import repository as db
from app.services import long_memory
from app.services.chat import ask_llm
from app.services.notify import is_admin_user

router = Router(name="documents")
logger = logging.getLogger(__name__)


@router.message(F.photo)
async def handle_photo(message: Message) -> None:
    """Фото → Vision (описание стиля / референс стрижки)."""
    if message.from_user and message.from_user.username:
        db.remember_user(message.from_user.username, message.chat.id)

    photo = message.photo[-1]
    caption = (message.caption or "").strip()

    try:
        tg_file = await message.bot.get_file(photo.file_id)
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / "photo.jpg"
            await message.bot.download_file(tg_file.file_path, destination=local_path)
            image_bytes = local_path.read_bytes()

        answer = await ask_llm(
            message.bot,
            message.from_user.id,
            message.chat.id,
            caption,
            image_bytes=image_bytes,
            image_mime="image/jpeg",
        )
        await message.answer(answer)
    except Exception:  # noqa: BLE001
        logger.exception("Помилка обробки фото")
        await message.answer(
            "Не вдалося розібрати фото. Спробуйте ще раз або опишіть стиль словами."
        )


@router.message(F.document)
async def handle_document(message: Message) -> None:
    if not message.from_user or not is_admin_user(message.from_user):
        await message.answer("Завантаження документів доступне лише адміністраторам.")
        return

    doc = message.document
    file_name = doc.file_name or "document.txt"
    suffix = Path(file_name).suffix.lower()

    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }[suffix]
        try:
            tg_file = await message.bot.get_file(doc.file_id)
            with tempfile.TemporaryDirectory() as tmpdir:
                local_path = Path(tmpdir) / file_name
                await message.bot.download_file(
                    tg_file.file_path, destination=local_path
                )
                image_bytes = local_path.read_bytes()
            answer = await ask_llm(
                message.bot,
                message.from_user.id,
                message.chat.id,
                (message.caption or "").strip(),
                image_bytes=image_bytes,
                image_mime=mime,
            )
            await message.answer(answer)
        except Exception:  # noqa: BLE001
            logger.exception("Помилка зображення-документа")
            await message.answer("Не вдалося розібрати зображення.")
        return

    if suffix not in {".pdf", ".txt", ".docx", ".doc"}:
        await message.answer("Підтримуються PDF, TXT, DOCX та фото (JPG/PNG).")
        return

    await message.answer("Читаю документ і зберігаю в довгу пам'ять...")
    try:
        tg_file = await message.bot.get_file(doc.file_id)
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / file_name
            await message.bot.download_file(tg_file.file_path, destination=local_path)
            text = await asyncio.to_thread(long_memory.load_document, local_path)
            if not text.strip():
                await message.answer("Не вдалося витягти текст з файлу.")
                return
            chunks = await asyncio.to_thread(long_memory.split_into_chunks, text)
            saved = await asyncio.to_thread(
                long_memory.embed_chunks, message.from_user.id, chunks, file_name
            )
        await message.answer(
            f"Документ «{file_name}» збережено ({saved} чанків). "
            "Можна запитувати щодо нього."
        )
    except Exception:  # noqa: BLE001
        logger.exception("Помилка документа")
        await message.answer("Не вдалося обробити документ.")
