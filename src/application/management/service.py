import logging
from dataclasses import dataclass
from uuid import UUID

from src.application.exceptions import AccessDeniedError
from src.application.interfaces import (
    ImageStorage,
    MeterRepository,
    PropertyRepository,
    ReadingRepository,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DeletionResult:
    deleted_photo_count: int
    orphaned_photo_count: int


class ManagementService:
    def __init__(
        self,
        *,
        properties: PropertyRepository,
        meters: MeterRepository,
        readings: ReadingRepository,
        storage: ImageStorage,
    ) -> None:
        self._properties = properties
        self._meters = meters
        self._readings = readings
        self._storage = storage

    async def delete_meter(self, *, user_id: UUID, meter_id: UUID) -> DeletionResult:
        meter = await self._meters.get_owned(meter_id, user_id)
        if meter is None:
            raise AccessDeniedError("Meter not found or access denied")
        photo_paths = await self._readings.list_photo_paths_by_meter(meter_id, user_id)
        await self._meters.delete_owned(meter_id, user_id)
        return await self._delete_photos(photo_paths)

    async def delete_property(
        self,
        *,
        user_id: UUID,
        property_id: UUID,
    ) -> DeletionResult:
        property_ = await self._properties.get_owned(property_id, user_id)
        if property_ is None:
            raise AccessDeniedError("Property not found or access denied")
        meters = await self._meters.list_by_property(
            property_id,
            user_id,
            active_only=False,
        )
        photo_paths: list[str] = []
        for meter in meters:
            if meter.id is not None:
                photo_paths.extend(
                    await self._readings.list_photo_paths_by_meter(meter.id, user_id)
                )
        await self._properties.delete_owned(property_id, user_id)
        return await self._delete_photos(photo_paths)

    async def _delete_photos(self, photo_paths: list[str]) -> DeletionResult:
        if not photo_paths:
            return DeletionResult(deleted_photo_count=0, orphaned_photo_count=0)
        try:
            await self._storage.delete_files(photo_paths)
        except Exception:
            logger.exception(
                "Database resource deleted but %s Storage photos could not be removed",
                len(photo_paths),
            )
            return DeletionResult(
                deleted_photo_count=0,
                orphaned_photo_count=len(photo_paths),
            )
        return DeletionResult(
            deleted_photo_count=len(photo_paths),
            orphaned_photo_count=0,
        )
