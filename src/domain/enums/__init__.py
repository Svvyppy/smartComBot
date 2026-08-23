from enum import StrEnum


class UtilityType(StrEnum):
    COLD_WATER = "cold_water"
    HOT_WATER = "hot_water"
    WASTEWATER = "wastewater"
    ELECTRICITY = "electricity"
    GAS = "gas"
    HEATING = "heating"


class MeterUnit(StrEnum):
    CUBIC_METER = "m3"
    KILOWATT_HOUR = "kwh"


class ReadingStatus(StrEnum):
    RECOGNIZED = "recognized"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    MANUAL = "manual"


class TariffZone(StrEnum):
    STANDARD = "standard"
    DAY = "day"
    NIGHT = "night"
    T1 = "t1"
    T2 = "t2"
    T3 = "t3"


class BillingPeriodStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


__all__ = [
    "BillingPeriodStatus",
    "MeterUnit",
    "ReadingStatus",
    "TariffZone",
    "UtilityType",
]
