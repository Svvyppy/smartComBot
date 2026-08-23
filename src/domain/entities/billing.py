from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from src.domain.enums import BillingPeriodStatus


@dataclass(slots=True, kw_only=True)
class BillingPeriod:
    property_id: UUID
    year: int
    month: int
    status: BillingPeriodStatus = BillingPeriodStatus.OPEN
    id: UUID | None = None
    created_at: datetime | None = None


@dataclass(slots=True, kw_only=True)
class Charge:
    billing_period_id: UUID | None
    meter_id: UUID
    previous_reading: Decimal
    current_reading: Decimal
    consumption: Decimal
    tariff_price: Decimal
    amount: Decimal
    id: UUID | None = None
    created_at: datetime | None = None


@dataclass(slots=True, kw_only=True)
class WastewaterCharge:
    billing_period_id: UUID | None
    cold_water_consumption: Decimal
    hot_water_consumption: Decimal
    consumption: Decimal
    tariff_price: Decimal
    amount: Decimal
    id: UUID | None = None
    created_at: datetime | None = None
