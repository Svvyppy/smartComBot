from decimal import Decimal

import pytest

from src.domain.services import infer_mechanical_fraction_digits, mechanical_value


@pytest.mark.parametrize(
    ("digits", "fraction_digits", "expected"),
    [
        ("00127929", 3, Decimal("127.929")),
        ("004207", 1, Decimal("420.7")),
        ("001254", 0, Decimal("1254")),
    ],
)
def test_mechanical_value(
    digits: str,
    fraction_digits: int,
    expected: Decimal,
) -> None:
    assert mechanical_value(digits, fraction_digits) == expected


def test_infer_fraction_digits_from_user_correction() -> None:
    assert infer_mechanical_fraction_digits("001254", Decimal("12.54")) == 2


def test_infer_fraction_digits_returns_none_for_wrong_recognized_digits() -> None:
    assert infer_mechanical_fraction_digits("001254", Decimal("12.99")) is None
