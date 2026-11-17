from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
from aiogram import Bot
from aiogram.types import Update
from fastapi.testclient import TestClient

from poker_bot.clubs import Clubs
from poker_bot.mini_launcher import app_url, configure_menu
from poker_bot.telegram_ui import build_dispatcher
from poker_bot.web import create_app
from test_mini_app import TOKEN, signed


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["/start", "Create a club", "/start join_invitation-token"])
async def test_dispatcher_opens_app_without_creating_or_joining_clubs(db, monkeypatch, text):
    monkeypatch.setenv("MINI_APP_URL", "https://club.example/?lang=ru")
    event = Update.model_validate({"update_id": 1, "message": {
        "message_id": 1, "date": datetime.now(UTC), "text": text,
        "chat": {"id": 123, "type": "private"},
        "from": {"id": 123, "is_bot": False, "first_name": "Player"}}})
    async with Bot(TOKEN) as bot:
        with patch.object(bot, "send_message", new=AsyncMock()) as send:
            await build_dispatcher(db).feed_update(bot, event)
    send.assert_awaited_once()
    buttons = send.await_args.kwargs["reply_markup"].inline_keyboard
    assert len(buttons) == len(buttons[0]) == 1
    assert buttons[0][0].callback_data is None
    query = parse_qs(urlsplit(buttons[0][0].web_app.url).query)
    assert query["lang"] == ["ru"]
    assert query.get("invite") == (["invitation-token"] if "join_" in text else None)
    assert Clubs(db).list(123) == []


@pytest.mark.asyncio
async def test_menu_and_unconfigured_launcher(db, monkeypatch):
    monkeypatch.setenv("MINI_APP_URL", "https://club.example/")
    bot = AsyncMock()
    await configure_menu(bot)
    assert bot.set_chat_menu_button.await_args.kwargs["menu_button"].web_app.url == "https://club.example/"
    for url in ["", "http://club.example/", "https://", "https://user:password@club.example/"]:
        monkeypatch.setenv("MINI_APP_URL", url)
        assert app_url() is None


@pytest.mark.asyncio
async def test_old_callback_cannot_change_club(db, monkeypatch):
    monkeypatch.setenv("MINI_APP_URL", "https://club.example/")
    event = Update.model_validate({"update_id": 2, "callback_query": {
        "id": "old", "chat_instance": "chat", "data": "old:0",
        "from": {"id": 123, "is_bot": False, "first_name": "Player"},
        "message": {"message_id": 1, "date": datetime.now(UTC),
                    "chat": {"id": 123, "type": "private"}}}})
    async with Bot(TOKEN) as bot:
        with patch.object(bot, "send_message", new=AsyncMock()) as send, \
             patch.object(bot.session, "make_request", new=AsyncMock(return_value=True)):
            await build_dispatcher(db).feed_update(bot, event)
    send.assert_awaited_once()
    assert Clubs(db).list(123) == []


def test_invitation_link_joins_only_through_authenticated_app(db, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TOKEN)
    monkeypatch.setenv("BOT_USERNAME", "poker_test_bot")
    clubs = Clubs(db)
    club = clubs.create(1, "Owner", "Club")
    with TestClient(create_app(database=db)) as client:
        invite = client.post(f"/api/clubs/{club}/invite", json={},
                             headers={"Authorization": "tma " + signed(1)}).json()
        assert invite["url"] == f"https://t.me/poker_test_bot?start=join_{invite['token']}"
        body = {"token": invite["token"]}
        assert client.post("/api/join", json=body).status_code == 401
        assert clubs.list(2) == []
        headers = {"Authorization": "tma " + signed(2)}
        assert client.post("/api/join", json=body, headers=headers).json()["id"] == club
        assert client.post("/api/join", json=body, headers=headers).json()["id"] == club
        assert len(clubs.roster(1, club)) == 2
