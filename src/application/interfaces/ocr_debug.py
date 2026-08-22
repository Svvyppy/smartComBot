from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from src.application.interfaces.ocr import OCRResult


class OCRDebugSampleStore(Protocol):
    async def create(
        self,
        *,
        user_id: UUID,
        telegram_id: int,
        image_content: bytes,
        captured_at: datetime,
        current_result: OCRResult | None,
        error: str | None,
    ) -> UUID: ...

    async def set_expected_value(
        self,
        *,
        sample_id: UUID,
        user_id: UUID,
        expected_value: Decimal,
    ) -> None: ...
