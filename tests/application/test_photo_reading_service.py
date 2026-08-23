from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from src.application.exceptions import OCRReadingNotFoundError
from src.application.interfaces import OCRResult
from src.application.readings import PhotoReadingService
from src.domain.entities import BillingPeriod, Charge, Meter, Reading, WastewaterCharge
from src.domain.enums import MeterUnit, ReadingStatus, UtilityType
from src.domain.services import BillingService, ReadingValidationService

USER_ID = UUID("10000000-0000-0000-0000-000000000001")
PROPERTY_ID = UUID("20000000-0000-0000-0000-000000000002")
METER_ID = UUID("30000000-0000-0000-0000-000000000003")
READING_ID = UUID("40000000-0000-0000-0000-000000000004")
CAPTURED_AT = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


class FakeMeterRepository:
    meter = Meter(
        id=METER_ID,
        property_id=PROPERTY_ID,
        name="Электричество",
        type=UtilityType.ELECTRICITY,
        unit=MeterUnit.KILOWATT_HOUR,
    )

    async def get_owned(self, meter_id: UUID, user_id: UUID) -> Meter | None:
        return self.meter if (meter_id, user_id) == (METER_ID, USER_ID) else None


class FakeReadingRepository:
    def __init__(self, previous: Reading | None) -> None:
        self.previous = previous
        self.saved: Reading | None = None

    async def get_latest_confirmed(self, meter_id: UUID, user_id: UUID) -> Reading | None:
        return self.previous

    async def add(self, reading: Reading, user_id: UUID) -> Reading:
        self.saved = replace(reading, id=READING_ID, created_at=CAPTURED_AT)
        return self.saved

    async def get_owned(self, reading_id: UUID, user_id: UUID) -> Reading | None:
        if (reading_id, user_id) != (READING_ID, USER_ID):
            return None
        return self.saved

    async def save_owned(self, reading: Reading, user_id: UUID) -> Reading:
        self.saved = reading
        return reading


class FakeRecognizedPersistence:
    def __init__(self) -> None:
        self.confirmed: Reading | None = None
        self.charge: Charge | None = None

    async def confirm(
        self,
        *,
        reading: Reading,
        period: BillingPeriod | None,
        charge: Charge | None,
        wastewater_tariff_price: Decimal | None,
        user_id: UUID,
    ) -> tuple[Reading, BillingPeriod | None, Charge | None, WastewaterCharge | None]:
        self.confirmed = reading
        self.charge = charge
        if period is not None:
            period = replace(period, id=uuid4())
        if charge is not None:
            charge = replace(charge, id=uuid4(), billing_period_id=period.id if period else None)
        return reading, period, charge, None


class FakeOCRExecutor:
    def __init__(self, result: OCRResult) -> None:
        self.result = result
        self.previous_reading: Decimal | None = None
        self.max_delta: Decimal | None = None

    async def recognize(
        self,
        image_content: bytes,
        *,
        previous_reading: Decimal | None = None,
        max_delta: Decimal | None = None,
    ) -> OCRResult:
        self.previous_reading = previous_reading
        self.max_delta = max_delta
        return self.result


class FakeStorage:
    def __init__(self) -> None:
        self.uploads = 0

    async def save_meter_photo(self, **_: object) -> str:
        self.uploads += 1
        return f"{USER_ID}/{PROPERTY_ID}/{METER_ID}/photo.jpg"


class FakeTariffService:
    async def get_simple_price(self, **_: object) -> Decimal:
        return Decimal("8.25")


def _previous(value: str = "100") -> Reading:
    return Reading(
        id=uuid4(),
        meter_id=METER_ID,
        confirmed_value=Decimal(value),
        status=ReadingStatus.MANUAL,
        captured_at=datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
    )


def _service(
    ocr_result: OCRResult,
    previous: Reading | None = None,
) -> tuple[
    PhotoReadingService,
    FakeReadingRepository,
    FakeRecognizedPersistence,
    FakeOCRExecutor,
    FakeStorage,
]:
    readings = FakeReadingRepository(previous)
    persistence = FakeRecognizedPersistence()
    ocr = FakeOCRExecutor(ocr_result)
    storage = FakeStorage()
    service = PhotoReadingService(
        meters=FakeMeterRepository(),  # type: ignore[arg-type]
        readings=readings,  # type: ignore[arg-type]
        recognized_readings=persistence,
        tariffs=FakeTariffService(),  # type: ignore[arg-type]
        billing=BillingService(),
        validation=ReadingValidationService({UtilityType.ELECTRICITY: Decimal("3000")}),
        ocr=ocr,  # type: ignore[arg-type]
        storage=storage,
    )
    return service, readings, persistence, ocr, storage


async def test_photo_is_uploaded_only_after_successful_recognition() -> None:
    service, readings, _, ocr, storage = _service(
        OCRResult(Decimal("125.4"), "99887766", 0.91, ["00125.4"]),
        _previous(),
    )

    result = await service.recognize_photo(
        user_id=USER_ID,
        meter_id=METER_ID,
        image_content=b"jpeg",
        captured_at=CAPTURED_AT,
    )

    assert result.reading.status == ReadingStatus.RECOGNIZED
    assert result.reading.ocr_value == Decimal("125.4")
    assert result.reading.confirmed_value is None
    assert result.serial_number == "99887766"
    assert result.billing is not None
    assert result.billing.amount == Decimal("209.55")
    assert readings.saved == result.reading
    assert storage.uploads == 1
    assert ocr.previous_reading == Decimal("100")
    assert ocr.max_delta == Decimal("3000")


async def test_failed_recognition_does_not_upload_or_create_reading() -> None:
    service, readings, _, _, storage = _service(OCRResult(None, None, 0.0, ["Модель 201"]))

    with pytest.raises(OCRReadingNotFoundError):
        await service.recognize_photo(
            user_id=USER_ID,
            meter_id=METER_ID,
            image_content=b"jpeg",
            captured_at=CAPTURED_AT,
        )

    assert readings.saved is None
    assert storage.uploads == 0


async def test_correction_preserves_ocr_value_and_confirms_corrected_value() -> None:
    service, _, persistence, _, _ = _service(
        OCRResult(Decimal("125.4"), None, 0.91, ["00125.4"]),
        _previous(),
    )
    recognized = await service.recognize_photo(
        user_id=USER_ID,
        meter_id=METER_ID,
        image_content=b"jpeg",
        captured_at=CAPTURED_AT,
    )

    result = await service.confirm(
        user_id=USER_ID,
        reading_id=recognized.reading.id,  # type: ignore[arg-type]
        value=Decimal("124"),
    )

    assert result.reading.ocr_value == Decimal("125.4")
    assert result.reading.confirmed_value == Decimal("124")
    assert result.reading.status == ReadingStatus.CONFIRMED
    assert result.billing is not None
    assert result.billing.amount == Decimal("198.00")
    assert persistence.charge is not None


async def test_first_photo_reading_is_confirmed_as_baseline_without_charge() -> None:
    service, _, persistence, _, _ = _service(
        OCRResult(Decimal("42.5"), None, 0.95, ["42.5"])
    )
    recognized = await service.recognize_photo(
        user_id=USER_ID,
        meter_id=METER_ID,
        image_content=b"jpeg",
        captured_at=CAPTURED_AT,
    )

    result = await service.confirm(
        user_id=USER_ID,
        reading_id=recognized.reading.id,  # type: ignore[arg-type]
    )

    assert result.is_baseline
    assert result.charge is None
    assert persistence.charge is None
