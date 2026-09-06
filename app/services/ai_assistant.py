"""ИИ-ассистент: OpenAI Chat Completions + tools + короткая/долгая память."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, List, Tuple

from openai import AsyncOpenAI

from app.services import booking
from app import config
from app.db import repository as db
from app.services import long_memory
from app import salon_data as kb

logger = logging.getLogger(__name__)

openai_client = AsyncOpenAI(**config.openai_client_kwargs())

# Короткая память: user_id -> последние N сообщений (role/content)
short_memory: Dict[int, Deque[dict]] = defaultdict(
    lambda: deque(maxlen=config.HISTORY_LIMIT)
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_available_slots",
            "description": "Получить список свободных слотов на указанный день для услуги.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Дата: YYYY-MM-DD, 'сегодня' или 'завтра'.",
                    },
                    "service": {
                        "type": "string",
                        "description": "Название услуги, например 'Мужская стрижка'.",
                    },
                },
                "required": ["date", "service"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_booking",
            "description": "Создать запись клиента на приём.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Дата: YYYY-MM-DD, 'сегодня' или 'завтра'.",
                    },
                    "time": {
                        "type": "string",
                        "description": "Время начала в формате ЧЧ:ММ.",
                    },
                    "service": {
                        "type": "string",
                        "description": "Название услуги.",
                    },
                    "client_name": {
                        "type": "string",
                        "description": "Имя клиента.",
                    },
                    "client_phone": {
                        "type": "string",
                        "description": "Телефон клиента.",
                    },
                },
                "required": [
                    "date",
                    "time",
                    "service",
                    "client_name",
                    "client_phone",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_bookings",
            "description": (
                "Показать активные записи и сохранённые данные клиента "
                "(имя, телефон) для текущего Telegram-чата."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_booking",
            "description": (
                "Отменить запись клиента. Удаляет из базы и из Google Calendar. "
                "Можно передать booking_id или date+time. "
                "Если у клиента одна запись — параметры можно не указывать."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_id": {
                        "type": "integer",
                        "description": "Id записи из get_my_bookings.",
                    },
                    "date": {
                        "type": "string",
                        "description": "Дата записи: YYYY-MM-DD, сегодня или завтра.",
                    },
                    "time": {
                        "type": "string",
                        "description": "Время записи ЧЧ:ММ.",
                    },
                },
                "required": [],
            },
        },
    },
]


def load_base_instruction() -> str:
    path = Path(config.KNOWLEDGE_FILE)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return (
        f"Ты — виртуальный ассистент салона «{kb.SALON_NAME}». "
        "Помогай записываться. Отвечай по-русски, вежливо и кратко."
    )


BASE_INSTRUCTION = load_base_instruction()


def clear_short_memory(user_id: int) -> None:
    short_memory[user_id].clear()


def append_to_history(user_id: int, role: str, content: str) -> None:
    short_memory[user_id].append({"role": role, "content": content})


def get_history(user_id: int) -> List[dict]:
    return list(short_memory[user_id])


def _client_context(chat_id: int) -> str:
    """Имя, телефон и активные записи клиента из БД."""
    profile = db.get_client_profile(chat_id) or db.get_last_booking_contacts(chat_id)
    now_iso = datetime.now(config.TZ).isoformat()
    bookings = db.get_upcoming_bookings(chat_id, now_iso)

    lines = ["ДАННЫЕ ЭТОГО КЛИЕНТА (из базы салона, можно использовать в ответах):"]
    if profile and (profile.get("client_name") or profile.get("client_phone")):
        if profile.get("client_name"):
            lines.append(f"- Имя: {profile['client_name']}")
        if profile.get("client_phone"):
            lines.append(f"- Телефон: {profile['client_phone']}")
    else:
        lines.append("- Имя и телефон ещё не сохранены.")

    if bookings:
        lines.append("- Активные записи:")
        for b in bookings:
            start = datetime.fromisoformat(b["start"])
            lines.append(
                f"  • {b['service']} — {start.strftime('%Y-%m-%d')} "
                f"в {start.strftime('%H:%M')} (id={b['id']})"
            )
    else:
        lines.append("- Активных записей нет.")

    lines.append(
        "Если спрашивают «как меня зовут», «мои данные», «мои записи» — "
        "отвечай по этим данным или вызови get_my_bookings. "
        "Не говори, что у тебя нет доступа к записям клиента."
    )
    return "\n".join(lines)


def build_system_prompt(rag_context: str, chat_id: int) -> str:
    now = datetime.now(config.TZ)
    prompt = (
        f"{BASE_INSTRUCTION}\n\n"
        f"---\n"
        f"АКТУАЛЬНО СЕЙЧАС\n"
        f"Сегодня {now.strftime('%Y-%m-%d')}, время {now.strftime('%H:%M')} "
        f"({config.SALON_TIMEZONE}).\n"
        f"Салон «{kb.SALON_NAME}»: {kb.SALON_ADDRESS}, тел. {kb.SALON_PHONE}.\n"
        f"Часы: {kb.OPEN_HOUR:02d}:00–{kb.CLOSE_HOUR:02d}:00, "
        f"перерыв {kb.LUNCH_START_HOUR:02d}:00–{kb.LUNCH_END_HOUR:02d}:00.\n\n"
        f"Услуги для записи (только эти):\n{kb.services_text()}\n\n"
        f"{_client_context(chat_id)}\n\n"
        "ПРАВИЛА ЗАПИСИ (строго):\n"
        "1) Чтобы показать свободное время — вызывай get_available_slots.\n"
        "2) Перед create_booking обязательно узнай имя и телефон "
        "(если они уже есть в данных клиента выше — можно использовать их, "
        "спросив короткое подтверждение).\n"
        "3) НИКОГДА не говори «вы записаны», пока create_booking не вернул ok=true.\n"
        "4) НИКОГДА не говори «запись отменена», пока cancel_booking не вернул ok=true.\n"
        "5) Если слот занят/перерыв — предложи ближайшие свободные.\n"
        "6) Не выдумывай услуги и цены вне списка.\n"
        "7) Вопросы про имя/телефон/записи клиента — смотри блок ДАННЫЕ ЭТОГО КЛИЕНТА "
        "или вызывай get_my_bookings.\n"
        "8) Для отмены записи всегда вызывай cancel_booking.\n"
        "9) Клиент может прислать фото причёски/референс. Ты ВИДИШЬ изображение: "
        "опиши стиль простыми словами, предложи подходящую услугу из каталога "
        "и мягко предложи записаться. Не говори, что не можешь смотреть фото.\n"
    )
    if rag_context:
        prompt += f"\nРелевантный контекст из памяти:\n{rag_context}\n"
    return prompt


def _my_bookings_payload(chat_id: int) -> dict:
    profile = db.get_client_profile(chat_id) or db.get_last_booking_contacts(chat_id) or {}
    now_iso = datetime.now(config.TZ).isoformat()
    rows = db.get_upcoming_bookings(chat_id, now_iso)
    bookings = []
    for b in rows:
        start = datetime.fromisoformat(b["start"])
        bookings.append(
            {
                "id": b["id"],
                "service": b["service"],
                "date": start.strftime("%Y-%m-%d"),
                "time": start.strftime("%H:%M"),
            }
        )
    return {
        "ok": True,
        "client_name": profile.get("client_name"),
        "client_phone": profile.get("client_phone"),
        "bookings": bookings,
    }


async def reply(
    user_id: int,
    chat_id: int,
    user_text: str,
    *,
    image_bytes: bytes | None = None,
    image_mime: str = "image/jpeg",
) -> Tuple[str, List[dict], List[dict]]:
    """
    Ответ модели с tool-calling, короткой памятью и RAG.
    image_bytes — опционально фото (Vision).
    Возвращает (текст, созданные записи, отменённые записи).
    """
    import base64

    query_for_rag = user_text or "фото причёски стиль стрижка"
    rag_context = await asyncio.to_thread(
        long_memory.retrieve_all_context, user_id, query_for_rag
    )
    system_prompt = build_system_prompt(rag_context, chat_id)

    history_text = user_text.strip() if user_text.strip() else "Клиент прислал фото."
    if image_bytes:
        history_text = f"[Фото] {history_text}"
    append_to_history(user_id, "user", history_text)

    messages: List[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    # История без последнего user — его добавим с картинкой при необходимости
    prior = get_history(user_id)[:-1]
    messages.extend(prior)

    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        caption = (
            user_text.strip()
            or "Посмотри фото. Опиши причёску/стиль и подскажи, какую услугу "
            "из нашего салона подобрать. Если уместно — предложи записаться."
        )
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": caption},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image_mime};base64,{b64}",
                        },
                    },
                ],
            }
        )
    else:
        messages.append({"role": "user", "content": user_text})

    created: list[dict] = []
    cancelled: list[dict] = []

    for _ in range(5):
        response = await openai_client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.4,
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            answer = msg.content or "Извините, не расслышал. Повторите, пожалуйста."
            append_to_history(user_id, "assistant", answer)
            return answer, created, cancelled

        assistant_msg = msg.model_dump(exclude_unset=True)
        messages.append(assistant_msg)

        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _dispatch(tc.function.name, args, chat_id, created, cancelled)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    fallback = "Извините, не удалось обработать запрос. Попробуйте переформулировать."
    append_to_history(user_id, "assistant", fallback)
    return fallback, created, cancelled


def _dispatch(
    name: str,
    args: dict,
    chat_id: int,
    created: list,
    cancelled: list,
) -> dict:
    logger.info("Tool call: %s args=%s chat_id=%s", name, args, chat_id)
    if name == "get_available_slots":
        result = booking.available_slots(args.get("date", ""), args.get("service", ""))
        logger.info("get_available_slots → ok=%s slots=%s", result.get("ok"), result.get("slots"))
        return result
    if name == "create_booking":
        result = booking.create_booking(
            chat_id,
            args.get("date", ""),
            args.get("time", ""),
            args.get("service", ""),
            args.get("client_name", ""),
            args.get("client_phone", ""),
        )
        logger.info("create_booking → %s", result)
        if result.get("ok"):
            created.append(result)
        return result
    if name == "get_my_bookings":
        result = _my_bookings_payload(chat_id)
        logger.info("get_my_bookings → %s", result)
        return result
    if name == "cancel_booking":
        bid = args.get("booking_id")
        result = booking.cancel_booking(
            chat_id,
            booking_id=bid,
            date_str=args.get("date"),
            time_str=args.get("time"),
        )
        logger.info("cancel_booking → %s", result)
        if result.get("ok"):
            cancelled.append(result)
        return result
    return {"ok": False, "error": f"Неизвестная функция {name}"}
