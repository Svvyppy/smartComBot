from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from src.application.exceptions import (
    AccessDeniedError,
    OCRReadingNotFoundError,
    ReadingRejectedError,
)
from src.application.interfaces import (
    ImageStorage,
    MeterRepository,
    ReadingRepository,
    RecognizedReadingPersistence,
)
from src.application.ocr import OCRExecutor
from src.application.tariffs import TariffService
from src.domain.entities import BillingPeriod, Charge, Meter, Reading
from src.domain.enums import ReadingStatus
from src.domain.services import (
    BillingResult,
    BillingService,
    ReadingValidationResult,
    ReadingValidationService,
)


@dataclass(frozen=True, slots=True)
class PhotoReadingResult:
    reading: Reading
    previous_reading: Decimal | None
    billing: BillingResult | None
    validation: ReadingValidationResult | None
    serial_number: str | None = None
    charge: Charge | None = None

    @property
    def is_baseline(self) -> bool:
        return self.previous_reading is None


class PhotoReadingService:
    def __init__(
        self,
        *,
        meters: MeterRepository,
        readings: ReadingRepository,
        recognized_readings: RecognizedReadingPersistence,
        tariffs: TariffService,
        billing: BillingService,
        validation: ReadingValidationService,
        ocr: OCRExecutor,
        storage: ImageStorage,
    ) -> None:
        self._meters = meters
        self._readings = readings
        self._recognized_readings = recognized_readings
        self._tariffs = tariffs
        self._billing = billing
        self._validation = validation
        self._ocr = ocr
        self._storage = storage

    async def recognize_photo(
        self,
        *,
        user_id: UUID,
        meter_id: UUID,
        image_content: bytes,
        captured_at: datetime | None = None,
    ) -> PhotoReadingResult:
        meter = await self._get_active_meter(user_id=user_id, meter_id=meter_id)
        captured = captured_at or datetime.now(UTC)
        if captured.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware")
        previous = await self._readings.get_latest_confirmed(meter_id, user_id)
        previous_value = self._confirmed_value(previous)
        ocr_result = await self._ocr.recognize(
            image_content,
            previous_reading=previous_value,
            max_delta=self._validation.max_delta_for(meter.type),
        )
        if ocr_result.reading is None:
            raise OCRReadingNotFoundError("На фотографии не найдено показание счётчика.")

        validation, billing_result, tariff_price = await self._preview(
            user_id=user_id,
            meter=meter,
            previous_value=previous_value,
            current_value=ocr_result.reading,
            captured_at=captured,
        )
        photo_path = await self._storage.save_meter_photo(
            user_id=user_id,
            property_id=meter.property_id,
            meter_id=meter_id,
            content=image_content,
        )
        reading = await self._readings.add(
            Reading(
                meter_id=meter_id,
                ocr_value=ocr_result.reading,
                ocr_confidence=ocr_result.confidence,
                status=ReadingStatus.RECOGNIZED,
                photo_path=photo_path,
                captured_at=captured,
            ),
            user_id,
        )
        return PhotoReadingResult(
            reading=reading,
            previous_reading=previous_value,
            billing=billing_result,
            validation=validation,
            serial_number=ocr_result.serial_number,
            charge=self._charge_preview(
                reading=reading,
                previous_value=previous_value,
                billing_result=billing_result,
                tariff_price=tariff_price,
            ),
        )

    async def confirm(
        self,
        *,
        user_id: UUID,
        reading_id: UUID,
        value: Decimal | None = None,
    ) -> PhotoReadingResult:
        existing = await self._readings.get_owned(reading_id, user_id)
        if existing is None:
            raise AccessDeniedError("Reading not found or access denied")
        if existing.status != ReadingStatus.RECOGNIZED or existing.ocr_value is None:
            raise ReadingRejectedError("Показание уже обработано.")
        confirmed_value = existing.ocr_value if value is None else value
        meter = await self._get_active_meter(user_id=user_id, meter_id=existing.meter_id)
        previous = await self._readings.get_latest_confirmed(existing.meter_id, user_id)
        previous_value = self._confirmed_value(previous)
        validation, billing_result, tariff_price = await self._preview(
            user_id=user_id,
            meter=meter,
            previous_value=previous_value,
            current_value=confirmed_value,
            captured_at=existing.captured_at,
        )
        final_reading = replace(
            existing,
            confirmed_value=confirmed_value,
            status=ReadingStatus.CONFIRMED,
        )
        period: BillingPeriod | None = None
        charge = self._charge_preview(
            reading=final_reading,
            previous_value=previous_value,
            billing_result=billing_result,
            tariff_price=tariff_price,
        )
        if charge is not None:
            period = BillingPeriod(
                property_id=meter.property_id,
                year=existing.captured_at.year,
                month=existing.captured_at.month,
            )
        final_reading, _, charge = await self._recognized_readings.confirm(
            reading=final_reading,
            period=period,
            charge=charge,
            user_id=user_id,
        )
        return PhotoReadingResult(
            reading=final_reading,
            previous_reading=previous_value,
            billing=billing_result,
            validation=validation,
            charge=charge,
        )

    async def reject(self, *, user_id: UUID, reading_id: UUID) -> Reading:
        existing = await self._readings.get_owned(reading_id, user_id)
        if existing is None:
            raise AccessDeniedError("Reading not found or access denied")
        if existing.status != ReadingStatus.RECOGNIZED:
            raise ReadingRejectedError("Показание уже обработано.")
        return await self._readings.save_owned(
            replace(existing, status=ReadingStatus.REJECTED),
            user_id,
        )

    async def _get_active_meter(self, *, user_id: UUID, meter_id: UUID) -> Meter:
        meter = await self._meters.get_owned(meter_id, user_id)
        if meter is None:
            raise AccessDeniedError("Meter not found or access denied")
        if not meter.active:
            raise ReadingRejectedError("Cannot add a reading to an inactive meter")
        return meter

    @staticmethod
    def _confirmed_value(previous: Reading | None) -> Decimal | None:
        if previous is None:
            return None
        if previous.confirmed_value is None:
            raise RuntimeError("Confirmed reading is missing confirmed_value")
        return previous.confirmed_value

    async def _preview(
        self,
        *,
        user_id: UUID,
        meter: Meter,
        previous_value: Decimal | None,
        current_value: Decimal,
        captured_at: datetime,
    ) -> tuple[ReadingValidationResult | None, BillingResult | None, Decimal | None]:
        if current_value < 0:
            raise ReadingRejectedError("Reading cannot be negative")
        if previous_value is None:
            return None, None, None
        validation = self._validation.validate(
            utility_type=meter.type,
            previous_reading=previous_value,
            current_reading=current_value,
        )
        if not validation.is_valid:
            raise ReadingRejectedError(validation.errors[0])
        tariff_price = await self._tariffs.get_simple_price(
            user_id=user_id,
            property_id=meter.property_id,
            utility_type=meter.type,
            on_date=captured_at.date(),
        )
        return (
            validation,
            self._billing.calculate(previous_value, current_value, tariff_price),
            tariff_price,
        )

    @staticmethod
    def _charge_preview(
        *,
        reading: Reading,
        previous_value: Decimal | None,
        billing_result: BillingResult | None,
        tariff_price: Decimal | None,
    ) -> Charge | None:
        if previous_value is None or billing_result is None or tariff_price is None:
            return None
        current_value = (
            reading.confirmed_value
            if reading.confirmed_value is not None
            else reading.ocr_value
        )
        if current_value is None:
            raise RuntimeError("Reading is missing both OCR and confirmed values")
        return Charge(
            billing_period_id=None,
            meter_id=reading.meter_id,
            previous_reading=previous_value,
            current_reading=current_value,
            consumption=billing_result.consumption,
            tariff_price=tariff_price,
            amount=billing_result.amount,
        )
