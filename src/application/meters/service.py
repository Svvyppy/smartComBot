from uuid import UUID

from src.application.exceptions import AccessDeniedError
from src.application.interfaces import MeterRepository
from src.domain.entities import Meter
from src.domain.enums import MeterUnit, UtilityType
from src.domain.services import clean_serial_number, serial_numbers_match

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

    async def bind_serial_number_if_missing(
        self,
        *,
        user_id: UUID,
        meter_id: UUID,
        serial_number: str,
    ) -> tuple[Meter, bool]:
        meter = await self.get(user_id=user_id, meter_id=meter_id)
        if meter.serial_number:
            return meter, False

        cleaned = await self._validated_serial_number(
            user_id=user_id,
            meter=meter,
            serial_number=serial_number,
        )
        updated = await self._meters.set_serial_number_if_missing(
            meter_id,
            user_id,
            cleaned,
        )
        return updated, updated.serial_number == cleaned

    async def set_serial_number(
        self,
        *,
        user_id: UUID,
        meter_id: UUID,
        serial_number: str,
    ) -> tuple[Meter, bool]:
        meter = await self.get(user_id=user_id, meter_id=meter_id)
        cleaned = await self._validated_serial_number(
            user_id=user_id,
            meter=meter,
            serial_number=serial_number,
        )
        if meter.serial_number and serial_numbers_match(meter.serial_number, cleaned):
            return meter, False
        updated = await self._meters.set_serial_number(
            meter_id,
            user_id,
            cleaned,
        )
        return updated, True

    async def _validated_serial_number(
        self,
        *,
        user_id: UUID,
        meter: Meter,
        serial_number: str,
    ) -> str:
        cleaned = clean_serial_number(serial_number)
        if not cleaned:
            raise ValueError("Serial number cannot be empty")
        if len(cleaned) > 100:
            raise ValueError("Serial number cannot be longer than 100 characters")
        siblings = await self.list(
            user_id=user_id,
            property_id=meter.property_id,
            active_only=False,
        )
        for sibling in siblings:
            if (
                sibling.id != meter.id
                and sibling.serial_number
                and serial_numbers_match(sibling.serial_number, cleaned)
            ):
                raise ValueError(
                    f"Серийный номер уже привязан к счётчику «{sibling.name}»."
                )
        return cleaned
