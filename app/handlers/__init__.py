"""Регистрация роутеров хэндлеров."""
from aiogram import Dispatcher, Router

from app.handlers import bookings, chat, documents, start


def setup_routers(dp: Dispatcher) -> None:
    root = Router(name="root")
    # порядок: команды/колбэки/документы раньше общего text
    root.include_router(start.router)
    root.include_router(bookings.router)
    root.include_router(documents.router)
    root.include_router(chat.router)
    dp.include_router(root)
