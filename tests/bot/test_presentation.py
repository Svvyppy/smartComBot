from decimal import Decimal

import pytest

from src.bot.presentation import format_decimal, format_money, parse_decimal


def test_parse_decimal_accepts_russian_separator_and_spaces() -> None:
    assert parse_decimal(" 18 621,40 ") == Decimal("18621.40")


@pytest.mark.parametrize("value", ["", "не число", "NaN", "Infinity"])
def test_parse_decimal_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_decimal(value)


def test_decimal_formatters_are_stable() -> None:
    assert format_decimal(Decimal("18621.400000")) == "18621.4"
    assert format_money(Decimal("1556.78")) == "1556.78"

