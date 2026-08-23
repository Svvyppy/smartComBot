from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from src.application.exceptions import (
    AccessDeniedError,
    ReadingRejectedError,
    SuspiciousReadingError,
)
from src.application.interfaces import ManualReadingPersistence, MeterRepository, ReadingRepository
from src.application.tariffs import TariffService
from src.domain.entities import BillingPeriod, Charge, Reading, WastewaterCharge
from src.domain.enums import ReadingStatus, UtilityType
from src.domain.services import (
    BillingResult,
    BillingService,
    ReadingValidationResult,
    ReadingValidationService,
)


@dataclass(frozen=True, slots=True)
class ManualReadingResult:
    reading: Reading
    previous_reading: Decimal | None
    billing: BillingResult | None
    validation: ReadingValidationResult | None
    charge: Charge | None
    wastewater_charge: WastewaterCharge | None = None

    @property
    def is_baseline(self) -> bool:
        return self.previous_reading is None


class ReadingService:
    def __init__(
        self,
        *,
        meters: MeterRepository,
        readings: ReadingRepository,
        manual_readings: ManualReadingPersistence,
        tariffs: TariffService,
        billing: BillingService,
        validation: ReadingValidationService,
    ) -> None:
        self._meters = meters
        self._readings = readings
        self._manual_readings = manual_readings
        self._tariffs = tariffs
        self._billing = billing
        self._validation = validation

    async def record_manual(
        self,
        *,
        user_id: UUID,
        meter_id: UUID,
        value: Decimal,
        captured_at: datetime | None = None,
        allow_suspicious: bool = False,
    ) -> ManualReadingResult:
        if value < 0:
            raise ReadingRejectedError("Reading cannot be negative")
        meter = await self._meters.get_owned(meter_id, user_id)
        if meter is None:
            raise AccessDeniedError("Meter not found or access denied")
        if not meter.active:
            raise ReadingRejectedError("Cannot add a reading to an inactive meter")

        captured = captured_at or datetime.now(UTC)
        if captured.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware")
        previous = await self._readings.get_latest_confirmed(meter_id, user_id)

        validation: ReadingValidationResult | None = None
        billing_result: BillingResult | None = None
        charge: Charge | None = None
        tariff_price: Decimal | None = None
        wastewater_tariff_price: Decimal | None = None
        wastewater_charge: WastewaterCharge | None = None
        previous_value: Decimal | None = None
        if previous is not None:
            if previous.confirmed_value is None:
                raise RuntimeError("Confirmed reading is missing confirmed_value")
            previous_value = previous.confirmed_value
            validation = self._validation.validate(
                utility_type=meter.type,
                previous_reading=previous_value,
                current_reading=value,
            )
            if not validation.is_valid:
                raise ReadingRejectedError(validation.errors[0])
            if validation.requires_confirmation and not allow_suspicious:
                raise SuspiciousReadingError(validation.warnings[0])

            tariff_price = await self._tariffs.get_simple_price(
                user_id=user_id,
                property_id=meter.property_id,
                utility_type=meter.type,
                on_date=captured.date(),
            )
            billing_result = self._billing.calculate(previous_value, value, tariff_price)
            if meter.type in {UtilityType.COLD_WATER, UtilityType.HOT_WATER}:
                wastewater_tariff_price = await self._tariffs.get_simple_price(
                    user_id=user_id,
                    property_id=meter.property_id,
                    utility_type=UtilityType.WASTEWATER,
                    on_date=captured.date(),
                )

        reading = Reading(
            meter_id=meter_id,
            confirmed_value=value,
            status=ReadingStatus.MANUAL,
            captured_at=captured,
        )

        if previous_value is not None and billing_result is not None and tariff_price is not None:
            period = BillingPeriod(
                property_id=meter.property_id,
                year=captured.year,
                month=captured.month,
            )
            charge = Charge(
                billing_period_id=None,
                meter_id=meter_id,
                previous_reading=previous_value,
                current_reading=value,
                consumption=billing_result.consumption,
                tariff_price=tariff_price,
                amount=billing_result.amount,
            )
            reading, _, charge, wastewater_charge = await self._manual_readings.save_billed(
                reading=reading,
                period=period,
                charge=charge,
                wastewater_tariff_price=wastewater_tariff_price,
                user_id=user_id,
            )
        else:
            reading = await self._readings.add(reading, user_id)

        return ManualReadingResult(
            reading=reading,
            previous_reading=None if previous is None else previous.confirmed_value,
            billing=billing_result,
            validation=validation,
            charge=charge,
            wastewater_charge=wastewater_charge,
        )

    async def list_history(
        self,
        *,
        user_id: UUID,
        meter_id: UUID,
        limit: int = 10,
    ) -> list[Reading]:
        meter = await self._meters.get_owned(meter_id, user_id)
        if meter is None:
            raise AccessDeniedError("Meter not found or access denied")
        readings = await self._readings.list_by_meter(
            meter_id,
            user_id,
            limit=limit,
        )
        return [reading for reading in readings if reading.confirmed_value is not None]
