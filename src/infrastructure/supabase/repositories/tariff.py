from datetime import date
from typing import Any
from uuid import UUID

from src.domain.entities import TariffPlan, TariffRate
from src.domain.enums import UtilityType
from src.infrastructure.supabase.repositories.base import SupabaseRepository
from src.infrastructure.supabase.repositories.mappers import (
    tariff_plan_from_row,
    tariff_rate_from_row,
)


class SupabaseTariffRepository(SupabaseRepository):
    async def add_plan(self, plan: TariffPlan, user_id: UUID) -> TariffPlan:
        await self._require_property_owned(plan.property_id, user_id)
        payload: dict[str, Any] = {
            "property_id": str(plan.property_id),
            "utility_type": plan.utility_type.value,
            "name": plan.name,
            "valid_from": plan.valid_from.isoformat(),
            "valid_to": None if plan.valid_to is None else plan.valid_to.isoformat(),
        }
        if plan.id is not None:
            payload["id"] = str(plan.id)
        response = await self._run(
            lambda: self._client.table("tariff_plans").insert(payload).execute()
        )
        row = self._first(response)
        if row is None:
            raise RuntimeError("Supabase did not return the created tariff plan")
        return tariff_plan_from_row(row)

    async def add_rate(self, rate: TariffRate, user_id: UUID) -> TariffRate:
        await self._require_plan_owned(rate.tariff_plan_id, user_id)
        payload: dict[str, Any] = {
            "tariff_plan_id": str(rate.tariff_plan_id),
            "zone": rate.zone.value,
            "min_consumption": (
                None if rate.min_consumption is None else str(rate.min_consumption)
            ),
            "max_consumption": (
                None if rate.max_consumption is None else str(rate.max_consumption)
            ),
            "price": str(rate.price),
        }
        if rate.id is not None:
            payload["id"] = str(rate.id)
        response = await self._run(
            lambda: self._client.table("tariff_rates").insert(payload).execute()
        )
        row = self._first(response)
        if row is None:
            raise RuntimeError("Supabase did not return the created tariff rate")
        return tariff_rate_from_row(row)

    async def get_active_plan(
        self,
        property_id: UUID,
        user_id: UUID,
        utility_type: UtilityType,
        on_date: date,
    ) -> TariffPlan | None:
        await self._require_property_owned(property_id, user_id)
        iso_date = on_date.isoformat()
        response = await self._run(
            lambda: self._client.table("tariff_plans")
            .select("*")
            .eq("property_id", str(property_id))
            .eq("utility_type", utility_type.value)
            .lte("valid_from", iso_date)
            .or_(f"valid_to.is.null,valid_to.gte.{iso_date}")
            .order("valid_from", desc=True)
            .limit(1)
            .execute()
        )
        row = self._first(response)
        return None if row is None else tariff_plan_from_row(row)

    async def list_rates(self, tariff_plan_id: UUID, user_id: UUID) -> list[TariffRate]:
        await self._require_plan_owned(tariff_plan_id, user_id)
        response = await self._run(
            lambda: self._client.table("tariff_rates")
            .select("*")
            .eq("tariff_plan_id", str(tariff_plan_id))
            .order("min_consumption")
            .execute()
        )
        return [tariff_rate_from_row(row) for row in self._data(response)]

    async def _require_plan_owned(self, tariff_plan_id: UUID, user_id: UUID) -> None:
        from src.application.exceptions import AccessDeniedError

        response = await self._run(
            lambda: self._client.table("tariff_plans")
            .select("id, properties!inner(user_id)")
            .eq("id", str(tariff_plan_id))
            .eq("properties.user_id", str(user_id))
            .limit(1)
            .execute()
        )
        if self._first(response) is None:
            raise AccessDeniedError("Tariff plan does not belong to the current user")

