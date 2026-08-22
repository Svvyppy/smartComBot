from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from src.domain.enums import ReadingStatus


@dataclass(slots=True, kw_only=True)
class Reading:
    meter_id: UUID
    status: ReadingStatus
    captured_at: datetime
    ocr_value: Decimal | None = None
    confirmed_value: Decimal | None = None
    ocr_confidence: float | None = None
    photo_path: str | None = None
    id: UUID | None = None
    created_at: datetime | None = None
