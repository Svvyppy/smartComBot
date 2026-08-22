from typing import Protocol
from uuid import UUID

from src.domain.entities import BillingPeriod, Charge, Reading


class ManualReadingPersistence(Protocol):
    """Atomic persistence boundary for one billed manual reading."""

    async def save_billed(
        self,
        *,
        reading: Reading,
        period: BillingPeriod,
        charge: Charge,
        user_id: UUID,
    ) -> tuple[Reading, BillingPeriod, Charge]: ...

