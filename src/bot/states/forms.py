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
    method = State()
    photo = State()
    unassigned_photo = State()
    photo_meter_selection = State()
    photo_album = State()
    photo_album_confirmation = State()
    photo_confirmation = State()
    photo_correction = State()
    value = State()
    suspicious_confirmation = State()


class OCRDebugForm(StatesGroup):
    photo = State()
    goal = State()
