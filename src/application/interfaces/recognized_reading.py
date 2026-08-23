from decimal import Decimal
from typing import Protocol
from uuid import UUID

from src.domain.entities import BillingPeriod, Charge, Reading, WastewaterCharge


class RecognizedReadingPersistence(Protocol):
    """Atomically confirm one OCR reading and its optional billing snapshot."""

    async def confirm(
        self,
        *,
        reading: Reading,
        period: BillingPeriod | None,
        charge: Charge | None,
        wastewater_tariff_price: Decimal | None,
        user_id: UUID,
    ) -> tuple[Reading, BillingPeriod | None, Charge | None, WastewaterCharge | None]: ...
