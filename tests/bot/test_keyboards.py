from uuid import UUID

from src.bot.keyboards.callbacks import (
    ActionCallback,
    MeterCallback,
    PropertyCallback,
    TariffCallback,
    UtilityCallback,
)
from src.bot.keyboards.common import main_menu_keyboard
from src.bot.texts import MenuButton
from src.domain.enums import UtilityType

ID = UUID("10000000-0000-0000-0000-000000000001")


def test_callback_payloads_fit_telegram_limit() -> None:
    callbacks = [
        ActionCallback(action="add_property").pack(),
        PropertyCallback(action="add_meter", property_id=str(ID)).pack(),
        MeterCallback(action="confirm", meter_id=str(ID)).pack(),
        UtilityCallback(action="meter", utility_type=UtilityType.ELECTRICITY.value).pack(),
        TariffCallback(
            property_id=str(ID),
            utility_type=UtilityType.ELECTRICITY.value,
        ).pack(),
    ]

    assert all(len(callback.encode()) <= 64 for callback in callbacks)


def test_main_menu_contains_all_sections() -> None:
    keyboard = main_menu_keyboard()
    labels = {button.text for row in keyboard.keyboard for button in row}

    assert labels == set(MenuButton)

