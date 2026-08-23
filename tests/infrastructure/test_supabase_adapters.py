from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from src.application.exceptions import AccessDeniedError
from src.domain.entities import BillingPeriod, Charge, Meter, Reading, User
from src.domain.enums import MeterUnit, ReadingStatus, UtilityType
from src.infrastructure.supabase.repositories import (
    SupabaseManualReadingPersistence,
    SupabaseMeterRepository,
    SupabaseUserRepository,
)
from src.infrastructure.supabase.storage import SupabaseImageStorage


class Response:
    def __init__(self, data: list[dict[str, Any]] | dict[str, Any]) -> None:
        self.data = data


class EmptyQuery:
    def select(self, *_: object, **__: object) -> "EmptyQuery":
        return self

    def eq(self, *_: object, **__: object) -> "EmptyQuery":
        return self

    def limit(self, *_: object, **__: object) -> "EmptyQuery":
        return self

    def insert(self, *_: object, **__: object) -> "EmptyQuery":
        raise AssertionError("An unauthorized insert must not be attempted")

    def execute(self) -> Response:
        return Response([])


class EmptyClient:
    def table(self, _: str) -> EmptyQuery:
        return EmptyQuery()


async def test_meter_repository_blocks_foreign_property_before_insert() -> None:
    repository = SupabaseMeterRepository(EmptyClient())
    meter = Meter(
        property_id=UUID("20000000-0000-0000-0000-000000000002"),
        name="Счётчик",
        type=UtilityType.COLD_WATER,
        unit=MeterUnit.CUBIC_METER,
    )

    with pytest.raises(AccessDeniedError):
        await repository.add(meter, UUID("10000000-0000-0000-0000-000000000001"))


class UserQuery:
    def __init__(self) -> None:
        self.payload: dict[str, Any] = {}

    def upsert(self, payload: dict[str, Any], **_: object) -> "UserQuery":
        self.payload = payload
        return self

    def execute(self) -> Response:
        return Response(
            [
                {
                    **self.payload,
                    "id": "10000000-0000-0000-0000-000000000001",
                    "created_at": "2026-08-23T12:00:00Z",
                }
            ]
        )


class UserClient:
    def __init__(self) -> None:
        self.query = UserQuery()

    def table(self, name: str) -> UserQuery:
        assert name == "users"
        return self.query


async def test_user_repository_upserts_telegram_profile() -> None:
    repository = SupabaseUserRepository(UserClient())

    saved = await repository.save(User(telegram_id=42, username="neo", first_name="Neo"))

    assert saved.telegram_id == 42
    assert saved.username == "neo"
    assert saved.id == UUID("10000000-0000-0000-0000-000000000001")


class Bucket:
    def __init__(self) -> None:
        self.uploaded: dict[str, Any] | None = None

    def upload(self, **kwargs: Any) -> None:
        self.uploaded = kwargs


class Storage:
    def __init__(self) -> None:
        self.bucket = Bucket()
        self.bucket_name: str | None = None

    def from_(self, bucket_name: str) -> Bucket:
        self.bucket_name = bucket_name
        return self.bucket


class StorageClient:
    def __init__(self) -> None:
        self.storage = Storage()


async def test_storage_returns_private_bucket_relative_path() -> None:
    client = StorageClient()
    storage = SupabaseImageStorage(client)
    user_id = UUID("10000000-0000-0000-0000-000000000001")
    property_id = UUID("20000000-0000-0000-0000-000000000002")
    meter_id = UUID("30000000-0000-0000-0000-000000000003")

    path = await storage.save_meter_photo(
        user_id=user_id,
        property_id=property_id,
        meter_id=meter_id,
        content=b"jpeg-data",
    )

    assert path.startswith(f"{user_id}/{property_id}/{meter_id}/")
    assert path.endswith(".jpg")
    assert client.storage.bucket_name == "meter-photos"
    assert client.storage.bucket.uploaded is not None
    assert client.storage.bucket.uploaded["path"] == path
    assert client.storage.bucket.uploaded["file"] == b"jpeg-data"


