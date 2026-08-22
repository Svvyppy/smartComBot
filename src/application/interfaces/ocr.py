from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OCRTextLine:
    text: str
    confidence: float


@dataclass(frozen=True, slots=True)
class OCRResult:
    reading: Decimal | None
    serial_number: str | None
    confidence: float
    raw_text: list[str]


class SynchronousOCR(Protocol):
    def recognize(
        self,
        image_content: bytes,
        *,
        previous_reading: Decimal | None = None,
        max_delta: Decimal | None = None,
    ) -> OCRResult: ...
