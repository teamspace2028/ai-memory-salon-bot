"""Конфигурация: переменные окружения из .env."""
from __future__ import annotations

import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")

# OpenAI / ProxyAPI (ключ: OPENAI_API_KEY или PROXYAPI_API_KEY)
OPENAI_API_KEY = (
    os.getenv("OPENAI_API_KEY")
    or os.getenv("PROXYAPI_API_KEY")
    or ""
)
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

# ProxyAPI: https://proxyapi.ru — OpenAI без VPN, оплата в ₽
PROXYAPI_ENABLED = os.getenv("PROXYAPI_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)
PROXYAPI_BASE_URL = os.getenv(
    "PROXYAPI_BASE_URL",
    "https://api.proxyapi.ru/openai/v1",
)
# Если PROXYAPI_ENABLED — по умолчанию ProxyAPI; иначе официальный OpenAI
# или явный OPENAI_BASE_URL
_default_base = PROXYAPI_BASE_URL if PROXYAPI_ENABLED else None
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") or _default_base

SALON_TIMEZONE = os.getenv("SALON_TIMEZONE", "Asia/Yekaterinburg")
TZ = ZoneInfo(SALON_TIMEZONE)

DB_PATH = os.getenv("DB_PATH", "bookings.db")
MEMORY_DIR = os.getenv("MEMORY_DIR", "./memory")
KNOWLEDGE_FILE = os.getenv("KNOWLEDGE_FILE", "./knowledge_base/salon_strijka.txt")

HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "10"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))
TOP_K = int(os.getenv("TOP_K", "4"))


def _parse_admin_ids(*values: str) -> set[int]:
    ids: set[int] = set()
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part.lstrip("-").isdigit():
                ids.add(int(part))
    return ids


def _parse_usernames(*values: str) -> list[str]:
    result: list[str] = []
    for value in values:
        for part in value.split(","):
            name = part.strip().lstrip("@").lower()
            if name and not name.lstrip("-").isdigit():
                result.append(name)
    return result


_accounts = os.getenv("ADMIN_ACCOUNTS", "")
ADMIN_CHAT_IDS = _parse_admin_ids(
    _accounts, os.getenv("ADMIN_CHAT_ID", ""), os.getenv("ADMIN_CHAT_IDS", "")
)
ADMIN_USERNAMES = _parse_usernames(_accounts, os.getenv("ADMIN_USERNAMES", ""))

GOOGLE_CALENDAR_ENABLED = os.getenv("GOOGLE_CALENDAR_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
)
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")


def validate() -> None:
    missing: list[str] = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN (или TELEGRAM_BOT_TOKEN)")
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY (или PROXYAPI_API_KEY)")
    if missing:
        raise SystemExit(
            "Не заданы обязательные переменные окружения: "
            + ", ".join(missing)
            + ".\nСкопируйте .env.example в .env и заполните значения."
        )


def openai_client_kwargs() -> dict:
    """Аргументы для AsyncOpenAI / OpenAI: ключ + base_url ProxyAPI."""
    kwargs: dict = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    return kwargs


def openai_endpoint_label() -> str:
    if OPENAI_BASE_URL and "proxyapi" in OPENAI_BASE_URL.lower():
        return f"ProxyAPI ({OPENAI_BASE_URL})"
    if OPENAI_BASE_URL:
        return OPENAI_BASE_URL
    return "OpenAI (api.openai.com)"
