from datetime import date
from decimal import Decimal
from uuid import UUID

from src.application.exceptions import ActiveTariffNotFoundError
from src.application.interfaces import TariffRepository
from src.domain.entities import TariffPlan, TariffRate
from src.domain.enums import TariffZone, UtilityType


class TariffService:
    def __init__(self, tariffs: TariffRepository) -> None:
        self._tariffs = tariffs

    async def create_simple(
        self,
        *,
        user_id: UUID,
        property_id: UUID,
        utility_type: UtilityType,
        name: str,
        price: Decimal,
        valid_from: date,
        valid_to: date | None = None,
    ) -> tuple[TariffPlan, TariffRate]:
        if price < 0:
            raise ValueError("Tariff price cannot be negative")
        if valid_to is not None and valid_to < valid_from:
            raise ValueError("Tariff valid_to cannot be earlier than valid_from")
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Tariff name cannot be empty")

        plan = await self._tariffs.add_plan(
            TariffPlan(
                property_id=property_id,
                utility_type=utility_type,
                name=clean_name,
                valid_from=valid_from,
                valid_to=valid_to,
            ),
            user_id,
        )
        if plan.id is None:
            raise RuntimeError("Saved tariff plan does not have an id")
        rate = await self._tariffs.add_rate(
            TariffRate(
                tariff_plan_id=plan.id,
                zone=TariffZone.STANDARD,
                price=price,
            ),
            user_id,
        )
        return plan, rate

    async def get_simple_price(
        self,
        *,
        user_id: UUID,
        property_id: UUID,
        utility_type: UtilityType,
        on_date: date,
    ) -> Decimal:
        plan = await self._tariffs.get_active_plan(
            property_id,
            user_id,
            utility_type,
            on_date,
        )
        if plan is None or plan.id is None:
            raise ActiveTariffNotFoundError("No active tariff plan")
        rates = await self._tariffs.list_rates(plan.id, user_id)
        simple_rates = [
            rate
            for rate in rates
            if rate.zone == TariffZone.STANDARD
            and rate.min_consumption is None
            and rate.max_consumption is None
        ]
        if len(simple_rates) != 1:
            raise ActiveTariffNotFoundError("Active plan must contain one simple rate")
        return simple_rates[0].price

