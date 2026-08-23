from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.bot.filters import TextEquals
from src.bot.keyboards import main_menu_keyboard
from src.bot.keyboards.callbacks import ActionCallback
from src.bot.keyboards.common import mini_app_keyboard
from src.bot.texts import MenuButton
from src.domain.entities import User

HELP_TEXT = (
    "Я помогу вести объекты, счётчики, тарифы и распознавать показания по фото.\n\n"
    "Доступные команды:\n"
    "/properties — объекты\n"
    "/meters — счётчики\n"
    "/add_meter — добавить счётчик\n"
    "/tariffs — тарифы\n"
    "/readings — передать показания\n"
    "/history — история показаний\n"
    "/ocr_debug — отправить проблемное фото для настройки OCR\n"
    "/cancel — отменить текущий ввод"
)


def create_start_router(mini_app_url: str | None = None) -> Router:
    router = Router(name="start")

    @router.message(CommandStart())
    async def start(message: Message, current_user: User, state: FSMContext) -> None:
        await state.clear()
        greeting = f", {current_user.first_name}" if current_user.first_name else ""
        await message.answer(
            f"Здравствуйте{greeting}!\n\n"
            "Я помогу учитывать показания счётчиков и коммунальные платежи. "
            "Начните с добавления объекта.",
            reply_markup=main_menu_keyboard(mini_app_url),
        )

    @router.message(Command("app"))
    async def open_mini_app(message: Message) -> None:
        if not mini_app_url:
            await message.answer(
                "Mini App пока не настроен.",
                reply_markup=main_menu_keyboard(),
            )
            return
        await message.answer(
            "Откройте дашборд SmartCom:",
            reply_markup=mini_app_keyboard(mini_app_url),
        )

    @router.message(Command("help"))
    @router.message(TextEquals(MenuButton.HELP))
    async def help_message(message: Message) -> None:
        await message.answer(HELP_TEXT, reply_markup=main_menu_keyboard())

    @router.message(Command("cancel"))
    async def cancel_command(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Действие отменено.", reply_markup=main_menu_keyboard())

    @router.callback_query(ActionCallback.filter(F.action == "cancel"))
    async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await callback.answer("Отменено")
        if isinstance(callback.message, Message):
            await callback.message.answer("Действие отменено.", reply_markup=main_menu_keyboard())

    @router.message(Command("report"))
    async def report_placeholder(message: Message) -> None:
        await message.answer(
            "Отчёты и экспорт появятся на следующем этапе.",
            reply_markup=main_menu_keyboard(),
        )

    return router
