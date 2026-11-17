from functools import lru_cache
from pathlib import Path
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .cash import Cash
from .clubs import Clubs
from .db import Database
from .mini_auth import verify_init_data
from .money import CURRENCIES, ClubError, parse_money
from .tournaments import Tournaments


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewClub(Input):
    name: str = Field(min_length=1, max_length=80)
    currency: Literal["RUB", "UZS", "USD", "EUR", "KZT", "JPY"]
    timezone: str = Field(min_length=1, max_length=80)
    key: str = Field(min_length=8, max_length=64, pattern=r"^[\w-]+$")


class Join(Input):
    token: str = Field(min_length=1, max_length=64)


class Guest(Input):
    name: str = Field(min_length=1, max_length=80)


class Role(Input):
    member_id: int
    role: Literal["organizer", "member"]


class NewGame(Input):
    title: str = Field(min_length=1, max_length=80)
    starts_at: str = Field(max_length=40)
    location: str = Field(max_length=250)
    buyin: str = Field(max_length=30)
    key: str = Field(min_length=8, max_length=64, pattern=r"^[\w-]+$")


class Player(Input):
    member_id: int


class Operation(Player):
    kind: Literal["buyin", "rebuy", "cashout"]
    amount: str = Field(max_length=30)
    key: str = Field(min_length=8, max_length=64, pattern=r"^[\w-]+$")


class Decision(Input):
    accept: bool


class Transition(Input):
    status: Literal["active", "reconciling", "completed", "cancelled"]


class Correction(Input):
    amounts: dict[int, Annotated[str, Field(max_length=30)]] = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=5, max_length=500)
    key: str = Field(min_length=8, max_length=64, pattern=r"^[\w-]+$")


class NewTournament(Input):
    title: str = Field(min_length=1, max_length=80)
    starts_at: str = Field(max_length=40)
    location: str = Field(default="", max_length=250)
    key: str = Field(min_length=8, max_length=64, pattern=r"^[\w-]+$")


class Standing(Input):
    member_id: int = Field(strict=True, gt=0)
    place: int = Field(strict=True, gt=0)


class TournamentResult(Input):
    standings: list[Standing] = Field(min_length=2, max_length=500)
    note: str = Field(default="", max_length=500)
    revision: int = Field(strict=True, ge=0)


