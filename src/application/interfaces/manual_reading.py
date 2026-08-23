from decimal import Decimal
from typing import Protocol
from uuid import UUID

from src.domain.entities import BillingPeriod, Charge, Reading, WastewaterCharge


class ManualReadingPersistence(Protocol):
    """Atomic persistence boundary for one billed manual reading."""

    async def save_billed(
        self,
        *,
        reading: Reading,
        period: BillingPeriod,
        charge: Charge,
        wastewater_tariff_price: Decimal | None,
        user_id: UUID,
    ) -> tuple[Reading, BillingPeriod, Charge, WastewaterCharge | None]: ...
