import asyncio
from collections.abc import Callable
from typing import Any, TypeVar
from uuid import UUID

from src.application.exceptions import AccessDeniedError

T = TypeVar("T")


class SupabaseRepository:
    """Common non-blocking execution and ownership guards for Supabase adapters."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def _run(self, operation: Callable[[], T]) -> T:
        return await asyncio.to_thread(operation)

    @staticmethod
    def _data(response: Any) -> list[dict[str, Any]]:
        data = (
            response.get("data")
            if isinstance(response, dict)
            else getattr(response, "data", None)
        )
        if data is None:
            return []
        if isinstance(data, dict):
            return [data]
        return list(data)

    @classmethod
    def _first(cls, response: Any) -> dict[str, Any] | None:
        rows = cls._data(response)
        return rows[0] if rows else None

    async def _require_property_owned(self, property_id: UUID, user_id: UUID) -> None:
        response = await self._run(
            lambda: self._client.table("properties")
            .select("id")
            .eq("id", str(property_id))
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )
        if self._first(response) is None:
            raise AccessDeniedError("Property does not belong to the current user")

    async def _require_meter_owned(self, meter_id: UUID, user_id: UUID) -> None:
        response = await self._run(
            lambda: self._client.table("meters")
            .select("id, properties!inner(user_id)")
            .eq("id", str(meter_id))
            .eq("properties.user_id", str(user_id))
            .limit(1)
            .execute()
        )
        if self._first(response) is None:
            raise AccessDeniedError("Meter does not belong to the current user")

    async def _require_period_owned(self, period_id: UUID, user_id: UUID) -> None:
        response = await self._run(
            lambda: self._client.table("billing_periods")
            .select("id, properties!inner(user_id)")
            .eq("id", str(period_id))
            .eq("properties.user_id", str(user_id))
            .limit(1)
            .execute()
        )
        if self._first(response) is None:
            raise AccessDeniedError("Billing period does not belong to the current user")
