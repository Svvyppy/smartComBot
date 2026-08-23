from collections.abc import Sequence
from uuid import UUID

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot.keyboards.callbacks import (
    ActionCallback,
    MeterCallback,
    PropertyCallback,
    ReadingCallback,
    TariffCallback,
    UtilityCallback,
)
from src.bot.texts import MenuButton, utility_label
from src.domain.entities import Meter, Property
from src.domain.enums import UtilityType


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MenuButton.PROPERTIES), KeyboardButton(text=MenuButton.METERS)],
            [KeyboardButton(text=MenuButton.READINGS), KeyboardButton(text=MenuButton.TARIFFS)],
            [KeyboardButton(text=MenuButton.HISTORY), KeyboardButton(text=MenuButton.HELP)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=ActionCallback(action="cancel").pack(),
                )
            ]
        ]
    )


def skip_or_cancel_keyboard(skip_action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Пропустить",
                    callback_data=ActionCallback(action=skip_action).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=ActionCallback(action="cancel").pack(),
                )
            ],
        ]
    )


def properties_keyboard(
    properties: Sequence[Property],
    *,
    action: str,
    with_add: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for property_ in properties:
        if property_.id is None:
            continue
        builder.button(
            text=property_.name,
            callback_data=PropertyCallback(
                action=action,
                property_id=str(property_.id),
            ),
        )
    if with_add:
        builder.button(
            text="➕ Добавить объект",
            callback_data=ActionCallback(action="add_property"),
        )
    builder.adjust(1)
    return builder.as_markup()


def property_actions_keyboard(property_: Property) -> InlineKeyboardMarkup:
    if property_.id is None:
        raise ValueError("Property must have an id")
    property_id = str(property_.id)
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📟 Счётчики",
        callback_data=PropertyCallback(action="meters", property_id=property_id),
    )
    builder.button(
        text="➕ Добавить счётчик",
        callback_data=PropertyCallback(action="add_meter", property_id=property_id),
    )
    builder.button(
        text="💰 Тарифы",
        callback_data=PropertyCallback(action="tariffs", property_id=property_id),
    )
    builder.button(
        text="✍️ Передать показания",
        callback_data=PropertyCallback(action="reading", property_id=property_id),
    )
    builder.button(
        text="📚 История",
        callback_data=PropertyCallback(action="history", property_id=property_id),
    )
    builder.adjust(1)
    return builder.as_markup()


def meters_keyboard(meters: Sequence[Meter], *, action: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for meter in meters:
        if meter.id is None:
            continue
        builder.button(
            text=f"{utility_label(meter.type)} — {meter.name}",
            callback_data=MeterCallback(action=action, meter_id=str(meter.id)),
        )
    builder.adjust(1)
    return builder.as_markup()


def reading_meters_keyboard(
    property_id: str,
    meters: Sequence[Meter],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if len(meters) > 1 and all(meter.serial_number for meter in meters):
        builder.button(
            text="🖼 Отправить все фото одним альбомом",
            callback_data=PropertyCallback(
                action="photo_album",
                property_id=property_id,
            ),
        )
    builder.button(
        text="📷 Определить счётчик по фото",
        callback_data=PropertyCallback(
            action="photo_meter",
            property_id=property_id,
        ),
    )
    for meter in meters:
        if meter.id is None:
            continue
        builder.button(
            text=f"{utility_label(meter.type)} — {meter.name}",
            callback_data=MeterCallback(action="reading", meter_id=str(meter.id)),
        )
    builder.adjust(1)
    return builder.as_markup()


def photo_album_confirmation_keyboard(property_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить все",
                    callback_data=PropertyCallback(
                        action="confirm_album",
                        property_id=property_id,
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=PropertyCallback(
                        action="reject_album",
                        property_id=property_id,
                    ).pack(),
                )
            ],
        ]
    )


def photo_meter_selection_keyboard(
    meters: Sequence[Meter],
    *,
    suggested_meter_id: UUID | None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    ordered = sorted(
        (meter for meter in meters if meter.id is not None),
        key=lambda meter: meter.id != suggested_meter_id,
    )
    for meter in ordered:
        suggested = meter.id == suggested_meter_id
        builder.button(
            text=("⭐ " if suggested else "")
            + f"{utility_label(meter.type)} — {meter.name}",
            callback_data=MeterCallback(
                action="select_photo",
                meter_id=str(meter.id),
            ),
        )
    builder.button(text="Отмена", callback_data=ActionCallback(action="cancel"))
    builder.adjust(1)
    return builder.as_markup()


def utility_keyboard(*, action: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for utility_type in (
        UtilityType.COLD_WATER,
        UtilityType.HOT_WATER,
        UtilityType.ELECTRICITY,
    ):
        builder.button(
            text=utility_label(utility_type),
            callback_data=UtilityCallback(
                action=action,
                utility_type=utility_type.value,
            ),
        )
    builder.button(text="Отмена", callback_data=ActionCallback(action="cancel"))
    builder.adjust(1)
    return builder.as_markup()


def tariffs_keyboard(property_: Property) -> InlineKeyboardMarkup:
    if property_.id is None:
        raise ValueError("Property must have an id")
    builder = InlineKeyboardBuilder()
    for utility_type in (
        UtilityType.COLD_WATER,
        UtilityType.HOT_WATER,
        UtilityType.WASTEWATER,
        UtilityType.ELECTRICITY,
    ):
        builder.button(
            text=f"Настроить: {utility_label(utility_type)}",
            callback_data=TariffCallback(
                property_id=str(property_.id),
                utility_type=utility_type.value,
            ),
        )
    builder.adjust(1)
    return builder.as_markup()


def suspicious_reading_keyboard(meter_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Всё равно сохранить",
                    callback_data=MeterCallback(action="confirm", meter_id=meter_id).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Исправить",
                    callback_data=MeterCallback(action="retry", meter_id=meter_id).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=ActionCallback(action="cancel").pack(),
                )
            ],
        ]
    )


def reading_method_keyboard(meter_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📷 Отправить фото",
                    callback_data=MeterCallback(action="photo", meter_id=meter_id).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⌨️ Ввести вручную",
                    callback_data=MeterCallback(action="manual", meter_id=meter_id).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=ActionCallback(action="cancel").pack(),
                )
            ],
        ]
    )


def photo_confirmation_keyboard(reading_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=ReadingCallback(
                        action="confirm",
                        reading_id=reading_id,
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Исправить",
                    callback_data=ReadingCallback(
                        action="correct",
                        reading_id=reading_id,
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=ReadingCallback(
                        action="reject",
                        reading_id=reading_id,
                    ).pack(),
                )
            ],
        ]
    )


def photo_serial_correction_keyboard(
    recognized_serial_number: str | None,
) -> InlineKeyboardMarkup:
    keep_label = (
        f"Оставить: {recognized_serial_number[:32]}"
        if recognized_serial_number
        else "Пропустить"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=keep_label,
                    callback_data=ActionCallback(action="keep_photo_serial").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=ActionCallback(action="cancel").pack(),
                )
            ],
        ]
    )
