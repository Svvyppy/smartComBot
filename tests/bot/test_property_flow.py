import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any, TypeVar, cast
from uuid import UUID, uuid4

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import GetMe, SendMessage
from aiogram.methods.base import TelegramMethod
from aiogram.types import (
    Chat,
    Message,
    MessageEntity,
    Update,
)
from aiogram.types import (
    User as TelegramUser,
)

from src.bot.handlers.properties import create_properties_router
from src.bot.middlewares import CurrentUserMiddleware
from src.domain.entities import Property, User

TelegramType = TypeVar("TelegramType")
USER_ID = UUID("10000000-0000-0000-0000-000000000001")


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.sent_texts: list[str] = []

    async def close(self) -> None:
        return None

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,
    ) -> TelegramType:
        if isinstance(method, GetMe):
            return cast(
                TelegramType,
                TelegramUser(id=999, is_bot=True, first_name="Bot", username="test_bot"),
            )
        if isinstance(method, SendMessage):
            self.sent_texts.append(method.text)
            return cast(
                TelegramType,
                Message(
                    message_id=len(self.sent_texts) + 100,
                    date=datetime.now(UTC),
                    chat=Chat(id=int(method.chat_id), type="private"),
                    text=method.text,
                ),
            )
        raise AssertionError(f"Unexpected Telegram method: {type(method).__name__}")

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        if False:
            yield b""


class FakeUserService:
    async def register(self, **_: object) -> User:
        return User(id=USER_ID, telegram_id=42, first_name="Тест")


class FakePropertyService:
    def __init__(self) -> None:
        self.created: list[Property] = []

    async def create(
        self,
        *,
        user_id: UUID,
        name: str,
        address: str | None,
    ) -> Property:
        property_ = Property(
            id=uuid4(),
            user_id=user_id,
            name=name,
            address=address,
        )
        self.created.append(property_)
        return property_


def incoming_message(update_id: int, text: str, *, command: bool = False) -> Update:
    entities = None
    if command:
        entities = [MessageEntity(type="bot_command", offset=0, length=len(text))]
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=42, type="private"),
            from_user=TelegramUser(id=42, is_bot=False, first_name="Тест"),
            text=text,
            entities=entities,
        ),
    )


async def test_add_property_fsm_flow() -> None:
    properties = FakePropertyService()
    session = RecordingSession()
    bot = Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi", session=session)
    dispatcher = Dispatcher()
    dispatcher.message.outer_middleware(
        CurrentUserMiddleware(FakeUserService())  # type: ignore[arg-type]
    )
    dispatcher.include_router(
        create_properties_router(properties)  # type: ignore[arg-type]
    )

    await asyncio.wait_for(
        dispatcher.feed_update(bot, incoming_message(1, "/add_property", command=True)),
        timeout=2,
    )
    await asyncio.wait_for(
        dispatcher.feed_update(bot, incoming_message(2, "Квартира")),
        timeout=2,
    )
    await asyncio.wait_for(
        dispatcher.feed_update(bot, incoming_message(3, "ул. Пушкина, 1")),
        timeout=2,
    )
    await bot.session.close()

    assert len(properties.created) == 1
    assert properties.created[0].user_id == USER_ID
    assert properties.created[0].name == "Квартира"
    assert properties.created[0].address == "ул. Пушкина, 1"
    assert any("добавлен" in text for text in session.sent_texts)
