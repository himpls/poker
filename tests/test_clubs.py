from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, insert, select

from poker_bot.clubs import Clubs
from poker_bot.db import audit, games, members
from poker_bot.money import ClubError, money, parse_money


def test_create_and_join_are_idempotent(db):
    service = Clubs(db)
    club = service.create(111, "Антон", "Друзья", key="same-update")
    assert service.create(111, "Антон", "Друзья", key="same-update") == club
    invitation = service.invite(111, club)
    with ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(lambda _: service.join(222, "Борис", invitation), range(8)))
    assert result == [club] * 8
    assert len(service.roster(111, club)) == 2
    assert service.get(222, club)["role"] == "member"
    assert "invite" not in service.get(222, club)


def test_club_isolation_and_roles(db):
    service = Clubs(db)
    first = service.create(1, "Владелец", "Первый")
    second = service.create(3, "Другой", "Второй")
    service.join(2, "Участник", service.invite(1, first))
    with pytest.raises(ClubError):
        service.get(2, second)
    with pytest.raises(ClubError):
        service.invite(2, first)
    target = next(r["id"] for r in service.roster(1, first) if r["tg_id"] == 2)
    with pytest.raises(ClubError):
        service.role(3, second, target, "organizer")
    service.role(1, first, target, "organizer")
    assert service.invite(2, first)
    with pytest.raises(ClubError):
        service.configure(2, first, "USD", "UTC")
    with pytest.raises(ClubError):
        service.role(2, first, target, "member")
    owner = next(r["id"] for r in service.roster(1, first) if r["tg_id"] == 1)
    with pytest.raises(ClubError):
        service.role(1, first, owner, "member")
    with db.tx() as c:
        assert c.execute(select(func.count()).select_from(audit)).scalar_one() >= 4


def test_rotation_and_guest(db):
    service = Clubs(db)
    club = service.create(1, "Антон", "Клуб")
    old = service.invite(1, club)
    new = service.invite(1, club, rotate=True)
    assert old != new
    with pytest.raises(ClubError):
        service.join(2, "Борис", old)
    service.join(2, "Борис", new)
    with pytest.raises(ClubError):
        service.guest(2, club, "Гость")
    guest = service.guest(1, club, "Вика")
    with db.tx() as c:
        assert c.execute(select(members.c.tg_id).where(members.c.id == guest)).scalar_one() is None
    with pytest.raises(ClubError):
        service.role(1, club, guest, "organizer")


def test_settings_currency_locked_after_game(db):
    service = Clubs(db)
    club = service.create(1, "Антон", "Клуб")
    service.configure(1, club, "UZS", "Asia/Tashkent")
    with db.tx() as c:
        c.execute(
            insert(games).values(
                club_id=club,
                title="Вечер",
                starts_at="2026-11-17T15:00:00+00:00",
                location="Дома",
                buyin=100000,
                author=1,
                status="planned",
            )
        )
    with pytest.raises(ClubError):
        service.configure(1, club, "USD", "UTC")
    assert service.get(1, club)["currency"] == "UZS"
    service.configure(1, club, "UZS", "UTC")
    with pytest.raises(ClubError):
        service.configure(1, club, "UZS", "Nowhere/Nowhere")


@pytest.mark.parametrize(
    "value,currency,amount", [("1 250,50", "RUB", 125050), ("500", "JPY", 500), ("0", "UZS", 0)]
)
def test_money_precision(value, currency, amount):
    assert parse_money(value, currency) == amount
    assert currency in money(amount, currency)


@pytest.mark.parametrize(
    "value,currency", [("1.5", "JPY"), ("0.001", "USD"), ("-20", "RUB"), ("NaN", "RUB"), ("1e8", "UZS")]
)
def test_money_rejects_invalid(value, currency):
    with pytest.raises(ClubError):
        parse_money(value, currency)
