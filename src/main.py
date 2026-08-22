import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from src.bootstrap import build_application
from src.bot.handlers import create_bot_router
from src.bot.middlewares import CurrentUserMiddleware
from src.config import get_settings

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = get_settings()
    settings.validate_runtime_secrets()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    services = build_application(settings)

    dispatcher = Dispatcher()
    user_middleware = CurrentUserMiddleware(services.users)
    dispatcher.message.outer_middleware(user_middleware)
    dispatcher.callback_query.outer_middleware(user_middleware)
    dispatcher.include_router(
        create_bot_router(services, max_photo_bytes=settings.ocr_max_image_bytes)
    )

    logger.info("Starting utility bot with long polling")
    async with Bot(token=settings.bot_token.get_secret_value()) as bot:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Главное меню"),
                BotCommand(command="properties", description="Объекты"),
                BotCommand(command="meters", description="Счётчики"),
                BotCommand(command="add_meter", description="Добавить счётчик"),
                BotCommand(command="tariffs", description="Тарифы"),
                BotCommand(command="readings", description="Передать показания"),
                BotCommand(command="history", description="История показаний"),
                BotCommand(command="help", description="Помощь"),
                BotCommand(command="cancel", description="Отменить ввод"),
            ]
        )
        await bot.delete_webhook(drop_pending_updates=False)
        await dispatcher.start_polling(bot)


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Utility bot stopped")


if __name__ == "__main__":
    main()
