import logging
from collections.abc import Sequence
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
    OCRFeedbackRepository,
    OCRResult,
    ReadingRepository,
    RecognizedReadingPersistence,
)
from src.application.ocr import OCRExecutor
from src.application.tariffs import TariffService
from src.domain.entities import (
    BillingPeriod,
    Charge,
    Meter,
    MeterOCRProfile,
    OCRFeedback,
    Reading,
    WastewaterCharge,
)
from src.domain.enums import ReadingStatus, UtilityType
from src.domain.services import (
    BillingResult,
    BillingService,
    ReadingValidationResult,
    ReadingValidationService,
    infer_mechanical_fraction_digits,
    mechanical_value,
    serial_number_keys,
    serial_numbers_match,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PhotoReadingResult:
    reading: Reading
    previous_reading: Decimal | None
    billing: BillingResult | None
    validation: ReadingValidationResult | None
    serial_number: str | None = None
    raw_text: tuple[str, ...] = ()
    mechanical_digits: str | None = None
    mechanical_fraction_digits: int | None = None
    feedback_saved: bool = False
    profile_updated: bool = False
    charge: Charge | None = None
    wastewater_tariff_price: Decimal | None = None
    wastewater_charge: WastewaterCharge | None = None

    @property
    def is_baseline(self) -> bool:
        return self.previous_reading is None


@dataclass(frozen=True, slots=True)
class PhotoMeterCandidate:
    meter: Meter
    previous_reading: Decimal | None
    delta: Decimal | None
    is_plausible: bool


@dataclass(frozen=True, slots=True)
class PhotoMeterIdentification:
    ocr_result: OCRResult
    matched_meter: Meter | None
    suggested_meter: Meter | None
    candidates: tuple[PhotoMeterCandidate, ...]


class PhotoReadingService:
    def __init__(
        self,
        *,
        meters: MeterRepository,
        readings: ReadingRepository,
        ocr_feedback: OCRFeedbackRepository,
        recognized_readings: RecognizedReadingPersistence,
        tariffs: TariffService,
        billing: BillingService,
        validation: ReadingValidationService,
        ocr: OCRExecutor,
        storage: ImageStorage,
    ) -> None:
        self._meters = meters
        self._readings = readings
        self._ocr_feedback = ocr_feedback
        self._recognized_readings = recognized_readings
        self._tariffs = tariffs
        self._billing = billing
        self._validation = validation
        self._ocr = ocr
        self._storage = storage

    async def identify_meter(
        self,
        *,
        user_id: UUID,
        property_id: UUID,
        image_content: bytes,
    ) -> PhotoMeterIdentification:
        meters = await self._meters.list_by_property(
            property_id,
            user_id,
            active_only=True,
        )
        if not meters:
            raise ReadingRejectedError("У объекта нет активных счётчиков.")

        ocr_result = await self._ocr.recognize(image_content)
        if ocr_result.reading is None:
            raise OCRReadingNotFoundError("На фотографии не найдено показание счётчика.")

        matched_meter = self._match_serial(meters, ocr_result.serial_number)
        if matched_meter is not None:
            ocr_result = await self._apply_meter_profile(
                ocr_result=ocr_result,
                meter=matched_meter,
                user_id=user_id,
            )
            if ocr_result.reading is None:
                raise OCRReadingNotFoundError(
                    "На фотографии не найдено показание счётчика."
                )
        current_value = ocr_result.reading
        if current_value is None:
            raise OCRReadingNotFoundError("На фотографии не найдено показание счётчика.")
        candidates = await self._rank_candidates(
            meters=meters,
            user_id=user_id,
            current_value=current_value,
        )
        suggested_meter = matched_meter
        if suggested_meter is None:
            suggested_meter = next(
                (
                    candidate.meter
                    for candidate in candidates
                    if candidate.previous_reading is not None and candidate.is_plausible
                ),
                None,
            )
        return PhotoMeterIdentification(
            ocr_result=ocr_result,
            matched_meter=matched_meter,
            suggested_meter=suggested_meter,
            candidates=candidates,
        )

    async def recognize_photo(
        self,
        *,
        user_id: UUID,
        meter_id: UUID,
        image_content: bytes,
        captured_at: datetime | None = None,
        ocr_result: OCRResult | None = None,
    ) -> PhotoReadingResult:
        meter = await self._get_active_meter(user_id=user_id, meter_id=meter_id)
        captured = captured_at or datetime.now(UTC)
        if captured.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware")
        previous = await self._readings.get_latest_confirmed(meter_id, user_id)
        previous_value = self._confirmed_value(previous)
        profile = await self._ocr_feedback.get_meter_profile(meter_id, user_id)
        if ocr_result is None:
            ocr_result = await self._ocr.recognize(
                image_content,
                previous_reading=previous_value,
                max_delta=self._validation.max_delta_for(meter.type),
                mechanical_fraction_digits=(
                    None if profile is None else profile.mechanical_fraction_digits
                ),
            )
        ocr_result = self._with_profile(ocr_result, profile)
        if ocr_result.reading is None:
            raise OCRReadingNotFoundError("На фотографии не найдено показание счётчика.")

        validation, billing_result, tariff_price, wastewater_tariff_price = await self._preview(
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
            raw_text=tuple(ocr_result.raw_text),
            mechanical_digits=ocr_result.mechanical_digits,
            mechanical_fraction_digits=ocr_result.mechanical_fraction_digits,
            charge=self._charge_preview(
                reading=reading,
                previous_value=previous_value,
                billing_result=billing_result,
                tariff_price=tariff_price,
            ),
            wastewater_tariff_price=wastewater_tariff_price,
        )

    async def confirm(
        self,
        *,
        user_id: UUID,
        reading_id: UUID,
        value: Decimal | None = None,
        detected_serial_number: str | None = None,
        corrected_serial_number: str | None = None,
        raw_text: Sequence[str] = (),
        mechanical_digits: str | None = None,
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
        validation, billing_result, tariff_price, wastewater_tariff_price = await self._preview(
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
        final_reading, _, charge, wastewater_charge = await self._recognized_readings.confirm(
            reading=final_reading,
            period=period,
            charge=charge,
            wastewater_tariff_price=wastewater_tariff_price,
            user_id=user_id,
        )
        feedback_saved = False
        profile_updated = False
        value_changed = confirmed_value != existing.ocr_value
        serial_changed = self._serial_was_corrected(
            detected_serial_number,
            corrected_serial_number,
        )
        if value_changed or serial_changed:
            try:
                feedback_saved, profile_updated = await self._record_correction(
                    user_id=user_id,
                    reading=final_reading,
                    detected_value=existing.ocr_value,
                    corrected_value=confirmed_value,
                    detected_serial_number=detected_serial_number,
                    corrected_serial_number=corrected_serial_number,
                    raw_text=raw_text,
                    mechanical_digits=mechanical_digits,
                    value_changed=value_changed,
                )
            except Exception:
                logger.exception(
                    "OCR correction feedback save failed user_id=%s reading_id=%s",
                    user_id,
                    reading_id,
                )
        return PhotoReadingResult(
            reading=final_reading,
            previous_reading=previous_value,
            billing=billing_result,
            validation=validation,
            charge=charge,
            wastewater_tariff_price=wastewater_tariff_price,
            wastewater_charge=wastewater_charge,
            feedback_saved=feedback_saved,
            profile_updated=profile_updated,
        )

    async def _record_correction(
        self,
        *,
        user_id: UUID,
        reading: Reading,
        detected_value: Decimal,
        corrected_value: Decimal,
        detected_serial_number: str | None,
        corrected_serial_number: str | None,
        raw_text: Sequence[str],
        mechanical_digits: str | None,
        value_changed: bool,
    ) -> tuple[bool, bool]:
        if reading.id is None:
            raise RuntimeError("Confirmed reading does not have an id")
        fraction_digits = (
            infer_mechanical_fraction_digits(
                mechanical_digits,
                corrected_value,
            )
            if value_changed
            else None
        )
        feedback = await self._ocr_feedback.add(
            OCRFeedback(
                reading_id=reading.id,
                meter_id=reading.meter_id,
                user_id=user_id,
                detected_value=detected_value,
                corrected_value=corrected_value,
                serial_number=detected_serial_number,
                corrected_serial_number=corrected_serial_number,
                raw_text=tuple(raw_text),
                mechanical_digits=mechanical_digits,
                photo_path=reading.photo_path,
            ),
            user_id,
        )
        if fraction_digits is None or feedback.id is None:
            return True, False
        try:
            await self._ocr_feedback.save_meter_profile(
                MeterOCRProfile(
                    meter_id=reading.meter_id,
                    mechanical_fraction_digits=fraction_digits,
                    learned_from_feedback_id=feedback.id,
                ),
                user_id,
            )
        except Exception:
            logger.exception(
                "Meter OCR profile save failed user_id=%s meter_id=%s",
                user_id,
                reading.meter_id,
            )
            return True, False
        try:
            await self._ocr_feedback.set_feedback_status(
                feedback.id,
                user_id,
                "profiled",
            )
        except Exception:
            logger.exception(
                "OCR feedback status update failed feedback_id=%s",
                feedback.id,
            )
        return True, True

    @staticmethod
    def _serial_was_corrected(
        detected_serial_number: str | None,
        corrected_serial_number: str | None,
    ) -> bool:
        if corrected_serial_number is None:
            return False
        if detected_serial_number is None:
            return True
        return not serial_numbers_match(
            detected_serial_number,
            corrected_serial_number,
        )

    async def _apply_meter_profile(
        self,
        *,
        ocr_result: OCRResult,
        meter: Meter,
        user_id: UUID,
    ) -> OCRResult:
        if meter.id is None:
            return ocr_result
        profile = await self._ocr_feedback.get_meter_profile(meter.id, user_id)
        return self._with_profile(ocr_result, profile)

    @staticmethod
    def _with_profile(
        ocr_result: OCRResult,
        profile: MeterOCRProfile | None,
    ) -> OCRResult:
        if (
            profile is None
            or profile.mechanical_fraction_digits is None
            or ocr_result.mechanical_digits is None
        ):
            return ocr_result
        return replace(
            ocr_result,
            reading=mechanical_value(
                ocr_result.mechanical_digits,
                profile.mechanical_fraction_digits,
            ),
            mechanical_fraction_digits=profile.mechanical_fraction_digits,
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

    async def _rank_candidates(
        self,
        *,
        meters: list[Meter],
        user_id: UUID,
        current_value: Decimal,
    ) -> tuple[PhotoMeterCandidate, ...]:
        candidates: list[PhotoMeterCandidate] = []
        for meter in meters:
            if meter.id is None:
                continue
            previous = await self._readings.get_latest_confirmed(meter.id, user_id)
            previous_value = self._confirmed_value(previous)
            delta = None if previous_value is None else current_value - previous_value
            limit = self._validation.max_delta_for(meter.type)
            is_plausible = delta is None or (
                delta >= 0 and (limit is None or delta <= limit)
            )
            candidates.append(
                PhotoMeterCandidate(
                    meter=meter,
                    previous_reading=previous_value,
                    delta=delta,
                    is_plausible=is_plausible,
                )
            )
        candidates.sort(key=self._candidate_sort_key)
        return tuple(candidates)

    @staticmethod
    def _candidate_sort_key(candidate: PhotoMeterCandidate) -> tuple[int, Decimal, str]:
        if candidate.previous_reading is not None and candidate.is_plausible:
            return 0, candidate.delta or Decimal(0), candidate.meter.name.casefold()
        if candidate.previous_reading is None:
            return 1, Decimal(0), candidate.meter.name.casefold()
        return 2, abs(candidate.delta or Decimal(0)), candidate.meter.name.casefold()

    @classmethod
    def _match_serial(cls, meters: list[Meter], serial_number: str | None) -> Meter | None:
        if serial_number is None:
            return None
        recognized_keys = cls._serial_keys(serial_number)
        if not recognized_keys:
            return None
        for meter in meters:
            if meter.serial_number and recognized_keys & cls._serial_keys(meter.serial_number):
                return meter
        return None

    @staticmethod
    def _serial_keys(serial_number: str) -> frozenset[str]:
        return serial_number_keys(serial_number)

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
    ) -> tuple[
        ReadingValidationResult | None,
        BillingResult | None,
        Decimal | None,
        Decimal | None,
    ]:
        if current_value < 0:
            raise ReadingRejectedError("Reading cannot be negative")
        if previous_value is None:
            return None, None, None, None
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
        wastewater_tariff_price: Decimal | None = None
        if meter.type in {UtilityType.COLD_WATER, UtilityType.HOT_WATER}:
            wastewater_tariff_price = await self._tariffs.get_simple_price(
                user_id=user_id,
                property_id=meter.property_id,
                utility_type=UtilityType.WASTEWATER,
                on_date=captured_at.date(),
            )
        return (
            validation,
            self._billing.calculate(previous_value, current_value, tariff_price),
            tariff_price,
            wastewater_tariff_price,
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
