from typing import Any
from uuid import UUID

from src.application.exceptions import AccessDeniedError
from src.domain.entities import Property
from src.infrastructure.supabase.repositories.base import SupabaseRepository
from src.infrastructure.supabase.repositories.mappers import property_from_row


class SupabasePropertyRepository(SupabaseRepository):
    async def add(self, property_: Property, user_id: UUID) -> Property:
        if property_.user_id != user_id:
            raise AccessDeniedError("Cannot create a property for another user")
        payload: dict[str, Any] = {
            "user_id": str(user_id),
            "name": property_.name,
            "address": property_.address,
        }
        if property_.id is not None:
            payload["id"] = str(property_.id)
        response = await self._run(
            lambda: self._client.table("properties").insert(payload).execute()
        )
        row = self._first(response)
        if row is None:
            raise RuntimeError("Supabase did not return the created property")
        return property_from_row(row)

    async def get_owned(self, property_id: UUID, user_id: UUID) -> Property | None:
        response = await self._run(
            lambda: self._client.table("properties")
            .select("*")
            .eq("id", str(property_id))
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )
        row = self._first(response)
        return None if row is None else property_from_row(row)

    async def list_by_user(self, user_id: UUID) -> list[Property]:
        response = await self._run(
            lambda: self._client.table("properties")
            .select("*")
            .eq("user_id", str(user_id))
            .order("created_at")
            .execute()
        )
        return [property_from_row(row) for row in self._data(response)]

