from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from poker_bot.cash import Cash
from poker_bot.clubs import Clubs
from poker_bot.db import operations
from poker_bot.money import ClubError


@pytest.fixture
def table(db):
    clubs, cash = Clubs(db), Cash(db)
    club = clubs.create(1, "Антон", "Клуб")
    for actor, name in [(2, "Борис"), (3, "Вика")]:
        clubs.join(actor, name, clubs.invite(1, club))
    roster = clubs.roster(1, club)
    game = cash.create(1, club, "Вечер", datetime.now(UTC).isoformat(), "Дома", 100000, "create-test")
    for member in roster:
        cash.add_player(1, game, member["id"])
    cash.transition(1, game, "active")
    return cash, clubs, club, game, [m["id"] for m in roster]


def complete(table):
    cash, _, _, game, ids = table
    for member in ids:
        cash.record(1, game, member, "buyin", 100000, f"buy-{member}")
    cash.record(1, game, ids[0], "rebuy", 50000, "rebuy-anton")
    for member, amount in zip(ids, [200000, 70000, 80000], strict=True):
        cash.record(1, game, member, "cashout", amount, f"out-{member}")
    cash.transition(1, game, "reconciling")
    cash.transition(1, game, "completed")


def test_control_example_and_closed_buttons(table):
    complete(table)
    cash, _, club, game, ids = table
    assert [r["profit"] for r in cash.get(1, game)["players"]] == [50000, -30000, -20000]
    assert sum(r["profit"] for r in cash.stats(1, club)["ranking"]) == 0
    with pytest.raises(ClubError):
        cash.record(1, game, ids[0], "rebuy", 1000, "late")
    with pytest.raises(ClubError):
        cash.add_player(1, game, ids[0])
    cash.transition(1, game, "completed")
    assert cash.stats(1, club)["ranking"][0]["games"] == 1


def test_missing_and_zero_cashout_and_balance(table):
    cash, _, _, game, ids = table
    for member in ids:
        cash.record(1, game, member, "buyin", 100000, f"buy-{member}")
    assert cash.get(1, game)["players"][0]["profit"] is None
    cash.transition(1, game, "reconciling")
    with pytest.raises(ClubError, match="каждого"):
        cash.transition(1, game, "completed")
    for member, amount in zip(ids, [299900, 0, 0], strict=True):
        cash.record(1, game, member, "cashout", amount, f"out-{member}")
    with pytest.raises(ClubError, match="1 RUB"):
        cash.transition(1, game, "completed")
    assert cash.get(1, game)["status"] == "reconciling"


def test_concurrent_confirmation_and_repeated_operation(table):
    cash, _, _, game, ids = table
    op = cash.record(2, game, ids[1], "buyin", 100000, "own-request")
    assert cash.get(2, game)["players"][1]["invested"] == 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: cash.decide(1, op, True), range(8)))
    assert cash.get(2, game)["players"][1]["invested"] == 100000
    assert cash.record(2, game, ids[1], "buyin", 100000, "own-request") == op
    with pytest.raises(ClubError, match="другой"):
        cash.record(2, game, ids[1], "buyin", 200000, "own-request")
    with pytest.raises(ClubError):
        cash.decide(1, op, False)


def test_rights_and_double_buyin(table):
    cash, clubs, _club, game, ids = table
    other = clubs.create(9, "Чужой", "Чужой клуб")
    guest = clubs.guest(9, other, "Гость")
    for action in [lambda: cash.get(9, game), lambda: cash.add_player(1, game, guest),
                   lambda: cash.record(2, game, ids[0], "buyin", 1000, "forged"),
                   lambda: cash.record(2, game, ids[1], "cashout", 0, "forged"),
                   lambda: cash.transition(2, game, "cancelled")]:
        with pytest.raises(ClubError):
            action()
    cash.record(1, game, ids[0], "buyin", 100000, "buy")
    with pytest.raises(ClubError):
        cash.record(1, game, ids[0], "buyin", 100000, "buy-again")
    with pytest.raises(ClubError):
        cash.record(1, game, ids[0], "rebuy", 0, "zero")
    with pytest.raises(ClubError):
        cash.record(1, game, ids[0], "rebuy", -50, "negative")
    cash.record(1, game, ids[0], "cashout", 0, "zero-out")
    with pytest.raises(ClubError):
        cash.record(1, game, ids[0], "rebuy", 50000, "after-out")


def test_correction_recalculates_and_rolls_back_on_imbalance(table, db):
    complete(table)
    cash, _, club, game, ids = table
    original = {o["member_id"]: o["id"] for o in cash.get(1, game)["operations"] if o["kind"] == "cashout"}
    with pytest.raises(ClubError):
        cash.correct(1, game, {original[ids[0]]:190000}, "Ошибка пересчёта", "failed-fix")
    assert cash.stats(1, club)["ranking"][0]["profit"] == 50000
    cash.correct(1, game, {original[ids[0]]:190000, original[ids[1]]:80000}, "Перепутали фишки", "valid-fix")
    cash.correct(1, game, {original[ids[0]]:190000, original[ids[1]]:80000}, "Перепутали фишки", "valid-fix")
    assert cash.stats(1, club)["ranking"][0]["profit"] == 40000
    with db.tx() as c:
        assert c.execute(select(operations.c.status).where(operations.c.id == original[ids[0]])).scalar_one() == "void"
    assert cash.get(1, game)["revision"] == 1


def test_stats_empty_month_and_cancelled(table):
    cash, _, club, _game, ids = table
    assert cash.stats(1, club)["ranking"] == []
    complete(table)
    old_date=(datetime.now(UTC).replace(day=1)-timedelta(days=2)).isoformat()
    old=cash.create(1, club, "Старый вечер", old_date, "", 1000, "old-game")
    cash.add_player(1, old, ids[0]);cash.transition(1, old, "active")
    cash.record(1, old, ids[0], "buyin", 1000, "old-buy")
    cash.record(1, old, ids[0], "cashout", 1000, "old-out")
    cash.transition(1, old, "reconciling");cash.transition(1, old, "completed")
    assert cash.stats(1, club, "all")["ranking"][0]["games"] == 2
    assert cash.stats(1, club, "month")["ranking"][0]["games"] == 1
    with pytest.raises(ClubError):
        cash.stats(1, club, "invalid")
