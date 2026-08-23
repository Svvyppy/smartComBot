from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl


class MiniAppAuthError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TelegramMiniAppIdentity:
    telegram_id: int
    username: str | None
    first_name: str | None
    auth_date: datetime


def validate_init_data(
    init_data: str,
    *,
    bot_token: str,
    max_age_seconds: int,
    now: datetime | None = None,
) -> TelegramMiniAppIdentity:
    if not init_data:
        raise MiniAppAuthError("Telegram init data is missing")
    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    values = dict(pairs)
    received_hash = values.pop("hash", None)
    if not received_hash:
        raise MiniAppAuthError("Telegram init data hash is missing")
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(values.items())
    )
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise MiniAppAuthError("Telegram init data signature is invalid")

    try:
        auth_timestamp = int(values["auth_date"])
        auth_date = datetime.fromtimestamp(auth_timestamp, tz=UTC)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise MiniAppAuthError("Telegram auth_date is invalid") from exc
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    age_seconds = (current - auth_date).total_seconds()
    if age_seconds < -30 or age_seconds > max_age_seconds:
        raise MiniAppAuthError("Telegram init data has expired")

    try:
        raw_user = json.loads(values["user"])
        if not isinstance(raw_user, dict):
            raise TypeError
        telegram_id = int(raw_user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MiniAppAuthError("Telegram user data is invalid") from exc
    username = raw_user.get("username")
    first_name = raw_user.get("first_name")
    return TelegramMiniAppIdentity(
        telegram_id=telegram_id,
        username=username if isinstance(username, str) else None,
        first_name=first_name if isinstance(first_name, str) else None,
        auth_date=auth_date,
    )
