"""Опциональная интеграция с Google Calendar.

Включается при GOOGLE_CALENDAR_ENABLED=true и наличии credentials.json.
Иначе функции — безопасные no-op.
"""
from __future__ import annotations

import logging
from datetime import datetime

from app import config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def is_enabled() -> bool:
    return bool(config.GOOGLE_CALENDAR_ENABLED)


def _get_service():
    import os

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(config.GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(config.GOOGLE_TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                config.GOOGLE_CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(config.GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def create_event(
    summary: str,
    description: str,
    start: datetime,
    end: datetime,
) -> str | None:
    if not is_enabled():
        logger.warning(
            "Google Calendar выключен (GOOGLE_CALENDAR_ENABLED=false) — событие не создаём"
        )
        return None
    logger.info("Создаю событие Google Calendar: %s %s→%s", summary, start, end)
    try:
        service = _get_service()
        # dateTime без смещения + timeZone — Google сам считает локальное время салона
        event = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": start.replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": config.SALON_TIMEZONE,
            },
            "end": {
                "dateTime": end.replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": config.SALON_TIMEZONE,
            },
        }
        created = (
            service.events()
            .insert(calendarId=config.GOOGLE_CALENDAR_ID, body=event)
            .execute()
        )
        event_id = created.get("id")
        logger.info("Google Calendar: событие создано id=%s", event_id)
        return event_id
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось создать событие в Google Calendar")
        return None


def delete_event(event_id: str) -> bool:
    if not is_enabled() or not event_id:
        return False
    logger.info("Удаляю событие Google Calendar id=%s", event_id)
    try:
        service = _get_service()
        service.events().delete(
            calendarId=config.GOOGLE_CALENDAR_ID, eventId=event_id
        ).execute()
        logger.info("Google Calendar: событие удалено id=%s", event_id)
        return True
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось удалить событие из Google Calendar")
        return False
