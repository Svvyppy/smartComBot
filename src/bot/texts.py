from enum import StrEnum

from src.domain.enums import MeterUnit, UtilityType


class MenuButton(StrEnum):
    PROPERTIES = "🏠 Объекты"
    METERS = "📟 Счётчики"
    READINGS = "✍️ Передать показания"
    TARIFFS = "💰 Тарифы"
    HISTORY = "📚 История"
    OCR_DEBUG = "🧪 Отладка OCR"
    HELP = "ℹ️ Помощь"


UTILITY_LABELS: dict[UtilityType, str] = {
    UtilityType.COLD_WATER: "Холодная вода",
    UtilityType.HOT_WATER: "Горячая вода",
    UtilityType.ELECTRICITY: "Электричество",
    UtilityType.GAS: "Газ",
    UtilityType.HEATING: "Отопление",
}

UNIT_LABELS: dict[MeterUnit, str] = {
    MeterUnit.CUBIC_METER: "м³",
    MeterUnit.KILOWATT_HOUR: "кВт⋅ч",
}


def utility_label(utility_type: UtilityType) -> str:
    return UTILITY_LABELS[utility_type]


def unit_label(unit: MeterUnit) -> str:
    return UNIT_LABELS[unit]
