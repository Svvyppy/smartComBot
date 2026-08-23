from uuid import UUID

from src.application.management import ManagementService
from src.domain.entities import Meter, Property
from src.domain.enums import MeterUnit, UtilityType

USER_ID = UUID("10000000-0000-0000-0000-000000000001")
PROPERTY_ID = UUID("20000000-0000-0000-0000-000000000002")
METER_ID = UUID("30000000-0000-0000-0000-000000000003")
SECOND_METER_ID = UUID("30000000-0000-0000-0000-000000000004")


def _meter(meter_id: UUID) -> Meter:
    return Meter(
        id=meter_id,
        property_id=PROPERTY_ID,
        name="Счётчик",
        type=UtilityType.COLD_WATER,
        unit=MeterUnit.CUBIC_METER,
    )


class FakeProperties:
    def __init__(self) -> None:
        self.property = Property(id=PROPERTY_ID, user_id=USER_ID, name="Квартира")
        self.deleted = False

    async def get_owned(self, property_id: UUID, user_id: UUID) -> Property | None:
        if (property_id, user_id) == (PROPERTY_ID, USER_ID) and not self.deleted:
            return self.property
        return None

    async def delete_owned(self, property_id: UUID, user_id: UUID) -> None:
        assert (property_id, user_id) == (PROPERTY_ID, USER_ID)
        self.deleted = True


class FakeMeters:
    def __init__(self) -> None:
        self.meters = [_meter(METER_ID), _meter(SECOND_METER_ID)]
        self.deleted: list[UUID] = []

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
        assert (property_id, user_id) == (PROPERTY_ID, USER_ID)
        return self.meters

    async def delete_owned(self, meter_id: UUID, user_id: UUID) -> None:
        assert user_id == USER_ID
        self.deleted.append(meter_id)


class FakeReadings:
    async def list_photo_paths_by_meter(
        self,
        meter_id: UUID,
        user_id: UUID,
    ) -> list[str]:
        assert user_id == USER_ID
        return [f"{meter_id}/first.jpg", f"{meter_id}/second.jpg"]


class FakeStorage:
    def __init__(self, *, fails: bool = False) -> None:
        self.fails = fails
        self.deleted: list[str] = []

    async def delete_files(self, paths: list[str]) -> None:
        if self.fails:
            raise RuntimeError("storage unavailable")
        self.deleted.extend(paths)


def _service(
    *,
    storage_fails: bool = False,
) -> tuple[ManagementService, FakeProperties, FakeMeters, FakeStorage]:
    properties = FakeProperties()
    meters = FakeMeters()
    storage = FakeStorage(fails=storage_fails)
    service = ManagementService(
        properties=properties,  # type: ignore[arg-type]
        meters=meters,  # type: ignore[arg-type]
        readings=FakeReadings(),  # type: ignore[arg-type]
        storage=storage,  # type: ignore[arg-type]
    )
    return service, properties, meters, storage


async def test_delete_meter_removes_database_data_and_photos() -> None:
    service, _, meters, storage = _service()

    result = await service.delete_meter(user_id=USER_ID, meter_id=METER_ID)

    assert meters.deleted == [METER_ID]
    assert storage.deleted == [f"{METER_ID}/first.jpg", f"{METER_ID}/second.jpg"]
    assert result.deleted_photo_count == 2
    assert result.orphaned_photo_count == 0


async def test_delete_property_collects_photos_from_every_meter() -> None:
    service, properties, _, storage = _service()

    result = await service.delete_property(user_id=USER_ID, property_id=PROPERTY_ID)

    assert properties.deleted
    assert len(storage.deleted) == 4
    assert result.deleted_photo_count == 4


async def test_database_deletion_succeeds_when_storage_cleanup_fails() -> None:
    service, _, meters, _ = _service(storage_fails=True)

    result = await service.delete_meter(user_id=USER_ID, meter_id=METER_ID)

    assert meters.deleted == [METER_ID]
    assert result.deleted_photo_count == 0
    assert result.orphaned_photo_count == 2
