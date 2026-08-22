from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.domain.entities import BillingPeriod, Charge, Reading
from src.domain.enums import ReadingStatus
from src.infrastructure.supabase.repositories import SupabaseRecognizedReadingPersistence

USER_ID = UUID("10000000-0000-0000-0000-000000000001")
PROPERTY_ID = UUID("20000000-0000-0000-0000-000000000002")
METER_ID = UUID("30000000-0000-0000-0000-000000000003")
READING_ID = UUID("40000000-0000-0000-0000-000000000004")
CAPTURED_AT = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


class Response:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data


class RpcQuery:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def execute(self) -> Response:
        captured = CAPTURED_AT.isoformat()
        return Response(
            {
                "reading": {
                    "id": str(READING_ID),
                    "meter_id": str(METER_ID),
                    "ocr_value": "125.4",
                    "confirmed_value": self.payload["p_confirmed_value"],
                    "ocr_confidence": 0.91,
                    "status": "confirmed",
                    "photo_path": "photo.jpg",
                    "captured_at": captured,
                    "created_at": captured,
                },
                "billing_period": {
                    "id": "50000000-0000-0000-0000-000000000005",
                    "property_id": str(PROPERTY_ID),
                    "year": self.payload["p_year"],
                    "month": self.payload["p_month"],
                    "status": "open",
                    "created_at": captured,
                },
                "charge": {
                    "id": "60000000-0000-0000-0000-000000000006",
                    "billing_period_id": "50000000-0000-0000-0000-000000000005",
                    "meter_id": str(METER_ID),
                    "previous_reading": self.payload["p_previous_reading"],
                    "current_reading": self.payload["p_confirmed_value"],
                    "consumption": self.payload["p_consumption"],
                    "tariff_price": self.payload["p_tariff_price"],
                    "amount": self.payload["p_amount"],
                    "created_at": captured,
                },
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


async def test_confirmed_ocr_reading_uses_atomic_rpc() -> None:
    client = RpcClient()
    persistence = SupabaseRecognizedReadingPersistence(client)
    reading = Reading(
        id=READING_ID,
        meter_id=METER_ID,
        ocr_value=Decimal("125.4"),
        confirmed_value=Decimal("124"),
        ocr_confidence=0.91,
        status=ReadingStatus.CONFIRMED,
        photo_path="photo.jpg",
        captured_at=CAPTURED_AT,
    )

    saved, period, charge = await persistence.confirm(
        reading=reading,
        period=BillingPeriod(property_id=PROPERTY_ID, year=2026, month=8),
        charge=Charge(
            billing_period_id=None,
            meter_id=METER_ID,
            previous_reading=Decimal("100"),
            current_reading=Decimal("124"),
            consumption=Decimal("24"),
            tariff_price=Decimal("8.25"),
            amount=Decimal("198.00"),
        ),
        user_id=USER_ID,
    )

    assert client.function_name == "confirm_recognized_reading_charge"
    assert client.payload is not None
    assert client.payload["p_reading_id"] == str(READING_ID)
    assert saved.ocr_value == Decimal("125.4")
    assert saved.confirmed_value == Decimal("124")
    assert period is not None
    assert charge is not None
    assert charge.amount == Decimal("198.00")
