from typing import Any
from uuid import UUID

from src.application.exceptions import AccessDeniedError
from src.domain.entities import BillingPeriod, Charge
from src.infrastructure.supabase.repositories.base import SupabaseRepository
from src.infrastructure.supabase.repositories.mappers import (
    billing_period_from_row,
    charge_from_row,
)


class SupabaseBillingRepository(SupabaseRepository):
    async def get_or_create_period(
        self,
        period: BillingPeriod,
        user_id: UUID,
    ) -> BillingPeriod:
        await self._require_property_owned(period.property_id, user_id)
        existing = await self._run(
            lambda: self._client.table("billing_periods")
            .select("*")
            .eq("property_id", str(period.property_id))
            .eq("year", period.year)
            .eq("month", period.month)
            .limit(1)
            .execute()
        )
        row = self._first(existing)
        if row is not None:
            return billing_period_from_row(row)

        payload: dict[str, Any] = {
            "property_id": str(period.property_id),
            "year": period.year,
            "month": period.month,
            "status": period.status.value,
        }
        if period.id is not None:
            payload["id"] = str(period.id)
        response = await self._run(
            lambda: self._client.table("billing_periods")
            .upsert(payload, on_conflict="property_id,year,month")
            .execute()
        )
        row = self._first(response)
        if row is None:
            raise RuntimeError("Supabase did not return the billing period")
        return billing_period_from_row(row)

    async def add_charge(self, charge: Charge, user_id: UUID) -> Charge:
        if charge.billing_period_id is None:
            raise ValueError("Cannot save a charge without billing_period_id")
        period_property_id = await self._owned_period_property(charge.billing_period_id, user_id)
        meter_property_id = await self._owned_meter_property(charge.meter_id, user_id)
        if period_property_id != meter_property_id:
            raise AccessDeniedError(
                "Charge meter and billing period belong to different properties"
            )

        payload: dict[str, Any] = {
            "billing_period_id": str(charge.billing_period_id),
            "meter_id": str(charge.meter_id),
            "previous_reading": str(charge.previous_reading),
            "current_reading": str(charge.current_reading),
            "consumption": str(charge.consumption),
            "tariff_price": str(charge.tariff_price),
            "amount": str(charge.amount),
        }
        if charge.id is not None:
            payload["id"] = str(charge.id)
        response = await self._run(
            lambda: self._client.table("charges")
            .upsert(payload, on_conflict="billing_period_id,meter_id")
            .execute()
        )
        row = self._first(response)
        if row is None:
            raise RuntimeError("Supabase did not return the charge")
        return charge_from_row(row)

    async def list_charges(self, billing_period_id: UUID, user_id: UUID) -> list[Charge]:
        await self._require_period_owned(billing_period_id, user_id)
        response = await self._run(
            lambda: self._client.table("charges")
            .select("*")
            .eq("billing_period_id", str(billing_period_id))
            .order("created_at")
            .execute()
        )
        return [charge_from_row(row) for row in self._data(response)]

    async def _owned_period_property(self, period_id: UUID, user_id: UUID) -> UUID:
        response = await self._run(
            lambda: self._client.table("billing_periods")
            .select("property_id, properties!inner(user_id)")
            .eq("id", str(period_id))
            .eq("properties.user_id", str(user_id))
            .limit(1)
            .execute()
        )
        row = self._first(response)
        if row is None:
            raise AccessDeniedError("Billing period does not belong to the current user")
        return UUID(str(row["property_id"]))

    async def _owned_meter_property(self, meter_id: UUID, user_id: UUID) -> UUID:
        response = await self._run(
            lambda: self._client.table("meters")
            .select("property_id, properties!inner(user_id)")
            .eq("id", str(meter_id))
            .eq("properties.user_id", str(user_id))
            .limit(1)
            .execute()
        )
        row = self._first(response)
        if row is None:
            raise AccessDeniedError("Meter does not belong to the current user")
        return UUID(str(row["property_id"]))
