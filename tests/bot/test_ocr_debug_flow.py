import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, TypeVar, cast
from uuid import UUID

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import GetFile, GetMe, SendMessage
from aiogram.methods.base import TelegramMethod
from aiogram.types import Chat, File, Message, MessageEntity, PhotoSize, Update
from aiogram.types import User as TelegramUser

from src.application.interfaces import OCRResult
from src.application.ocr import OCRDebugCapture
from src.bot.handlers.ocr_debug import _capture_summary, create_ocr_debug_router
from src.bot.middlewares import CurrentUserMiddleware
from src.domain.entities import User

TelegramType = TypeVar("TelegramType")
USER_ID = UUID("10000000-0000-0000-0000-000000000001")
SAMPLE_ID = UUID("20000000-0000-0000-0000-000000000002")


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
        if isinstance(method, GetFile):
            return cast(
                TelegramType,
                File(
                    file_id=method.file_id,
                    file_unique_id="photo-unique",
                    file_size=10,
                    file_path="photos/debug.jpg",
                ),
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
        yield b"jpeg-data"


class FakeUserService:
    async def register(self, **_: object) -> User:
        return User(id=USER_ID, telegram_id=42, first_name="Тест")


class FakeOCRDebugService:
    def __init__(self) -> None:
        self.image_content: bytes | None = None
        self.goal: str | None = None

    async def capture(self, *, image_content: bytes, **_: object) -> OCRDebugCapture:
        self.image_content = image_content
        return OCRDebugCapture(
            sample_id=SAMPLE_ID,
            current_result=OCRResult(Decimal("123.4"), "998877", 0.91, ["00123.4"]),
            error=None,
        )

    async def set_goal(self, *, goal: str, **_: object) -> None:
        self.goal = goal


def incoming_text(update_id: int, text: str, *, command: bool = False) -> Update:
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


def incoming_photo(update_id: int) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=42, type="private"),
            from_user=TelegramUser(id=42, is_bot=False, first_name="Тест"),
            photo=[
                PhotoSize(
                    file_id="photo-id",
                    file_unique_id="photo-unique",
                    width=1280,
                    height=720,
                    file_size=10,
                )
            ],
        ),
    )


def test_ocr_debug_summary_shows_received_error_and_pending_expectation() -> None:
    summary = _capture_summary(
        OCRDebugCapture(
            sample_id=SAMPLE_ID,
            current_result=None,
            error="ValueError: not enough values to unpack (expected 3, got 2)",
        )
    )

    assert "Получено OCR:" in summary
    assert "expected 3, got 2" in summary
    assert "Ожидается:\n• пока не указано" in summary


async def test_ocr_debug_photo_and_goal_flow() -> None:
    service = FakeOCRDebugService()
    session = RecordingSession()
    bot = Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi", session=session)
    dispatcher = Dispatcher()
    dispatcher.message.outer_middleware(
        CurrentUserMiddleware(FakeUserService())  # type: ignore[arg-type]
    )
    dispatcher.include_router(
        create_ocr_debug_router(service)  # type: ignore[arg-type]
    )

    await asyncio.wait_for(
        dispatcher.feed_update(bot, incoming_text(1, "/ocr_debug", command=True)),
        timeout=2,
    )
    await asyncio.wait_for(dispatcher.feed_update(bot, incoming_photo(2)), timeout=2)
    await asyncio.wait_for(
        dispatcher.feed_update(bot, incoming_text(3, "Показание 123.4, номер 998877")),
        timeout=2,
    )
    await bot.session.close()

    assert service.image_content == b"jpeg-data"
    assert service.goal == "Показание 123.4, номер 998877"
    assert any("Получено OCR:\n• показание: 123.4" in text for text in session.sent_texts)
    assert any("Ожидается:\n• пока не указано" in text for text in session.sent_texts)
    assert any(
        "Ожидается:\nПоказание 123.4, номер 998877" in text for text in session.sent_texts
    )
    assert any(str(SAMPLE_ID) in text for text in session.sent_texts)
