import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from src.application.interfaces import OCRDebugSampleStore, OCRResult
from src.application.ocr.executor import OCRExecutor

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OCRDebugCapture:
    sample_id: UUID
    current_result: OCRResult | None
    error: str | None


class OCRDebugService:
    def __init__(self, *, ocr: OCRExecutor, samples: OCRDebugSampleStore) -> None:
        self._ocr = ocr
        self._samples = samples

    async def capture(
        self,
        *,
        user_id: UUID,
        telegram_id: int,
        image_content: bytes,
        captured_at: datetime | None = None,
    ) -> OCRDebugCapture:
        captured = captured_at or datetime.now(UTC)
        if captured.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware")
        current_result: OCRResult | None = None
        error: str | None = None
        try:
            current_result = await self._ocr.recognize(image_content)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("OCR debug capture failed during initial recognition")

        sample_id = await self._samples.create(
            user_id=user_id,
            telegram_id=telegram_id,
            image_content=image_content,
            captured_at=captured,
            current_result=current_result,
            error=error,
        )
        return OCRDebugCapture(
            sample_id=sample_id,
            current_result=current_result,
            error=error,
        )

    async def set_expected_value(
        self,
        *,
        sample_id: UUID,
        user_id: UUID,
        expected_value: Decimal,
    ) -> None:
        if expected_value < 0:
            raise ValueError("Expected reading cannot be negative")
        await self._samples.set_expected_value(
            sample_id=sample_id,
            user_id=user_id,
            expected_value=expected_value,
        )
