from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from src.application.exceptions import ReadingRejectedError, SuspiciousReadingError
from src.application.readings import ReadingService
from src.domain.entities import BillingPeriod, Charge, Meter, Reading
from src.domain.enums import MeterUnit, ReadingStatus, UtilityType
from src.domain.services import BillingService, ReadingValidationService

USER_ID = UUID("10000000-0000-0000-0000-000000000001")
PROPERTY_ID = UUID("20000000-0000-0000-0000-000000000002")
METER_ID = UUID("30000000-0000-0000-0000-000000000003")
CAPTURED_AT = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


class FakeMeterRepository:
    def __init__(self) -> None:
        self.meter = Meter(
            id=METER_ID,
            property_id=PROPERTY_ID,
            name="Электричество",
            type=UtilityType.ELECTRICITY,
            unit=MeterUnit.KILOWATT_HOUR,
        )

    async def get_owned(self, meter_id: UUID, user_id: UUID) -> Meter | None:
        return self.meter if (meter_id, user_id) == (METER_ID, USER_ID) else None


class FakeReadingRepository:
    def __init__(
        self,
        previous: Reading | None = None,
        history: list[Reading] | None = None,
    ) -> None:
        self.previous = previous
        self.history = history or []
        self.added: list[Reading] = []

    async def get_latest_confirmed(self, meter_id: UUID, user_id: UUID) -> Reading | None:
        return self.previous

    async def add(self, reading: Reading, user_id: UUID) -> Reading:
        saved = replace(reading, id=uuid4(), created_at=CAPTURED_AT)
        self.added.append(saved)
        return saved

    async def list_by_meter(
        self,
        meter_id: UUID,
        user_id: UUID,
        *,
        limit: int = 100,
    ) -> list[Reading]:
        return self.history[:limit]


class FakeManualReadingPersistence:
    def __init__(self) -> None:
        self.periods: list[BillingPeriod] = []
        self.charges: list[Charge] = []

    async def save_billed(
        self,
        *,
        reading: Reading,
        period: BillingPeriod,
        charge: Charge,
        user_id: UUID,
    ) -> tuple[Reading, BillingPeriod, Charge]:
        saved_reading = replace(reading, id=uuid4(), created_at=CAPTURED_AT)
        saved_period = replace(period, id=uuid4(), created_at=CAPTURED_AT)
        saved_charge = replace(
            charge,
            id=uuid4(),
            billing_period_id=saved_period.id,
            created_at=CAPTURED_AT,
        )
        self.periods.append(saved_period)
        self.charges.append(saved_charge)
        return saved_reading, saved_period, saved_charge


class FakeTariffService:
    def __init__(self, price: Decimal = Decimal("8.25")) -> None:
        self.price = price
        self.calls = 0

    async def get_simple_price(self, **_: object) -> Decimal:
        self.calls += 1
        return self.price


def previous_reading(value: str) -> Reading:
    return Reading(
        id=uuid4(),
        meter_id=METER_ID,
        confirmed_value=Decimal(value),
        status=ReadingStatus.MANUAL,
        captured_at=datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
    )


def make_service(
    previous: Reading | None,
) -> tuple[
    ReadingService,
    FakeReadingRepository,
    FakeManualReadingPersistence,
    FakeTariffService,
]:
    readings = FakeReadingRepository(previous)
    billing_repository = FakeManualReadingPersistence()
    tariffs = FakeTariffService()
    service = ReadingService(
        meters=FakeMeterRepository(),  # type: ignore[arg-type]
        readings=readings,  # type: ignore[arg-type]
        manual_readings=billing_repository,  # type: ignore[arg-type]
        tariffs=tariffs,  # type: ignore[arg-type]
        billing=BillingService(),
        validation=ReadingValidationService({UtilityType.ELECTRICITY: Decimal("3000")}),
    )
    return service, readings, billing_repository, tariffs


async def test_first_manual_reading_is_saved_as_baseline() -> None:
    service, readings, billing_repository, tariffs = make_service(None)

    result = await service.record_manual(
        user_id=USER_ID,
        meter_id=METER_ID,
        value=Decimal("18432.7"),
        captured_at=CAPTURED_AT,
    )

    assert result.is_baseline
    assert result.reading.confirmed_value == Decimal("18432.7")
    assert result.reading.status == ReadingStatus.MANUAL
    assert len(readings.added) == 1
    assert billing_repository.charges == []
    assert tariffs.calls == 0


async def test_subsequent_reading_creates_snapshot_charge() -> None:
    service, _, billing_repository, _ = make_service(previous_reading("18432.7"))

    result = await service.record_manual(
        user_id=USER_ID,
        meter_id=METER_ID,
        value=Decimal("18621.4"),
        captured_at=CAPTURED_AT,
    )

    assert result.billing is not None
    assert result.billing.consumption == Decimal("188.7")
    assert result.billing.amount == Decimal("1556.78")
    assert result.charge is not None
    assert result.charge.tariff_price == Decimal("8.25")
    assert billing_repository.periods[0].month == 8


async def test_decreasing_reading_is_not_saved() -> None:
    service, readings, _, _ = make_service(previous_reading("100"))

    with pytest.raises(ReadingRejectedError):
        await service.record_manual(
            user_id=USER_ID,
            meter_id=METER_ID,
            value=Decimal("99.9"),
            captured_at=CAPTURED_AT,
        )

    assert readings.added == []


async def test_large_delta_requires_explicit_confirmation() -> None:
    service, readings, _, _ = make_service(previous_reading("100"))

    with pytest.raises(SuspiciousReadingError):
        await service.record_manual(
            user_id=USER_ID,
            meter_id=METER_ID,
            value=Decimal("4000"),
            captured_at=CAPTURED_AT,
        )

    assert readings.added == []


async def test_large_delta_can_be_explicitly_confirmed() -> None:
    service, readings, manual_readings, _ = make_service(previous_reading("100"))

    result = await service.record_manual(
        user_id=USER_ID,
        meter_id=METER_ID,
        value=Decimal("4000"),
        captured_at=CAPTURED_AT,
        allow_suspicious=True,
    )

    assert result.validation is not None
    assert result.validation.requires_confirmation
    assert readings.added == []
    assert len(manual_readings.charges) == 1


async def test_history_contains_only_confirmed_values() -> None:
    service, readings, _, _ = make_service(None)
    confirmed = previous_reading("123.4")
    recognized = Reading(
        id=uuid4(),
        meter_id=METER_ID,
        ocr_value=Decimal("125"),
        status=ReadingStatus.RECOGNIZED,
        captured_at=CAPTURED_AT,
    )
    readings.history = [confirmed, recognized]

    history = await service.list_history(user_id=USER_ID, meter_id=METER_ID)

    assert history == [confirmed]
