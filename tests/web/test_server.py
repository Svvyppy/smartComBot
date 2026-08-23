import hashlib
import hmac
import json
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlencode
from uuid import UUID

from aiohttp.test_utils import TestClient, TestServer

from src.application.dashboard import (
    DashboardMeter,
    DashboardProperty,
    DashboardSnapshot,
)
from src.application.management import DeletionResult
from src.config import Settings
from src.domain.entities import Meter, Property, User
from src.domain.enums import MeterUnit, UtilityType
from src.web.server import create_mini_app

BOT_TOKEN = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
USER_ID = UUID("10000000-0000-0000-0000-000000000001")
PROPERTY_ID = UUID("20000000-0000-0000-0000-000000000002")
METER_ID = UUID("30000000-0000-0000-0000-000000000003")


def signed_init_data() -> str:
    values = {
        "auth_date": str(int(datetime.now(UTC).timestamp())),
        "user": json.dumps(
            {"id": 42, "first_name": "Тест"},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class FakeUsers:
    async def resolve(self, **_: object) -> User:
        return User(id=USER_ID, telegram_id=42, first_name="Тест")


class FakeDashboard:
    async def get_snapshot(self, **_: object) -> DashboardSnapshot:
        meter = DashboardMeter(
            id=METER_ID,
            name="ХВС",
            type=UtilityType.COLD_WATER,
            unit=MeterUnit.CUBIC_METER,
            serial_number="N164701553",
            active=True,
            latest_value=Decimal("127.929"),
            previous_value=Decimal("120.100"),
            consumption=Decimal("7.829"),
            latest_captured_at=datetime(2026, 8, 20, tzinfo=UTC),
            needs_reading=False,
        )
        return DashboardSnapshot(
            properties=(
                DashboardProperty(
                    id=PROPERTY_ID,
                    name="Квартира",
                    address=None,
                    meters=(meter,),
                ),
            ),
            property_count=1,
            meter_count=1,
            meters_with_readings=1,
            meters_needing_reading=0,
        )


class FakeProperties:
    async def create(self, **_: object) -> Property:
        return Property(id=PROPERTY_ID, user_id=USER_ID, name="Квартира")


class FakeMeters:
    async def create(self, **_: object) -> Meter:
        return Meter(
            id=METER_ID,
            property_id=PROPERTY_ID,
            name="ХВС",
            type=UtilityType.COLD_WATER,
            unit=MeterUnit.CUBIC_METER,
        )


class FakeManagement:
    def __init__(self) -> None:
        self.deleted_meter_id: UUID | None = None

    async def delete_meter(self, *, meter_id: UUID, **_: object) -> DeletionResult:
        self.deleted_meter_id = meter_id
        return DeletionResult(deleted_photo_count=2, orphaned_photo_count=0)

    async def delete_property(self, **_: object) -> DeletionResult:
        return DeletionResult(deleted_photo_count=0, orphaned_photo_count=0)


async def test_api_requires_valid_telegram_init_data_and_returns_dashboard() -> None:
    management = FakeManagement()
    app = create_mini_app(
        Settings(bot_token=BOT_TOKEN),
        users=FakeUsers(),  # type: ignore[arg-type]
        dashboard=FakeDashboard(),  # type: ignore[arg-type]
        properties=FakeProperties(),  # type: ignore[arg-type]
        meters=FakeMeters(),  # type: ignore[arg-type]
        management=management,  # type: ignore[arg-type]
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        unauthorized = await client.get("/api/v1/dashboard")
        assert unauthorized.status == 401

        headers = {"X-Telegram-Init-Data": signed_init_data()}
        dashboard = await client.get("/api/v1/dashboard", headers=headers)
        assert dashboard.status == 200
        payload = await dashboard.json()
        assert payload["summary"]["meter_count"] == 1
        assert payload["properties"][0]["meters"][0]["latest_value"] == "127.929"

        deleted = await client.delete(f"/api/v1/meters/{METER_ID}", headers=headers)
        assert deleted.status == 200
        assert management.deleted_meter_id == METER_ID
    finally:
        await client.close()
