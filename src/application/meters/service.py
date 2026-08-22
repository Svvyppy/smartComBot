from uuid import UUID

from src.application.exceptions import AccessDeniedError
from src.application.interfaces import MeterRepository
from src.domain.entities import Meter
from src.domain.enums import MeterUnit, UtilityType

EXPECTED_UNITS = {
    UtilityType.COLD_WATER: MeterUnit.CUBIC_METER,
    UtilityType.HOT_WATER: MeterUnit.CUBIC_METER,
    UtilityType.GAS: MeterUnit.CUBIC_METER,
    UtilityType.ELECTRICITY: MeterUnit.KILOWATT_HOUR,
    UtilityType.HEATING: MeterUnit.KILOWATT_HOUR,
}


class MeterService:
    def __init__(self, meters: MeterRepository) -> None:
        self._meters = meters

    async def create(
        self,
        *,
        user_id: UUID,
        property_id: UUID,
        name: str,
        utility_type: UtilityType,
        unit: MeterUnit,
        serial_number: str | None = None,
    ) -> Meter:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Meter name cannot be empty")
        if EXPECTED_UNITS[utility_type] != unit:
            raise ValueError(f"Unit {unit.value} is not valid for {utility_type.value}")
        return await self._meters.add(
            Meter(
                property_id=property_id,
                name=clean_name,
                type=utility_type,
                unit=unit,
                serial_number=(
                    serial_number.strip() if serial_number and serial_number.strip() else None
                ),
            ),
            user_id,
        )

    async def get(self, *, user_id: UUID, meter_id: UUID) -> Meter:
        meter = await self._meters.get_owned(meter_id, user_id)
        if meter is None:
            raise AccessDeniedError("Meter not found or access denied")
        return meter

    async def list(
        self,
        *,
        user_id: UUID,
        property_id: UUID,
        active_only: bool = True,
    ) -> list[Meter]:
        return await self._meters.list_by_property(
            property_id,
            user_id,
            active_only=active_only,
        )

