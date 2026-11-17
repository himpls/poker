"""Tournament places are recorded after play, independently of cash profit."""
from datetime import UTC, datetime

from sqlalchemy import delete, insert, select, update

from .clubs import Clubs, name_checked
from .db import members, tournaments
from .db import tournament_results as results
from .money import ClubError

STAFF = {"owner", "organizer"}


class Tournaments:
    def __init__(self, db):
        self.db = db

    @staticmethod
    def require(c, actor, tournament_id, roles=None):
        row = c.execute(select(tournaments).where(tournaments.c.id == tournament_id)).mappings().first()
        if not row:
            raise ClubError("Турнир не найден.")
        Clubs.require(c, actor, row["club_id"], roles)
        return dict(row)

    def create(self, actor, club_id, title, starts_at, location, key):
        title = name_checked(title)
        try:
            instant = datetime.fromisoformat(starts_at)
            if instant.tzinfo is None:
                raise ValueError
        except (ValueError, TypeError):
            raise ClubError("Укажите дату со временем и часовым поясом.") from None
        if len(location) > 250:
            raise ClubError("Место: не более 250 символов.")
        values = {"club_id": club_id, "title": title, "starts_at": instant.astimezone(UTC).isoformat(),
                      "location": location.strip()}
        with self.db.tx() as c:
            Clubs.require(c, actor, club_id, STAFF)
            old = c.execute(select(tournaments).where(
                tournaments.c.request_key == f"{actor}:{key}")).mappings().first()
            if old:
                if any(old[k] != v for k, v in values.items()):
                    raise ClubError("Ключ запроса уже использован для другого турнира.")
                return old["id"]
            tournament_id = c.execute(insert(tournaments).values(
                **values, request_key=f"{actor}:{key}")).inserted_primary_key[0]
            Clubs.log(c, club_id, actor, "tournament_created", {"tournament_id": tournament_id})
            return tournament_id

    def list(self, actor, club_id):
        with self.db.tx() as c:
            Clubs.require(c, actor, club_id)
            return [dict(r) for r in c.execute(select(tournaments).where(
                tournaments.c.club_id == club_id).order_by(
                tournaments.c.starts_at.desc(), tournaments.c.id.desc())).mappings()]

    def get(self, actor, tournament_id):
        with self.db.tx() as c:
            row = self.require(c, actor, tournament_id)
            row["results"] = [dict(r) for r in c.execute(select(
                results.c.member_id, members.c.name, results.c.place).join(
                members, members.c.id == results.c.member_id).where(
                results.c.tournament_id == tournament_id).order_by(results.c.place)).mappings()]
            return row

    def finish(self, actor, tournament_id, standings, note, revision):
        if len(note) > 500:
            raise ClubError("Комментарий: не более 500 символов.")
        ids = [r["member_id"] for r in standings]
        places = [r["place"] for r in standings]
        if (len(ids) < 2 or len(set(ids)) != len(ids) or
                any(type(v) is not int for v in ids + places) or
                sorted(places) != list(range(1, len(ids) + 1))):
            raise ClubError("Укажите минимум двух игроков и места от 1 до числа участников без повторов.")
        with self.db.tx() as c:
            row = self.require(c, actor, tournament_id, STAFF)
            if row["status"] == "cancelled":
                raise ClubError("Турнир отменён.")
            valid = set(c.execute(select(members.c.id).where(
                members.c.club_id == row["club_id"], members.c.id.in_(ids))).scalars())
            if set(ids) != valid:
                raise ClubError("Участник не принадлежит клубу.")
            before = [dict(r) for r in c.execute(select(results.c.member_id, results.c.place).where(
                results.c.tournament_id == tournament_id)).mappings()]
            canonical = lambda rows: sorted((r["member_id"], r["place"]) for r in rows)
            # A retry of the same save after a lost response must remain harmless.
            if row["status"] == "completed" and canonical(before) == canonical(standings) and row["note"] == note:
                return
            if row["revision"] != revision:
                raise ClubError("Итоги уже изменились. Закройте форму, обновите страницу и откройте турнир заново.")
            c.execute(delete(results).where(results.c.tournament_id == tournament_id))
            c.execute(insert(results), [dict(tournament_id=tournament_id, **r) for r in standings])
            c.execute(update(tournaments).where(tournaments.c.id == tournament_id).values(
                status="completed", revision=revision + 1, note=note))
            Clubs.log(c, row["club_id"], actor, "tournament_results", {
                "tournament_id": tournament_id, "before": before, "after": standings,
                "previous_note": row["note"], "note": note, "revision": revision + 1})

    def ranking(self, actor, club_id):
        with self.db.tx() as c:
            Clubs.require(c, actor, club_id)
            totals = {}
            rows = c.execute(select(results.c.member_id, results.c.place, members.c.name).join(
                tournaments, tournaments.c.id == results.c.tournament_id).join(
                members, members.c.id == results.c.member_id).where(
                tournaments.c.club_id == club_id, tournaments.c.status == "completed")).mappings()
            for row in rows:
                t = totals.setdefault(row["member_id"], {"id": row["member_id"], "name": row["name"],
                    "games": 0, "wins": 0, "podiums": 0, "place_sum": 0})
                t["games"] += 1
                t["wins"] += row["place"] == 1
                t["podiums"] += row["place"] <= 3
                t["place_sum"] += row["place"]
            for t in totals.values():
                t["average_place"] = t.pop("place_sum") / t["games"]
            return sorted(totals.values(), key=lambda r: (-r["wins"], r["average_place"], r["id"]))
