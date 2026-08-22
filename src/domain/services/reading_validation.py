from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from src.domain.enums import UtilityType


@dataclass(frozen=True, slots=True)
class ReadingValidationResult:
    delta: Decimal
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def requires_confirmation(self) -> bool:
        return bool(self.warnings)


class ReadingValidationService:
    """Validate monotonic readings and flag configurable unusually large deltas."""

    def __init__(self, max_monthly_deltas: Mapping[UtilityType, Decimal]) -> None:
        self._max_monthly_deltas = MappingProxyType(dict(max_monthly_deltas))

    def validate(
        self,
        *,
        utility_type: UtilityType,
        previous_reading: Decimal,
        current_reading: Decimal,
    ) -> ReadingValidationResult:
        delta = current_reading - previous_reading
        if delta < 0:
            return ReadingValidationResult(
                delta=delta,
                errors=("Новое показание не может быть меньше предыдущего.",),
            )

        limit = self._max_monthly_deltas.get(utility_type)
        warnings: tuple[str, ...] = ()
        if limit is not None and delta > limit:
            warnings = ("Расход выглядит необычно большим.",)

        return ReadingValidationResult(delta=delta, warnings=warnings)

