from datetime import date
from typing import Protocol
from uuid import UUID

from src.domain.entities import (
    BillingPeriod,
    Charge,
    Meter,
    Property,
    Reading,
    TariffPlan,
    TariffRate,
    User,
)
from src.domain.enums import UtilityType


class UserRepository(Protocol):
    async def save(self, user: User) -> User: ...

    async def get_by_telegram_id(self, telegram_id: int) -> User | None: ...


class PropertyRepository(Protocol):
    async def add(self, property_: Property, user_id: UUID) -> Property: ...

    async def get_owned(self, property_id: UUID, user_id: UUID) -> Property | None: ...

    async def list_by_user(self, user_id: UUID) -> list[Property]: ...


class MeterRepository(Protocol):
    async def add(self, meter: Meter, user_id: UUID) -> Meter: ...

    async def get_owned(self, meter_id: UUID, user_id: UUID) -> Meter | None: ...

    async def set_serial_number_if_missing(
        self,
        meter_id: UUID,
        user_id: UUID,
        serial_number: str,
    ) -> Meter: ...

    async def list_by_property(
        self,
        property_id: UUID,
        user_id: UUID,
        *,
        active_only: bool = True,
    ) -> list[Meter]: ...


class ReadingRepository(Protocol):
    async def add(self, reading: Reading, user_id: UUID) -> Reading: ...

    async def get_owned(self, reading_id: UUID, user_id: UUID) -> Reading | None: ...

    async def save_owned(self, reading: Reading, user_id: UUID) -> Reading: ...

    async def get_latest_confirmed(self, meter_id: UUID, user_id: UUID) -> Reading | None: ...

    async def list_by_meter(
        self,
        meter_id: UUID,
        user_id: UUID,
        *,
        limit: int = 100,
    ) -> list[Reading]: ...


class TariffRepository(Protocol):
    async def add_plan(self, plan: TariffPlan, user_id: UUID) -> TariffPlan: ...

    async def add_rate(self, rate: TariffRate, user_id: UUID) -> TariffRate: ...

    async def get_active_plan(
        self,
        property_id: UUID,
        user_id: UUID,
        utility_type: UtilityType,
        on_date: date,
    ) -> TariffPlan | None: ...

    async def list_rates(self, tariff_plan_id: UUID, user_id: UUID) -> list[TariffRate]: ...


class BillingRepository(Protocol):
    async def get_or_create_period(self, period: BillingPeriod, user_id: UUID) -> BillingPeriod: ...

    async def add_charge(self, charge: Charge, user_id: UUID) -> Charge: ...

    async def list_charges(self, billing_period_id: UUID, user_id: UUID) -> list[Charge]: ...
