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
            "description": "Отримати список вільних слотів на вказаний день для послуги.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Дата: YYYY-MM-DD, 'сьогодні' або 'завтра'.",
                    },
                    "service": {
                        "type": "string",
                        "description": "Назва послуги, наприклад 'Чоловіча стрижка'.",
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
            "description": "Створити запис клієнта на прийом.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Дата: YYYY-MM-DD, 'сьогодні' або 'завтра'.",
                    },
                    "time": {
                        "type": "string",
                        "description": "Час початку у форматі ГГ:ХХ.",
                    },
                    "service": {
                        "type": "string",
                        "description": "Назва послуги.",
                    },
                    "client_name": {
                        "type": "string",
                        "description": "Ім'я клієнта.",
                    },
                    "client_phone": {
                        "type": "string",
                        "description": "Телефон клієнта.",
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
                "Показати активні записи та збережені дані клієнта "
                "(ім'я, телефон) для поточного Telegram-чату."
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
                "Скасувати запис клієнта. Видаляє з бази та з Google Calendar. "
                "Можна передати booking_id або date+time. "
                "Якщо у клієнта один запис — параметри можна не вказувати."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_id": {
                        "type": "integer",
                        "description": "Id запису з get_my_bookings.",
                    },
                    "date": {
                        "type": "string",
                        "description": "Дата запису: YYYY-MM-DD, сьогодні або завтра.",
                    },
                    "time": {
                        "type": "string",
                        "description": "Час запису ГГ:ХХ.",
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
        f"Ти — віртуальний асистент салону «{kb.SALON_NAME}». "
        "Допомагай записуватися. Відповідай українською мовою, ввічливо та коротко."
    )


BASE_INSTRUCTION = load_base_instruction()


def clear_short_memory(user_id: int) -> None:
    short_memory[user_id].clear()


def append_to_history(user_id: int, role: str, content: str) -> None:
    short_memory[user_id].append({"role": role, "content": content})


def get_history(user_id: int) -> List[dict]:
    return list(short_memory[user_id])


def _client_context(chat_id: int) -> str:
    """Ім'я, телефон та активні записи клієнта з БД."""
    profile = db.get_client_profile(chat_id) or db.get_last_booking_contacts(chat_id)
    now_iso = datetime.now(config.TZ).isoformat()
    bookings = db.get_upcoming_bookings(chat_id, now_iso)

    lines = ["ДАНИЕ ЦЬОГО КЛІЄНТА (з бази салону, можна використовувати у відповідях):" if False else "ДАНІ ЦЬОГО КЛІЄНТА (з бази салону, можна використовувати у відповідях):"]
    if profile and (profile.get("client_name") or profile.get("client_phone")):
        if profile.get("client_name"):
            lines.append(f"- Ім'я: {profile['client_name']}")
        if profile.get("client_phone"):
            lines.append(f"- Телефон: {profile['client_phone']}")
    else:
        lines.append("- Ім'я та телефон ще не збережені.")

    if bookings:
        lines.append("- Активні записи:")
        for b in bookings:
            start = datetime.fromisoformat(b["start"])
            lines.append(
                f"  • {b['service']} — {start.strftime('%Y-%m-%d')} "
                f"о {start.strftime('%H:%M')} (id={b['id']})"
            )
    else:
        lines.append("- Активних записів немає.")

    lines.append(
        "Якщо запитують «як мене звуть», «мої дані», «мої записи» — "
        "відповідай за цими даними або виклич get_my_bookings. "
        "Не кажи, що у тебе немає доступу до записів клієнта."
    )
    return "\n".join(lines)


def build_system_prompt(rag_context: str, chat_id: int) -> str:
    now = datetime.now(config.TZ)
    prompt = (
        f"{BASE_INSTRUCTION}\n\n"
        f"---\n"
        f"АКТУАЛЬНО ЗАРАЗ\n"
        f"Сьогодні {now.strftime('%Y-%m-%d')}, час {now.strftime('%H:%M')} "
        f"({config.SALON_TIMEZONE}).\n"
        f"Салон «{kb.SALON_NAME}»: {kb.SALON_ADDRESS}, тел. {kb.SALON_PHONE}.\n"
        f"Години: {kb.OPEN_HOUR:02d}:00–{kb.CLOSE_HOUR:02d}:00, "
        f"перерва {kb.LUNCH_START_HOUR:02d}:00–{kb.LUNCH_END_HOUR:02d}:00.\n\n"
        f"Послуги для запису (тільки ці):\n{kb.services_text()}\n\n"
        f"{_client_context(chat_id)}\n\n"
        "ПРАВИЛА ЗАПИСУ (суворо):\n"
        "1) Щоб показати вільний час — викликай get_available_slots.\n"
        "2) Перед create_booking обов'язково дізнайся ім'я та телефон "
        "(якщо вони вже є в даних клієнта вище — можна використовувати їх, "
        "запитавши коротке підтвердження).\n"
        "3) НІКОЛИ не кажи «ви записані», поки create_booking не повернув ok=true.\n"
        "4) НІКОЛИ не кажи «запис скасовано», поки cancel_booking не повернув ok=true.\n"
        "5) Якщо слот зайнятий/перерва — запропонуй найближчі вільні.\n"
        "6) Не вигадуй послуги та ціни поза списком.\n"
        "7) Запитання про ім'я/телефон/записи клієнта — дивись блок ДАНІ ЦЬОГО КЛІЄНТА "
        "або викликай get_my_bookings.\n"
        "8) Для скасування запису завжди викликай cancel_booking.\n"
        "9) Клієнт може надіслати фото зачіски/референс. Ти БАЧИШ зображення: "
        "опиши стиль простими словами, запропонуй відповідну послугу з каталогу "
        "та м'яко запропонуй записатися. Не кажи, що не можеш дивитися фото.\n"
        "10) Після успішного виклику create_booking обов'язково підтверджуй запис, "
        "використовуючи точний шаблон із бази знань:\n"
        "«Запис підтверджено!\n"
        "• Послуга: …\n"
        "• Дата та час: …\n"
        "• Майстер: …\n"
        "• Клієнт: …\n"
        "• Телефон: …\n"
        "• Орієнтовна вартість: … грн\n\n"
        "Нагадаємо SMS за день до візиту.\n"
        "Якщо потрібно перенести або скасувати запис — напишіть сюди. Будемо раді бачити вас у салоні „Стрижка“!»\n"
    )
    if rag_context:
        prompt += f"\nРелевантний контекст з пам'яті:\n{rag_context}\n"
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

    history_text = user_text.strip() if user_text.strip() else "Клієнт надіслав фото."
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
            or "Подивись фото. Опиши зачіску/стиль і підкажи, яку послугу "
            "з нашого салону підібрати. Якщо доречно — запропонуй записатися."
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
            answer = msg.content or "Вибачте, не почув. Повторіть, будь ласка."
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

    fallback = "Вибачте, не вдалося обробити запит. Спробуйте переформулювати."
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
