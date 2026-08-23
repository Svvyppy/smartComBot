import asyncio
from decimal import Decimal

from src.application.interfaces import OCRResult, SynchronousOCR


class OCRExecutor:
    """Run a synchronous OCR engine away from the Telegram event loop."""

    def __init__(self, ocr: SynchronousOCR, *, max_concurrency: int = 1) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self._ocr = ocr
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def recognize(
        self,
        image_content: bytes,
        *,
        previous_reading: Decimal | None = None,
        max_delta: Decimal | None = None,
        mechanical_fraction_digits: int | None = None,
    ) -> OCRResult:
        async with self._semaphore:
            return await asyncio.to_thread(
                self._ocr.recognize,
                image_content,
                previous_reading=previous_reading,
                max_delta=max_delta,
                mechanical_fraction_digits=mechanical_fraction_digits,
            )
