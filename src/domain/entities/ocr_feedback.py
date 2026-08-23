from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(slots=True, kw_only=True)
class OCRFeedback:
    reading_id: UUID
    meter_id: UUID
    user_id: UUID
    detected_value: Decimal
    corrected_value: Decimal
    raw_text: tuple[str, ...] = ()
    serial_number: str | None = None
    corrected_serial_number: str | None = None
    mechanical_digits: str | None = None
    photo_path: str | None = None
    status: str = "pending"
    id: UUID | None = None
    created_at: datetime | None = None


@dataclass(slots=True, kw_only=True)
class MeterOCRProfile:
    meter_id: UUID
    mechanical_fraction_digits: int | None = None
    learned_from_feedback_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
