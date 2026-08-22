from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from src.application.properties import PropertyService
from src.bot.filters import TextEquals
from src.bot.keyboards import main_menu_keyboard
from src.bot.keyboards.callbacks import ActionCallback, PropertyCallback
from src.bot.keyboards.common import (
    cancel_keyboard,
    properties_keyboard,
    property_actions_keyboard,
    skip_or_cancel_keyboard,
)
from src.bot.states import PropertyForm
from src.bot.texts import MenuButton
from src.domain.entities import User


def create_properties_router(properties: PropertyService) -> Router:
    router = Router(name="properties")

    async def send_properties(message: Message, current_user: User) -> None:
        assert current_user.id is not None
        items = await properties.list(user_id=current_user.id)
        text = "Ваши объекты:" if items else "Объектов пока нет. Добавьте квартиру или дом."
        await message.answer(
            text,
            reply_markup=properties_keyboard(items, action="view", with_add=True),
        )

    @router.message(Command("properties"))
    @router.message(TextEquals(MenuButton.PROPERTIES))
    async def list_properties(message: Message, current_user: User) -> None:
        await send_properties(message, current_user)

    @router.callback_query(PropertyCallback.filter(F.action == "view"))
    async def view_property(
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
        address = property_.address or "не указан"
        await callback.message.answer(
            f"{property_.name}\nАдрес: {address}",
            reply_markup=property_actions_keyboard(property_),
        )

    @router.message(Command("add_property"))
    async def add_property_command(message: Message, state: FSMContext) -> None:
        await state.set_state(PropertyForm.name)
        await message.answer(
            "Введите название объекта, например «Квартира»:",
            reply_markup=ReplyKeyboardRemove(),
        )

    @router.callback_query(ActionCallback.filter(F.action == "add_property"))
    async def add_property_callback(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        await state.set_state(PropertyForm.name)
        await callback.message.answer(
            "Введите название объекта, например «Квартира»:",
            reply_markup=ReplyKeyboardRemove(),
        )

    @router.message(StateFilter(PropertyForm.name))
    async def property_name(message: Message, state: FSMContext) -> None:
        if not message.text or not message.text.strip():
            await message.answer("Название не может быть пустым.", reply_markup=cancel_keyboard())
            return
        await state.update_data(name=message.text.strip())
        await state.set_state(PropertyForm.address)
        await message.answer(
            "Введите адрес или нажмите «Пропустить»: ",
            reply_markup=skip_or_cancel_keyboard("skip_address"),
        )

    async def save_property(
        message: Message,
        state: FSMContext,
        current_user: User,
        address: str | None,
    ) -> None:
        data = await state.get_data()
        name = data.get("name")
        if not isinstance(name, str):
            await state.clear()
            await message.answer(
                "Сценарий устарел. Начните заново.",
                reply_markup=main_menu_keyboard(),
            )
            return
        assert current_user.id is not None
        property_ = await properties.create(
            user_id=current_user.id,
            name=name,
            address=address,
        )
        await state.clear()
        await message.answer(
            f"Объект «{property_.name}» добавлен.",
            reply_markup=main_menu_keyboard(),
        )

    @router.message(StateFilter(PropertyForm.address))
    async def property_address(
        message: Message,
        state: FSMContext,
        current_user: User,
    ) -> None:
        if not message.text:
            await message.answer("Введите адрес текстом или нажмите «Пропустить».")
            return
        await save_property(message, state, current_user, message.text.strip())

    @router.callback_query(
        StateFilter(PropertyForm.address),
        ActionCallback.filter(F.action == "skip_address"),
    )
    async def skip_address(
        callback: CallbackQuery,
        state: FSMContext,
        current_user: User,
    ) -> None:
        await callback.answer()
        if isinstance(callback.message, Message):
            await save_property(callback.message, state, current_user, None)

    return router
