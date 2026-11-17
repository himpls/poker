"""Локальный просмотр Mini App без токена, только на 127.0.0.1 и в отдельной базе."""
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config

from .cash import Cash
from .clubs import Clubs
from .db import Database


def seed(db):
    service, cash = Clubs(db), Cash(db)
    if service.list(1):
        return
    club = service.create(1, "Антон", "Пятничный клуб", key="demo-club")
    invitation = service.invite(1, club)
    for actor, name in enumerate(["Борис", "Вика", "Максим", "Даша", "Никита"], start=2):
        service.join(actor, name, invitation)
    roster = service.roster(1, club)
    current = datetime.now(UTC)
    for index, payouts in enumerate([[200000, 70000, 80000],
                                    [180000, 120000, 50000, 160000, 90000, 0]]):
        game = cash.create(1, club, ["Тёплый вечер", "Пятница у Макса"][index],
            (current-timedelta(days=14-index*7)).isoformat(), "У друзей", 100000, f"demo-game-{index}")
        for member in roster[:len(payouts)]:
            cash.add_player(1, game, member["id"])
        cash.transition(1, game, "active")
        for member, payout in zip(roster, payouts, strict=False):
            cash.record(1, game, member["id"], "buyin", 100000, f"demo-{index}-{member['id']}-buy")
            if index == 0 and member["tg_id"] == 1:
                cash.record(1, game, member["id"], "rebuy", 50000, "demo-first-rebuy")
            cash.record(1, game, member["id"], "cashout", payout, f"demo-{index}-{member['id']}-out")
        cash.transition(1, game, "reconciling")
        cash.transition(1, game, "completed")
    game = cash.create(1, club, "Вечер в своём кругу", current.isoformat(), "У Антона · кухня",
        100000, "demo-live")
    for member in roster[:5]:
        cash.add_player(1, game, member["id"])
    cash.transition(1, game, "active")
    for member in roster[:5]:
        cash.record(1, game, member["id"], "buyin", 100000, f"demo-live-{member['id']}")
    cash.record(1, game, roster[0]["id"], "rebuy", 50000, "demo-live-rebuy")
    cash.record(2, game, roster[1]["id"], "rebuy", 50000, "demo-pending")
    cash.create(1, club, "Следующая пятница", (current+timedelta(days=7)).isoformat(),
        "Место решим в чате", 100000, "demo-next")


def main():
    import uvicorn
    from .web import create_app

    url = f"sqlite:///{(Path(__file__).parent.parent / 'data' / 'demo.db').resolve().as_posix()}"
    # Процесс демопросмотра всегда выбирает отдельный файл, независимо от рабочего .env.
    os.environ["DATABASE_URL"] = url
    command.upgrade(Config("alembic.ini"), "head")
    db = Database(url)
    seed(db)
    print("Mini App demo: http://127.0.0.1:8765 (separate database, Ctrl+C to stop)")
    try:
        uvicorn.run(create_app(database=db, demo=True), host="127.0.0.1", port=8765, log_level="warning")
    finally:
        db.engine.dispose()


if __name__ == "__main__":
    main()
