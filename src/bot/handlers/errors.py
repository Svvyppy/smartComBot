import logging

from aiogram import Router
from aiogram.types import ErrorEvent, Message

from src.bot.keyboards import main_menu_keyboard

logger = logging.getLogger(__name__)


def create_errors_router() -> Router:
    router = Router(name="errors")

    @router.errors()
    async def handle_error(event: ErrorEvent) -> bool:
        exception = event.exception
        logger.error(
            "Unhandled Telegram update error: %s",
            exception,
            exc_info=(type(exception), exception, exception.__traceback__),
        )
        message = event.update.message
        if isinstance(message, Message):
            await message.answer(
                "Не удалось выполнить действие. Попробуйте ещё раз или используйте /cancel.",
                reply_markup=main_menu_keyboard(),
            )
        return True

    return router

