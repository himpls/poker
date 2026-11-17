from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from poker_bot.web import create_app


def test_webhook_auth_and_validation(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "test-secret")
    process = AsyncMock()
    with TestClient(create_app(process)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.post("/telegram/webhook", json={"update_id": 1}).status_code == 403
        headers = {"X-Telegram-Bot-Api-Secret-Token": "test-secret"}
        assert client.post("/telegram/webhook", content="broken", headers=headers).status_code == 400
        assert client.post("/telegram/webhook", json={"update_id": 1}, headers=headers).status_code == 200
    process.assert_awaited_once()


def test_widget_update_is_not_lost(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "test-secret")
    process = AsyncMock()
    event = {
        "update_id": 7,
        "widget_query": {
            "id": "w1",
            "from": {"id": 123, "is_bot": False, "first_name": "Антон"},
            "chat": {"id": 123, "type": "private", "first_name": "Антон"},
            "message_id": 10,
            "chat_instance": "instance",
            "type": {"type": "data"},
            "data": "refresh",
        },
    }
    with TestClient(create_app(process)) as client:
        response = client.post(
            "/telegram/webhook", json=event, headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"}
        )
    assert response.status_code == 200
    parsed = process.await_args.args[0]
    assert parsed.widget_query.data == "refresh"
    assert parsed.widget_query.from_user.id == 123


@pytest.mark.asyncio
async def test_persistent_create_flow_and_stale_button(db):
    from types import SimpleNamespace as Obj

    from poker_bot.telegram_ui import ClubUI

    bot = AsyncMock()
    user = Obj(id=111, full_name="Антон")
    message = Obj(chat=Obj(type="private", id=111), from_user=user, text="/start")
    ui = ClubUI(db)
    await ui.message(message, bot)
    state = ui.state(111)
    query = Obj(
        from_user=user,
        message=Obj(chat=Obj(id=111), message_id=5),
        data=f"{state['generation']}:0",
        answer=AsyncMock(),
    )
    await ui.callback(query, bot)
    assert ui.state(111)["step"] == "title"
    restarted = ClubUI(db)
    message.text = "Клуб друзей"
    await restarted.message(message, bot)
    assert restarted.state(111)["step"] == "currency"
    await restarted.callback(query, bot)
    assert query.answer.await_args.kwargs["show_alert"] is True
    state = restarted.state(111)
    query.data = f"{state['generation']}:0"
    await restarted.callback(query, bot)
    message.text = "Asia/Tashkent"
    await restarted.message(message, bot)
    state = restarted.state(111)
    query.data = f"{state['generation']}:0"
    await restarted.callback(query, bot)
    assert len(restarted.clubs.list(111)) == 1
