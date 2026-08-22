from aiogram import Router

from src.bootstrap import ApplicationServices
from src.bot.handlers.errors import create_errors_router
from src.bot.handlers.meters import create_meters_router
from src.bot.handlers.properties import create_properties_router
from src.bot.handlers.readings import create_readings_router
from src.bot.handlers.start import create_start_router
from src.bot.handlers.tariffs import create_tariffs_router


def create_bot_router(
    services: ApplicationServices,
    *,
    max_photo_bytes: int = 10_000_000,
) -> Router:
    router = Router(name="utility_bot")
    router.include_router(create_start_router())
    router.include_router(create_properties_router(services.properties))
    router.include_router(create_meters_router(services.properties, services.meters))
    router.include_router(create_tariffs_router(services.properties, services.tariffs))
    router.include_router(
        create_readings_router(
            services.properties,
            services.meters,
            services.readings,
            services.photo_readings,
            max_photo_bytes=max_photo_bytes,
        )
    )
    router.include_router(create_errors_router())
    return router


__all__ = ["create_bot_router"]
