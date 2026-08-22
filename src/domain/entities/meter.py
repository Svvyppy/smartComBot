from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.domain.enums import MeterUnit, UtilityType


@dataclass(slots=True, kw_only=True)
class Meter:
    property_id: UUID
    name: str
    type: UtilityType
    unit: MeterUnit
    serial_number: str | None = None
    active: bool = True
    id: UUID | None = None
    created_at: datetime | None = None
