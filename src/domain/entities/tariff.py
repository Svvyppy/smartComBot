from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from src.domain.enums import TariffZone, UtilityType


@dataclass(slots=True, kw_only=True)
class TariffPlan:
    property_id: UUID
    utility_type: UtilityType
    name: str
    valid_from: date
    valid_to: date | None = None
    id: UUID | None = None
    created_at: datetime | None = None


@dataclass(slots=True, kw_only=True)
class TariffRate:
    tariff_plan_id: UUID
    price: Decimal
    zone: TariffZone = TariffZone.STANDARD
    min_consumption: Decimal | None = None
    max_consumption: Decimal | None = None
    id: UUID | None = None
