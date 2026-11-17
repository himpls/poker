"""Запуск одного экземпляра бота в Amvera с постоянным хранилищем."""

import asyncio
import os

from aiogram import Bot
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv

from .db import Database
from .telegram_ui import build_dispatcher
from .mini_launcher import configure_menu


async def serve():
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Добавьте BOT_TOKEN в секреты приложения Amvera.")
    url = os.getenv("DATABASE_URL", "sqlite:////data/poker.db")
    os.environ["DATABASE_URL"] = url
    # Миграции завершаются до получения первого update.
    command.upgrade(Config("alembic.ini"), "head")
    db = Database(url)
    dispatcher = build_dispatcher(db)
    try:
        async with Bot(token) as bot:
            await configure_menu(bot)
            await bot.delete_webhook(drop_pending_updates=False)
            # Telegram serves only as an entry point; actions run through the Mini App API.
            await dispatcher.start_polling(
                bot,
                allowed_updates=dispatcher.resolve_used_update_types(),
                handle_as_tasks=False,
                close_bot_session=False,
            )
    finally:
        db.engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass
