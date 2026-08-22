from datetime import datetime
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

    async def set_goal(
        self,
        *,
        sample_id: UUID,
        user_id: UUID,
        goal: str,
    ) -> None: ...
