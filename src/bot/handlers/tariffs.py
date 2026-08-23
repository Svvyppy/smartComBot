import logging
from datetime import UTC, datetime
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from src.application.exceptions import ActiveTariffNotFoundError
from src.application.properties import PropertyService
from src.application.tariffs import TariffService
from src.bot.filters import TextEquals
from src.bot.keyboards import main_menu_keyboard
from src.bot.keyboards.callbacks import PropertyCallback, TariffCallback
from src.bot.keyboards.common import cancel_keyboard, properties_keyboard, tariffs_keyboard
from src.bot.presentation import format_decimal, parse_decimal
from src.bot.states import TariffForm
from src.bot.texts import MenuButton, utility_label
from src.domain.entities import User
from src.domain.enums import UtilityType

logger = logging.getLogger(__name__)


DISPLAYED_UTILITY_TYPES = (
    UtilityType.COLD_WATER,
    UtilityType.HOT_WATER,
    UtilityType.WASTEWATER,
    UtilityType.ELECTRICITY,
)


def create_tariffs_router(properties: PropertyService, tariffs: TariffService) -> Router:
    router = Router(name="tariffs")

    @router.message(Command("tariffs"))
    @router.message(TextEquals(MenuButton.TARIFFS))
    async def tariffs_menu(message: Message, current_user: User) -> None:
        assert current_user.id is not None
        items = await properties.list(user_id=current_user.id)
        if not items:
            await message.answer(
                "Сначала добавьте объект.",
                reply_markup=properties_keyboard([], action="view", with_add=True),
            )
            return
        await message.answer(
            "Для какого объекта настроить тарифы?",
            reply_markup=properties_keyboard(items, action="tariffs"),
        )

    @router.callback_query(PropertyCallback.filter(F.action == "tariffs"))
    async def property_tariffs(
        callback: CallbackQuery,
        callback_data: PropertyCallback,
        current_user: User,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        assert current_user.id is not None
        property_ = await properties.get(
            user_id=current_user.id,
            property_id=UUID(callback_data.property_id),
        )
        lines = [f"Тарифы объекта «{property_.name}»: "]
        today = datetime.now(UTC).date()
        for utility_type in DISPLAYED_UTILITY_TYPES:
            try:
                price = await tariffs.get_simple_price(
                    user_id=current_user.id,
                    property_id=UUID(callback_data.property_id),
                    utility_type=utility_type,
                    on_date=today,
                )
                value = f"{format_decimal(price)} ₽"
            except ActiveTariffNotFoundError:
                value = "не настроен"
            lines.append(f"• {utility_label(utility_type)}: {value}")
        await callback.message.answer(
            "\n".join(lines),
            reply_markup=tariffs_keyboard(property_),
        )

    @router.callback_query(TariffCallback.filter())
    async def start_tariff_form(
        callback: CallbackQuery,
        callback_data: TariffCallback,
        state: FSMContext,
        current_user: User,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        assert current_user.id is not None
        property_id = UUID(callback_data.property_id)
        await properties.get(user_id=current_user.id, property_id=property_id)
        utility_type = UtilityType(callback_data.utility_type)
        await state.clear()
        await state.update_data(
            property_id=str(property_id),
            utility_type=utility_type.value,
        )
        await state.set_state(TariffForm.price)
        await callback.message.answer(
            f"Введите цену для «{utility_label(utility_type)}» в рублях за единицу, "
            "например 8.25:",
            reply_markup=ReplyKeyboardRemove(),
        )

    @router.message(StateFilter(TariffForm.price))
    async def tariff_price(
        message: Message,
        state: FSMContext,
        current_user: User,
    ) -> None:
        if not message.text:
            await message.answer("Введите цену числом.", reply_markup=cancel_keyboard())
            return
        try:
            price = parse_decimal(message.text)
        except ValueError as exc:
            await message.answer(str(exc), reply_markup=cancel_keyboard())
            return
        if price < 0:
            await message.answer(
                "Цена не может быть отрицательной.",
                reply_markup=cancel_keyboard(),
            )
            return
        data = await state.get_data()
        try:
            property_id = UUID(str(data["property_id"]))
            utility_type = UtilityType(str(data["utility_type"]))
        except (KeyError, ValueError):
            await state.clear()
            await message.answer(
                "Сценарий устарел. Начните заново.",
                reply_markup=main_menu_keyboard(),
            )
            return
        assert current_user.id is not None
        today = datetime.now(UTC).date()
        await tariffs.create_simple(
            user_id=current_user.id,
            property_id=property_id,
            utility_type=utility_type,
            name=f"{utility_label(utility_type)} от {today.isoformat()}",
            price=price,
            valid_from=today,
        )
        logger.info(
            "Tariff created telegram_id=%s property_id=%s type=%s",
            current_user.telegram_id,
            property_id,
            utility_type.value,
        )
        await state.clear()
        await message.answer(
            f"Тариф для «{utility_label(utility_type)}» сохранён: "
            f"{format_decimal(price)} ₽ за единицу.",
            reply_markup=main_menu_keyboard(),
        )

    return router
