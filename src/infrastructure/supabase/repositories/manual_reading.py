from typing import Any
from uuid import UUID

from src.domain.entities import BillingPeriod, Charge, Reading
from src.infrastructure.supabase.repositories.base import SupabaseRepository
from src.infrastructure.supabase.repositories.mappers import (
    billing_period_from_row,
    charge_from_row,
    reading_from_row,
)


class SupabaseManualReadingPersistence(SupabaseRepository):
    """Persist a reading and its billing snapshot through one PostgreSQL transaction."""

    async def save_billed(
        self,
        *,
        reading: Reading,
        period: BillingPeriod,
        charge: Charge,
        user_id: UUID,
    ) -> tuple[Reading, BillingPeriod, Charge]:
        if reading.confirmed_value is None:
            raise ValueError("A billed reading requires confirmed_value")
        payload: dict[str, Any] = {
            "p_user_id": str(user_id),
            "p_meter_id": str(reading.meter_id),
            "p_confirmed_value": str(reading.confirmed_value),
            "p_captured_at": reading.captured_at.isoformat(),
            "p_year": period.year,
            "p_month": period.month,
            "p_previous_reading": str(charge.previous_reading),
            "p_consumption": str(charge.consumption),
            "p_tariff_price": str(charge.tariff_price),
            "p_amount": str(charge.amount),
        }
        response = await self._run(
            lambda: self._client.rpc("record_manual_reading_charge", payload).execute()
        )
        bundle = self._first(response)
        if bundle is None:
            raise RuntimeError("Supabase did not return the saved manual reading bundle")
        return (
            reading_from_row(bundle["reading"]),
            billing_period_from_row(bundle["billing_period"]),
            charge_from_row(bundle["charge"]),
        )
