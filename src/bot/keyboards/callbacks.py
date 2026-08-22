from aiogram.filters.callback_data import CallbackData


class ActionCallback(CallbackData, prefix="a"):
    action: str


class PropertyCallback(CallbackData, prefix="p"):
    action: str
    property_id: str


class MeterCallback(CallbackData, prefix="m"):
    action: str
    meter_id: str


class ReadingCallback(CallbackData, prefix="r"):
    action: str
    reading_id: str


class UtilityCallback(CallbackData, prefix="u"):
    action: str
    utility_type: str


class TariffCallback(CallbackData, prefix="t"):
    property_id: str
    utility_type: str
