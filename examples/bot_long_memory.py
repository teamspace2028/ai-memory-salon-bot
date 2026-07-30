"""
Telegram-бот с долгой памятью: документ → чанки → эмбеддинги → ChromaDB.
Отвечает на вопросы по загруженному документу (RAG).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import List

import chromadb
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from chromadb.utils import embedding_functions
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

# --- Конфиг ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
TOP_K = 4
MEMORY_DIR = Path("./memory")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в окружении")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY не задан в окружении")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# Persistent ChromaDB + OpenAI embeddings
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
chroma_client = chromadb.PersistentClient(path=str(MEMORY_DIR))
openai_ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key=OPENAI_API_KEY,
    model_name=EMBEDDING_MODEL,
)


def collection_name(user_id: int) -> str:
    """Имя коллекции Chroma для пользователя."""
    return f"user_{user_id}"


def get_user_collection(user_id: int):
    """Получить или создать коллекцию пользователя."""
    return chroma_client.get_or_create_collection(
        name=collection_name(user_id),
        embedding_function=openai_ef,
        metadata={"hnsw:space": "cosine"},
    )


# ---------------------------------------------------------------------------
# Работа с документами
# ---------------------------------------------------------------------------


def load_document(file_path: str | Path) -> str:
    """Загрузить текст из PDF / TXT / DOCX."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore")

    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        parts = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text)
        return "\n".join(parts)

    if suffix in {".docx", ".doc"}:
        from docx import Document

        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    raise ValueError(f"Неподдерживаемый формат: {suffix}. Нужен PDF, TXT или DOCX.")


def split_into_chunks(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> List[str]:
    """Разбить текст на перекрывающиеся чанки ~chunk_size символов."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def embed_chunks(user_id: int, chunks: List[str], source_name: str) -> int:
    """
    Сохранить чанки в ChromaDB (эмбеддинги считает embedding_function).
    Возвращает число сохранённых чанков.
    """
    if not chunks:
        return 0

    collection = get_user_collection(user_id)
    # Очищаем предыдущие документы пользователя (одна «база» на юзера)
    existing = collection.get()
    if existing and existing["ids"]:
        collection.delete(ids=existing["ids"])

    ids = [f"{source_name}_{i}" for i in range(len(chunks))]
    metadatas = [{"source": source_name, "chunk_index": i} for i in range(len(chunks))]
    collection.add(documents=chunks, ids=ids, metadatas=metadatas)
    return len(chunks)


def retrieve_context(user_id: int, query: str, top_k: int = TOP_K) -> str:
    """Поиск релевантных фрагментов в векторной базе пользователя."""
    collection = get_user_collection(user_id)
    if collection.count() == 0:
        return ""

    results = collection.query(query_texts=[query], n_results=min(top_k, collection.count()))
    documents = (results.get("documents") or [[]])[0]
    if not documents:
        return ""

    parts = [f"[{i + 1}] {doc}" for i, doc in enumerate(documents) if doc]
    return "\n\n".join(parts)


async def answer_question(user_id: int, question: str) -> str:
    """
    RAG: контекст из Chroma + вопрос → ChatCompletion.
    Модель опирается только на документ, без выдумок.
    """
    # Эмбеддинг/поиск синхронный — выносим в thread, чтобы не блокировать loop
    context = await asyncio.to_thread(retrieve_context, user_id, question)

    if not context:
        return (
            "Документ ещё не загружен или в нём нет данных. "
            "Пришли PDF, TXT или DOCX — я запомню содержимое."
        )

    system_prompt = (
        "Ты ассистент по документам. Отвечай ТОЛЬКО на основе переданного контекста. "
        "Если ответа в контексте нет — честно скажи, что информации недостаточно. "
        "Не выдумывай факты."
    )
    user_prompt = (
        f"Контекст из документа:\n{context}\n\n"
        f"Вопрос пользователя: {question}\n\n"
        "Ответ:"
    )

    response = await openai_client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Я бот с долгой памятью по документам.\n\n"
        "1) Загрузи PDF / TXT / DOCX\n"
        "2) Задай вопрос по содержимому\n\n"
        "Команды: /status — сколько чанков в памяти, /clear — очистить, /help"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Загрузи документ (PDF, TXT, DOCX) — я разобью его на части и сохраню эмбеддинги.\n"
        "Потом спрашивай по тексту — отвечу только по документу.\n\n"
        "/status — состояние памяти\n"
        "/clear — удалить документ из памяти\n"
        "/help — справка"
    )


@dp.message(Command("status"))
async def cmd_status(message: Message) -> None:
    collection = get_user_collection(message.from_user.id)
    count = collection.count()
    await message.answer(f"В долгой памяти: {count} чанков.")


@dp.message(Command("clear"))
async def cmd_clear(message: Message) -> None:
    collection = get_user_collection(message.from_user.id)
    existing = collection.get()
    if existing and existing["ids"]:
        collection.delete(ids=existing["ids"])
    await message.answer("Долгая память очищена.")


@dp.message(F.document)
async def handle_document(message: Message) -> None:
    """Скачать файл → load_document → чанки → embed_chunks."""
    doc = message.document
    file_name = doc.file_name or "document.txt"
    suffix = Path(file_name).suffix.lower()

    if suffix not in {".pdf", ".txt", ".docx", ".doc"}:
        await message.answer("Поддерживаются только PDF, TXT и DOCX.")
        return

    await message.answer("Читаю документ и сохраняю в память...")

    try:
        tg_file = await bot.get_file(doc.file_id)
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / file_name
            await bot.download_file(tg_file.file_path, destination=local_path)

            # CPU/IO-тяжёлые шаги — в thread
            text = await asyncio.to_thread(load_document, local_path)
            if not text.strip():
                await message.answer("Не удалось извлечь текст из файла.")
                return

            chunks = await asyncio.to_thread(split_into_chunks, text)
            saved = await asyncio.to_thread(
                embed_chunks, message.from_user.id, chunks, file_name
            )

        await message.answer(
            f"Документ «{file_name}» сохранён.\n"
            f"Чанков: {saved}. Можно задавать вопросы."
        )
    except Exception:
        logger.exception("Ошибка обработки документа user_id=%s", message.from_user.id)
        await message.answer("Не удалось обработать документ. Попробуй другой файл.")


@dp.message(F.text)
async def handle_question(message: Message) -> None:
    question = (message.text or "").strip()
    if not question:
        return

    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        answer = await answer_question(message.from_user.id, question)
        await message.answer(answer)
    except Exception:
        logger.exception("Ошибка ответа user_id=%s", message.from_user.id)
        await message.answer("Не удалось сформировать ответ. Попробуй ещё раз.")


async def main() -> None:
    logger.info("Запуск бота с долгой памятью (Chroma → %s)...", MEMORY_DIR.resolve())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