def install_mini_app(app, database=None, demo=False):
    import os

    @lru_cache
    def db():
        return database or Database(os.getenv("DATABASE_URL", "sqlite:///data/poker.db"))

    def identity(request: Request, authorization: str = Header(default="")):
        if demo:
            if request.client and request.client.host in {"127.0.0.1", "::1"}:
                return {"id": 1, "name": "Антон"}
            raise HTTPException(403, "Деморежим доступен только на этом компьютере.")
        prefix, _, raw = authorization.partition(" ")
        if prefix != "tma":
            raise HTTPException(401, "Откройте приложение через Telegram.")
        try:
            return verify_init_data(raw, os.getenv("BOT_TOKEN", ""))
        except ClubError as error:
            raise HTTPException(401, str(error)) from None

    actor = Annotated[dict, Depends(identity)]
    router = APIRouter(prefix="/api")

    @router.get("/config")
    def config():
        return {"demo": demo, "currencies": CURRENCIES}

    @router.get("/clubs")
    def clubs(user: actor):
        return {"user": user, "clubs": Clubs(db()).list(user["id"])}

    @router.post("/clubs")
    def create_club(body: NewClub, user: actor):
        return {"id": Clubs(db()).create(user["id"], user["name"], body.name,
            body.currency, body.timezone, body.key)}

    @router.post("/join")
    def join_club(body: Join, user: actor):
        return {"id": Clubs(db()).join(user["id"], user["name"], body.token)}

    @router.get("/clubs/{club_id}")
    def club(club_id: int, user: actor):
        return {"club": Clubs(db()).get(user["id"], club_id),
            "members": Clubs(db()).roster(user["id"], club_id),
            "games": Cash(db()).list(user["id"], club_id)}

    @router.post("/clubs/{club_id}/invite")
    def invite(club_id: int, user: actor):
        token = Clubs(db()).invite(user["id"], club_id)
        username = os.getenv("BOT_USERNAME", "").strip().lstrip("@")
        url = f"https://t.me/{username}?start=join_{token}" if re.fullmatch(r"[A-Za-z0-9_]{5,32}", username) else None
        return {"token": token, "url": url}

    @router.post("/clubs/{club_id}/guests")
    def guest(club_id: int, body: Guest, user: actor):
        return {"id": Clubs(db()).guest(user["id"], club_id, body.name)}

    @router.post("/clubs/{club_id}/roles")
    def role(club_id: int, body: Role, user: actor):
        Clubs(db()).role(user["id"], club_id, body.member_id, body.role)
        return {"ok": True}

    @router.post("/clubs/{club_id}/games")
    def create_game(club_id: int, body: NewGame, user: actor):
        club = Clubs(db()).get(user["id"], club_id)
        return {"id": Cash(db()).create(user["id"], club_id, body.title, body.starts_at,
            body.location, parse_money(body.buyin, club["currency"]), body.key)}

    @router.get("/games/{game_id}")
    def game(game_id: int, user: actor):
        return Cash(db()).get(user["id"], game_id)

    @router.post("/games/{game_id}/players")
    def player(game_id: int, body: Player, user: actor):
        Cash(db()).add_player(user["id"], game_id, body.member_id)
        return {"ok": True}

    @router.post("/games/{game_id}/operations")
    def operation(game_id: int, body: Operation, user: actor):
        current = Cash(db()).get(user["id"], game_id)
        club = Clubs(db()).get(user["id"], current["club_id"])
        return {"id": Cash(db()).record(user["id"], game_id, body.member_id, body.kind,
            parse_money(body.amount, club["currency"]), body.key)}

    @router.post("/operations/{operation_id}/decision")
    def decide(operation_id: int, body: Decision, user: actor):
        Cash(db()).decide(user["id"], operation_id, body.accept)
        return {"ok": True}

    @router.post("/games/{game_id}/status")
    def status(game_id: int, body: Transition, user: actor):
        Cash(db()).transition(user["id"], game_id, body.status)
        return {"ok": True}

    @router.post("/games/{game_id}/corrections")
    def correct(game_id: int, body: Correction, user: actor):
        current = Cash(db()).get(user["id"], game_id)
        club = Clubs(db()).get(user["id"], current["club_id"])
        Cash(db()).correct(user["id"], game_id,
            {k: parse_money(v, club["currency"]) for k, v in body.amounts.items()}, body.reason, body.key)
        return {"ok": True}

    @router.get("/clubs/{club_id}/stats")
    def stats(club_id: int, user: actor, period: str = "all"):
        return Cash(db()).stats(user["id"], club_id, period)

    @router.get("/clubs/{club_id}/tournaments")
    def list_tournaments(club_id: int, user: actor):
        service = Tournaments(db())
        return {"tournaments": service.list(user["id"], club_id), "ranking": service.ranking(user["id"], club_id)}

    @router.post("/clubs/{club_id}/tournaments")
    def create_tournament(club_id: int, body: NewTournament, user: actor):
        return {"id": Tournaments(db()).create(user["id"], club_id, body.title,
            body.starts_at, body.location, body.key)}

    @router.get("/tournaments/{tournament_id}")
    def tournament(tournament_id: int, user: actor):
        return Tournaments(db()).get(user["id"], tournament_id)

    @router.post("/tournaments/{tournament_id}/results")
    def tournament_result(tournament_id: int, body: TournamentResult, user: actor):
        Tournaments(db()).finish(user["id"], tournament_id,
            [r.model_dump() for r in body.standings], body.note, body.revision)
        return {"ok": True}

    @app.exception_handler(ClubError)
    async def business_error(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @app.middleware("http")
    async def privacy_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "no-cache"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    assets = Path(__file__).parent / "assets"

    @app.get("/")
    async def index():
        return FileResponse(assets / "index.html", headers={"Cache-Control": "no-cache"})

    app.include_router(router)
    app.mount("/assets", StaticFiles(directory=assets), name="assets")
