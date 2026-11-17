from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_mini_app import TOKEN, signed

from poker_bot.cash import Cash
from poker_bot.clubs import Clubs
from poker_bot.db import audit
from poker_bot.money import ClubError
from poker_bot.tournaments import Tournaments
from poker_bot.web import create_app


def setup_tournament(db):
    clubs = Clubs(db)
    club = clubs.create(1, "Owner", "Club")
    clubs.join(2, "Player", clubs.invite(1, club))
    ids = [m["id"] for m in clubs.roster(1, club)]
    service = Tournaments(db)
    args = (1, club, "Friday", datetime.now(UTC).isoformat(), "Home", "new-tournament")
    t = service.create(*args)
    assert service.create(*args) == t
    return service, club, t, ids


def test_finish_retry_correction_and_cash_separation(db):
    service, club, t, ids = setup_tournament(db)
    rows = [{"member_id": mid, "place": i + 1} for i, mid in enumerate(ids)]
    service.finish(1, t, rows, "Good evening", 0)
    service.finish(1, t, rows, "Good evening", 0)
    assert service.get(2, t)["revision"] == 1
    assert service.ranking(2, club)[0]["id"] == ids[0]
    assert Cash(db).stats(1, club)["ranking"] == []
    reversed_rows = [{"member_id": r["member_id"], "place": 3 - r["place"]} for r in rows]
    with pytest.raises(ClubError):
        service.finish(1, t, reversed_rows, "Correction", 0)
    service.finish(1, t, reversed_rows, "Correction", 1)
    assert service.ranking(2, club)[0]["id"] == ids[1]
    assert service.get(2, t)["revision"] == 2
    with db.tx() as c:
        history = list(c.execute(select(audit).where(audit.c.reason == "tournament_results")))
    assert len(history) == 2


def test_permissions_validation_and_no_partial_updates(db):
    service, club, t, ids = setup_tournament(db)
    rows = [{"member_id": mid, "place": i + 1} for i, mid in enumerate(ids)]
    with pytest.raises(ClubError):
        service.finish(2, t, rows, "", 0)
    with pytest.raises(ClubError):
        service.get(99, t)
    with pytest.raises(ClubError):
        service.list(99, club)
    other = Clubs(db).create(99, "Other", "Other club")
    foreign = Clubs(db).roster(99, other)[0]["id"]
    for invalid in [rows[:1], [rows[0], rows[0]],
                    [rows[0], {"member_id": ids[1], "place": 3}],
                    [rows[0], {"member_id": foreign, "place": 2}],
                    [rows[0], {"member_id": ids[1], "place": True}]]:
        with pytest.raises(ClubError):
            service.finish(1, t, invalid, "", 0)
        assert service.get(1, t)["status"] == "planned"
        assert service.get(1, t)["results"] == []
    Clubs(db).role(1, club, ids[1], "organizer")
    service.finish(2, t, rows, "", 0)
    assert service.get(1, t)["status"] == "completed"


def test_concurrent_result_edits_reject_stale_version(db):
    service, _club, t, ids = setup_tournament(db)
    rows = [{"member_id": mid, "place": i + 1} for i, mid in enumerate(ids)]

    def finish(note):
        try:
            service.finish(1, t, rows, note, 0)
            return True
        except ClubError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(finish, ["First edit", "Second edit"])) == [False, True]
    assert service.get(1, t)["revision"] == 1


def test_api_authenticated_tournament_flow(db, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TOKEN)
    _service, club, _, ids = setup_tournament(db)
    with TestClient(create_app(database=db)) as client:
        path = f"/api/clubs/{club}/tournaments"
        headers = {"Authorization": "tma " + signed(1)}
        payload = {"title": "API tournament", "starts_at": datetime.now(UTC).isoformat(), "key": "api-tournament"}
        assert client.post(path, json=payload).status_code == 401
        t = client.post(path, json=payload, headers=headers).json()["id"]
        body = {"standings": [{"member_id": mid, "place": i + 1} for i, mid in enumerate(ids)],
                "note": "Results", "revision": 0}
        endpoint = f"/api/tournaments/{t}/results"
        assert client.post(endpoint, json=body, headers={"Authorization": "tma " + signed(2)}).status_code == 400
        assert client.post(endpoint, json=body, headers=headers).status_code == 200
        assert client.post(endpoint, json=body, headers=headers).status_code == 200
        assert client.get(f"/api/tournaments/{t}", headers=headers).json()["results"][0]["place"] == 1
        assert client.get(path, headers=headers).json()["ranking"][0]["wins"] == 1
        body["standings"][0]["place"] = True
        assert client.post(endpoint, json=body, headers=headers).status_code == 422
