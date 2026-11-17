"""Проверка подписанного Telegram initData, без доверия initDataUnsafe."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from .money import ClubError


def verify_init_data(raw, bot_token, max_age=3600, clock=None):
    try:
        if not bot_token or not raw or len(raw) > 16384:
            raise ValueError
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        if len(pairs) != len(data):
            raise ValueError
        signature = data.pop("hash")
        check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        age = (clock if clock is not None else time.time()) - int(data["auth_date"])
        if not -30 <= age <= max_age:
            raise ValueError
        user = json.loads(data["user"])
        if type(user["id"]) is not int or user["id"] <= 0 or user.get("is_bot", False):
            raise ValueError
        return {"id": user["id"], "name": " ".join(
            str(user.get(k, "")) for k in ("first_name", "last_name")).strip()[:80] or "Игрок"}
    except (ValueError, KeyError, TypeError):
        raise ClubError("Откройте приложение заново через Telegram: сессия недействительна.") from None
