import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

from src.bootstrap import build_application
from src.bot.handlers import create_bot_router
from src.bot.middlewares import CurrentUserMiddleware
from src.config import get_settings
from src.web import start_mini_app_server

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = get_settings()
    settings.validate_runtime_secrets()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    services = build_application(settings)

    mini_app_runner = None
    if settings.mini_app_server_enabled:
        mini_app_runner = await start_mini_app_server(
            settings,
            users=services.users,
            dashboard=services.dashboard,
            properties=services.properties,
            meters=services.meters,
            management=services.management,
        )
        logger.info(
            "Mini App server listening on %s:%s public_url=%s",
            settings.mini_app_host,
            settings.mini_app_port,
            settings.mini_app_url or "not configured yet",
        )

    dispatcher = Dispatcher()
    user_middleware = CurrentUserMiddleware(services.users)
    dispatcher.message.outer_middleware(user_middleware)
    dispatcher.callback_query.outer_middleware(user_middleware)
    dispatcher.include_router(
        create_bot_router(
            services,
            max_photo_bytes=settings.ocr_max_image_bytes,
            mini_app_url=settings.mini_app_url or None,
        )
    )

    try:
        logger.info("Starting utility bot with long polling")
        async with Bot(token=settings.bot_token.get_secret_value()) as bot:
            commands = [
                BotCommand(command="start", description="Главное меню"),
                BotCommand(command="properties", description="Объекты"),
                BotCommand(command="meters", description="Счётчики"),
                BotCommand(command="add_meter", description="Добавить счётчик"),
                BotCommand(command="tariffs", description="Тарифы"),
                BotCommand(command="readings", description="Передать показания"),
                BotCommand(command="history", description="История показаний"),
                BotCommand(command="ocr_debug", description="Отладка распознавания фото"),
                BotCommand(command="help", description="Помощь"),
                BotCommand(command="cancel", description="Отменить ввод"),
            ]
            if settings.mini_app_url:
                commands.insert(1, BotCommand(command="app", description="Открыть дашборд"))
                await bot.set_chat_menu_button(
                    menu_button=MenuButtonWebApp(
                        text="Дашборд",
                        web_app=WebAppInfo(url=settings.mini_app_url),
                    )
                )
            await bot.set_my_commands(commands)
            await bot.delete_webhook(drop_pending_updates=False)
            await dispatcher.start_polling(bot)
    finally:
        if mini_app_runner is not None:
            await mini_app_runner.cleanup()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Utility bot stopped")


if __name__ == "__main__":
    main()
