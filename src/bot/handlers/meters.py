from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from src.application.meters import MeterService
from src.application.properties import PropertyService
from src.bot.filters import TextEquals
from src.bot.keyboards import main_menu_keyboard
from src.bot.keyboards.callbacks import (
    ActionCallback,
    MeterCallback,
    PropertyCallback,
    UtilityCallback,
)
from src.bot.keyboards.common import (
    cancel_keyboard,
    meters_keyboard,
    properties_keyboard,
    skip_or_cancel_keyboard,
    utility_keyboard,
)
from src.bot.states import MeterForm
from src.bot.texts import MenuButton, unit_label, utility_label
from src.domain.entities import User
from src.domain.enums import MeterUnit, UtilityType


def create_meters_router(properties: PropertyService, meters: MeterService) -> Router:
    router = Router(name="meters")

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

    @router.message(Command("meters"))
    @router.message(TextEquals(MenuButton.METERS))
    async def meters_menu(message: Message, current_user: User) -> None:
        await choose_property(
            message,
            current_user,
            action="meters",
            prompt="Выберите объект, чтобы посмотреть счётчики:",
        )

    @router.message(Command("add_meter"))
    async def add_meter_command(message: Message, current_user: User) -> None:
        await choose_property(
            message,
            current_user,
            action="add_meter",
            prompt="Для какого объекта добавить счётчик?",
        )

    @router.callback_query(PropertyCallback.filter(F.action == "meters"))
    async def list_meters(
        callback: CallbackQuery,
        callback_data: PropertyCallback,
        current_user: User,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        assert current_user.id is not None
        property_id = UUID(callback_data.property_id)
        property_ = await properties.get(user_id=current_user.id, property_id=property_id)
        items = await meters.list(user_id=current_user.id, property_id=property_id)
        if not items:
            await callback.message.answer(
                f"У объекта «{property_.name}» пока нет счётчиков.",
                reply_markup=properties_keyboard(
                    [property_],
                    action="add_meter",
                ),
            )
            return
        await callback.message.answer(
            f"Счётчики объекта «{property_.name}»: ",
            reply_markup=meters_keyboard(items, action="view"),
        )

    @router.callback_query(MeterCallback.filter(F.action == "view"))
    async def view_meter(
        callback: CallbackQuery,
        callback_data: MeterCallback,
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
        serial = meter.serial_number or "не указан"
        await callback.message.answer(
            f"{meter.name}\n"
            f"Тип: {utility_label(meter.type)}\n"
            f"Единица: {unit_label(meter.unit)}\n"
            f"Серийный номер: {serial}"
        )

    async def begin_meter_form(
        message: Message,
        state: FSMContext,
        property_id: str,
    ) -> None:
        await state.clear()
        await state.update_data(property_id=property_id)
        await state.set_state(MeterForm.name)
        await message.answer(
            "Введите название счётчика, например «Электричество в прихожей»: ",
            reply_markup=ReplyKeyboardRemove(),
        )

    @router.callback_query(PropertyCallback.filter(F.action == "add_meter"))
    async def select_property_for_meter(
        callback: CallbackQuery,
        callback_data: PropertyCallback,
        state: FSMContext,
        current_user: User,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        assert current_user.id is not None
        await properties.get(
            user_id=current_user.id,
            property_id=UUID(callback_data.property_id),
        )
        await begin_meter_form(callback.message, state, callback_data.property_id)

    @router.message(StateFilter(MeterForm.name))
    async def meter_name(message: Message, state: FSMContext) -> None:
        if not message.text or not message.text.strip():
            await message.answer("Название не может быть пустым.", reply_markup=cancel_keyboard())
            return
        await state.update_data(name=message.text.strip())
        await state.set_state(MeterForm.utility_type)
        await message.answer(
            "Выберите тип ресурса:",
            reply_markup=utility_keyboard(action="meter"),
        )

    @router.callback_query(
        StateFilter(MeterForm.utility_type),
        UtilityCallback.filter(F.action == "meter"),
    )
    async def meter_utility_type(
        callback: CallbackQuery,
        callback_data: UtilityCallback,
        state: FSMContext,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        utility_type = UtilityType(callback_data.utility_type)
        await state.update_data(utility_type=utility_type.value)
        await state.set_state(MeterForm.serial_number)
        await callback.message.answer(
            "Введите серийный номер счётчика или нажмите «Пропустить»: ",
            reply_markup=skip_or_cancel_keyboard("skip_serial"),
        )

    async def save_meter(
        message: Message,
        state: FSMContext,
        current_user: User,
        serial_number: str | None,
    ) -> None:
        data = await state.get_data()
        try:
            property_id = UUID(str(data["property_id"]))
            name = str(data["name"])
            utility_type = UtilityType(str(data["utility_type"]))
        except (KeyError, ValueError):
            await state.clear()
            await message.answer(
                "Сценарий устарел. Начните заново.",
                reply_markup=main_menu_keyboard(),
            )
            return
        unit = (
            MeterUnit.KILOWATT_HOUR
            if utility_type == UtilityType.ELECTRICITY
            else MeterUnit.CUBIC_METER
        )
        assert current_user.id is not None
        meter = await meters.create(
            user_id=current_user.id,
            property_id=property_id,
            name=name,
            utility_type=utility_type,
            unit=unit,
            serial_number=serial_number,
        )
        await state.clear()
        await message.answer(
            f"Счётчик «{meter.name}» добавлен ({utility_label(meter.type)}).",
            reply_markup=main_menu_keyboard(),
        )

    @router.message(StateFilter(MeterForm.serial_number))
    async def meter_serial(
        message: Message,
        state: FSMContext,
        current_user: User,
    ) -> None:
        if not message.text:
            await message.answer("Введите серийный номер текстом или нажмите «Пропустить».")
            return
        await save_meter(message, state, current_user, message.text.strip())

    @router.callback_query(
        StateFilter(MeterForm.serial_number),
        ActionCallback.filter(F.action == "skip_serial"),
    )
    async def skip_serial(
        callback: CallbackQuery,
        state: FSMContext,
        current_user: User,
    ) -> None:
        await callback.answer()
        if isinstance(callback.message, Message):
            await save_meter(callback.message, state, current_user, None)

    return router
