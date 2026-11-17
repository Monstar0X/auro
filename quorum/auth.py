"""Telegram Mini App `initData` verification (https://core.telegram.org/bots/webapps#validating-data)."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class AuthError(Exception):
    pass


def validate_init_data(init_data: str, bot_token: str, max_age: int = 86400, now: float | None = None) -> dict:
    if not init_data or not bot_token:
        raise AuthError("Missing Telegram credentials.")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    got = pairs.pop("hash", None)
    if not got:
        raise AuthError("Missing hash.")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    want = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, got):
        raise AuthError("Bad signature.")
    try:
        age = (now or time.time()) - int(pairs.get("auth_date", "0"))
    except ValueError:
        raise AuthError("Bad auth_date.")
    if age > max_age:
        raise AuthError("Session expired - reopen the Mini App.")
    try:
        user = json.loads(pairs["user"])
        uid = int(user["id"])
    except (KeyError, ValueError, TypeError):
        raise AuthError("No user in initData.")
    name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x) or user.get("username") or str(uid)
    return {"id": uid, "name": name, "start_param": pairs.get("start_param", "")}


def sign_init_data(fields: dict[str, str], bot_token: str) -> str:
    """Build a valid initData string (used by tests and the local dev helper)."""
    from urllib.parse import urlencode
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": h})
