from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

MONEY_QUANTUM = Decimal("0.01")


class InvalidReadingError(ValueError):
    """Raised when a reading cannot be used for billing."""


@dataclass(frozen=True, slots=True)
class BillingResult:
    consumption: Decimal
    amount: Decimal


class BillingService:
    """Calculate a simple single-rate charge without infrastructure dependencies."""

    def calculate(
        self,
        previous_reading: Decimal,
        current_reading: Decimal,
        price: Decimal,
    ) -> BillingResult:
        if current_reading < previous_reading:
            raise InvalidReadingError("Current reading cannot be less than previous reading")
        if price < 0:
            raise ValueError("Tariff price cannot be negative")

        consumption = current_reading - previous_reading
        amount = (consumption * price).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        return BillingResult(consumption=consumption, amount=amount)

