"""Логика расписания: свободные слоты и создание записи (+ Google Calendar)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app import config
from app.db import repository as db
from app.services import google_calendar
from app import salon_data as kb


def _today() -> datetime:
    return datetime.now(config.TZ).replace(microsecond=0)


def parse_date(date_str: str) -> datetime | None:
    s = (date_str or "").strip().lower()
    now = _today()
    if s in ("today", "сегодня"):
        return now
    if s in ("tomorrow", "завтра"):
        return now + timedelta(days=1)
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m"):
        try:
            dt = datetime.strptime(s, fmt)
            if fmt == "%d.%m":
                dt = dt.replace(year=now.year)
            return dt.replace(tzinfo=config.TZ)
        except ValueError:
            continue
    return None


def _in_lunch(hour_start: datetime, hour_end: datetime) -> bool:
    lunch_start = hour_start.replace(hour=kb.LUNCH_START_HOUR, minute=0)
    lunch_end = hour_start.replace(hour=kb.LUNCH_END_HOUR, minute=0)
    return hour_start < lunch_end and hour_end > lunch_start


def available_slots(date_str: str, service_name: str) -> dict[str, Any]:
    day = parse_date(date_str)
    if day is None:
        return {
            "ok": False,
            "error": (
                "Не удалось распознать дату. "
                "Уточните в формате ГГГГ-ММ-ДД, 'сегодня' или 'завтра'."
            ),
        }

    service = kb.find_service(service_name)
    if service is None:
        return {
            "ok": False,
            "error": f"Услуга «{service_name}» не найдена.",
            "services": kb.services_text(),
        }
    _, _, duration = service

    day = day.replace(minute=0, second=0, microsecond=0)
    open_dt = day.replace(hour=kb.OPEN_HOUR)
    close_dt = day.replace(hour=kb.CLOSE_HOUR)
    now = _today()

    existing = db.get_bookings_for_day(day.strftime("%Y-%m-%d"))
    busy = [
        (datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"]))
        for b in existing
    ]

    slots: list[str] = []
    step = timedelta(minutes=kb.SLOT_STEP_MINUTES)
    cur = open_dt
    while cur + timedelta(minutes=duration) <= close_dt:
        slot_end = cur + timedelta(minutes=duration)
        conflict = _in_lunch(cur, slot_end) or cur < now
        for bs, be in busy:
            if cur < be and slot_end > bs:
                conflict = True
                break
        if not conflict:
            slots.append(cur.strftime("%H:%M"))
        cur += step

    return {
        "ok": True,
        "date": day.strftime("%Y-%m-%d"),
        "service": service[0],
        "slots": slots,
        "work_hours": f"{kb.OPEN_HOUR:02d}:00-{kb.CLOSE_HOUR:02d}:00",
        "lunch": f"{kb.LUNCH_START_HOUR:02d}:00-{kb.LUNCH_END_HOUR:02d}:00",
    }


def create_booking(
    chat_id: int,
    date_str: str,
    time_str: str,
    service_name: str,
    client_name: str,
    client_phone: str,
) -> dict[str, Any]:
    day = parse_date(date_str)
    if day is None:
        return {"ok": False, "error": "Не удалось распознать дату."}

    service = kb.find_service(service_name)
    if service is None:
        return {"ok": False, "error": f"Услуга «{service_name}» не найдена."}
    name, price, duration = service

    try:
        hh, mm = map(int, time_str.strip().split(":"))
    except ValueError:
        return {"ok": False, "error": "Не удалось распознать время. Укажите в формате ЧЧ:ММ."}

    start = day.replace(hour=hh, minute=mm, second=0, microsecond=0)
    end = start + timedelta(minutes=duration)

    open_dt = start.replace(hour=kb.OPEN_HOUR, minute=0)
    close_dt = start.replace(hour=kb.CLOSE_HOUR, minute=0)
    if start < open_dt or end > close_dt:
        return {
            "ok": False,
            "error": (
                f"Время вне часов работы "
                f"({kb.OPEN_HOUR:02d}:00-{kb.CLOSE_HOUR:02d}:00)."
            ),
        }
    if _in_lunch(start, end):
        return {
            "ok": False,
            "error": (
                f"Это время попадает на перерыв "
                f"({kb.LUNCH_START_HOUR:02d}:00-{kb.LUNCH_END_HOUR:02d}:00)."
            ),
        }
    if start < _today():
        return {"ok": False, "error": "Нельзя записаться на прошедшее время."}
    if db.has_overlap(start.isoformat(), end.isoformat()):
        return {"ok": False, "error": "Это время уже занято. Выберите другой слот."}
    if not client_name or not client_phone:
        return {"ok": False, "error": "Нужны имя и номер телефона клиента."}

    booking_id = db.add_booking(
        chat_id, name, start.isoformat(), end.isoformat(), client_name, client_phone
    )

    event_id = google_calendar.create_event(
        summary=f"{name} — {client_name}",
        description=(
            f"Услуга: {name}\nКлиент: {client_name}\nТелефон: {client_phone}"
        ),
        start=start,
        end=end,
    )
    if event_id:
        db.set_gcal_event(booking_id, event_id)

    return {
        "ok": True,
        "booking_id": booking_id,
        "service": name,
        "price": price,
        "date": start.strftime("%Y-%m-%d"),
        "time": start.strftime("%H:%M"),
        "client_name": client_name,
        "client_phone": client_phone,
        "gcal_synced": bool(event_id),
    }


def cancel_booking(
    chat_id: int,
    booking_id: int | None = None,
    date_str: str | None = None,
    time_str: str | None = None,
) -> dict[str, Any]:
    """Отменить запись клиента: SQLite + Google Calendar."""
    row = None
    if booking_id is not None:
        try:
            row = db.get_booking(int(booking_id), chat_id)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Некорректный id записи."}
    elif date_str and time_str:
        day = parse_date(date_str)
        if day is None:
            return {"ok": False, "error": "Не удалось распознать дату."}
        try:
            hh, mm = map(int, time_str.strip().split(":"))
        except ValueError:
            return {"ok": False, "error": "Не удалось распознать время. Укажите ЧЧ:ММ."}
        target_date = day.strftime("%Y-%m-%d")
        target_time = f"{hh:02d}:{mm:02d}"
        for b in db.get_upcoming_bookings(chat_id, "1970-01-01T00:00:00+00:00"):
            if int(b["chat_id"]) != int(chat_id):
                continue
            start = datetime.fromisoformat(b["start"])
            if (
                start.strftime("%Y-%m-%d") == target_date
                and start.strftime("%H:%M") == target_time
            ):
                row = b
                break
    else:
        # Одна активная запись — отменяем её
        now_iso = _today().isoformat()
        upcoming = db.get_upcoming_bookings(chat_id, now_iso)
        if len(upcoming) == 1:
            row = upcoming[0]
        elif len(upcoming) == 0:
            return {"ok": False, "error": "Активных записей нет."}
        else:
            return {
                "ok": False,
                "error": "Несколько записей. Уточните дату/время или id.",
                "bookings": [
                    {
                        "id": b["id"],
                        "service": b["service"],
                        "date": datetime.fromisoformat(b["start"]).strftime("%Y-%m-%d"),
                        "time": datetime.fromisoformat(b["start"]).strftime("%H:%M"),
                    }
                    for b in upcoming
                ],
            }

    if row is None:
        return {"ok": False, "error": "Запись не найдена или уже отменена."}

    gcal_id = row.get("gcal_event_id")
    gcal_deleted = False
    if gcal_id:
        gcal_deleted = bool(google_calendar.delete_event(gcal_id))

    deleted = db.delete_booking(int(row["id"]), chat_id)
    if not deleted:
        return {"ok": False, "error": "Не удалось удалить запись из базы."}

    start = datetime.fromisoformat(row["start"])
    return {
        "ok": True,
        "booking_id": row["id"],
        "service": row["service"],
        "date": start.strftime("%Y-%m-%d"),
        "time": start.strftime("%H:%M"),
        "client_name": row.get("client_name"),
        "gcal_deleted": gcal_deleted,
    }
