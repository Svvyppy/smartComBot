from typing import Any
from uuid import UUID

from src.domain.entities import BillingPeriod, Charge, Reading
from src.domain.enums import ReadingStatus
from src.infrastructure.supabase.repositories.base import SupabaseRepository
from src.infrastructure.supabase.repositories.mappers import (
    billing_period_from_row,
    charge_from_row,
    reading_from_row,
)


class SupabaseRecognizedReadingPersistence(SupabaseRepository):
    async def confirm(
        self,
        *,
        reading: Reading,
        period: BillingPeriod | None,
        charge: Charge | None,
        user_id: UUID,
    ) -> tuple[Reading, BillingPeriod | None, Charge | None]:
        if reading.id is None or reading.confirmed_value is None:
            raise ValueError("A confirmed OCR reading requires id and confirmed_value")
        if reading.status != ReadingStatus.CONFIRMED:
            raise ValueError("OCR reading must have confirmed status")
        if (period is None) != (charge is None):
            raise ValueError("Billing period and charge must either both be set or both be absent")

        payload: dict[str, Any] = {
            "p_user_id": str(user_id),
            "p_reading_id": str(reading.id),
            "p_confirmed_value": str(reading.confirmed_value),
            "p_year": None if period is None else period.year,
            "p_month": None if period is None else period.month,
            "p_previous_reading": (
                None if charge is None else str(charge.previous_reading)
            ),
            "p_consumption": None if charge is None else str(charge.consumption),
            "p_tariff_price": None if charge is None else str(charge.tariff_price),
            "p_amount": None if charge is None else str(charge.amount),
        }
        response = await self._run(
            lambda: self._client.rpc("confirm_recognized_reading_charge", payload).execute()
        )
        bundle = self._first(response)
        if bundle is None:
            raise RuntimeError("Supabase did not return the confirmed OCR reading bundle")
        saved_period = bundle.get("billing_period")
        saved_charge = bundle.get("charge")
        return (
            reading_from_row(bundle["reading"]),
            None if saved_period is None else billing_period_from_row(saved_period),
            None if saved_charge is None else charge_from_row(saved_charge),
        )
