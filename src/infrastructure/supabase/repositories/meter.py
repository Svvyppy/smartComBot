from typing import Any
from uuid import UUID

from src.domain.entities import Meter
from src.infrastructure.supabase.repositories.base import SupabaseRepository
from src.infrastructure.supabase.repositories.mappers import meter_from_row


class SupabaseMeterRepository(SupabaseRepository):
    async def add(self, meter: Meter, user_id: UUID) -> Meter:
        await self._require_property_owned(meter.property_id, user_id)
        payload: dict[str, Any] = {
            "property_id": str(meter.property_id),
            "name": meter.name,
            "type": meter.type.value,
            "serial_number": meter.serial_number,
            "unit": meter.unit.value,
            "active": meter.active,
        }
        if meter.id is not None:
            payload["id"] = str(meter.id)
        response = await self._run(
            lambda: self._client.table("meters").insert(payload).execute()
        )
        row = self._first(response)
        if row is None:
            raise RuntimeError("Supabase did not return the created meter")
        return meter_from_row(row)

    async def get_owned(self, meter_id: UUID, user_id: UUID) -> Meter | None:
        response = await self._run(
            lambda: self._client.table("meters")
            .select("*, properties!inner(user_id)")
            .eq("id", str(meter_id))
            .eq("properties.user_id", str(user_id))
            .limit(1)
            .execute()
        )
        row = self._first(response)
        return None if row is None else meter_from_row(row)

    async def list_by_property(
        self,
        property_id: UUID,
        user_id: UUID,
        *,
        active_only: bool = True,
    ) -> list[Meter]:
        await self._require_property_owned(property_id, user_id)

        def query() -> Any:
            builder = (
                self._client.table("meters")
                .select("*")
                .eq("property_id", str(property_id))
                .order("created_at")
            )
            if active_only:
                builder = builder.eq("active", True)
            return builder.execute()

        response = await self._run(query)
        return [meter_from_row(row) for row in self._data(response)]

