from typing import Any
from uuid import UUID

from src.application.exceptions import EntityNotFoundError
from src.domain.entities import Reading
from src.infrastructure.supabase.repositories.base import SupabaseRepository
from src.infrastructure.supabase.repositories.mappers import reading_from_row


def _reading_payload(reading: Reading) -> dict[str, Any]:
    return {
        "meter_id": str(reading.meter_id),
        "ocr_value": None if reading.ocr_value is None else str(reading.ocr_value),
        "confirmed_value": (
            None if reading.confirmed_value is None else str(reading.confirmed_value)
        ),
        "ocr_confidence": reading.ocr_confidence,
        "status": reading.status.value,
        "photo_path": reading.photo_path,
        "captured_at": reading.captured_at.isoformat(),
    }


class SupabaseReadingRepository(SupabaseRepository):
    async def add(self, reading: Reading, user_id: UUID) -> Reading:
        await self._require_meter_owned(reading.meter_id, user_id)
        payload = _reading_payload(reading)
        if reading.id is not None:
            payload["id"] = str(reading.id)
        response = await self._run(
            lambda: self._client.table("readings").insert(payload).execute()
        )
        row = self._first(response)
        if row is None:
            raise RuntimeError("Supabase did not return the created reading")
        return reading_from_row(row)

    async def get_owned(self, reading_id: UUID, user_id: UUID) -> Reading | None:
        response = await self._run(
            lambda: self._client.table("readings")
            .select("*, meters!inner(properties!inner(user_id))")
            .eq("id", str(reading_id))
            .eq("meters.properties.user_id", str(user_id))
            .limit(1)
            .execute()
        )
        row = self._first(response)
        return None if row is None else reading_from_row(row)

    async def save_owned(self, reading: Reading, user_id: UUID) -> Reading:
        if reading.id is None:
            raise ValueError("Cannot update a reading without an id")
        existing = await self.get_owned(reading.id, user_id)
        if existing is None:
            raise EntityNotFoundError("Reading not found")
        response = await self._run(
            lambda: self._client.table("readings")
            .update(_reading_payload(reading))
            .eq("id", str(reading.id))
            .execute()
        )
        row = self._first(response)
        if row is None:
            raise RuntimeError("Supabase did not return the updated reading")
        return reading_from_row(row)

    async def get_latest_confirmed(self, meter_id: UUID, user_id: UUID) -> Reading | None:
        await self._require_meter_owned(meter_id, user_id)
        response = await self._run(
            lambda: self._client.table("readings")
            .select("*")
            .eq("meter_id", str(meter_id))
            .in_("status", ["confirmed", "manual"])
            .order("captured_at", desc=True)
            .limit(1)
            .execute()
        )
        row = self._first(response)
        return None if row is None else reading_from_row(row)

    async def list_by_meter(
        self,
        meter_id: UUID,
        user_id: UUID,
        *,
        limit: int = 100,
    ) -> list[Reading]:
        await self._require_meter_owned(meter_id, user_id)
        safe_limit = max(1, min(limit, 500))
        response = await self._run(
            lambda: self._client.table("readings")
            .select("*")
            .eq("meter_id", str(meter_id))
            .order("captured_at", desc=True)
            .limit(safe_limit)
            .execute()
        )
        return [reading_from_row(row) for row in self._data(response)]

    async def list_photo_paths_by_meter(
        self,
        meter_id: UUID,
        user_id: UUID,
    ) -> list[str]:
        await self._require_meter_owned(meter_id, user_id)
        response = await self._run(
            lambda: self._client.table("readings")
            .select("photo_path")
            .eq("meter_id", str(meter_id))
            .execute()
        )
        return [
            path
            for row in self._data(response)
            if isinstance((path := row.get("photo_path")), str) and path
        ]

    async def list_confirmed_by_meter(
        self,
        meter_id: UUID,
        user_id: UUID,
        *,
        limit: int = 2,
    ) -> list[Reading]:
        await self._require_meter_owned(meter_id, user_id)
        safe_limit = max(1, min(limit, 100))
        response = await self._run(
            lambda: self._client.table("readings")
            .select("*")
            .eq("meter_id", str(meter_id))
            .in_("status", ["confirmed", "manual"])
            .not_.is_("confirmed_value", "null")
            .order("captured_at", desc=True)
            .limit(safe_limit)
            .execute()
        )
        return [reading_from_row(row) for row in self._data(response)]
