from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from src.application.interfaces import MeterRepository, PropertyRepository, ReadingRepository
from src.domain.enums import MeterUnit, UtilityType


@dataclass(frozen=True, slots=True)
class DashboardMeter:
    id: UUID
    name: str
    type: UtilityType
    unit: MeterUnit
    serial_number: str | None
    active: bool
    latest_value: Decimal | None
    previous_value: Decimal | None
    consumption: Decimal | None
    latest_captured_at: datetime | None
    needs_reading: bool


@dataclass(frozen=True, slots=True)
class DashboardProperty:
    id: UUID
    name: str
    address: str | None
    meters: tuple[DashboardMeter, ...]


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    properties: tuple[DashboardProperty, ...]
    property_count: int
    meter_count: int
    meters_with_readings: int
    meters_needing_reading: int


class DashboardService:
    def __init__(
        self,
        *,
        properties: PropertyRepository,
        meters: MeterRepository,
        readings: ReadingRepository,
    ) -> None:
        self._properties = properties
        self._meters = meters
        self._readings = readings

    async def get_snapshot(
        self,
        *,
        user_id: UUID,
        now: datetime | None = None,
    ) -> DashboardSnapshot:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        properties = await self._properties.list_by_user(user_id)
        dashboard_properties: list[DashboardProperty] = []
        meter_count = 0
        meters_with_readings = 0
        meters_needing_reading = 0
        for property_ in properties:
            if property_.id is None:
                continue
            meters = await self._meters.list_by_property(
                property_.id,
                user_id,
                active_only=False,
            )
            dashboard_meters: list[DashboardMeter] = []
            for meter in meters:
                if meter.id is None:
                    continue
                confirmed = await self._readings.list_confirmed_by_meter(
                    meter.id,
                    user_id,
                    limit=2,
                )
                latest = confirmed[0] if confirmed else None
                previous = confirmed[1] if len(confirmed) > 1 else None
                latest_value = None if latest is None else latest.confirmed_value
                previous_value = None if previous is None else previous.confirmed_value
                consumption = (
                    None
                    if latest_value is None or previous_value is None
                    else latest_value - previous_value
                )
                latest_captured_at = None if latest is None else latest.captured_at
                needs_reading = latest_captured_at is None or (
                    latest_captured_at.year,
                    latest_captured_at.month,
                ) != (current.year, current.month)
                dashboard_meters.append(
                    DashboardMeter(
                        id=meter.id,
                        name=meter.name,
                        type=meter.type,
                        unit=meter.unit,
                        serial_number=meter.serial_number,
                        active=meter.active,
                        latest_value=latest_value,
                        previous_value=previous_value,
                        consumption=consumption,
                        latest_captured_at=latest_captured_at,
                        needs_reading=needs_reading,
                    )
                )
                meter_count += 1
                meters_with_readings += int(latest_value is not None)
                meters_needing_reading += int(meter.active and needs_reading)
            dashboard_properties.append(
                DashboardProperty(
                    id=property_.id,
                    name=property_.name,
                    address=property_.address,
                    meters=tuple(dashboard_meters),
                )
            )
        return DashboardSnapshot(
            properties=tuple(dashboard_properties),
            property_count=len(dashboard_properties),
            meter_count=meter_count,
            meters_with_readings=meters_with_readings,
            meters_needing_reading=meters_needing_reading,
        )
