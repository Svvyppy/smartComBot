from decimal import Decimal
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from src.application.exceptions import (
    ActiveTariffNotFoundError,
    ReadingRejectedError,
    SuspiciousReadingError,
)
from src.application.meters import MeterService
from src.application.properties import PropertyService
from src.application.readings import ManualReadingResult, ReadingService
from src.bot.filters import TextEquals
from src.bot.keyboards import main_menu_keyboard
from src.bot.keyboards.callbacks import MeterCallback, PropertyCallback
from src.bot.keyboards.common import (
    cancel_keyboard,
    meters_keyboard,
    properties_keyboard,
    suspicious_reading_keyboard,
)
from src.bot.presentation import format_decimal, format_money, parse_decimal
from src.bot.states import ReadingForm
from src.bot.texts import MenuButton, unit_label, utility_label
from src.domain.entities import Meter, User


def create_readings_router(
    properties: PropertyService,
    meters: MeterService,
    readings: ReadingService,
) -> Router:
    router = Router(name="readings")

    async def choose_property(
        message: Message,
        current_user: User,
        *,
        action: str,
        prompt: str,
    ) -> None:
        assert current_user.id is not None
        items = await properties.list(user_id=current_user.id)
        if not items:
            await message.answer(
                "Сначала добавьте объект.",
                reply_markup=properties_keyboard([], action="view", with_add=True),
            )
            return
        await message.answer(prompt, reply_markup=properties_keyboard(items, action=action))

    @router.message(Command("readings"))
    @router.message(TextEquals(MenuButton.READINGS))
    async def reading_menu(message: Message, current_user: User) -> None:
        await choose_property(
            message,
            current_user,
            action="reading",
            prompt="Выберите объект:",
        )

    @router.message(Command("history"))
    @router.message(TextEquals(MenuButton.HISTORY))
    async def history_menu(message: Message, current_user: User) -> None:
        await choose_property(
            message,
            current_user,
            action="history",
            prompt="История какого объекта вас интересует?",
        )

    async def choose_meter(
        callback: CallbackQuery,
        callback_data: PropertyCallback,
        current_user: User,
        *,
        action: str,
        empty_text: str,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        assert current_user.id is not None
        property_id = UUID(callback_data.property_id)
        await properties.get(user_id=current_user.id, property_id=property_id)
        items = await meters.list(user_id=current_user.id, property_id=property_id)
        if not items:
            await callback.message.answer(empty_text)
            return
        await callback.message.answer(
            "Выберите счётчик:",
            reply_markup=meters_keyboard(items, action=action),
        )

    @router.callback_query(PropertyCallback.filter(F.action == "reading"))
    async def choose_reading_meter(
        callback: CallbackQuery,
        callback_data: PropertyCallback,
        current_user: User,
    ) -> None:
        await choose_meter(
            callback,
            callback_data,
            current_user,
            action="reading",
            empty_text="У объекта нет активных счётчиков.",
        )

    @router.callback_query(PropertyCallback.filter(F.action == "history"))
    async def choose_history_meter(
        callback: CallbackQuery,
        callback_data: PropertyCallback,
        current_user: User,
    ) -> None:
        await choose_meter(
            callback,
            callback_data,
            current_user,
            action="history",
            empty_text="У объекта пока нет счётчиков.",
        )

    @router.callback_query(MeterCallback.filter(F.action == "reading"))
    async def start_reading_form(
        callback: CallbackQuery,
        callback_data: MeterCallback,
        state: FSMContext,
        current_user: User,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        assert current_user.id is not None
        meter = await meters.get(
            user_id=current_user.id,
            meter_id=UUID(callback_data.meter_id),
        )
        await state.clear()
        await state.update_data(meter_id=callback_data.meter_id)
        await state.set_state(ReadingForm.value)
        await callback.message.answer(
            f"Введите текущее показание счётчика «{meter.name}» в {unit_label(meter.unit)}:",
            reply_markup=ReplyKeyboardRemove(),
        )

    def result_text(meter: Meter, result: ManualReadingResult) -> str:
        assert result.reading.confirmed_value is not None
        current = format_decimal(result.reading.confirmed_value)
        unit = unit_label(meter.unit)
        if result.is_baseline:
            return (
                f"Показание сохранено как начальное.\n\n"
                f"{meter.name}: {current} {unit}\n"
                "Расход и стоимость будут рассчитаны со следующего показания."
            )
        assert result.previous_reading is not None
        assert result.billing is not None
        assert result.charge is not None
        return (
            f"{utility_label(meter.type)} — {meter.name}\n\n"
            f"Предыдущие: {format_decimal(result.previous_reading)} {unit}\n"
            f"Текущие: {current} {unit}\n"
            f"Расход: {format_decimal(result.billing.consumption)} {unit}\n"
            f"Тариф: {format_decimal(result.charge.tariff_price)} ₽/{unit}\n"
            f"Стоимость: {format_money(result.billing.amount)} ₽"
        )

    async def persist_reading(
        message: Message,
        state: FSMContext,
        current_user: User,
        *,
        meter_id: UUID,
        value: Decimal,
        allow_suspicious: bool,
    ) -> None:
        assert current_user.id is not None
        meter = await meters.get(user_id=current_user.id, meter_id=meter_id)
        try:
            result = await readings.record_manual(
                user_id=current_user.id,
                meter_id=meter_id,
                value=value,
                allow_suspicious=allow_suspicious,
            )
        except SuspiciousReadingError as exc:
            await state.update_data(meter_id=str(meter_id), value=str(value))
            await state.set_state(ReadingForm.suspicious_confirmation)
            await message.answer(
                f"{exc}\n\nПоказание выглядит необычно большим. Сохранить его?",
                reply_markup=suspicious_reading_keyboard(str(meter_id)),
            )
            return
        except ReadingRejectedError as exc:
            await message.answer(f"Показание не принято: {exc}\nВведите другое значение.")
            return
        except ActiveTariffNotFoundError:
            await message.answer(
                "Для этого ресурса не настроен действующий тариф. "
                "Сначала откройте раздел «Тарифы».",
                reply_markup=main_menu_keyboard(),
            )
            await state.clear()
            return
        await state.clear()
        await message.answer(result_text(meter, result), reply_markup=main_menu_keyboard())

    @router.message(StateFilter(ReadingForm.value))
    async def reading_value(
        message: Message,
        state: FSMContext,
        current_user: User,
    ) -> None:
        if not message.text:
            await message.answer("Введите показание числом.", reply_markup=cancel_keyboard())
            return
        try:
            value = parse_decimal(message.text)
        except ValueError as exc:
            await message.answer(str(exc), reply_markup=cancel_keyboard())
            return
        data = await state.get_data()
        try:
            meter_id = UUID(str(data["meter_id"]))
        except (KeyError, ValueError):
            await state.clear()
            await message.answer(
                "Сценарий устарел. Начните заново.",
                reply_markup=main_menu_keyboard(),
            )
            return
        await persist_reading(
            message,
            state,
            current_user,
            meter_id=meter_id,
            value=value,
            allow_suspicious=False,
        )

    @router.callback_query(
        StateFilter(ReadingForm.suspicious_confirmation),
        MeterCallback.filter(F.action == "confirm"),
    )
    async def confirm_suspicious(
        callback: CallbackQuery,
        callback_data: MeterCallback,
        state: FSMContext,
        current_user: User,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        data = await state.get_data()
        if data.get("meter_id") != callback_data.meter_id or "value" not in data:
            await state.clear()
            await callback.message.answer(
                "Подтверждение устарело. Начните заново.",
                reply_markup=main_menu_keyboard(),
            )
            return
        await persist_reading(
            callback.message,
            state,
            current_user,
            meter_id=UUID(callback_data.meter_id),
            value=Decimal(str(data["value"])),
            allow_suspicious=True,
        )

    @router.callback_query(
        StateFilter(ReadingForm.suspicious_confirmation),
        MeterCallback.filter(F.action == "retry"),
    )
    async def retry_suspicious(
        callback: CallbackQuery,
        callback_data: MeterCallback,
        state: FSMContext,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        await state.update_data(meter_id=callback_data.meter_id)
        await state.set_state(ReadingForm.value)
        await callback.message.answer("Введите исправленное показание:")

    @router.callback_query(MeterCallback.filter(F.action == "history"))
    async def meter_history(
        callback: CallbackQuery,
        callback_data: MeterCallback,
        current_user: User,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        assert current_user.id is not None
        meter_id = UUID(callback_data.meter_id)
        meter = await meters.get(user_id=current_user.id, meter_id=meter_id)
        history = await readings.list_history(
            user_id=current_user.id,
            meter_id=meter_id,
            limit=10,
        )
        if not history:
            await callback.message.answer(f"У счётчика «{meter.name}» пока нет показаний.")
            return
        unit = unit_label(meter.unit)
        lines = [f"Последние показания — {meter.name}: "]
        for reading in history:
            assert reading.confirmed_value is not None
            lines.append(
                f"• {reading.captured_at:%d.%m.%Y}: "
                f"{format_decimal(reading.confirmed_value)} {unit}"
            )
        await callback.message.answer("\n".join(lines))

    return router
