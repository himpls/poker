"""Клубы и права. Все публичные методы проверяют пользователя на сервере."""

import json
import secrets
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import insert, select, update

from .db import audit, clubs, games, members
from .money import CURRENCIES, ClubError


def now():
    return datetime.now(UTC).isoformat()


def name_checked(value):
    value = " ".join(value.split())
    if not 1 <= len(value) <= 80:
        raise ClubError("Название или имя должно содержать от 1 до 80 символов.")
    return value


def timezone_checked(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ClubError("Неизвестный часовой пояс. Пример: Asia/Tashkent.") from None
    return value


class Clubs:
    def __init__(self, db):
        self.db = db

    @staticmethod
    def require(connection, actor, club_id, roles=None):
        row = (
            connection.execute(select(members).where(members.c.club_id == club_id, members.c.tg_id == actor))
            .mappings()
            .first()
        )
        if not row or (roles and row["role"] not in roles):
            raise ClubError("Нет доступа к клубу или этому действию.")
        return dict(row)

    @staticmethod
    def log(connection, club_id, actor, reason, details):
        connection.execute(
            insert(audit).values(
                club_id=club_id,
                actor=actor,
                at=now(),
                reason=reason,
                details=json.dumps(details, ensure_ascii=False),
            )
        )

    def create(self, actor, actor_name, title, currency="RUB", tz="Asia/Tashkent", key=None):
        title = name_checked(title)
        actor_name = name_checked(actor_name)
        timezone_checked(tz)
        if currency not in CURRENCIES:
            raise ClubError("Выберите поддерживаемую валюту.")
        with self.db.tx() as c:
            # Telegram update_id может быть доставлен повторно после сетевого сбоя.
            if key:
                old = c.execute(
                    select(audit.c.club_id).where(audit.c.actor == actor, audit.c.reason == f"create:{key}")
                ).scalar_one_or_none()
                if old:
                    return old
            result = c.execute(
                insert(clubs).values(
                    name=title,
                    currency=currency,
                    timezone=tz,
                    invite=secrets.token_urlsafe(24),
                    season_start=datetime.now(ZoneInfo(tz)).date().replace(month=1, day=1).isoformat(),
                )
            )
            club_id = result.inserted_primary_key[0]
            c.execute(insert(members).values(club_id=club_id, tg_id=actor, name=actor_name, role="owner"))
            self.log(c, club_id, actor, f"create:{key}" if key else "create", {"name": title})
            return club_id

    def list(self, actor):
        with self.db.tx() as c:
            return [
                dict(r)
                for r in c.execute(
                    select(clubs.c.id, clubs.c.name, members.c.role)
                    .join(members)
                    .where(members.c.tg_id == actor)
                    .order_by(clubs.c.id)
                ).mappings()
            ]

    def get(self, actor, club_id):
        with self.db.tx() as c:
            member = self.require(c, actor, club_id)
            row = dict(c.execute(select(clubs).where(clubs.c.id == club_id)).mappings().one())
            # Приглашение выдаётся только через отдельное действие с проверкой роли.
            row.pop("invite")
            row["role"] = member["role"]
            return row

    def invite(self, actor, club_id, rotate=False):
        with self.db.tx() as c:
            self.require(c, actor, club_id, {"owner", "organizer"})
            if rotate:
                self.require(c, actor, club_id, {"owner"})
                c.execute(update(clubs).where(clubs.c.id == club_id).values(invite=secrets.token_urlsafe(24)))
                self.log(c, club_id, actor, "rotate_invite", {})
            return c.execute(select(clubs.c.invite).where(clubs.c.id == club_id)).scalar_one()

    def join(self, actor, actor_name, token):
        actor_name = name_checked(actor_name)
        with self.db.tx() as c:
            club_id = c.execute(select(clubs.c.id).where(clubs.c.invite == token)).scalar_one_or_none()
            if not club_id:
                raise ClubError("Приглашение недействительно. Попросите новую ссылку у организатора.")
            existing = c.execute(
                select(members.c.id).where(members.c.club_id == club_id, members.c.tg_id == actor)
            ).scalar_one_or_none()
            if not existing:
                c.execute(
                    insert(members).values(club_id=club_id, tg_id=actor, name=actor_name, role="member")
                )
                self.log(c, club_id, actor, "join", {})
            return club_id

    def roster(self, actor, club_id):
        with self.db.tx() as c:
            self.require(c, actor, club_id)
            return [
                dict(r)
                for r in c.execute(
                    select(members).where(members.c.club_id == club_id).order_by(members.c.id)
                ).mappings()
            ]

    def guest(self, actor, club_id, guest_name):
        with self.db.tx() as c:
            self.require(c, actor, club_id, {"owner", "organizer"})
            result = c.execute(
                insert(members).values(club_id=club_id, name=name_checked(guest_name), role="member")
            )
            self.log(c, club_id, actor, "guest_added", {"member_id": result.inserted_primary_key[0]})
            return result.inserted_primary_key[0]

    def role(self, actor, club_id, target_id, role):
        if role not in {"member", "organizer"}:
            raise ClubError("Доступные роли: участник и организатор.")
        with self.db.tx() as c:
            self.require(c, actor, club_id, {"owner"})
            target = (
                c.execute(select(members).where(members.c.id == target_id, members.c.club_id == club_id))
                .mappings()
                .first()
            )
            if not target or target["role"] == "owner" or target["tg_id"] is None:
                raise ClubError("Роль этого участника изменить нельзя.")
            c.execute(update(members).where(members.c.id == target_id).values(role=role))
            self.log(
                c,
                club_id,
                actor,
                "role_changed",
                {"member_id": target_id, "before": target["role"], "after": role},
            )

    def configure(self, actor, club_id, currency, tz):
        timezone_checked(tz)
        if currency not in CURRENCIES:
            raise ClubError("Выберите поддерживаемую валюту.")
        with self.db.tx() as c:
            self.require(c, actor, club_id, {"owner"})
            old = c.execute(select(clubs).where(clubs.c.id == club_id)).mappings().one()
            if (
                currency != old["currency"]
                and c.execute(select(games.c.id).where(games.c.club_id == club_id).limit(1)).first()
            ):
                raise ClubError("После создания игр валюту менять нельзя. Создайте отдельный клуб.")
            c.execute(update(clubs).where(clubs.c.id == club_id).values(currency=currency, timezone=tz))
            self.log(c, club_id, actor, "settings_changed", {"currency": currency, "timezone": tz})
