"""Хранилище записей на приём (SQLite)."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from app import config


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id      INTEGER NOT NULL,
                service      TEXT    NOT NULL,
                start        TEXT    NOT NULL,
                end          TEXT    NOT NULL,
                client_name  TEXT,
                client_phone TEXT,
                gcal_event_id TEXT,
                created_at   TEXT    DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cols = [r[1] for r in conn.execute("PRAGMA table_info(bookings)").fetchall()]
        if "gcal_event_id" not in cols:
            conn.execute("ALTER TABLE bookings ADD COLUMN gcal_event_id TEXT")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS known_users (
                username   TEXT PRIMARY KEY,
                chat_id    INTEGER NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Долговременный профиль клиента в этом Telegram-чате
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS client_profiles (
                chat_id      INTEGER PRIMARY KEY,
                client_name  TEXT,
                client_phone TEXT,
                updated_at   TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def remember_user(username: str, chat_id: int) -> None:
    if not username:
        return
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO known_users (username, chat_id, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(username) DO UPDATE SET
                chat_id = excluded.chat_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (username.lower(), chat_id),
        )


def get_chat_id_by_username(username: str) -> int | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT chat_id FROM known_users WHERE username = ?",
            (username.lower(),),
        ).fetchone()
        return int(row["chat_id"]) if row else None


def get_bookings_for_day(day_iso: str) -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM bookings WHERE substr(start, 1, 10) = ? ORDER BY start",
            (day_iso,),
        ).fetchall()
        return [dict(r) for r in rows]


def has_overlap(start_iso: str, end_iso: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM bookings WHERE start < ? AND end > ? LIMIT 1",
            (end_iso, start_iso),
        ).fetchone()
        return row is not None


def add_booking(
    chat_id: int,
    service: str,
    start_iso: str,
    end_iso: str,
    client_name: str,
    client_phone: str,
) -> int:
    with _conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO bookings (chat_id, service, start, end, client_name, client_phone)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (chat_id, service, start_iso, end_iso, client_name, client_phone),
        )
        booking_id = int(cur.lastrowid)

    upsert_client_profile(chat_id, client_name, client_phone)
    return booking_id


def upsert_client_profile(
    chat_id: int,
    client_name: str | None,
    client_phone: str | None,
) -> None:
    """Сохраняет/обновляет имя и телефон клиента для этого чата."""
    if not client_name and not client_phone:
        return
    with _conn() as conn:
        existing = conn.execute(
            "SELECT client_name, client_phone FROM client_profiles WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        name = (client_name or (existing["client_name"] if existing else None) or "").strip()
        phone = (client_phone or (existing["client_phone"] if existing else None) or "").strip()
        conn.execute(
            """
            INSERT INTO client_profiles (chat_id, client_name, client_phone, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id) DO UPDATE SET
                client_name = excluded.client_name,
                client_phone = excluded.client_phone,
                updated_at = CURRENT_TIMESTAMP
            """,
            (chat_id, name or None, phone or None),
        )


def get_client_profile(chat_id: int) -> dict[str, Any] | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM client_profiles WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        return dict(row) if row else None


def get_last_booking_contacts(chat_id: int) -> dict[str, Any] | None:
    """Fallback: имя/телефон из последней записи, если профиля ещё нет."""
    with _conn() as conn:
        row = conn.execute(
            """
            SELECT client_name, client_phone FROM bookings
            WHERE chat_id = ? AND client_name IS NOT NULL AND client_name != ''
            ORDER BY id DESC LIMIT 1
            """,
            (chat_id,),
        ).fetchone()
        return dict(row) if row else None


def set_gcal_event(booking_id: int, event_id: str) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE bookings SET gcal_event_id = ? WHERE id = ?",
            (event_id, booking_id),
        )


def get_upcoming_bookings(chat_id: int, now_iso: str) -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM bookings WHERE chat_id = ? AND end >= ? ORDER BY start",
            (chat_id, now_iso),
        ).fetchall()
        return [dict(r) for r in rows]


def get_booking(booking_id: int, chat_id: int) -> dict[str, Any] | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM bookings WHERE id = ? AND chat_id = ?",
            (booking_id, chat_id),
        ).fetchone()
        return dict(row) if row else None


def delete_booking(booking_id: int, chat_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM bookings WHERE id = ? AND chat_id = ?",
            (booking_id, chat_id),
        )
        return cur.rowcount > 0


def backfill_client_profiles() -> int:
    """Заполнить профили из уже существующих записей (один раз при старте)."""
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT chat_id, client_name, client_phone FROM bookings
            WHERE client_name IS NOT NULL AND trim(client_name) != ''
            ORDER BY id ASC
            """
        ).fetchall()
    count = 0
    for row in rows:
        upsert_client_profile(row["chat_id"], row["client_name"], row["client_phone"])
        count += 1
    return count
