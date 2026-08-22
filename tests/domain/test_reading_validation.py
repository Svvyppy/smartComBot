from decimal import Decimal

from src.domain.enums import UtilityType
from src.domain.services import ReadingValidationService


def make_service() -> ReadingValidationService:
    return ReadingValidationService(
        {
            UtilityType.COLD_WATER: Decimal("100"),
            UtilityType.HOT_WATER: Decimal("100"),
            UtilityType.ELECTRICITY: Decimal("3000"),
        }
    )


def test_accepts_normal_delta() -> None:
    result = make_service().validate(
        utility_type=UtilityType.COLD_WATER,
        previous_reading=Decimal("25"),
        current_reading=Decimal("31.5"),
    )

    assert result.is_valid
    assert not result.requires_confirmation
    assert result.delta == Decimal("6.5")


def test_rejects_value_below_previous() -> None:
    result = make_service().validate(
        utility_type=UtilityType.ELECTRICITY,
        previous_reading=Decimal("500"),
        current_reading=Decimal("499.9"),
    )

    assert not result.is_valid
    assert result.errors


def test_warns_about_large_delta_without_rejecting() -> None:
    result = make_service().validate(
        utility_type=UtilityType.HOT_WATER,
        previous_reading=Decimal("10"),
        current_reading=Decimal("111"),
    )

    assert result.is_valid
    assert result.requires_confirmation
    assert result.warnings

