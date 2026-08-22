from decimal import Decimal

import pytest

from src.domain.services.billing import BillingService, InvalidReadingError


@pytest.fixture
def service() -> BillingService:
    return BillingService()


def test_calculates_simple_charge(service: BillingService) -> None:
    result = service.calculate(Decimal("100"), Decimal("112"), Decimal("8.25"))

    assert result.consumption == Decimal("12")
    assert result.amount == Decimal("99.00")


def test_preserves_fractional_consumption(service: BillingService) -> None:
    result = service.calculate(Decimal("18.125"), Decimal("19.375"), Decimal("42.10"))

    assert result.consumption == Decimal("1.250")
    assert result.amount == Decimal("52.63")


def test_rounds_money_half_up(service: BillingService) -> None:
    result = service.calculate(Decimal("0"), Decimal("12.5"), Decimal("8.25"))

    assert result.amount == Decimal("103.13")


def test_equal_readings_produce_zero_charge(service: BillingService) -> None:
    result = service.calculate(Decimal("7.1"), Decimal("7.1"), Decimal("10"))

    assert result.consumption == Decimal("0.0")
    assert result.amount == Decimal("0.00")


def test_rejects_decreasing_reading(service: BillingService) -> None:
    with pytest.raises(InvalidReadingError):
        service.calculate(Decimal("10"), Decimal("9.99"), Decimal("8"))