class RpcQuery:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def execute(self) -> Response:
        meter_id = self.payload["p_meter_id"]
        captured_at = self.payload["p_captured_at"]
        wastewater_price = self.payload["p_wastewater_tariff_price"]
        wastewater_charge = None
        if wastewater_price is not None:
            wastewater_charge = {
                "id": "70000000-0000-0000-0000-000000000007",
                "billing_period_id": "50000000-0000-0000-0000-000000000005",
                "cold_water_consumption": self.payload["p_consumption"],
                "hot_water_consumption": "2.5",
                "consumption": "22.5",
                "tariff_price": wastewater_price,
                "amount": "803.70",
                "created_at": captured_at,
            }
        return Response(
            {
                "reading": {
                    "id": "40000000-0000-0000-0000-000000000004",
                    "meter_id": meter_id,
                    "confirmed_value": self.payload["p_confirmed_value"],
                    "ocr_value": None,
                    "ocr_confidence": None,
                    "status": "manual",
                    "photo_path": None,
                    "captured_at": captured_at,
                    "created_at": captured_at,
                },
                "billing_period": {
                    "id": "50000000-0000-0000-0000-000000000005",
                    "property_id": "20000000-0000-0000-0000-000000000002",
                    "year": self.payload["p_year"],
                    "month": self.payload["p_month"],
                    "status": "open",
                    "created_at": captured_at,
                },
                "charge": {
                    "id": "60000000-0000-0000-0000-000000000006",
                    "billing_period_id": "50000000-0000-0000-0000-000000000005",
                    "meter_id": meter_id,
                    "previous_reading": self.payload["p_previous_reading"],
                    "current_reading": self.payload["p_confirmed_value"],
                    "consumption": self.payload["p_consumption"],
                    "tariff_price": self.payload["p_tariff_price"],
                    "amount": self.payload["p_amount"],
                    "created_at": captured_at,
                },
                "wastewater_charge": wastewater_charge,
            }
        )


class RpcClient:
    def __init__(self) -> None:
        self.function_name: str | None = None
        self.payload: dict[str, Any] | None = None

    def rpc(self, function_name: str, payload: dict[str, Any]) -> RpcQuery:
        self.function_name = function_name
        self.payload = payload
        return RpcQuery(payload)


async def test_billed_manual_reading_uses_one_atomic_rpc() -> None:
    client = RpcClient()
    persistence = SupabaseManualReadingPersistence(client)
    user_id = UUID("10000000-0000-0000-0000-000000000001")
    property_id = UUID("20000000-0000-0000-0000-000000000002")
    meter_id = UUID("30000000-0000-0000-0000-000000000003")
    captured = datetime(2026, 8, 23, tzinfo=UTC)

    reading, period, charge, wastewater_charge = await persistence.save_billed(
        reading=Reading(
            meter_id=meter_id,
            confirmed_value=Decimal("120"),
            status=ReadingStatus.MANUAL,
            captured_at=captured,
        ),
        period=BillingPeriod(property_id=property_id, year=2026, month=8),
        charge=Charge(
            billing_period_id=None,
            meter_id=meter_id,
            previous_reading=Decimal("100"),
            current_reading=Decimal("120"),
            consumption=Decimal("20"),
            tariff_price=Decimal("8.25"),
            amount=Decimal("165.00"),
        ),
        wastewater_tariff_price=None,
        user_id=user_id,
    )

    assert client.function_name == "record_manual_reading_charge"
    assert reading.confirmed_value == Decimal("120")
    assert period.property_id == property_id
    assert charge.amount == Decimal("165.00")
    assert wastewater_charge is None


async def test_billed_water_reading_maps_recalculated_wastewater_charge() -> None:
    client = RpcClient()
    persistence = SupabaseManualReadingPersistence(client)
    captured = datetime(2026, 8, 23, tzinfo=UTC)

    _, _, _, wastewater_charge = await persistence.save_billed(
        reading=Reading(
            meter_id=UUID("30000000-0000-0000-0000-000000000003"),
            confirmed_value=Decimal("120"),
            status=ReadingStatus.MANUAL,
            captured_at=captured,
        ),
        period=BillingPeriod(
            property_id=UUID("20000000-0000-0000-0000-000000000002"),
            year=2026,
            month=8,
        ),
        charge=Charge(
            billing_period_id=None,
            meter_id=UUID("30000000-0000-0000-0000-000000000003"),
            previous_reading=Decimal("100"),
            current_reading=Decimal("120"),
            consumption=Decimal("20"),
            tariff_price=Decimal("8.25"),
            amount=Decimal("165.00"),
        ),
        wastewater_tariff_price=Decimal("35.72"),
        user_id=UUID("10000000-0000-0000-0000-000000000001"),
    )

    assert client.payload is not None
    assert client.payload["p_wastewater_tariff_price"] == "35.72"
    assert wastewater_charge is not None
    assert wastewater_charge.cold_water_consumption == Decimal("20")
    assert wastewater_charge.hot_water_consumption == Decimal("2.5")
    assert wastewater_charge.consumption == Decimal("22.5")
    assert wastewater_charge.amount == Decimal("803.70")
