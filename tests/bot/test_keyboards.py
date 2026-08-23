from dataclasses import replace
from uuid import UUID

from src.bot.keyboards.callbacks import (
    ActionCallback,
    MeterCallback,
    PropertyCallback,
    ReadingCallback,
    TariffCallback,
    UtilityCallback,
)
from src.bot.keyboards.common import (
    main_menu_keyboard,
    photo_album_confirmation_keyboard,
    photo_confirmation_keyboard,
    photo_meter_selection_keyboard,
    photo_serial_correction_keyboard,
    reading_meters_keyboard,
    reading_method_keyboard,
    tariffs_keyboard,
    utility_keyboard,
)
from src.bot.texts import MenuButton
from src.domain.entities import Meter, Property
from src.domain.enums import MeterUnit, UtilityType

ID = UUID("10000000-0000-0000-0000-000000000001")


def test_callback_payloads_fit_telegram_limit() -> None:
    callbacks = [
        ActionCallback(action="add_property").pack(),
        PropertyCallback(action="add_meter", property_id=str(ID)).pack(),
        PropertyCallback(action="confirm_album", property_id=str(ID)).pack(),
        MeterCallback(action="confirm", meter_id=str(ID)).pack(),
        MeterCallback(action="select_photo", meter_id=str(ID)).pack(),
        ReadingCallback(action="correct", reading_id=str(ID)).pack(),
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

    assert labels == set(MenuButton) - {MenuButton.OCR_DEBUG}


def test_main_menu_can_launch_mini_app() -> None:
    keyboard = main_menu_keyboard("https://meters.example.com/miniapp/")
    dashboard = keyboard.keyboard[0][0]

    assert dashboard.text == "📊 Открыть дашборд"
    assert dashboard.web_app is not None
    assert str(dashboard.web_app.url) == "https://meters.example.com/miniapp/"


def test_reading_method_keyboard_offers_photo_and_manual_input() -> None:
    keyboard = reading_method_keyboard(str(ID))
    labels = [button.text for row in keyboard.inline_keyboard for button in row]

    assert labels == ["📷 Отправить фото", "⌨️ Ввести вручную", "Отмена"]


def test_photo_confirmation_keyboard_has_all_decisions() -> None:
    keyboard = photo_confirmation_keyboard(str(ID))
    labels = [button.text for row in keyboard.inline_keyboard for button in row]

    assert labels == ["✅ Подтвердить", "✏️ Исправить", "Отмена"]


def test_photo_serial_correction_can_keep_recognized_number() -> None:
    keyboard = photo_serial_correction_keyboard("N164701553")
    labels = [button.text for row in keyboard.inline_keyboard for button in row]

    assert labels == ["Оставить: N164701553", "Отмена"]


def test_wastewater_is_a_tariff_but_not_a_physical_meter_type() -> None:
    property_ = Property(id=ID, user_id=ID, name="Квартира")
    tariff_labels = [
        button.text for row in tariffs_keyboard(property_).inline_keyboard for button in row
    ]
    meter_labels = [
        button.text
        for row in utility_keyboard(action="meter").inline_keyboard
        for button in row
    ]

    assert "Настроить: Водоотведение" in tariff_labels
    assert "Водоотведение" not in meter_labels


def test_reading_meters_keyboard_offers_photo_identification() -> None:
    meter = Meter(
        id=ID,
        property_id=ID,
        name="ГВС",
        type=UtilityType.HOT_WATER,
        unit=MeterUnit.CUBIC_METER,
    )

    keyboard = reading_meters_keyboard(str(ID), [meter])
    labels = [button.text for row in keyboard.inline_keyboard for button in row]

    assert labels == ["📷 Определить счётчик по фото", "Горячая вода — ГВС"]


def test_reading_meters_keyboard_offers_album_only_when_all_meters_are_bound() -> None:
    second_id = UUID("20000000-0000-0000-0000-000000000002")
    first = Meter(
        id=ID,
        property_id=ID,
        name="ГВС",
        type=UtilityType.HOT_WATER,
        unit=MeterUnit.CUBIC_METER,
        serial_number="11111111",
    )
    second = Meter(
        id=second_id,
        property_id=ID,
        name="ХВС",
        type=UtilityType.COLD_WATER,
        unit=MeterUnit.CUBIC_METER,
        serial_number="22222222",
    )

    bound_keyboard = reading_meters_keyboard(str(ID), [first, second])
    bound_labels = [
        button.text for row in bound_keyboard.inline_keyboard for button in row
    ]
    unbound_keyboard = reading_meters_keyboard(
        str(ID),
        [first, replace(second, serial_number=None)],
    )
    unbound_labels = [
        button.text for row in unbound_keyboard.inline_keyboard for button in row
    ]

    assert "🖼 Отправить все фото одним альбомом" in bound_labels
    assert "🖼 Отправить все фото одним альбомом" not in unbound_labels


def test_photo_album_confirmation_keyboard_has_bulk_actions() -> None:
    keyboard = photo_album_confirmation_keyboard(str(ID))
    labels = [button.text for row in keyboard.inline_keyboard for button in row]

    assert labels == ["✅ Подтвердить все", "Отмена"]


def test_photo_meter_selection_marks_suggestion() -> None:
    suggested = Meter(
        id=ID,
        property_id=ID,
        name="ГВС",
        type=UtilityType.HOT_WATER,
        unit=MeterUnit.CUBIC_METER,
    )
    other_id = UUID("20000000-0000-0000-0000-000000000002")
    other = Meter(
        id=other_id,
        property_id=ID,
        name="ХВС",
        type=UtilityType.COLD_WATER,
        unit=MeterUnit.CUBIC_METER,
    )

    keyboard = photo_meter_selection_keyboard(
        [other, suggested],
        suggested_meter_id=ID,
    )
    labels = [button.text for row in keyboard.inline_keyboard for button in row]

    assert labels == ["⭐ Горячая вода — ГВС", "Холодная вода — ХВС", "Отмена"]
