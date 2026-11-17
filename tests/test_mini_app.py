import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from poker_bot.demo import seed
from poker_bot.mini_auth import verify_init_data
from poker_bot.money import ClubError
from poker_bot.web import create_app

TOKEN = "123456789:test-secret"


def signed(user=1, when=None):
    data={"auth_date":str(int(time.time()) if when is None else when),
        "user":json.dumps({"id":user,"first_name":"Антон"},ensure_ascii=False)}
    secret=hmac.new(b"WebAppData",TOKEN.encode(),hashlib.sha256).digest()
    data["hash"]=hmac.new(secret,"\n".join(f"{k}={v}" for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
    return urlencode(data)


def test_auth_signature_age_and_duplicates():
    raw=signed(42)
    assert verify_init_data(raw,TOKEN)["id"] == 42
    for invalid in [raw+"&user=42",raw.replace("42","43"),signed(when=1),signed(when=int(time.time())+120),"",raw+"&hash=bad"]:
        with pytest.raises(ClubError):
            verify_init_data(invalid,TOKEN)
    with pytest.raises(ClubError):
        verify_init_data(raw,"other-bot-token")


def test_api_auth_and_club_isolation(db,monkeypatch):
    monkeypatch.setenv("BOT_TOKEN",TOKEN)
    seed(db)
    with TestClient(create_app(database=db)) as client:
        assert client.get("/").status_code==200
        assert client.get("/assets/app.js").status_code==200
        assert client.get("/api/clubs").status_code==401
        headers={"Authorization":"tma "+signed()}
        club=client.get("/api/clubs",headers=headers).json()["clubs"][0]["id"]
        assert client.get(f"/api/clubs/{club}",headers=headers).status_code==200
        assert client.get(f"/api/clubs/{club}",headers={"Authorization":"tma "+signed(100)}).status_code==400
        assert client.get(f"/api/clubs/{club}/stats",headers=headers).json()["ranking"][0]["games"]==2
        assert client.get("/api/clubs",headers=headers).headers["cache-control"]=="no-store"


def test_demo_loopback_only_and_separate_initialization(db):
    seed(db);seed(db)
    with TestClient(create_app(database=db,demo=True),client=("127.0.0.1",1234)) as client:
        assert len(client.get("/api/clubs").json()["clubs"])==1
        club=client.get("/api/clubs").json()["clubs"][0]["id"]
        assert len(client.get(f"/api/clubs/{club}").json()["members"])==6
    with TestClient(create_app(database=db,demo=True),client=("198.51.100.1",1234)) as client:
        assert client.get("/api/clubs").status_code==403


def test_api_rejects_member_financial_escalation(db,monkeypatch):
    monkeypatch.setenv("BOT_TOKEN",TOKEN);seed(db)
    with TestClient(create_app(database=db)) as client:
        headers={"Authorization":"tma "+signed(2)}
        club=client.get("/api/clubs",headers=headers).json()["clubs"][0]["id"]
        current=next(g for g in client.get(f"/api/clubs/{club}",headers=headers).json()["games"] if g["status"]=="active")
        g=client.get(f"/api/games/{current['id']}",headers=headers).json()
        assert client.post(f"/api/games/{g['id']}/status",json={"status":"completed"},headers=headers).status_code==400
        response=client.post(f"/api/games/{g['id']}/operations",headers=headers,json={
            "member_id":g["member_id"],"kind":"rebuy","amount":"500","key":"test-request-key"})
        assert response.status_code==200
        updated=client.get(f"/api/games/{g['id']}",headers=headers).json()
        assert next(o for o in updated["operations"] if o["id"]==response.json()["id"])["status"]=="pending"
