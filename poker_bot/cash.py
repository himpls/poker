"""Учёт cash-игр. Все изменения выполняются под транзакционной блокировкой."""
import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import insert, select, update

from .clubs import Clubs, name_checked, now
from .db import audit, clubs, games, members, operations, players
from .money import MAX_AMOUNT, ClubError

STAFF = {"owner", "organizer"}


class Cash:
    def __init__(self, db):
        self.db = db

    @staticmethod
    def game(c, actor, game_id, roles=None):
        row = c.execute(select(games).where(games.c.id == game_id)).mappings().first()
        if not row:
            raise ClubError("Игра не найдена.")
        member = Clubs.require(c, actor, row["club_id"], roles)
        return dict(row), member

    @staticmethod
    def totals(c, game_id):
        roster = c.execute(select(members.c.id, members.c.name, members.c.tg_id)
            .join(players, players.c.member_id == members.c.id)
            .where(players.c.game_id == game_id).order_by(members.c.id)).mappings()
        rows = {r["id"]: {**dict(r), "invested": 0, "cashout": None, "profit": None} for r in roster}
        for op in c.execute(select(operations).where(operations.c.game_id == game_id,
                operations.c.status == "confirmed")).mappings():
            if op["kind"] == "cashout":
                rows[op["member_id"]]["cashout"] = op["amount"]
            else:
                rows[op["member_id"]]["invested"] += op["amount"]
        for r in rows.values():
            if r["cashout"] is not None:
                r["profit"] = r["cashout"] - r["invested"]
        return list(rows.values())

    def list(self, actor, club_id):
        with self.db.tx() as c:
            Clubs.require(c, actor, club_id)
            return [dict(r) for r in c.execute(select(games).where(games.c.club_id == club_id)
                .order_by(games.c.starts_at.desc(), games.c.id.desc())).mappings()]

    def create(self, actor, club_id, title, starts_at, location, buyin, key):
        if not isinstance(buyin, int) or not 0 < buyin <= MAX_AMOUNT:
            raise ClubError("Стандартный вход должен быть положительным.")
        try:
            instant = datetime.fromisoformat(starts_at)
            if instant.tzinfo is None:
                raise ValueError
        except (ValueError, TypeError):
            raise ClubError("Укажите дату со временем и часовым поясом.") from None
        if len(location) > 250:
            raise ClubError("Место: не более 250 символов.")
        with self.db.tx() as c:
            Clubs.require(c, actor, club_id, STAFF)
            old = c.execute(select(audit.c.game_id).where(audit.c.actor == actor,
                audit.c.club_id == club_id, audit.c.reason == f"game:{key}")).scalar_one_or_none()
            if old:
                return old
            result = c.execute(insert(games).values(club_id=club_id, title=name_checked(title),
                starts_at=instant.astimezone(UTC).isoformat(), location=location.strip(),
                buyin=buyin, author=actor, status="planned"))
            game_id = result.inserted_primary_key[0]
            c.execute(insert(audit).values(game_id=game_id, club_id=club_id, actor=actor,
                at=now(), reason=f"game:{key}", details="{}"))
            return game_id

    def add_player(self, actor, game_id, member_id):
        with self.db.tx() as c:
            game, _ = self.game(c, actor, game_id, STAFF)
            if game["status"] not in {"planned", "active"}:
                raise ClubError("Добавлять игроков можно до начала или во время игры.")
            target = c.execute(select(members.c.id).where(members.c.id == member_id,
                members.c.club_id == game["club_id"])).scalar_one_or_none()
            if not target:
                raise ClubError("Участник не принадлежит клубу.")
            if not c.execute(select(players).where(players.c.game_id == game_id,
                    players.c.member_id == member_id)).first():
                c.execute(insert(players).values(game_id=game_id, member_id=member_id))

    @staticmethod
    def check_operation(c, game, member_id, kind):
        if game["status"] not in {"active", "reconciling"}:
            raise ClubError("Игра не принимает операции.")
        row = next((r for r in Cash.totals(c, game["id"]) if r["id"] == member_id), None)
        if not row:
            raise ClubError("Сначала добавьте участника в игру.")
        if row["cashout"] is not None:
            raise ClubError("Игрок уже закончил. Исправления выполняются отдельно.")
        if kind == "buyin" and row["invested"]:
            raise ClubError("Первый вход уже записан. Выберите докупку.")
        if kind != "buyin" and not row["invested"]:
            raise ClubError("Сначала запишите первый вход.")
        if game["status"] == "reconciling" and kind != "cashout":
            raise ClubError("При сверке можно записывать только кэшауты.")

    def record(self, actor, game_id, member_id, kind, amount, key):
        if kind not in {"buyin", "rebuy", "cashout"}:
            raise ClubError("Неизвестный вид операции.")
        if not isinstance(amount, int) or not 0 <= amount <= MAX_AMOUNT or (kind != "cashout" and not amount):
            raise ClubError("Вход и докупка должны быть положительными; кэшаут может быть нулевым.")
        with self.db.tx() as c:
            game, member = self.game(c, actor, game_id)
            if member["role"] not in STAFF and (member_id != member["id"] or kind == "cashout"):
                raise ClubError("Можно подать заявку только на собственный вход или докупку.")
            request_key = f"{actor}:{key}"
            old = c.execute(select(operations).where(operations.c.key == request_key)).mappings().first()
            if old:
                if (old["game_id"], old["member_id"], old["kind"], old["amount"]) != (
                        game_id, member_id, kind, amount):
                    raise ClubError("Ключ запроса уже использован для другой операции.")
                return old["id"]
            self.check_operation(c, game, member_id, kind)
            confirmed = member["role"] in STAFF
            result = c.execute(insert(operations).values(game_id=game_id, member_id=member_id,
                kind=kind, amount=amount, status="confirmed" if confirmed else "pending", author=actor,
                created_at=now(), confirmed_by=actor if confirmed else None,
                confirmed_at=now() if confirmed else None, key=request_key))
            return result.inserted_primary_key[0]

    def decide(self, actor, operation_id, accept):
        with self.db.tx() as c:
            op = c.execute(select(operations).where(operations.c.id == operation_id)).mappings().first()
            if not op:
                raise ClubError("Операция не найдена.")
            game, _ = self.game(c, actor, op["game_id"], STAFF)
            wanted = "confirmed" if accept else "rejected"
            if op["status"] == wanted:
                return
            if op["status"] != "pending" or game["status"] not in {"active", "reconciling"}:
                raise ClubError("Заявка уже обработана или игра закрыта.")
            if accept:
                self.check_operation(c, game, op["member_id"], op["kind"])
            c.execute(update(operations).where(operations.c.id == operation_id).values(
                status=wanted, confirmed_by=actor, confirmed_at=now()))

    @staticmethod
    def balanced(c, game_id):
        rows = Cash.totals(c, game_id)
        if not rows or any(r["cashout"] is None or not r["invested"] for r in rows):
            raise ClubError("У каждого игрока должны быть вход и кэшаут, включая нулевой.")
        if c.execute(select(operations.c.id).where(operations.c.game_id == game_id,
                operations.c.status == "pending").limit(1)).first():
            raise ClubError("Сначала подтвердите или отклоните все заявки.")
        diff = sum(r["invested"] - r["cashout"] for r in rows)
        if diff:
            currency = c.execute(select(clubs.c.currency).join(games).where(games.c.id == game_id)).scalar_one()
            from .money import money
            raise ClubError(f"Баланс не сошёлся: входы минус кэшауты = {money(diff, currency)}. Проверьте записи.")

    def transition(self, actor, game_id, status):
        allowed = {"planned": {"active", "cancelled"}, "active": {"reconciling", "cancelled"},
            "reconciling": {"completed", "cancelled"}, "completed": set(), "cancelled": set()}
        with self.db.tx() as c:
            game, _ = self.game(c, actor, game_id, STAFF)
            if game["status"] == status:
                return
            if status not in allowed[game["status"]]:
                raise ClubError("Этот переход состояния игры уже недоступен.")
            if status == "completed":
                self.balanced(c, game_id)
            c.execute(update(games).where(games.c.id == game_id).values(status=status))
            Clubs.log(c, game["club_id"], actor, "game_status", {"game_id": game_id,
                "before": game["status"], "after": status})

    def get(self, actor, game_id):
        with self.db.tx() as c:
            game, member = self.game(c, actor, game_id)
            game["players"] = self.totals(c, game_id)
            game["operations"] = [dict(r) for r in c.execute(select(operations).where(
                operations.c.game_id == game_id).order_by(operations.c.id.desc())).mappings()]
            game["role"] = member["role"]
            game["member_id"] = member["id"]
            return game

    def correct(self, actor, game_id, replacements, reason, key):
        if len(reason.strip()) < 5:
            raise ClubError("Укажите причину исправления: не менее 5 символов.")
        with self.db.tx() as c:
            game, _ = self.game(c, actor, game_id, STAFF)
            if game["status"] not in {"active", "reconciling", "completed"}:
                raise ClubError("Исправления доступны во время игры, сверки и после завершения.")
            if not replacements:
                raise ClubError("Измените хотя бы одну сумму.")
            if c.execute(select(audit.c.id).where(audit.c.game_id == game_id,
                    audit.c.reason == f"correction:{actor}:{key}")).first():
                return
            for operation_id, amount in replacements.items():
                old = c.execute(select(operations).where(operations.c.id == int(operation_id),
                    operations.c.game_id == game_id, operations.c.status == "confirmed")).mappings().first()
                if not old or not isinstance(amount, int) or not 0 <= amount <= MAX_AMOUNT or (
                        old["kind"] != "cashout" and amount == 0):
                    raise ClubError("Недопустимая операция или сумма исправления.")
                c.execute(update(operations).where(operations.c.id == old["id"]).values(status="void"))
                c.execute(insert(operations).values(game_id=game_id, member_id=old["member_id"],
                    kind=old["kind"], amount=amount, status="confirmed", author=actor, created_at=now(),
                    confirmed_by=actor, confirmed_at=now(), key=f"fix:{actor}:{key}:{old['id']}"))
            if game["status"] == "completed":
                self.balanced(c, game_id)
            c.execute(insert(audit).values(game_id=game_id, club_id=game["club_id"], actor=actor,
                at=now(), reason=f"correction:{actor}:{key}", details=json.dumps(
                    {"reason": reason.strip(), "replacements": replacements}, ensure_ascii=False)))
            c.execute(update(games).where(games.c.id == game_id).values(revision=game["revision"] + 1))

    def stats(self, actor, club_id, period="all"):
        with self.db.tx() as c:
            own = Clubs.require(c, actor, club_id)
            club = c.execute(select(clubs).where(clubs.c.id == club_id)).mappings().one()
            if period not in {"all", "month", "season"}:
                raise ClubError("Неизвестный период рейтинга.")
            current = datetime.now(ZoneInfo(club["timezone"]))
            start = current.date().replace(day=1).isoformat() if period == "month" else club["season_start"]
            totals = {}
            history = []
            for game in c.execute(select(games).where(games.c.club_id == club_id,
                    games.c.status == "completed").order_by(games.c.starts_at, games.c.id)).mappings():
                local_date = datetime.fromisoformat(game["starts_at"]).astimezone(ZoneInfo(club["timezone"])).date()
                if period != "all" and local_date.isoformat() < start:
                    continue
                if local_date > current.date():
                    continue
                for row in self.totals(c, game["id"]):
                    total = totals.setdefault(row["id"], {"id": row["id"], "name": row["name"],
                        "profit": 0, "games": 0, "wins": 0})
                    total["profit"] += row["profit"]
                    total["games"] += 1
                    total["wins"] += row["profit"] > 0
                    if row["id"] == own["id"]:
                        history.append({"id": game["id"], "title": game["title"],
                            "date": local_date.isoformat(), "profit": row["profit"]})
            ranked = sorted(totals.values(), key=lambda r: (-r["profit"], -r["wins"], r["id"]))
            return {"ranking": ranked, "history": history, "member_id": own["id"], "period": period}
