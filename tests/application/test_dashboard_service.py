from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from src.application.dashboard import DashboardService
from src.domain.entities import Meter, Property, Reading
from src.domain.enums import MeterUnit, ReadingStatus, UtilityType

USER_ID = UUID("10000000-0000-0000-0000-000000000001")
PROPERTY_ID = UUID("20000000-0000-0000-0000-000000000002")
METER_ID = UUID("30000000-0000-0000-0000-000000000003")


class FakeProperties:
    async def list_by_user(self, user_id: UUID) -> list[Property]:
        assert user_id == USER_ID
        return [Property(id=PROPERTY_ID, user_id=USER_ID, name="Квартира")]


class FakeMeters:
    async def list_by_property(
        self,
        property_id: UUID,
        user_id: UUID,
        *,
        active_only: bool = True,
    ) -> list[Meter]:
        assert (property_id, user_id) == (PROPERTY_ID, USER_ID)
        return [
            Meter(
                id=METER_ID,
                property_id=PROPERTY_ID,
                name="ХВС",
                type=UtilityType.COLD_WATER,
                unit=MeterUnit.CUBIC_METER,
                serial_number="N164701553",
            )
        ]


class FakeReadings:
    async def list_confirmed_by_meter(
        self,
        meter_id: UUID,
        user_id: UUID,
        *,
        limit: int = 2,
    ) -> list[Reading]:
        assert (meter_id, user_id, limit) == (METER_ID, USER_ID, 2)
        return [
            Reading(
                meter_id=METER_ID,
                confirmed_value=Decimal("127.929"),
                status=ReadingStatus.CONFIRMED,
                captured_at=datetime(2026, 8, 20, tzinfo=UTC),
            ),
            Reading(
                meter_id=METER_ID,
                confirmed_value=Decimal("120.100"),
                status=ReadingStatus.CONFIRMED,
                captured_at=datetime(2026, 7, 20, tzinfo=UTC),
            ),
        ]


async def test_dashboard_contains_latest_reading_and_consumption() -> None:
    service = DashboardService(
        properties=FakeProperties(),  # type: ignore[arg-type]
        meters=FakeMeters(),  # type: ignore[arg-type]
        readings=FakeReadings(),  # type: ignore[arg-type]
    )

    snapshot = await service.get_snapshot(
        user_id=USER_ID,
        now=datetime(2026, 8, 23, tzinfo=UTC),
    )

    meter = snapshot.properties[0].meters[0]
    assert snapshot.property_count == 1
    assert snapshot.meter_count == 1
    assert snapshot.meters_with_readings == 1
    assert snapshot.meters_needing_reading == 0
    assert meter.latest_value == Decimal("127.929")
    assert meter.previous_value == Decimal("120.100")
    assert meter.consumption == Decimal("7.829")
    assert not meter.needs_reading
