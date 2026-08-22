from typing import Protocol
from uuid import UUID

from src.domain.entities import BillingPeriod, Charge, Reading


class RecognizedReadingPersistence(Protocol):
    """Atomically confirm one OCR reading and its optional billing snapshot."""

    async def confirm(
        self,
        *,
        reading: Reading,
        period: BillingPeriod | None,
        charge: Charge | None,
        user_id: UUID,
    ) -> tuple[Reading, BillingPeriod | None, Charge | None]: ...
