from aiogram.fsm.state import State, StatesGroup


class PropertyForm(StatesGroup):
    name = State()
    address = State()


class MeterForm(StatesGroup):
    name = State()
    utility_type = State()
    serial_number = State()


class TariffForm(StatesGroup):
    price = State()


class ReadingForm(StatesGroup):
    value = State()
    suspicious_confirmation = State()

