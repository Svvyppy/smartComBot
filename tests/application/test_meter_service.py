from dataclasses import replace
from uuid import UUID

import pytest

from src.application.meters import MeterService
from src.domain.entities import Meter
from src.domain.enums import MeterUnit, UtilityType

USER_ID = UUID("10000000-0000-0000-0000-000000000001")
PROPERTY_ID = UUID("20000000-0000-0000-0000-000000000002")
METER_ID = UUID("30000000-0000-0000-0000-000000000003")
SECOND_METER_ID = UUID("30000000-0000-0000-0000-000000000004")


class FakeMeterRepository:
    def __init__(self, meters: list[Meter]) -> None:
        self.meters = meters
        self.updates = 0

    async def get_owned(self, meter_id: UUID, user_id: UUID) -> Meter | None:
        if user_id != USER_ID:
            return None
        return next((meter for meter in self.meters if meter.id == meter_id), None)

    async def list_by_property(
        self,
        property_id: UUID,
        user_id: UUID,
        *,
        active_only: bool = True,
    ) -> list[Meter]:
        if (property_id, user_id) != (PROPERTY_ID, USER_ID):
            return []
        return [meter for meter in self.meters if meter.active or not active_only]

    async def set_serial_number_if_missing(
        self,
        meter_id: UUID,
        user_id: UUID,
        serial_number: str,
    ) -> Meter:
        meter = await self.get_owned(meter_id, user_id)
        assert meter is not None
        if meter.serial_number is None:
            meter = replace(meter, serial_number=serial_number)
            index = next(
                index for index, item in enumerate(self.meters) if item.id == meter_id
            )
            self.meters[index] = meter
            self.updates += 1
        return meter


def _meter(
    meter_id: UUID = METER_ID,
    *,
    serial_number: str | None = None,
    name: str = "ХВС",
) -> Meter:
    return Meter(
        id=meter_id,
        property_id=PROPERTY_ID,
        name=name,
        type=UtilityType.COLD_WATER,
        unit=MeterUnit.CUBIC_METER,
        serial_number=serial_number,
    )


async def test_bind_serial_number_to_meter_without_one() -> None:
    repository = FakeMeterRepository([_meter()])
    service = MeterService(repository)  # type: ignore[arg-type]

    meter, was_bound = await service.bind_serial_number_if_missing(
        user_id=USER_ID,
        meter_id=METER_ID,
        serial_number=" no. 22297698 ",
    )

    assert was_bound
    assert meter.serial_number == "NO. 22297698"
    assert repository.updates == 1


async def test_existing_serial_number_is_never_overwritten() -> None:
    repository = FakeMeterRepository([_meter(serial_number="22297698")])
    service = MeterService(repository)  # type: ignore[arg-type]

    meter, was_bound = await service.bind_serial_number_if_missing(
        user_id=USER_ID,
        meter_id=METER_ID,
        serial_number="99999999",
    )

    assert not was_bound
    assert meter.serial_number == "22297698"
    assert repository.updates == 0


async def test_serial_number_cannot_be_bound_to_two_meters() -> None:
    repository = FakeMeterRepository(
        [
            _meter(),
            _meter(
                SECOND_METER_ID,
                serial_number="OB 898047813",
                name="ГВС",
            ),
        ]
    )
    service = MeterService(repository)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="ГВС"):
        await service.bind_serial_number_if_missing(
            user_id=USER_ID,
            meter_id=METER_ID,
            serial_number="898047813",
        )

    assert repository.updates == 0
