import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from aiogram.types import User as TelegramUser

from src.application.users import UserService

logger = logging.getLogger(__name__)


class CurrentUserMiddleware(BaseMiddleware):
    def __init__(self, users: UserService) -> None:
        self._users = users

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        telegram_user = data.get("event_from_user")
        if not isinstance(telegram_user, TelegramUser):
            return await handler(event, data)
        try:
            current_user = await self._users.register(
                telegram_id=telegram_user.id,
                username=telegram_user.username,
                first_name=telegram_user.first_name,
            )
            if current_user.id is None:
                raise RuntimeError("Saved user does not have an id")
            data["current_user"] = current_user
        except Exception:
            logger.exception("Failed to resolve Telegram user id=%s", telegram_user.id)
            if isinstance(event, Message):
                await event.answer("Сервис временно недоступен. Попробуйте ещё раз позже.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Сервис временно недоступен", show_alert=True)
            return None
        return await handler(event, data)

