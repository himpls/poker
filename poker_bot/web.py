"""Webhook-приложение: обработка завершается ДО ответа Telegram, без фоновых задач."""

import hmac
import os
from functools import lru_cache

from aiogram import Bot
from aiogram.types import Update
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from .db import Database
from .telegram_ui import build_dispatcher

load_dotenv()


@lru_cache
def runtime():
    url = os.environ["DATABASE_URL"]
    if os.getenv("VERCEL") and not url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("В serverless-режиме требуется постоянная база PostgreSQL.")
    return build_dispatcher(Database(url))


def create_app(process_update=None, database=None, demo=False):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    from .mini_api import install_mini_app

    install_mini_app(app, database, demo)

    @app.get("/health")
    async def health():
        return {"status": "ok"}  # Живость обработчика, не проверка подключения к БД.

    @app.post("/telegram/webhook")
    async def webhook(request: Request):
        expected = os.getenv("WEBHOOK_SECRET", "")
        received = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not expected:
            raise HTTPException(503, "Webhook is not configured")
        if not hmac.compare_digest(received.encode(), expected.encode()):
            raise HTTPException(403, "Forbidden")
        body = await request.body()
        if len(body) > 1024 * 1024:
            raise HTTPException(413, "Update too large")
        try:
            event = Update.model_validate_json(body)
        except ValidationError:
            raise HTTPException(400, "Invalid update") from None
        if process_update:
            await process_update(event)
        else:
            try:
                async with Bot(os.environ["BOT_TOKEN"]) as bot:
                    await runtime().feed_update(bot, event)
            except Exception:  # noqa: BLE001 — граница HTTP: скрываем секреты, Telegram повторит доставку.
                # Внешний ответ не раскрывает токен, строку подключения и данные игрока.
                raise HTTPException(503, "Update processing failed; retry later") from None
        return {"ok": True}

    return app


app = create_app()
