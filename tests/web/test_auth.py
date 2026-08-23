import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pytest

from src.web.auth import MiniAppAuthError, validate_init_data

BOT_TOKEN = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def signed_init_data(*, auth_date: datetime = NOW) -> str:
    values = {
        "auth_date": str(int(auth_date.timestamp())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps(
            {
                "id": 42,
                "first_name": "Николай",
                "username": "n_bulatov",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(values.items())
    )
    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode(),
        hashlib.sha256,
    ).digest()
    values["hash"] = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(values)


def test_valid_telegram_init_data_returns_identity() -> None:
    identity = validate_init_data(
        signed_init_data(),
        bot_token=BOT_TOKEN,
        max_age_seconds=3600,
        now=NOW,
    )

    assert identity.telegram_id == 42
    assert identity.first_name == "Николай"
    assert identity.username == "n_bulatov"


def test_tampered_telegram_init_data_is_rejected() -> None:
    tampered = signed_init_data().replace("n_bulatov", "attacker")

    with pytest.raises(MiniAppAuthError, match="signature is invalid"):
        validate_init_data(
            tampered,
            bot_token=BOT_TOKEN,
            max_age_seconds=3600,
            now=NOW,
        )


def test_expired_telegram_init_data_is_rejected() -> None:
    with pytest.raises(MiniAppAuthError, match="has expired"):
        validate_init_data(
            signed_init_data(auth_date=NOW - timedelta(hours=2)),
            bot_token=BOT_TOKEN,
            max_age_seconds=3600,
            now=NOW,
        )
