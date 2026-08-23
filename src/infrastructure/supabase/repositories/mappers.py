from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.domain.entities import (
    BillingPeriod,
    Charge,
    Meter,
    Property,
    Reading,
    TariffPlan,
    TariffRate,
    User,
    WastewaterCharge,
)
from src.domain.enums import (
    BillingPeriodStatus,
    MeterUnit,
    ReadingStatus,
    TariffZone,
    UtilityType,
)


def _datetime(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def user_from_row(row: dict[str, Any]) -> User:
    return User(
        id=UUID(str(row["id"])),
        telegram_id=int(row["telegram_id"]),
        username=row.get("username"),
        first_name=row.get("first_name"),
        created_at=_datetime(row.get("created_at")),
    )


def property_from_row(row: dict[str, Any]) -> Property:
    return Property(
        id=UUID(str(row["id"])),
        user_id=UUID(str(row["user_id"])),
        name=str(row["name"]),
        address=row.get("address"),
        created_at=_datetime(row.get("created_at")),
    )


def meter_from_row(row: dict[str, Any]) -> Meter:
    return Meter(
        id=UUID(str(row["id"])),
        property_id=UUID(str(row["property_id"])),
        name=str(row["name"]),
        type=UtilityType(row["type"]),
        serial_number=row.get("serial_number"),
        unit=MeterUnit(row["unit"]),
        active=bool(row["active"]),
        created_at=_datetime(row.get("created_at")),
    )


def reading_from_row(row: dict[str, Any]) -> Reading:
    captured_at = _datetime(row.get("captured_at"))
    if captured_at is None:
        raise ValueError("Reading is missing captured_at")
    return Reading(
        id=UUID(str(row["id"])),
        meter_id=UUID(str(row["meter_id"])),
        ocr_value=_decimal(row.get("ocr_value")),
        confirmed_value=_decimal(row.get("confirmed_value")),
        ocr_confidence=(
            None if row.get("ocr_confidence") is None else float(row["ocr_confidence"])
        ),
        status=ReadingStatus(row["status"]),
        photo_path=row.get("photo_path"),
        captured_at=captured_at,
        created_at=_datetime(row.get("created_at")),
    )


def tariff_plan_from_row(row: dict[str, Any]) -> TariffPlan:
    return TariffPlan(
        id=UUID(str(row["id"])),
        property_id=UUID(str(row["property_id"])),
        utility_type=UtilityType(row["utility_type"]),
        name=str(row.get("name") or ""),
        valid_from=_date(row["valid_from"]),
        valid_to=None if row.get("valid_to") is None else _date(row["valid_to"]),
        created_at=_datetime(row.get("created_at")),
    )


def tariff_rate_from_row(row: dict[str, Any]) -> TariffRate:
    price = _decimal(row["price"])
    if price is None:
        raise ValueError("Tariff rate is missing price")
    return TariffRate(
        id=UUID(str(row["id"])),
        tariff_plan_id=UUID(str(row["tariff_plan_id"])),
        zone=TariffZone(row.get("zone") or TariffZone.STANDARD),
        min_consumption=_decimal(row.get("min_consumption")),
        max_consumption=_decimal(row.get("max_consumption")),
        price=price,
    )


def billing_period_from_row(row: dict[str, Any]) -> BillingPeriod:
    return BillingPeriod(
        id=UUID(str(row["id"])),
        property_id=UUID(str(row["property_id"])),
        year=int(row["year"]),
        month=int(row["month"]),
        status=BillingPeriodStatus(row.get("status") or BillingPeriodStatus.OPEN),
        created_at=_datetime(row.get("created_at")),
    )


def charge_from_row(row: dict[str, Any]) -> Charge:
    decimal_fields = {
        key: _decimal(row[key])
        for key in (
            "previous_reading",
            "current_reading",
            "consumption",
            "tariff_price",
            "amount",
        )
    }
    if any(value is None for value in decimal_fields.values()):
        raise ValueError("Charge is missing a numeric value")
    return Charge(
        id=UUID(str(row["id"])),
        billing_period_id=UUID(str(row["billing_period_id"])),
        meter_id=UUID(str(row["meter_id"])),
        previous_reading=decimal_fields["previous_reading"],  # type: ignore[arg-type]
        current_reading=decimal_fields["current_reading"],  # type: ignore[arg-type]
        consumption=decimal_fields["consumption"],  # type: ignore[arg-type]
        tariff_price=decimal_fields["tariff_price"],  # type: ignore[arg-type]
        amount=decimal_fields["amount"],  # type: ignore[arg-type]
        created_at=_datetime(row.get("created_at")),
    )


def wastewater_charge_from_row(row: dict[str, Any]) -> WastewaterCharge:
    decimal_fields = {
        key: _decimal(row[key])
        for key in (
            "cold_water_consumption",
            "hot_water_consumption",
            "consumption",
            "tariff_price",
            "amount",
        )
    }
    if any(value is None for value in decimal_fields.values()):
        raise ValueError("Wastewater charge is missing a numeric value")
    return WastewaterCharge(
        id=UUID(str(row["id"])),
        billing_period_id=UUID(str(row["billing_period_id"])),
        cold_water_consumption=decimal_fields["cold_water_consumption"],  # type: ignore[arg-type]
        hot_water_consumption=decimal_fields["hot_water_consumption"],  # type: ignore[arg-type]
        consumption=decimal_fields["consumption"],  # type: ignore[arg-type]
        tariff_price=decimal_fields["tariff_price"],  # type: ignore[arg-type]
        amount=decimal_fields["amount"],  # type: ignore[arg-type]
        created_at=_datetime(row.get("created_at")),
    )
